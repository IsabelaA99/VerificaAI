"""Entrada e saída da Twilio: conferência da assinatura do webhook e envio de mensagens.

O RosaIA aceitava qualquer requisição em /mensagem. Aqui, quem não prova ser a Twilio recebe 403
(a Twilio assina cada chamada com o Auth Token, no cabeçalho X-Twilio-Signature).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, Protocol

from flask import Request
from twilio.request_validator import RequestValidator
from twilio.rest import Client

from config import Settings
from services.safe_log import log_event, origin_of

logger = logging.getLogger(__name__)


def webhook_url(req: Request, settings: Settings) -> str:
    """URL que a Twilio usou na chamada (ela entra no cálculo da assinatura).

    O jeito mais seguro é cadastrar a URL exata em PUBLIC_WEBHOOK_URL. Sem ela, usa-se a URL da
    requisição, trocando só o esquema pelo de X-Forwarded-Proto (proxies que terminam o HTTPS).
    """
    if settings.public_webhook_url:
        return settings.public_webhook_url
    url = req.url
    forwarded = req.headers.get("X-Forwarded-Proto", "").split(",")[0].strip().lower()
    if forwarded in {"http", "https"} and not url.startswith(f"{forwarded}://"):
        url = f"{forwarded}://{url.split('://', 1)[1]}"
    return url


def has_valid_signature(req: Request, settings: Settings) -> bool:
    if not settings.validate_signature:
        return True
    signature = req.headers.get("X-Twilio-Signature", "")
    if not signature:
        return False
    validator = RequestValidator(settings.twilio_auth_token)
    return bool(validator.validate(webhook_url(req, settings), req.form, signature))


class MessageSender(Protocol):
    """O que o fluxo de resposta precisa de quem envia mensagens (a Twilio, ou um falso nos testes)."""

    def send_all(self, *, to: str, from_: str, bodies: list[str]) -> None: ...


class TwilioSender:
    """Envia mensagens pela API REST da Twilio (usado quando a análise passa do prazo do webhook)."""

    def __init__(
        self,
        client: Any,
        *,
        pause_seconds: float = 0.6,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._pause = pause_seconds
        self._sleep = sleep

    def send_all(self, *, to: str, from_: str, bodies: list[str]) -> None:
        """Envia em sequência, com uma pausa curta para as mensagens chegarem na ordem."""
        for index, body in enumerate(bodies):
            if index:
                self._sleep(self._pause)
            self.send(to=to, from_=from_, body=body)

    def send(self, *, to: str, from_: str, body: str) -> None:
        try:
            self._client.messages.create(to=to, from_=from_, body=body)
        except Exception as exc:
            log_event(
                logger,
                "envio_falhou",
                level=logging.ERROR,
                error_class=type(exc).__name__,
                origin=origin_of(exc),
            )
            raise


def build_sender(settings: Settings) -> TwilioSender | None:
    """Cria o remetente quando há credenciais da API REST; senão, o envio posterior fica desligado."""
    if not settings.can_reply_later:
        return None
    return TwilioSender(Client(settings.twilio_account_sid, settings.twilio_auth_token))
