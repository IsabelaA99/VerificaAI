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

from .llm_schema import validate_llm_payload
from .preprocessing import mask_pii
from .timing import Deadline, DeadlineExceeded, ServiceBusy

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


def is_traditional_press_domain(domain: str) -> bool:
    """Verifica se o domínio pertence a um veículo reconhecido da imprensa tradicional."""
    if not domain:
        return False
    domain = domain.lower().strip()
    press_suffixes = (
        "globo.com", "g1.globo.com", "oglobo.globo.com", "uol.com.br", "folha.com.br", "folha.uol.com.br",
        "estadao.com.br", "cnnbrasil.com.br", "cnn.com", "bbc.com", "reuters.com", "ebc.com.br",
        "agenciabrasil.ebc.com.br", "metropoles.com", "poder360.com.br", "cartacapital.com.br",
        "abril.com.br", "veja.abril.com.br", "exame.com", "elpais.com", "dw.com", "rfi.fr",
        "r7.com", "terra.com.br", "band.uol.com.br", "sbtnews.com.br", "jovempan.com.br",
        "valor.globo.com", "noticias.uol.com.br",
    )
    return any(domain == p or domain.endswith("." + p) for p in press_suffixes)


def _build_prompt(
    title: str,
    body: str,
    model_fake_prob: float,
    model_confidence: float,
    model_label: str,
    linguistic_indicators: dict[str, Any],
    sources: list[dict[str, Any]],
    source_domain: str = "",
) -> str:
    safe_body = mask_pii(body)
    body_snippet = safe_body[:1600] + ("..." if len(safe_body) > 1600 else "")
    sensational = [mask_pii(term) for term in linguistic_indicators.get("sensational_terms") or []]

    sources_summary = []
    for s in sources[:4]:
        sources_summary.append(
            f"- Veículo: {mask_pii(str(s.get('publisher') or ''))}, Relação: {s.get('relation')}, "
            f"Título: {mask_pii(str(s.get('title') or ''))}, Resumo: {mask_pii(str(s.get('excerpt') or ''))}"
        )
    sources_text = "\n".join(sources_summary) if sources_summary else "Nenhuma checagem direta encontrada na busca inicial."

    press_guidance = ""
    if is_traditional_press_domain(source_domain):
        press_guidance = (
            f"--- ESCOPO DE IMPRENSA TRADICIONAL ---\n"
            f"O conteúdo avaliado é proveniente de veículo da IMPRENSA TRADICIONAL ({source_domain}).\n"
            "O classificador BERTimbau foi treinado especificamente com matérias da imprensa tradicional.\n"
            "Diretrizes estritas para este conteúdo:\n"
            "- discourse_type DEVE SER OBRIGATORIAMENTE 'factual' ('Relato Factual').\n"
            "- consensus_status DEVE SER 'conforme_consenso'.\n"
            "- NUNCA classifique matérias da imprensa tradicional como 'teoria_conspiratoria' nem 'sensacionalismo'.\n"
            "- NUNCA emita 'uncertainty_warning' nem alegue divergência de consenso histórico para notícias cotidianas da imprensa tradicional.\n"
            "- Respeite a probabilidade tradicional calculada pelo modelo BERTimbau.\n\n"
        )

    return (
        "Você é um Perito Sênior em Epistemologia, Análise do Discurso Jornalístico e Checagem de Fatos do sistema Apura.\n"
        "Sua missão é realizar uma AVALIAÇÃO ESPECIALISTA ESTRUTURADA, sem viés, com máxima calibração determinística e precisão factual.\n\n"
        f"{press_guidance}"
        f"--- CONTEÚDO AVALIADO ---\n"
        f"Título: {mask_pii(title) or 'Não informado'}\n"
        f"Texto: {body_snippet}\n\n"
        f"--- ANÁLISE ESTATÍSTICA DO MODELO BERTIMBAU V4 ---\n"
        f"Classe indicada: {model_label}\n"
        f"Probabilidade calculada de ser falsa: {model_fake_prob * 100:.1f}%\n"
        f"Confiança estatística do modelo: {model_confidence * 100:.1f}%\n"
        f"Termos apelativos detectados: {', '.join(sensational) if sensational else 'Nenhum'}\n\n"
        f"--- EVIDÊNCIAS DE CHECAGEM EXTERNA / INTERNET ---\n"
        f"{sources_text}\n\n"
        "1. DISTINGA FORMA DE CONTEÚDO: Um texto pode ter gramática perfeita, estilo formal ou citar autoridades, mas tratar de:\n"
        "   - TEORIA CONSPIRATÓRIA / ESPECULAÇÃO HISTÓRICA não comprovada;\n"
        "   - ARTIGO DE OPINIÃO / DEBATE DOUTRINÁRIO;\n"
        "   - SÁTIRA / HUMOR JORNALÍSTICO (ex.: Laranjas News, Sensacionalista, The Onion que simulam notícias formais com fatos fictícios e cômicos). Se for sátira/humor, classifique OBRIGATORIAMENTE discourse_type como 'satira' e consensus_status como 'diverge_consenso'.\n"
        "2. COMPARAÇÃO SEMÂNTICA COM O CONSENSO: Confronte a alegação central com o consenso histórico, científico e pericial consolidado.\n"
        "3. ANÁLISE LÉXICA DE ESPECULAÇÃO (HEDGING): Identifique expressões de dúvida calculada ('fortalecem teoria', 'documentos sugerem', 'supostamente', 'fontes alegam', 'há quem diga').\n"
        "4. ALERTA DE INCERTEZA: Se a probabilidade do modelo estiver próxima a 50% (ex.: entre 45% e 65%) ou se o texto usar formalidade para mascarar falta de provas, emita um alerta expositivo claro explicando que a probabilidade não atesta veracidade.\n\n"
        "Retorne OBRIGATORIAMENTE um JSON estrito no seguinte formato:\n"
        "{\n"
        '  "summary": "Resumo analítico explicando com rigor se a notícia é falsa, verdadeira, conspiratória, opinativa ou satírica.",\n'
        '  "key_points": [\n'
        '    "Ponto 1: Análise da redação e estilo",\n'
        '    "Ponto 2: Confronto com fatos e fontes oficiais",\n'
        '    "Ponto 3: Contextualização do risco para o leitor"\n'
        '  ],\n'
        '  "verdict_tendency": "alto_risco_falsa" ou "baixo_risco_verdadeira" ou "inconclusiva",\n'
        '  "discourse_type": "teoria_conspiratoria" ou "opiniao_ensaio" ou "factual" ou "sensacionalismo" ou "satira",\n'
        '  "discourse_label": "Teoria Especulativa / Conspiratória" ou "Artigo de Opinião / Debate Doutrinário" ou "Relato Factual" ou "Sensacionalismo" ou "Sátira / Humor Jornalístico",\n'
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


def is_satirical_domain(domain: str) -> bool:
    """Verifica se o domínio é conhecido por publicar sátiras, humor ou paródias fictícias."""
    if not domain:
        return False
    domain = domain.lower().strip()
    keywords = ("laranjas", "sensacionalista", "theonion", "babylonbee", "piauiconherald", "humor")
    return any(k in domain for k in keywords)


def _parse_llm_json(parsed: dict[str, Any], provider: str, source_domain: str = "") -> LLMExplanation:
    # O erro de contrato é capturado pelo provedor, permitindo tentar outro ou
    # recorrer à síntese local antes que qualquer conteúdo inválido seja salvo.
    parsed = validate_llm_payload(parsed)
    semantic = parsed["semantic_comparison"]
    lexical = parsed["lexical_analysis"]

    summary_lower = parsed["summary"].lower()
    discourse_raw = parsed["discourse_type"].lower()
    is_traditional = is_traditional_press_domain(source_domain) and not is_satirical_domain(source_domain)

    if (
        is_satirical_domain(source_domain)
        or any(k in discourse_raw for k in ("satir", "humor", "parod", "fictici", "comedi", "piada"))
        or "satíric" in summary_lower
        or "sátira" in summary_lower
        or "paródia" in summary_lower
    ):
        discourse_type = "satira"
        discourse_label = "Sátira / Humor Jornalístico"
        if isinstance(semantic, dict):
            semantic["consensus_status"] = "diverge_consenso"
            if not semantic.get("consensus_summary"):
                semantic["consensus_summary"] = "O conteúdo é uma peça de humor/sátira ficcional sem correspondência com fatos reais."
        uncertainty_warning = (
            "Atenção: Conteúdo satírico / paródia de humor. O modelo BERTimbau avalia apenas a norma culta "
            "do estilo jornalístico, mas os fatos narrados são intencionalmente fictícios."
        )
    elif is_traditional:
        discourse_type = "factual"
        discourse_label = "Relato Factual"
        semantic["consensus_status"] = "conforme_consenso"
        if not semantic.get("consensus_summary") or "diverge" in semantic.get("consensus_summary", "").lower():
            semantic["consensus_summary"] = "Compatível com a cobertura factual da imprensa tradicional."
        uncertainty_warning = ""
    else:
        if any(k in discourse_raw for k in ("conspir", "especul", "boato")):
            discourse_type = "teoria_conspiratoria"
            discourse_label = "Teoria Especulativa / Conspiratória"
        elif any(k in discourse_raw for k in ("opin", "ensaio", "doutrin", "editorial", "artigo")):
            discourse_type = "opiniao_ensaio"
            discourse_label = "Artigo de Opinião / Debate Doutrinário"
        elif any(k in discourse_raw for k in ("sensacional", "apelativ")):
            discourse_type = "sensacionalismo"
            discourse_label = "Sensacionalismo / Apelativo"
        else:
            discourse_type = "factual"
            discourse_label = "Relato Factual"
        uncertainty_warning = parsed.get("uncertainty_warning", "")

    return LLMExplanation(
        summary=parsed.get("summary", ""),
        key_points=parsed.get("key_points", []),
        provider=provider,
        verdict_tendency=parsed.get("verdict_tendency", "inconclusiva"),
        discourse_type=discourse_type,
        discourse_label=discourse_label,
        semantic_comparison=semantic,
        lexical_analysis=lexical,
        uncertainty_warning=uncertainty_warning,
    )


def _call_gemini(prompt: str, api_key: str, source_domain: str = "", *, deadline: Deadline | None = None) -> LLMExplanation | None:
    deadline = deadline or Deadline.after(7)
    for model_name in ("gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"):
        if deadline.remaining <= 0:
            break
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"},
        }
        try:
            resp = requests.post(url, json=payload, timeout=deadline.timeout(4))
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates") or []
                if candidates:
                    raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    parsed = json.loads(raw_text)
                    return _parse_llm_json(parsed, provider=f"Google Gemini ({model_name})", source_domain=source_domain)
            else:
                logger.warning("Gemini %s retornou status %d", model_name, resp.status_code)
                if resp.status_code in (401, 403, 429):
                    break
        except Exception as exc:
            logger.warning("Falha na chamada ao Gemini API (%s): %s", model_name, type(exc).__name__)
            break
    return None


