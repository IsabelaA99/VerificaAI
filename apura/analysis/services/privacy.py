"""Mascaramento dos dados derivados antes de persistir ou expor uma análise."""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from .preprocessing import mask_pii


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


def sanitize_analysis_data(value: Any, *, field: str = "") -> Any:
    """Mascara PII em textos aninhados sem transformar identificadores e números.

    Um endereço que contém PII é omitido: substituir só um trecho dele criaria
    um link diferente e potencialmente enganoso. A checagem inclui escapes de URL.
    """
    if isinstance(value, dict):
        return {key: sanitize_analysis_data(item, field=key) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_analysis_data(item, field=field) for item in value]
    if isinstance(value, str):
        if field == "url" and _url_contains_pii(value):
            return ""
        return mask_pii(value)
    return value
