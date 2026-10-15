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
from .preprocessing import NewsInput, build_news_input, mask_pii, summarize_claim
from .privacy import sanitize_analysis_data
from .scraper import scrape_url
from .timing import Deadline

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"


def _request_deadline() -> Deadline:
    # Reserva 3 s dos 30 s do navegador para serialização, banco e transporte.
    return Deadline.after(27)


def _classify_news(news: NewsInput, rules):
    classifier = get_classifier()
    temperature = float(rules.calibrator.get("temperature", 1.0))
    return classifier.classify(news.title, news.subtitle, news.body, temperature=temperature)


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


def _limitations(
    news: NewsInput, cls, rules: risk.Rules, evidence_enabled: bool,
    consensus_divergent: bool = False,
) -> list[str]:
    items = [
        "O resultado é um apoio à avaliação e não substitui a verificação em fontes confiáveis.",
        "O índice de risco é um indicador probabilístico e não representa certeza factual absoluta.",
    ]
    if consensus_divergent:
        items.append("Atenção: A redação formal do texto pode apresentar padrão jornalístico culto no modelo de linguagem, mas o conteúdo da tese diverge do consenso histórico/científico documentado.")
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
    deadline: Deadline,
) -> Analysis:
    rules = risk.load_rules()

    # 1. Inferência do modelo BERTimbau V4 (com fatiamento determinístico e tokens [SEP])
    stage_started = time.perf_counter()
    cls = deadline.child(27, reserve=2).call(_classify_news, news, rules)
    logger.info("analysis stage=model ms=%.1f", (time.perf_counter() - stage_started) * 1000)

    # 2. Indicadores estilísticos e linguísticos
    ling = risk.linguistic_indicators(news.full_text, rules.linguistic)

    # 3. Busca de checagens na internet (Google Fact Check Tools / Agências de Checagem)
    claim_query = mask_pii(news.title or summarize_claim(news))
    stage_started = time.perf_counter()
    fact_res = factcheck.search_fact_checks(claim_query, deadline=deadline.child(8, reserve=2))
    logger.info("analysis stage=sources ms=%.1f", (time.perf_counter() - stage_started) * 1000)
    verified_sources = [source for source in fact_res.get("sources", [])
                        if source.get("relation") in ("conflicting", "compatible")]
    # O score vem da relação validada no serviço de fontes; sem fonte verificada,
    # nem um score isolado nem a síntese podem fornecer evidência externa.
    evidence_conflict = fact_res.get("conflict_score") if verified_sources else None

    # Fontes apenas contextuais aparecem no resultado, mas não sustentam a síntese nem a abstenção.
    # 4. Síntese explicativa via LLM (Gemini / Groq / OpenAI / Síntese Neural Especializada)
    stage_started = time.perf_counter()
    llm_res = llm.synthesize_explanation(
        title=news.title,
        body=news.body,
        model_fake_prob=cls.fake_probability,
        model_confidence=cls.confidence,
        model_label=cls.label,
        linguistic_indicators=ling,
        sources=verified_sources,
        source_domain=source_domain,
        deadline=deadline.child(7, reserve=1),
    )
    logger.info("analysis stage=explanation ms=%.1f", (time.perf_counter() - stage_started) * 1000)

    # 5. Cálculo do Índice de Risco Ponderado
    sem_comp = getattr(llm_res, "semantic_comparison", {}) or {}
    consensus_status = sem_comp.get("consensus_status", "sem_consenso_ou_debate")
    discourse_type = getattr(llm_res, "discourse_type", "factual")

    is_traditional = llm.is_traditional_press_domain(source_domain)
    has_conflicting = any(s.get("relation") == "conflicting" for s in fact_res.get("sources", []))
    is_satire = (discourse_type == "satira") or llm.is_satirical_domain(source_domain)

    # Identifica conteúdo factual em-domínio: imprensa tradicional ou texto com alta probabilidade/confiança factual
    is_in_domain_factual = (is_traditional or (cls.fake_probability < 0.25 and cls.confidence > 0.80)) and not is_satire and discourse_type != "teoria_conspiratoria"

    if is_in_domain_factual and not has_conflicting:
        consensus_status = "conforme_consenso"
        discourse_type = "factual"

    signals = {
        "model_fake_probability": cls.fake_probability,
        "linguistic_indicators": ling["signal"],
        "evidence_conflict": evidence_conflict,
    }
    risk_info = risk.compute_risk_index(signals, rules.weights)

    # 6. Regra de Abstenção Probabilística (RF14)
    evidence_available = bool(verified_sources)
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

    # Salvaguarda epistemológica: aplicada EXCLUSIVAMENTE para teorias conspiratórias reais fora de domínio,
    # sátiras/paródias fictícias ou matérias com checagem conflitante comprovada. NUNCA sobrepor matérias factuais.
    if not is_in_domain_factual and (has_conflicting or discourse_type in ("teoria_conspiratoria", "conspiracy_or_theoretical", "satira")):
        if status == risk.STATUS_LOW:
            status = risk.STATUS_ATTENTION
            if risk_info["value"] is not None and risk_info["value"] <= rules.low_max:
                risk_info["value"] = round(rules.low_max + 10.0, 2)

    is_out_of_domain = bool(
        not is_in_domain_factual and (
            discourse_type in ("teoria_conspiratoria", "conspiracy_or_theoretical", "satira") or
            (consensus_status == "diverge_consenso" and cls.fake_probability < 0.35 and (has_conflicting or discourse_type == "satira"))
        )
    )
    if discourse_type == "satira":
        training_scope = "out_of_domain_satire"
    elif is_out_of_domain:
        training_scope = "out_of_domain_conspiracy"
    elif is_traditional:
        training_scope = "in_domain_press"
    else:
        training_scope = "in_domain_general"

    cls_dict = cls.to_dict()
    cls_dict["is_out_of_domain"] = is_out_of_domain
    cls_dict["training_scope"] = training_scope

    claim_summary_masked = summarize_claim(news)
    sem_comp_clean = dict(getattr(llm_res, "semantic_comparison", {}) or {})
    if "claim_analyzed" in sem_comp_clean:
        sem_comp_clean["claim_analyzed"] = claim_summary_masked

    technical = {
        "classification": cls_dict,
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
            "failed": fact_res.get("failed", False),
        },
        "llm_analysis": {
            "summary": llm_res.summary,
            "key_points": llm_res.key_points,
            "provider": llm_res.provider,
            "verdict_tendency": llm_res.verdict_tendency,
            "discourse_type": getattr(llm_res, "discourse_type", "factual"),
            "discourse_label": getattr(llm_res, "discourse_label", "Relato Factual"),
            "semantic_comparison": sem_comp_clean,
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
        "limitations": _limitations(
            news, cls, rules, evidence_enabled=True,
            consensus_divergent=(consensus_status == "diverge_consenso" and not is_traditional),
        ),
    }

    if fact_res.get("failed"):
        technical["limitations"].append(
            "Parte da consulta a fontes externas não terminou no prazo; as evidências podem estar incompletas."
        )
    version = code_version()
    deadline.check()
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
        technical=sanitize_analysis_data(technical),
        model_version=cls.model_version,
        model_sha256=cls.model_sha256,
        rules_version=rules.version,
        calibrator_version=str(rules.calibrator.get("version", "none")),
        schema_version=SCHEMA_VERSION,
        code_version=version,
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
    deadline = _request_deadline()
    news = build_news_input(text=text, title=title, subtitle=subtitle)
    return _execute_pipeline(
        news=news,
        input_type=Analysis.InputType.TEXT,
        source_domain="",
        user=user,
        visitor_id=visitor_id,
        started=started,
        deadline=deadline,
    )


def run_url_analysis(*, url: str, user=None, visitor_id: str = "") -> Analysis:
    started = time.perf_counter()
    deadline = _request_deadline()
    scrape_deadline = deadline.child(8)
    scraped = scrape_deadline.call(scrape_url, url, deadline=scrape_deadline)
    logger.info("analysis stage=scrape ms=%.1f", (time.perf_counter() - started) * 1000)
    news = build_news_input(text=scraped.body, title=scraped.title, subtitle=scraped.subtitle)
    return _execute_pipeline(
        news=news,
        input_type=Analysis.InputType.URL,
        source_domain=scraped.domain,
        user=user,
        visitor_id=visitor_id,
        started=started,
        deadline=deadline,
    )