def _call_groq(prompt: str, api_key: str, source_domain: str = "", *, deadline: Deadline | None = None) -> LLMExplanation | None:
    deadline = deadline or Deadline.after(7)
    for model_name in ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b", "llama-3.3-70b-versatile"):
        if deadline.remaining <= 0:
            break
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "Você é um perito em análise do discurso, checagem epistemológica e detecção de teorias conspiratórias e fake news. Responda em JSON válido."},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
        }
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=deadline.timeout(5))
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                return _parse_llm_json(parsed, provider=f"Groq ({model_name})", source_domain=source_domain)
            else:
                logger.warning("Groq (%s) retornou status %d", model_name, resp.status_code)
                if resp.status_code in (401, 403, 429):
                    break
        except Exception as exc:
            logger.warning("Falha na chamada ao Groq API (%s): %s", model_name, type(exc).__name__)
            break
    return None


def _call_openai(prompt: str, api_key: str, source_domain: str = "", *, deadline: Deadline | None = None) -> LLMExplanation | None:
    deadline = deadline or Deadline.after(7)
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
        resp = requests.post(url, headers=headers, json=payload, timeout=deadline.timeout(5))
        if resp.status_code == 200:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return _parse_llm_json(parsed, provider="OpenAI (gpt-4o-mini)", source_domain=source_domain)
    except Exception as exc:
        logger.warning("Falha na chamada ao OpenAI API: %s", type(exc).__name__)
    return None


