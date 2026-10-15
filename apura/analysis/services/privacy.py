"""Mascaramento dos dados derivados antes de persistir ou expor uma análise."""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from .preprocessing import mask_pii


# Apenas campos que podem conter texto da pessoa ou da síntese. Metadados como
# id, provider, versões, hashes, datas e enums não entram nessa lista.
_NARRATIVE_FIELDS = frozenset({
    "summary", "claim_summary", "key_points", "explanation", "limitations", "recommendations",
    "message", "discourse_label", "uncertainty_warning", "sensational_terms",
    "publisher", "title", "subtitle", "excerpt", "relation_reason",
    "claim_analyzed", "consensus_summary", "hedging_terms", "rhetorical_devices", "formality_gap_warning",
})
# Esses dois blocos admitem textos livres aninhados, inclusive campos extras.
_FREE_TEXT_OBJECTS = frozenset({"semantic_comparison", "lexical_analysis"})
_STRUCTURAL_FIELDS_IN_FREE_TEXT = frozenset({"consensus_status", "hedging_detected"})


def _url_contains_pii(url: str) -> bool:
    decoded = url
    for _ in range(4):
        if mask_pii(decoded) != decoded:
            return True
        expanded = unquote(decoded)
        if expanded == decoded:
            break
        decoded = expanded
    return False


def _sanitize(value: Any, *, field: str, narrative: bool) -> Any:
    if field in _STRUCTURAL_FIELDS_IN_FREE_TEXT:
        narrative = False
    else:
        narrative = narrative or field in _NARRATIVE_FIELDS or field in _FREE_TEXT_OBJECTS
    if isinstance(value, dict):
        return {key: _sanitize(item, field=key, narrative=narrative) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize(item, field=field, narrative=narrative) for item in value]
    if isinstance(value, str):
        if field == "url":
            return "" if _url_contains_pii(value) else value
        if narrative:
            return mask_pii(value)
    return value


def sanitize_analysis_data(value: Any, *, field: str = "") -> Any:
    """Mascara campos narrativos e preserva os metadados do contrato da análise.

    Um endereço que contém PII é omitido: substituir só um trecho dele criaria
    um link diferente e potencialmente enganoso. A checagem inclui escapes de URL.
    Novos campos narrativos do contrato devem ser incluídos na lista acima.
    """
    return _sanitize(value, field=field, narrative=False)
