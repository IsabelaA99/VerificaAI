"""Decide o que responder a cada mensagem do WhatsApp.

Fluxo de uma análise (por que existe a parte "depois"):
  - A Twilio espera no máximo 15 s pela resposta do webhook; a API do Apura tem até 30 s (RNF01).
  - A análise começa numa thread própria. Se terminar em até ``sync_wait_seconds`` (12 s por
    padrão), o resultado volta na própria resposta do webhook (TwiML), como no RosaIA.
  - Se demorar mais, o webhook responde na hora "estou analisando" (visibilidade do estado do
    sistema) e o resultado é enviado depois pela API REST da Twilio, quando ficar pronto. A
    janela de atendimento de 24 h do WhatsApp está aberta porque a pessoa acabou de escrever.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass

from config import TWILIO_BODY_LIMIT, Settings
from services import messages
from services.apura_client import ApuraClient
from services.errors import ApuraApiError, for_link
from services.reply_builder import (
    Analysis,
    build_error_messages,
    build_result_messages,
    effective_status,
    parse_analysis,
)
from services.safe_log import log_event, origin_of
from services.twilio_io import MessageSender
from utils.message_utils import as_link, normalize_command, shared_link, split_message

logger = logging.getLogger(__name__)

# Mensagens que pedem ajuda ou só cumprimentam: respondidas com a explicação de como usar.
HELP_COMMANDS = frozenset(
    {
        "oi",
        "ola",
        "oie",
        "ajuda",
        "menu",
        "help",
        "start",
        "inicio",
        "iniciar",
        "comecar",
        "bom dia",
        "boa tarde",
        "boa noite",
        "como funciona",
        "quem e voce",
        "o que voce faz",
    }
)


@dataclass(frozen=True, repr=False)
class Incoming:
    """Mensagem recebida. O ``repr`` esconde texto e telefone para não irem parar num log."""

    body: str
    num_media: int
    from_number: str
    to_number: str

    def __repr__(self) -> str:
        return f"Incoming(chars={len(self.body)}, media={self.num_media})"


@dataclass(frozen=True)
class Intent:
    kind: str  # text | link | help | media | empty | link_unavailable
    reply: tuple[str, ...] = ()  # resposta pronta, quando não precisa chamar a API
    text: str | None = None
    url: str | None = None


@dataclass(frozen=True)
class Outcome:
    analysis: Analysis | None = None
    error: ApuraApiError | None = None


def interpret(incoming: Incoming, *, url_input_enabled: bool) -> Intent:
    """Entende o que a pessoa mandou, sem chamar nada."""
    if incoming.num_media > 0:
        # Mesmo com legenda: a imagem ou o áudio não são analisados, e a pessoa precisa saber disso.
        return Intent("media", reply=(messages.MEDIA_NOT_SUPPORTED,))

    body = incoming.body.strip()
    command = normalize_command(body)
    if not body or not command:
        # Vazia, ou só emojis e pontuação.
        return Intent("empty", reply=(messages.NO_TEXT,))
    if command in HELP_COMMANDS:
        return Intent("help", reply=(messages.welcome(url_input_enabled=url_input_enabled),))

    link = as_link(body)
    if link is None:
        shared = shared_link(body, max_comment_chars=messages.MIN_TEXT_CHARS)
        link = (shared, True) if shared else None
    if link is not None:
        address, has_scheme = link
        if not url_input_enabled:
            return Intent("link_unavailable", reply=(messages.link_not_available(),))
        # "g1.globo.com/x" é um link: a pessoa não precisa saber o que é "https://". Sites de
        # notícia respondem em https; se não responder, a API devolve "página inacessível".
        return Intent("link", url=address if has_scheme else f"https://{address}")

    return Intent("text", text=incoming.body)


class ReplyService:
    def __init__(
        self,
        *,
        settings: Settings,
        client: ApuraClient,
        sender: MessageSender | None = None,
        executor: ThreadPoolExecutor | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._sender = sender
        self._executor = executor or ThreadPoolExecutor(
            max_workers=settings.max_workers, thread_name_prefix="apura-analise"
        )

    # ------------------------------------------------------------------ entrada

    def handle(self, incoming: Incoming) -> list[str]:
        """Devolve as mensagens para a resposta imediata do webhook."""
        intent = interpret(incoming, url_input_enabled=self._settings.url_input_enabled)
        log_event(logger, "mensagem_recebida", kind=intent.kind, chars=len(incoming.body))

        if intent.reply:
            return [block for text in intent.reply for block in split_message(text)]

        future = self._executor.submit(self._run, intent)
        try:
            outcome = future.result(timeout=self._settings.sync_wait_seconds)
        except FutureTimeout:
            ack = messages.ACK_LINK if intent.kind == "link" else messages.ACK
            return self._continue_later(future, incoming, ack=ack)
        return self._render(outcome, incoming)

    # ------------------------------------------------------------------ análise

    def _run(self, intent: Intent) -> Outcome:
        """Roda numa thread do pool. Nunca lança exceção: devolve sempre um Outcome."""
        started = time.monotonic()
        try:
            if intent.text is not None:
                raw = self._client.analyze(text=intent.text)
            else:
                raw = self._client.analyze(url=intent.url)
            analysis = parse_analysis(raw)
        except ApuraApiError as error:
            if intent.url is not None:
                error = for_link(error)
            log_event(
                logger,
                "analise_falhou",
                level=logging.WARNING,
                scenario=error.scenario,
                code=error.code,
                http_status=error.status or None,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
            return Outcome(error=error)
        except Exception as exc:  # noqa: BLE001 - qualquer defeito vira uma resposta controlada
            log_event(
                logger,
                "erro_inesperado",
                level=logging.ERROR,
                error_class=type(exc).__name__,
                origin=origin_of(exc),
            )
            return Outcome(error=ApuraApiError("unknown", code="unexpected"))

        log_event(
            logger,
            "analise_concluida",
            status=effective_status(analysis),
            analysis_id=analysis.id,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        return Outcome(analysis=analysis)

    def _render(self, outcome: Outcome, incoming: Incoming) -> list[str]:
        if outcome.analysis is not None:
            extra = (messages.BODY_AT_TWILIO_LIMIT_NOTE,) if len(incoming.body) >= TWILIO_BODY_LIMIT else ()
            return build_result_messages(
                outcome.analysis,
                web_base_url=self._settings.web_base_url,
                extra_limitations=extra,
            )
        return build_error_messages(outcome.error or ApuraApiError("unknown"))

    # ------------------------------------------------------------------ resposta depois do prazo

    def _continue_later(self, future: Future[Outcome], incoming: Incoming, *, ack: str = messages.ACK) -> list[str]:
        """A análise passou do prazo do webhook: avisa agora e envia o resultado quando terminar."""
        sender = self._sender
        if sender is None:
            log_event(logger, "envio_posterior_indisponivel", level=logging.WARNING)
            return split_message(messages.LATER_UNAVAILABLE)

        def deliver(done: Future[Outcome]) -> None:
            try:
                blocks = self._render(done.result(), incoming)
                sender.send_all(to=incoming.from_number, from_=incoming.to_number, bodies=blocks)
                log_event(logger, "resultado_enviado_depois", blocks=len(blocks))
            except Exception as exc:  # noqa: BLE001 - nada a fazer além de registrar a classe do erro
                log_event(
                    logger,
                    "resultado_nao_entregue",
                    level=logging.ERROR,
                    error_class=type(exc).__name__,
                    origin=origin_of(exc),
                )

        future.add_done_callback(deliver)
        return split_message(ack)