def _synthesize_deterministic(
    title: str,
    body: str,
    model_fake_prob: float,
    model_confidence: float,
    model_label: str,
    linguistic_indicators: dict[str, Any],
    sources: list[dict[str, Any]],
    source_domain: str = "",
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
    is_traditional = is_traditional_press_domain(source_domain)

    # 1. Detecção Léxica de Especulação (Hedging)
    hedging_patterns = [
        "fortalecem teoria", "fortalece teoria", "documentos sugerem", "documento sugere",
        "supostamente", "supostas evidencias", "suposta evidencia", "segundo teorias",
        "ha quem afirme", "ha quem diga", "fontes alegam", "rumores apontam",
        "especula-se", "teria fugido", "teria sido", "arquivos secretos sugerem",
    ]
    detected_hedging = [p for p in hedging_patterns if p in full_text_lower]

    # 2. Detecção de Tipologia Discursiva (termos explícitos e inequívocos)
    is_satire = is_satirical_domain(source_domain) or any(k in full_text_lower for k in ("laranjas", "sensacionalista", "sátira", "satira"))
    if is_satire:
        is_conspiracy = False
        is_opinion = False
        discourse_type = "satira"
        discourse_label = "Sátira / Humor Jornalístico"
    elif is_traditional:
        is_conspiracy = False
        is_opinion = False
        discourse_type = "factual"
        discourse_label = "Relato Factual"
    else:
        is_conspiracy = any(k in full_text_lower for k in [
            "fuga de hitler", "hitler fugiu para", "teoria da conspiracao", "teoria da conspiração",
            "terra plana", "reptilianos", "alienigenas na terra", "governo mundial secreto",
            "chips em vacinas", "clonagem humana secreta", "illuminati"
        ]) or ("teoria da conspiração" in full_text_lower and bool(detected_hedging))

        is_opinion = any(k in full_text_lower for k in [
            "mises", "doutrina", "ensaio de opiniao", "editorial", "artigo de opiniao",
            "artigo de opinião", "na minha visao", "na minha visão", "filosofia politica"
        ])

        if is_conspiracy:
            discourse_type = "teoria_conspiratoria"
            discourse_label = "Teoria Especulativa / Conspiratória"
        elif is_opinion:
            discourse_type = "opiniao_ensaio"
            discourse_label = "Artigo de Opinião / Debate Doutrinário"
        elif not is_traditional and (sensational or prob_pct >= 70):
            discourse_type = "sensacionalismo"
            discourse_label = "Sensacionalismo / Apelativo"
        else:
            discourse_type = "factual"
            discourse_label = "Relato Factual"

    # 3. Comparação Semântica e Consenso Histórico/Científico
    if is_satire:
        consensus_status = "diverge_consenso"
        consensus_summary = "O conteúdo é uma peça de humor/sátira ficcional sem correspondência com fatos reais."
        uncertainty_warning = (
            "Atenção: Conteúdo satírico / paródia de humor. O modelo avalia apenas a forma culta da escrita, "
            "mas a alegação é ficcional."
        )
    elif is_conspiracy:
        consensus_status = "diverge_consenso"
        if "hitler" in full_text_lower:
            consensus_summary = (
                "O consenso historiográfico e as perícias forenses internacionais consolidadas "
                "descartam teses de fuga após a Segunda Guerra Mundial."
            )
        else:
            consensus_summary = (
                "A tese apresentada carece de respaldo documental e contradiz o consenso científico ou histórico consolidado."
            )
    elif is_opinion:
        consensus_status = "sem_consenso_opiniao"
        consensus_summary = (
            "O texto apresenta um debate teórico de conceitos ou análise opinativa, não um relato factual objetivo."
        )
    elif has_conflicting:
        consensus_status = "diverge_consenso"
        consensus_summary = "A alegação central diverge dos registros oficiais e foi contestada por agências de checagem reconhecidas."
    elif has_compatible:
        consensus_status = "conforme_consenso"
        consensus_summary = "Os fatos relatados possuem correspondência com os registros de veículos de imprensa e agências públicas."
    else:
        consensus_status = "conforme_consenso" if discourse_type == "factual" else "nao_verificado"
        consensus_summary = (
            "Estrutura e cobertura condizentes com os padrões da imprensa tradicional."
            if discourse_type == "factual"
            else "Não foram localizadas averiguações específicas em bases de checagem até o momento."
        )

    # 4. Alerta de Incerteza ou Risco
    uncertainty_warning = ""
    if is_conspiracy:
        uncertainty_warning = (
            "Atenção epistemológica: O texto utiliza redação formal, mas veicula teorias especulativas sem respaldo comprobatório."
        )
    elif 35 <= true_pct <= 65:
        uncertainty_warning = (
            f"Atenção à margem estatística: {true_pct:.0f}% de chance reflete indefinição do modelo. "
            "Recomenda-se checagem em fontes primárias antes de qualquer conclusão."
        )
    elif prob_pct >= 65:
        uncertainty_warning = (
            f"Alerta de alto risco: probabilidade de falsidade em {prob_pct:.0f}%. "
            "Padrão textual e evidências apresentam fortes sinais de manipulação informacional."
        )

    # 5. Elaboração dos Motivos ("Por isso e por isso")
    key_points: list[str] = []

    if is_conspiracy:
        verdict = "inconclusiva" if prob_pct < 50 else "alto_risco_falsa"
        summary = (
            f"O texto classifica-se como {discourse_label}. Embora utilize redação formal, "
            "a matéria apoia-se em especulações que divergem do consenso documental ou científico consolidado."
        )
        if "fbi" in full_text_lower:
            key_points.append(
                "Uso de autoridade descontextualizada: menção a registros burocráticos do FBI que apenas arquivavam relatos populares sem validá-los."
            )
        else:
            key_points.append("Uso de alegações especulativas sem comprovação documental ou científica.")
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
            f"O conteúdo apresenta baixos sinais de falsidade ({prob_pct:.1f}%), "
            "mantendo padrão compatível com a imprensa jornalística profissional."
        )
        key_points.append(f"Probabilidade reduzida de manipulação ({prob_pct:.1f}%) com coesão informativa.")
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
    source_domain: str = "",
    *,
    deadline: Deadline | None = None,
) -> LLMExplanation:
    """
    Executa a avaliação especialista da notícia:
    Prioriza Groq (ultrarrápido com modelos ativos) ou Gemini se configurados,
    com fallback determinístico de alta precisão.
    """
    cfg = settings.FAKE_EYES
    deadline = deadline or Deadline.after(7)
    prompt = _build_prompt(
        title=title,
        body=body,
        model_fake_prob=model_fake_prob,
        model_confidence=model_confidence,
        model_label=model_label,
        linguistic_indicators=linguistic_indicators,
        sources=sources,
        source_domain=source_domain,
    )

    # Todos os provedores compartilham o mesmo prazo, inclusive suas retentativas.
    for key_name, provider in (
        ("GROQ_API_KEY", _call_groq),
        ("GEMINI_API_KEY", _call_gemini),
        ("OPENAI_API_KEY", _call_openai),
    ):
        key = cfg.get(key_name)
        if not key:
            continue
        try:
            res = deadline.call(provider, prompt, key, source_domain=source_domain, deadline=deadline)
        except (DeadlineExceeded, ServiceBusy):
            break
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
        source_domain=source_domain,
    )
