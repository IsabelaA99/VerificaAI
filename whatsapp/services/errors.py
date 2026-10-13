"""Erros da API do Apura, classificados nos mesmos cenários da interface web (RF27).

A API devolve ``{"error": {"code", "message", "action", "field", "details"}}``, com o código
"estável para a interface". O chatbot decide pelo CÓDIGO; mensagem e ação da API só entram quando
o código é desconhecido (o back end ainda pode ganhar códigos novos nas Etapas 2 e 3).
"""

from __future__ import annotations

from typing import Any

# Códigos que existem no back end hoje (verificAI, commit 63a0382).
CODE_TO_SCENARIO: dict[str, str] = {
    "empty_input": "text_insufficient",
    "text_too_short": "text_insufficient",
    "text_too_long": "text_too_long",
    "unreadable_input": "text_unreadable",
    "unsupported_language": "unsupported_language",
    "url_input_unavailable": "url_unavailable",
    "analysis_unavailable": "api_unavailable",
    "analysis_not_found": "not_found",
    "throttled": "rate_limited",
}

# PROPOSTA — estes códigos AINDA NÃO EXISTEM no back end (Etapas 2 e 3). São os mesmos que a
# interface web assume. Confirmar ou trocar com quem constrói o back end.
PROPOSED_CODE_TO_SCENARIO: dict[str, str] = {
    "invalid_url": "invalid_url",
    "page_unreachable": "page_unreachable",
    "page_blocked": "page_unreachable",
    "page_paywalled": "page_unreachable",
    "page_not_text": "page_unreachable",
    "evidence_unavailable": "evidence_failure",
}


class ApuraApiError(Exception):
    """Falha ao falar com a API, já classificada em um cenário."""

    def __init__(
        self,
        scenario: str,
        *,
        code: str = "",
        status: int = 0,
        field: str | None = None,
        details: dict[str, Any] | None = None,
        retry_after_seconds: int | None = None,
        api_message: str = "",
        api_action: str = "",
    ) -> None:
        # A mensagem da exceção é só o cenário: o texto da API nunca vai parar em log por acidente.
        super().__init__(scenario)
        self.scenario = scenario
        self.code = code or scenario
        self.status = status
        self.field = field
        self.details = details or {}
        self.retry_after_seconds = retry_after_seconds
        self.api_message = api_message
        self.api_action = api_action


def classify_failure(status: int, body: Any, retry_after_seconds: int | None = None) -> ApuraApiError:
    """Classifica uma resposta de erro HTTP da API."""
    envelope = body.get("error") if isinstance(body, dict) else None
    envelope = envelope if isinstance(envelope, dict) else {}
    code = envelope.get("code") if isinstance(envelope.get("code"), str) else ""
    field = envelope.get("field") if isinstance(envelope.get("field"), str) else None
    details = envelope.get("details") if isinstance(envelope.get("details"), dict) else {}
    base: dict[str, Any] = {
        "code": code,
        "status": status,
        "field": field,
        "details": dict(details),
        "retry_after_seconds": retry_after_seconds,
        "api_message": envelope.get("message") if isinstance(envelope.get("message"), str) else "",
        "api_action": envelope.get("action") if isinstance(envelope.get("action"), str) else "",
    }

    known = CODE_TO_SCENARIO.get(code) or PROPOSED_CODE_TO_SCENARIO.get(code)
    if known:
        return ApuraApiError(known, **base)

    # 400 genérico do serializer: decide pelo campo.
    if code == "validation_error":
        if field == "url":
            return ApuraApiError("invalid_url", **base)
        if field == "text":
            return ApuraApiError("text_insufficient", **base)
        return ApuraApiError("rejected", **base)

    # Sem código conhecido: decide pelo status HTTP.
    if status == 429:
        return ApuraApiError("rate_limited", **base)
    if status in (408, 504):
        return ApuraApiError("timeout", **base)
    if status == 404:
        return ApuraApiError("not_found", **base)
    if status >= 500:
        return ApuraApiError("api_unavailable", **base)
    if status >= 400:
        return ApuraApiError("rejected", **base)
    return ApuraApiError("unknown", **base)


def network_failure() -> ApuraApiError:
    """Sem resposta HTTP (API fora do ar, DNS, conexão recusada)."""
    return ApuraApiError("api_unavailable", code="network_error")


def timeout_failure() -> ApuraApiError:
    """O prazo de 30 s (RNF01) estourou."""
    return ApuraApiError("timeout", code="client_timeout")


def incompatible_api_failure(reason: str = "") -> ApuraApiError:
    """A API respondeu algo que esta versão do chatbot não sabe ler (RF29)."""
    return ApuraApiError("incompatible_api", code="incompatible_api", details={"reason": reason})
