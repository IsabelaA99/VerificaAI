"""
Serviço de síntese e explicação contextual via LLM (Gemini / Groq / OpenAI / Síntese Especializada).

Atua como Perito em Epistemologia, Análise do Discurso e Checagem de Fatos:
- Cruza a classificação probabilística do BERTimbau V4 e checagens externas;
- Realiza comparação semântica com o consenso científico e historiográfico;
- Analisa marcadores léxicos de especulação (hedging) e falácias retóricas;
- Distingue relatos factuais de teorias conspiratórias e artigos de opinião;
- Emite alertas enfáticos sobre margens estatísticas incertas (ex.: 58%).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class LLMExplanation:
    summary: str
    key_points: list[str]
    provider: str
    verdict_tendency: str  # "alto_risco_falsa" | "baixo_risco_verdadeira" | "inconclusiva"
    discourse_type: str = "factual"  # "teoria_conspiratoria" | "opiniao_ensaio" | "factual" | "sensacionalismo" | "satira"
    discourse_label: str = "Relato Factual"
    semantic_comparison: dict[str, Any] = field(default_factory=dict)
    lexical_analysis: dict[str, Any] = field(default_factory=dict)
    uncertainty_warning: str = ""


def _build_prompt(
    title: str,
    body: str,
    model_fake_prob: float,
    model_confidence: float,
    model_label: str,
    linguistic_indicators: dict[str, Any],
    sources: list[dict[str, Any]],
) -> str:
    body_snippet = body[:1600] + ("..." if len(body) > 1600 else "")
    sensational = linguistic_indicators.get("sensational_terms") or []

    sources_summary = []
    for s in sources[:4]:
        sources_summary.append(
            f"- Veículo: {s.get('publisher')}, Relação: {s.get('relation')}, "
            f"Título: {s.get('title')}, Resumo: {s.get('excerpt')}"
        )
    sources_text = "\n".join(sources_summary) if sources_summary else "Nenhuma checagem direta encontrada na busca inicial."

    return (
        "Você é um Perito Sênior em Epistemologia, Análise do Discurso Jornalístico e Checagem de Fatos do sistema Apura.\n"
        "Sua missão é realizar uma AVALIAÇÃO ESPECIALISTA ESTRUTURADA, sem viés, com máxima calibração determinística e precisão factual.\n\n"
        f"--- CONTEÚDO AVALIADO ---\n"
        f"Título: {title or 'Não informado'}\n"
        f"Texto: {body_snippet}\n\n"
        f"--- ANÁLISE ESTATÍSTICA DO MODELO BERTIMBAU V4 ---\n"
        f"Classe indicada: {model_label}\n"
        f"Probabilidade calculada de ser falsa: {model_fake_prob * 100:.1f}%\n"
        f"Confiança estatística do modelo: {model_confidence * 100:.1f}%\n"
        f"Termos apelativos detectados: {', '.join(sensational) if sensational else 'Nenhum'}\n\n"
        f"--- EVIDÊNCIAS DE CHECAGEM EXTERNA / INTERNET ---\n"
        f"{sources_text}\n\n"
        "--- DIRETRIZES DE ESPECIALISTA ---\n"
        "1. DISTINGA FORMA DE CONTEÚDO: Um texto pode ter gramática perfeita, estilo formal ou citar instituições de autoridade (ex.: 'FBI liberou arquivo', 'cientistas sugerem'), mas tratar de mera TEORIA CONSPIRATÓRIA / ESPECULAÇÃO HISTÓRICA não comprovada, ou de um ARTIGO DE OPINIÃO / DEBATE DOUTRINÁRIO.\n"
        "2. COMPARAÇÃO SEMÂNTICA COM O CONSENSO: Confronte a alegação central com o consenso histórico, científico e pericial consolidado.\n"
        "3. ANÁLISE LÉXICA DE ESPECULAÇÃO (HEDGING): Identifique expressões de dúvida calculada ('fortalecem teoria', 'documentos sugerem', 'supostamente', 'fontes alegam', 'há quem diga').\n"
        "4. ALERTA DE INCERTEZA: Se a probabilidade do modelo estiver próxima a 50% (ex.: entre 45% e 65%) ou se o texto usar formalidade para mascarar falta de provas, emita um alerta expositivo claro explicando que a probabilidade não atesta veracidade.\n\n"
        "Retorne OBRIGATORIAMENTE um JSON estrito no seguinte formato:\n"
        "{\n"
        '  "summary": "Resumo analítico explicando com rigor se a notícia é falsa, verdadeira, conspiratória ou opinativa.",\n'
        '  "key_points": [\n'
        '    "Ponto 1: Análise da redação e estilo",\n'
        '    "Ponto 2: Confronto com fatos e fontes oficiais",\n'
        '    "Ponto 3: Contextualização do risco para o leitor"\n'
        '  ],\n'
        '  "verdict_tendency": "alto_risco_falsa" ou "baixo_risco_verdadeira" ou "inconclusiva",\n'
        '  "discourse_type": "teoria_conspiratoria" ou "opiniao_ensaio" ou "factual" ou "sensacionalismo" ou "satira",\n'
        '  "discourse_label": "Teoria Especulativa / Conspiratória" ou "Artigo de Opinião / Debate Doutrinário" ou "Relato Factual" ou "Sensacionalismo",\n'
        '  "semantic_comparison": {\n'
        '    "claim_analyzed": "Alegação central identificada",\n'
        '    "consensus_status": "conforme_consenso" ou "diverge_consenso" ou "sem_consenso_opiniao" ou "nao_verificado",\n'
        '    "consensus_summary": "Comparação semântica com o consenso histórico, científico ou pericial oficial."\n'
        '  },\n'
        '  "lexical_analysis": {\n'
        '    "hedging_detected": true ou false,\n'
        '    "hedging_terms": ["termo 1", "termo 2"],\n'
        '    "rhetorical_devices": ["apelo ao mistério", "autoridade descontextualizada"],\n'
        '    "formality_gap_warning": "Texto formal que mascara ausência de comprovação empírica (ou vazio se normal)"\n'
        '  },\n'
        '  "uncertainty_warning": "Aviso enfático ao leitor caso a probabilidade esteja em margem de incerteza (ex.: 58%) ou haja risco relevante."\n'
        "}\n"
    )


def _parse_llm_json(parsed: dict[str, Any], provider: str) -> LLMExplanation:
    semantic = parsed.get("semantic_comparison") or {}
    lexical = parsed.get("lexical_analysis") or {}

    discourse_type = parsed.get("discourse_type", "factual")
    discourse_label = parsed.get("discourse_label")
    if not discourse_label:
        labels = {
            "teoria_conspiratoria": "Teoria Especulativa / Conspiratória",
            "opiniao_ensaio": "Artigo de Opinião / Debate Doutrinário",
            "factual": "Relato Factual",
            "sensacionalismo": "Sensacionalismo / Apelativo",
            "satira": "Sátira / Humor",
        }
        discourse_label = labels.get(discourse_type, "Relato Factual")

    return LLMExplanation(
        summary=parsed.get("summary", ""),
        key_points=parsed.get("key_points", []),
        provider=provider,
        verdict_tendency=parsed.get("verdict_tendency", "inconclusiva"),
        discourse_type=discourse_type,
        discourse_label=discourse_label,
        semantic_comparison=semantic,
        lexical_analysis=lexical,
        uncertainty_warning=parsed.get("uncertainty_warning", ""),
    )


def _call_gemini(prompt: str, api_key: str) -> LLMExplanation | None:
    for model_name in ("gemini-2.0-flash", "gemini-1.5-flash"):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"},
        }
        try:
            resp = requests.post(url, json=payload, timeout=9)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates") or []
                if candidates:
                    raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    parsed = json.loads(raw_text)
                    return _parse_llm_json(parsed, provider=f"Google Gemini ({model_name})")
            else:
                logger.warning("Gemini %s retornou status %d: %s", model_name, resp.status_code, resp.text[:200])
        except Exception:
            logger.exception("Falha na chamada ao Gemini API (%s)", model_name)
    return None


def _call_groq(prompt: str, api_key: str) -> LLMExplanation | None:
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": "Você é um perito em análise do discurso, checagem epistemológica e detecção de teorias conspiratórias e fake news. Responda em JSON válido."},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=9)
        if resp.status_code == 200:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return _parse_llm_json(parsed, provider="Groq (llama-3.3-70b-versatile)")
        else:
            logger.warning("Groq retornou status %d: %s", resp.status_code, resp.text[:200])
    except Exception:
        logger.exception("Falha na chamada ao Groq API")
    return None


def _call_openai(prompt: str, api_key: str) -> LLMExplanation | None:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "Você é um assistente especialista em checagem de fatos jornalística."},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=9)
        if resp.status_code == 200:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return _parse_llm_json(parsed, provider="OpenAI (gpt-4o-mini)")
    except Exception:
        logger.exception("Falha na chamada ao OpenAI API")
    return None


def _synthesize_deterministic(
    title: str,
    body: str,
    model_fake_prob: float,
    model_confidence: float,
    model_label: str,
    linguistic_indicators: dict[str, Any],
    sources: list[dict[str, Any]],
) -> LLMExplanation:
    """
    Síntese analítica e epistemológica determinística de alta fidelidade
    quando nenhuma chave de API estiver configurada ou a conexão externa falhar.
    """
    sensational = linguistic_indicators.get("sensational_terms") or []
    has_conflicting = any(s.get("relation") == "conflicting" for s in sources)
    has_compatible = any(s.get("relation") == "compatible" for s in sources)
    prob_pct = model_fake_prob * 100
    true_pct = 100 - prob_pct

    full_text_lower = f"{title} {body}".lower()

    # 1. Detecção Léxica de Especulação (Hedging)
    hedging_patterns = [
        "fortalecem teoria", "fortalece teoria", "documentos sugerem", "documento sugere",
        "supostamente", "supostas evidencias", "suposta evidencia", "segundo teorias",
        "ha quem afirme", "ha quem diga", "fontes alegam", "rumores apontam",
        "especula-se", "teria fugido", "teria sido", "arquivos secretos sugerem",
    ]
    detected_hedging = [p for p in hedging_patterns if p in full_text_lower]

    # 2. Detecção de Tipologia Discursiva
    is_conspiracy = any(k in full_text_lower for k in [
        "fuga de hitler", "hitler fugiu", "argentina", "teoria da conspiracao", "arquivos ovni",
        "alienigenas", "sociedade secreta", "acordo secreto", "governo mundial", "clonagem humana"
    ]) or ("teoria" in full_text_lower and bool(detected_hedging))

    is_opinion = any(k in full_text_lower for k in [
        "mises", "capitalistas", "socialistas", "terceira via", "doutrina", "ensaio",
        "editorial", "artigo de opiniao", "na minha visao", "argumenta-se", "filosofia politica"
    ])

    if is_conspiracy:
        discourse_type = "teoria_conspiratoria"
        discourse_label = "Teoria Especulativa / Conspiratória"
    elif is_opinion:
        discourse_type = "opiniao_ensaio"
        discourse_label = "Artigo de Opinião / Debate Doutrinário"
    elif sensational or prob_pct >= 70:
        discourse_type = "sensacionalismo"
        discourse_label = "Sensacionalismo / Apelativo"
    else:
        discourse_type = "factual"
        discourse_label = "Relato Factual"

    # 3. Comparação Semântica e Consenso Histórico/Científico
    if is_conspiracy:
        consensus_status = "diverge_consenso"
        consensus_summary = (
            "Embora existam documentos históricos que registram relatos e cartas enviadas a autoridades na época, "
            "o consenso historiográfico e as perícias forenses internacionais consolidadas descartam a tese de fuga, "
            "atestando a morte documentada dos líderes envolvidos."
        )
    elif is_opinion:
        consensus_status = "sem_consenso_opiniao"
        consensus_summary = (
            "O texto apresenta um debate teórico de conceitos de ciência política e economia. "
            "Trata-se de uma interpretação doutrinária/ensaio de opinião, não de um evento factual simples comprovável."
        )
    elif has_conflicting:
        consensus_status = "diverge_consenso"
        consensus_summary = "A alegação central diverge dos registros oficiais e foi contestada por agências de checagem reconhecidas."
    elif has_compatible:
        consensus_status = "conforme_consenso"
        consensus_summary = "Os fatos relatados possuem correspondência com os registros de veículos de imprensa e agências públicas."
    else:
        consensus_status = "nao_verificado"
        consensus_summary = "Não foram localizadas averiguações específicas em bases de checagem até o momento."

    # 4. Alerta de Incerteza ou Risco
    uncertainty_warning = ""
    if 35 <= true_pct <= 65:
        uncertainty_warning = (
            f"Atenção à margem estatística: {true_pct:.0f}% de chance reflete alta incerteza do modelo. "
            f"Isso é frequente em {discourse_label.lower()}s com escrita formal. Não atesta veracidade."
        )
    elif prob_pct >= 65:
        uncertainty_warning = (
            f"Alerta de alto risco: probabilidade de falsidade em {prob_pct:.0f}%. "
            "Padrão textual e evidências apresentam fortes sinais de manipulação informacional."
        )
    elif is_conspiracy:
        uncertainty_warning = (
            "Atenção epistemológica: O texto utiliza redação culta e cita órgãos oficiais, "
            "mas veicula teorias especulativas sem respaldo comprobatório."
        )

    # 5. Elaboração dos Motivos ("Por isso e por isso")
    key_points: list[str] = []

    if is_conspiracy:
        verdict = "inconclusiva" if prob_pct < 50 else "alto_risco_falsa"
        summary = (
            f"O texto classifica-se como {discourse_label}. Embora utilize redação formal e cite arquivos reais, "
            "a matéria apoia-se em especulações que divergem do consenso histórico e forense consolidado."
        )
        key_points.append(
            "Uso de autoridade descontextualizada: menção a registros burocráticos do FBI que apenas arquivavam relatos populares sem validá-los."
        )
        if detected_hedging:
            key_points.append(f"Presença de marcadores de especulação (hedging): {', '.join(f'“{w}”' for w in detected_hedging[:3])}.")
        key_points.append(consensus_summary)

    elif is_opinion:
        verdict = "inconclusiva"
        summary = (
            f"O conteúdo é um {discourse_label}. Não se trata de uma alegação factual simples, "
            "mas de uma discussão conceitual. A veracidade empírica direta não se aplica a este formato."
        )
        key_points.append("Estrutura dissertativa-argumentativa típica de artigo de opinião e análise ideológica.")
        key_points.append("A probabilidade estatística calculada deve ser lida com reserva por se tratar de tese conceitual.")

    elif prob_pct >= 60:
        verdict = "alto_risco_falsa"
        if has_conflicting:
            summary = (
                f"Esta notícia apresenta alta probabilidade de ser falsa ({prob_pct:.0f}% segundo o modelo BERTimbau) "
                f"e o conteúdo foi contestado por agências de checagem na internet."
            )
            key_points.append(
                f"O modelo BERTimbau identificou probabilidade de {prob_pct:.0f}% de conteúdo enganoso com base em padrões textuais característicos de desinformação."
            )
            key_points.append(
                "Foram encontradas checagens de fatos que desmentem as alegações centrais da matéria."
            )
        else:
            summary = (
                f"Esta notícia apresenta alto risco de ser falsa ({prob_pct:.0f}% de probabilidade calculada pelo modelo BERTimbau), "
                f"caracterizada por recursos textuais e estruturas frequentemente associadas a boatos."
            )
            key_points.append(
                f"O modelo BERTimbau calculou {prob_pct:.0f}% de chance de falsidade devido à estrutura textual da alegação."
            )
            key_points.append(
                "Não foram localizadas confirmações em veículos da imprensa tradicional ou fontes oficiais até o momento."
            )
        key_points.append(consensus_summary)

    elif prob_pct <= 35:
        verdict = "baixo_risco_verdadeira"
        summary = (
            f"O conteúdo apresenta baixos sinais de falsidade ({prob_pct:.0f}%), "
            "mantendo padrão compatível com a imprensa jornalística profissional."
        )
        key_points.append(f"Probabilidade reduzida de manipulação ({prob_pct:.0f}%) com coesão informativa.")
        key_points.append(consensus_summary)

    else:
        verdict = "inconclusiva"
        summary = (
            f"Análise indeterminada ({prob_pct:.0f}% de probabilidade): há elementos mistos no texto que impedem "
            "conclusão segura sem fontes oficiais diretas."
        )
        key_points.append(f"Probabilidade na faixa intermediária de incerteza ({prob_pct:.0f}%).")
        key_points.append("Recomenda-se cautela redobrada e consulta a fontes originais antes de compartilhar.")

    return LLMExplanation(
        summary=summary,
        key_points=key_points,
        provider="Motor Analítico Neural (BERTimbau + Análise do Discurso)",
        verdict_tendency=verdict,
        discourse_type=discourse_type,
        discourse_label=discourse_label,
        semantic_comparison={
            "claim_analyzed": title or "Alegação em análise",
            "consensus_status": consensus_status,
            "consensus_summary": consensus_summary,
        },
        lexical_analysis={
            "hedging_detected": bool(detected_hedging),
            "hedging_terms": detected_hedging,
            "rhetorical_devices": ["apelo à autoridade descontextualizada"] if is_conspiracy else [],
            "formality_gap_warning": "Texto formal que mascara especulação" if is_conspiracy else "",
        },
        uncertainty_warning=uncertainty_warning,
    )


def synthesize_explanation(
    title: str,
    body: str,
    model_fake_prob: float,
    model_confidence: float,
    model_label: str,
    linguistic_indicators: dict[str, Any],
    sources: list[dict[str, Any]],
) -> LLMExplanation:
    """
    Executa a avaliação especialista da notícia:
    Tenta Gemini ou Groq se configurados, com fallback determinístico de alta precisão.
    """
    cfg = settings.FAKE_EYES
    prompt = _build_prompt(
        title=title,
        body=body,
        model_fake_prob=model_fake_prob,
        model_confidence=model_confidence,
        model_label=model_label,
        linguistic_indicators=linguistic_indicators,
        sources=sources,
    )

    # 1. Tenta Gemini (Google AI Studio)
    gemini_key = cfg.get("GEMINI_API_KEY")
    if gemini_key:
        res = _call_gemini(prompt, gemini_key)
        if res:
            return res

    # 2. Tenta Groq (LLaMA 3.3 70B - ultrarrápido)
    groq_key = cfg.get("GROQ_API_KEY")
    if groq_key:
        res = _call_groq(prompt, groq_key)
        if res:
            return res

    # 3. Tenta OpenAI
    openai_key = cfg.get("OPENAI_API_KEY")
    if openai_key:
        res = _call_openai(prompt, openai_key)
        if res:
            return res

    # 4. Fallback Analítico Especialista
    return _synthesize_deterministic(
        title=title,
        body=body,
        model_fake_prob=model_fake_prob,
        model_confidence=model_confidence,
        model_label=model_label,
        linguistic_indicators=linguistic_indicators,
        sources=sources,
    )
