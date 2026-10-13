"""
Orquestração do fluxo de análise (Etapas 1, 2 e 3: texto e URL).

validação/raspagem → normalização → classificação BERTimbau (com [SEP]) →
indicadores linguísticos → checagem de fatos na internet (Google Fact Check) →
síntese e explicação via LLM → cálculo de risco ponderado → abstenção →
persistência segura sem texto bruto → resposta.
"""

from __future__ import annotations

import logging
import subprocess
import time
from functools import lru_cache

from django.conf import settings

from ..models import Analysis
from . import factcheck, llm, risk
from .classifier import get_classifier
from .preprocessing import NewsInput, build_news_input, summarize_claim
from .scraper import scrape_url

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"


@lru_cache(maxsize=1)
def code_version() -> str:
    configured = settings.FAKE_EYES.get("CODE_VERSION")
    if configured:
        return configured
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=settings.REPO_DIR,
            stderr=subprocess.DEVNULL, timeout=2,
        ).decode().strip()
    except Exception:  # noqa: BLE001 — ausência de git não deve derrubar a análise
        return "desconhecido"


def _limitations(news: NewsInput, cls, rules: risk.Rules, evidence_enabled: bool) -> list[str]:
    items = [
        "O resultado é um apoio à avaliação e não substitui a verificação em fontes confiáveis.",
        "O índice de risco é um indicador probabilístico e não representa certeza factual absoluta.",
    ]
    if not evidence_enabled:
        items.append("A consulta a fontes externas ainda não está habilitada; nenhuma evidência foi verificada.")
    if not rules.calibrator.get("calibrated", False):
        items.append("A confiança do modelo ainda não foi calibrada em dados independentes.")
    if not cls.fully_analyzed:
        items.append("Parte do conteúdo não pôde ser analisada pelo modelo.")
    if news.title_inferred:
        items.append("O título foi identificado automaticamente a partir da primeira linha do texto.")
    elif not news.title:
        items.append("Nenhum título foi informado; o modelo analisou apenas o corpo do texto.")
    return items


def _execute_pipeline(
    *,
    news: NewsInput,
    input_type: str,
    source_domain: str = "",
    user=None,
    visitor_id: str = "",
    started: float,
) -> Analysis:
    rules = risk.load_rules()

    # 1. Inferência do modelo BERTimbau V4 (com fatiamento determinístico e tokens [SEP])
    classifier = get_classifier()
    temperature = float(rules.calibrator.get("temperature", 1.0))
    cls = classifier.classify(news.title, news.subtitle, news.body, temperature=temperature)

    # 2. Indicadores estilísticos e linguísticos
    ling = risk.linguistic_indicators(news.full_text, rules.linguistic)

    # 3. Busca de checagens na internet (Google Fact Check Tools / Agências de Checagem)
    claim_query = news.title or summarize_claim(news)
    fact_res = factcheck.search_fact_checks(claim_query)
    evidence_conflict = fact_res.get("conflict_score")

    # 4. Síntese explicativa via LLM (Gemini / OpenAI / Síntese Neural Especializada)
    llm_res = llm.synthesize_explanation(
        title=news.title,
        body=news.body,
        model_fake_prob=cls.fake_probability,
        model_confidence=cls.confidence,
        model_label=cls.label,
        linguistic_indicators=ling,
        sources=fact_res.get("sources", []),
    )

    # 5. Cálculo do Índice de Risco Ponderado
    signals = {
        "model_fake_probability": cls.fake_probability,
        "linguistic_indicators": ling["signal"],
        "evidence_conflict": evidence_conflict,
    }
    risk_info = risk.compute_risk_index(signals, rules.weights)

    # 6. Regra de Abstenção Probabilística (RF14)
    evidence_available = bool(fact_res.get("sources"))
    reasons = risk.abstention_reasons(
        rules=rules,
        model_confidence=cls.confidence,
        chunk_disagreement=cls.chunk_disagreement,
        evidence_available=evidence_available,
    )
    if reasons or risk_info["value"] is None:
        status = risk.STATUS_INCONCLUSIVE
    else:
        status = risk.status_for_index(risk_info["value"], rules)

    technical = {
        "classification": cls.to_dict(),
        "linguistic_indicators": ling,
        "risk": risk_info,
        "rules": {
            "version": rules.version,
            "status_bands": {"low_max": rules.low_max, "attention_max": rules.attention_max},
            "abstention": {
                "min_model_confidence": rules.min_model_confidence,
                "max_chunk_disagreement": rules.max_chunk_disagreement,
                "require_evidence": rules.require_evidence,
            },
        },
        "calibrator": rules.calibrator,
        "evidence": {
            "enabled": True,
            "status": fact_res.get("status", "none"),
            "sources": fact_res.get("sources", []),
        },
        "llm_analysis": {
            "summary": llm_res.summary,
            "key_points": llm_res.key_points,
            "provider": llm_res.provider,
            "verdict_tendency": llm_res.verdict_tendency,
            "discourse_type": getattr(llm_res, "discourse_type", "factual"),
            "discourse_label": getattr(llm_res, "discourse_label", "Relato Factual"),
            "semantic_comparison": getattr(llm_res, "semantic_comparison", {}),
            "lexical_analysis": getattr(llm_res, "lexical_analysis", {}),
            "uncertainty_warning": getattr(llm_res, "uncertainty_warning", ""),
        },
        "input": {
            "type": input_type,
            "domain": source_domain,
            "title_provided": bool(news.title.strip()),
            "title_inferred": news.title_inferred,
            "subtitle_provided": bool(news.subtitle),
            "characters": len(news.full_text),
        },
        "limitations": _limitations(news, cls, rules, evidence_enabled=True),
    }

    analysis = Analysis.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        visitor_id=visitor_id[:64],
        input_type=input_type,
        source_domain=source_domain,
        claim_summary=summarize_claim(news),
        status=status,
        risk_index=None if status == risk.STATUS_INCONCLUSIVE else risk_info["value"],
        abstention_reasons=reasons,
        model_label=cls.label,
        model_fake_probability=cls.fake_probability,
        model_confidence=cls.confidence,
        technical=technical,
        model_version=cls.model_version,
        model_sha256=cls.model_sha256,
        rules_version=rules.version,
        calibrator_version=str(rules.calibrator.get("version", "none")),
        schema_version=SCHEMA_VERSION,
        code_version=code_version(),
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )

    logger.info(
        "analysis id=%s type=%s status=%s risk=%s conf=%.3f chunks=%d sources=%d ms=%.1f",
        analysis.id, input_type, status, analysis.risk_index, cls.confidence,
        cls.chunks_analyzed, len(fact_res.get("sources", [])), analysis.duration_ms,
    )
    return analysis


def run_text_analysis(*, text: str, title: str = "", subtitle: str = "", user=None, visitor_id: str = "") -> Analysis:
    started = time.perf_counter()
    news = build_news_input(text=text, title=title, subtitle=subtitle)
    return _execute_pipeline(
        news=news,
        input_type=Analysis.InputType.TEXT,
        source_domain="",
        user=user,
        visitor_id=visitor_id,
        started=started,
    )


def run_url_analysis(*, url: str, user=None, visitor_id: str = "") -> Analysis:
    started = time.perf_counter()
    scraped = scrape_url(url)
    news = build_news_input(text=scraped.body, title=scraped.title, subtitle=scraped.subtitle)
    return _execute_pipeline(
        news=news,
        input_type=Analysis.InputType.URL,
        source_domain=scraped.domain,
        user=user,
        visitor_id=visitor_id,
        started=started,
    )
