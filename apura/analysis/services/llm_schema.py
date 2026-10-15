"""Contrato estrutural da síntese, validado antes de confiar na resposta externa."""

from typing import Any


MAX_SUMMARY_CHARS = 4000
MAX_POINT_CHARS = 1000
MAX_POINTS = 10
MAX_DETAIL_CHARS = 4000
MAX_TERM_CHARS = 200
MAX_TERMS = 20

VERDICTS = frozenset({"alto_risco_falsa", "baixo_risco_verdadeira", "inconclusiva"})
DISCOURSE_TYPES = frozenset({"teoria_conspiratoria", "opiniao_ensaio", "factual", "sensacionalismo", "satira"})
CONSENSUS_STATUSES = frozenset({"conforme_consenso", "diverge_consenso", "sem_consenso_opiniao", "nao_verificado"})


class InvalidLLMResponse(ValueError):
    """A resposta é JSON, mas não atende ao contrato da aplicação."""


def validate_llm_payload(payload: Any, *, check_limits: bool = True) -> dict[str, Any]:
    """Devolve uma cópia com campos conhecidos e tipos seguros, sem coerções.

    Summary e key_points são obrigatórios. Campos opcionais ausentes recebem
    defaults neutros; null e tipos incorretos são rejeitados. Na leitura de
    registros anteriores, check_limits=False evita descartar textos que foram
    expandidos pelo mascaramento, mantendo a validação de tipos e enums.
    """
    if not isinstance(payload, dict):
        raise InvalidLLMResponse("A resposta deve ser um objeto.")

    def text(value, path, maximum, *, allow_blank=True):
        if not isinstance(value, str):
            raise InvalidLLMResponse(f"{path} deve ser texto.")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise InvalidLLMResponse(f"{path} contém Unicode inválido.") from None
        if check_limits and len(value) > maximum:
            raise InvalidLLMResponse(f"{path} excede o limite de caracteres.")
        value = value.strip()
        if not allow_blank and not value:
            raise InvalidLLMResponse(f"{path} não pode ficar vazio.")
        return value

    def texts(value, path, maximum_items, maximum_chars):
        if not isinstance(value, list):
            raise InvalidLLMResponse(f"{path} deve ser uma lista de textos.")
        if check_limits and len(value) > maximum_items:
            raise InvalidLLMResponse(f"{path} excede o limite de itens.")
        return [text(item, path, maximum_chars, allow_blank=False) for item in value]

    def choice(value, path, allowed):
        value = text(value, path, 100, allow_blank=False)
        if value not in allowed:
            raise InvalidLLMResponse(f"{path} contém um valor não permitido.")
        return value

    def obj(key):
        value = payload.get(key, {})
        if not isinstance(value, dict):
            raise InvalidLLMResponse(f"{key} deve ser um objeto.")
        return value

    semantic = obj("semantic_comparison")
    lexical = obj("lexical_analysis")
    hedging_detected = lexical.get("hedging_detected", False)
    if type(hedging_detected) is not bool:
        raise InvalidLLMResponse("lexical_analysis.hedging_detected deve ser booleano.")

    return {
        "summary": text(payload.get("summary"), "summary", MAX_SUMMARY_CHARS, allow_blank=False),
        "key_points": texts(payload.get("key_points"), "key_points", MAX_POINTS, MAX_POINT_CHARS),
        "verdict_tendency": choice(payload.get("verdict_tendency", "inconclusiva"), "verdict_tendency", VERDICTS),
        "discourse_type": choice(payload.get("discourse_type", "factual"), "discourse_type", DISCOURSE_TYPES),
        "discourse_label": text(payload.get("discourse_label", ""), "discourse_label", MAX_TERM_CHARS),
        "uncertainty_warning": text(payload.get("uncertainty_warning", ""), "uncertainty_warning", MAX_DETAIL_CHARS),
        "semantic_comparison": {
            "claim_analyzed": text(semantic.get("claim_analyzed", ""), "semantic_comparison.claim_analyzed", MAX_DETAIL_CHARS),
            "consensus_status": choice(semantic.get("consensus_status", "nao_verificado"), "semantic_comparison.consensus_status", CONSENSUS_STATUSES),
            "consensus_summary": text(semantic.get("consensus_summary", ""), "semantic_comparison.consensus_summary", MAX_DETAIL_CHARS),
        },
        "lexical_analysis": {
            "hedging_detected": hedging_detected,
            "hedging_terms": texts(lexical.get("hedging_terms", []), "lexical_analysis.hedging_terms", MAX_TERMS, MAX_TERM_CHARS),
            "rhetorical_devices": texts(lexical.get("rhetorical_devices", []), "lexical_analysis.rhetorical_devices", MAX_TERMS, MAX_TERM_CHARS),
            "formality_gap_warning": text(lexical.get("formality_gap_warning", ""), "lexical_analysis.formality_gap_warning", MAX_DETAIL_CHARS),
        },
    }
