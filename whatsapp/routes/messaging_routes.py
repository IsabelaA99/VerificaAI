"""Rotas do chatbot (mesmo desenho do RosaIA: um Blueprint com POST /mensagem)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import Blueprint, Response, current_app, jsonify, request
from twilio.twiml.messaging_response import MessagingResponse

from services.replies import Incoming
from services.safe_log import log_event
from services.twilio_io import has_valid_signature

logger = logging.getLogger(__name__)

bp = Blueprint("messaging", __name__)


def twilio_signature_required(view: Callable[..., Any]) -> Callable[..., Any]:
    """Só a Twilio, com a assinatura certa, pode chamar o webhook."""

    @wraps(view)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        settings = current_app.extensions["apura"].settings
        if not has_valid_signature(request, settings):
            log_event(logger, "assinatura_invalida", level=logging.WARNING)
            return Response(status=403)
        return view(*args, **kwargs)

    return wrapper


def _int(value: str | None) -> int:
    try:
        return int(value or 0)
    except ValueError:
        return 0


@bp.route("/mensagem", methods=["POST"])
@twilio_signature_required
def message() -> Response:
    """Webhook de mensagens recebidas no WhatsApp. Responde em TwiML."""
    incoming = Incoming(
        body=request.form.get("Body", ""),
        num_media=_int(request.form.get("NumMedia")),
        from_number=request.form.get("From", ""),
        to_number=request.form.get("To", ""),
    )
    blocks = current_app.extensions["apura"].replies.handle(incoming)

    twiml = MessagingResponse()
    for block in blocks:
        twiml.message(block)
    return Response(str(twiml), mimetype="application/xml")


@bp.route("/saude", methods=["GET"])
def health() -> Response:
    """Verificação de disponibilidade (no lugar do GET /test do RosaIA). Não chama a API nem a Twilio."""
    return jsonify({"status": "ok", "service": "apura-whatsapp"})
