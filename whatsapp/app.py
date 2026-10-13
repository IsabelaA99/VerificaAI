"""Chatbot do Apura no WhatsApp (Flask + Twilio), na estrutura do RosaIA.

    app.py                       cria a aplicação e registra o Blueprint
    routes/messaging_routes.py   POST /mensagem (webhook da Twilio) e GET /saude
    services/                    API do Apura, respostas, Twilio (no lugar do Gemini do RosaIA)
    utils/message_utils.py       split_message e leitura do que a pessoa enviou

Executar em desenvolvimento:   python app.py
Executar em produção:          gunicorn "app:create_app()" (veja o Procfile)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv
from flask import Flask, Response
from twilio.twiml.messaging_response import MessagingResponse
from werkzeug.exceptions import HTTPException

from config import Settings
from routes.messaging_routes import bp as messaging_bp
from services import messages
from services.apura_client import ApuraClient
from services.replies import ReplyService
from services.safe_log import log_event, origin_of
from services.twilio_io import MessageSender, build_sender

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppContext:
    settings: Settings
    replies: ReplyService


def create_app(
    settings: Settings | None = None,
    *,
    client: ApuraClient | None = None,
    sender: MessageSender | None = None,
) -> Flask:
    """Cria a aplicação. Os parâmetros existem para os testes trocarem API e Twilio por versões falsas."""
    if settings is None:
        load_dotenv()
        settings = Settings.from_env()

    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # A biblioteca da Twilio registra em INFO a URL de cada envio (com o Account SID) e os cabeçalhos,
    # fora da lista de campos de safe_log (RNF10). Só avisos e erros dela vão para o log.
    logging.getLogger("twilio").setLevel(logging.WARNING)

    app = Flask(__name__)
    # O webhook da Twilio é um formulário pequeno. Corpo grande demais é recusado antes de ser lido.
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

    api = client or ApuraClient(
        settings.apura_api_base_url,
        connect_timeout=settings.api_connect_timeout_seconds,
        read_timeout=settings.api_timeout_seconds,
    )
    app.extensions["apura"] = AppContext(
        settings=settings,
        replies=ReplyService(
            settings=settings,
            client=api,
            sender=sender if sender is not None else build_sender(settings),
        ),
    )
    app.register_blueprint(messaging_bp)

    @app.errorhandler(Exception)
    def unexpected_error(exc: Exception) -> Response | HTTPException:
        """Defeito não previsto: registra só a classe e o local (a mensagem poderia ter texto da pessoa)."""
        if isinstance(exc, HTTPException):
            return exc  # 403, 405, 413... mantêm o próprio código
        log_event(
            logger, "erro_inesperado_rota", level=logging.ERROR, error_class=type(exc).__name__, origin=origin_of(exc)
        )
        twiml = MessagingResponse()
        twiml.message(messages.UNEXPECTED)
        return Response(str(twiml), mimetype="application/xml")

    if not settings.validate_signature:
        logger.warning("Validação da assinatura da Twilio DESLIGADA. Use apenas em desenvolvimento local.")
    if not settings.can_reply_later:
        logger.warning(
            "TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN ausentes: análises acima do prazo do webhook não "
            "poderão ser entregues depois."
        )
    return app


if __name__ == "__main__":
    load_dotenv()
    create_app().run(
        host="0.0.0.0",  # noqa: S104 - o servidor de desenvolvimento roda em contêiner e precisa aceitar conexões externas
        port=int(os.environ.get("PORT", 5000)),
        threaded=True,
    )
