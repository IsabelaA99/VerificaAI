"""Conversa com o chatbot no terminal, como se fosse o WhatsApp. Não precisa de Twilio nem de conta.

    python tools/simulate.py --fake-api      # usa a API de mentirinha (tools/fake_apura_api.py)
    python tools/simulate.py                 # usa a API de APURA_API_BASE_URL (a real, se estiver no ar)

O que acontece de verdade: cada mensagem passa pela MESMA rota ``POST /mensagem`` do chatbot e
pelo MESMO código que atende o WhatsApp (interpretar a mensagem, chamar a API, montar a resposta,
dividir em mensagens de até 1.600 caracteres, avisar "estou analisando" quando demora). O que é
trocado: a Twilio. A assinatura não é conferida e o resultado enviado "depois do prazo" aparece
aqui no terminal, em vez de ir pelo WhatsApp.

Comandos: /exemplos  /1 a /10  /link  /midia  /arquivo CAMINHO  /logs  /ajuda  /sair
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app  # noqa: E402 - depende do sys.path acima
from config import Settings  # noqa: E402
from services import messages  # noqa: E402
from services.apura_client import ApuraClient  # noqa: E402

PHONE = "whatsapp:+5561999990000"
BOT_PHONE = "whatsapp:+14155238886"
MAX_FILE_BYTES = 20_000

# Textos prontos. Cada um provoca uma situação na API de mentirinha (veja tools/fake_apura_api.py);
# com a API real, o resultado depende do modelo.
EXAMPLES: list[tuple[str, str]] = [
    (
        "Alto risco",
        "URGENTE!!! Órgão público confirma que todos os brasileiros receberão R$ 5.000 amanhã. "
        "Compartilhe com todos os seus contatos antes que apaguem!!!",
    ),
    (
        "Poucos sinais de risco",
        "A biblioteca municipal anuncia programação de leitura para sábado, com atividades para "
        "crianças e adultos a partir das 9 horas.",
    ),
    (
        "Requer atenção",
        "Todas as linhas de ônibus deixarão de funcionar no próximo domingo, segundo uma mensagem "
        "que circula entre moradores da cidade.",
    ),
    (
        "Análise inconclusiva",
        "Ouvi dizer que a praça do bairro será fechada para obras no mês que vem, mas não sei de "
        "onde veio essa informação.",
    ),
    (
        "Com fontes (formato proposto)",
        "O governo anunciou novos dados abertos sobre vacinação, e fontes oficiais confirmam a "
        "divulgação semanal dos números.",
    ),
    ("Erro: texto curto demais", "Isso é verdade? Vi no grupo da família."),
    (
        "Erro: idioma não suportado",
        "This is an English text about the weather today. It should not be accepted because the "
        "Apura only analyzes Portuguese.",
    ),
    (
        "Erro: muitas solicitações",
        "Teste de limite: muitas solicitações em pouco tempo fazem a API pedir para esperar alguns "
        "segundos antes de tentar de novo.",
    ),
    (
        "Erro: serviço indisponível",
        "Simulação de serviço indisponível: a API de análise está fora do ar neste momento e "
        "devolve erro para o chatbot.",
    ),
    (
        "Análise demorada (aviso 'estou analisando')",
        "Texto demorado: esta análise vai demorar mais do que o WhatsApp permite esperar, para "
        "testar o aviso de que o bot está analisando.",
    ),
]


def twiml_messages(xml_text: str) -> list[str]:
    """Textos das mensagens de uma resposta TwiML (<Response><Message>…</Message></Response>)."""
    root = ET.fromstring(xml_text)  # noqa: S314 - o TwiML vem do nosso próprio chatbot
    return [(node.text or "") for node in root.iter("Message")]


def bold(text: str, *, enabled: bool) -> str:
    """No WhatsApp, *assim* é negrito. No terminal colorido, vira negrito de verdade."""
    if not enabled:
        return text
    return re.sub(r"\*([^*\n]+)\*", "\033[1m\\1\033[0m", text)


class Screen:
    """Escreve no terminal sem embaralhar o que a pessoa está digitando."""

    def __init__(self, *, color: bool) -> None:
        self._color = color
        self._lock = threading.Lock()
        self.pending_later = 0

    def say(self, who: str, blocks: list[str], *, note: str = "") -> None:
        with self._lock:
            print()
            header = f"── {who}" + (f"  {note}" if note else "")
            print(bold(f"*{header}*", enabled=self._color))
            for index, block in enumerate(blocks, start=1):
                if len(blocks) > 1:
                    print(f"[mensagem {index} de {len(blocks)}, {len(block)} caracteres]")
                print(bold(block, enabled=self._color))
                if index < len(blocks):
                    print()
            print()

    def prompt(self) -> None:
        print("Você> ", end="", flush=True)

    def info(self, text: str) -> None:
        with self._lock:
            print(text)


class ConsoleSender:
    """Faz o papel da Twilio no envio 'depois do prazo': mostra o resultado no terminal."""

    def __init__(self, screen: Screen) -> None:
        self._screen = screen

    def send_all(self, *, to: str, from_: str, bodies: list[str]) -> None:
        self._screen.say("Apura (enviado depois, pela API da Twilio)", bodies)
        self._screen.pending_later = max(0, self._screen.pending_later - 1)
        self._screen.prompt()


class Simulator:
    """Uma conversa. ``send`` devolve as mensagens da resposta imediata do chatbot."""

    def __init__(self, settings: Settings, screen: Screen, *, client: ApuraClient | None = None) -> None:
        sender = ConsoleSender(screen)
        self._screen = screen
        app = create_app(settings, client=client, sender=sender)
        self._http = app.test_client()

    def send(self, body: str, *, num_media: int = 0) -> list[str]:
        started = time.monotonic()
        response = self._http.post(
            "/mensagem",
            data={"Body": body, "From": PHONE, "To": BOT_PHONE, "NumMedia": str(num_media)},
        )
        elapsed = time.monotonic() - started
        if response.status_code != 200:
            self._screen.info(f"O chatbot respondeu HTTP {response.status_code} (era esperado 200).")
            return []
        blocks = twiml_messages(response.get_data(as_text=True))
        if messages.ACK in blocks:
            self._screen.pending_later += 1
        self._screen.say("Apura", blocks, note=f"(respondeu em {elapsed:.1f} s)".replace(".", ","))
        return blocks


def print_examples(screen: Screen) -> None:
    lines = ["Exemplos (digite /1, /2…):"]
    for number, (title, _text) in enumerate(EXAMPLES, start=1):
        lines.append(f"  /{number:<2} {title}")
    lines += [
        "  /link    um link sozinho",
        "  /midia   uma imagem (o chatbot só analisa texto)",
        "  /arquivo CAMINHO   envia o conteúdo de um arquivo de texto (útil para textos longos)",
    ]
    screen.info("\n".join(lines))


def build_settings(*, fake_api_url: str | None) -> Settings:
    environ = dict(os.environ)
    environ["TWILIO_VALIDATE_SIGNATURE"] = "false"  # sem Twilio aqui, não há assinatura para conferir
    if fake_api_url:
        environ["APURA_API_BASE_URL"] = fake_api_url
    return Settings.from_env(environ)


def start_fake_api() -> str:
    """Sobe a API de mentirinha numa porta livre, em segundo plano. Devolve o endereço base."""
    from werkzeug.serving import make_server

    from tools.fake_apura_api import create_fake_api

    server = make_server("127.0.0.1", 0, create_fake_api(), threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True, name="api-de-mentirinha").start()
    return f"http://127.0.0.1:{server.server_port}/api"


def read_file_text(raw_path: str) -> str | None:
    path = Path(raw_path.strip().strip('"').strip("'")).expanduser()
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def wait_for_later(screen: Screen, *, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while screen.pending_later > 0 and time.monotonic() < deadline:
        time.sleep(0.2)


def run(
    simulator: Simulator,
    screen: Screen,
    *,
    read_line: Callable[[], str | None],
    set_logs: Callable[[bool], None] = lambda _on: None,
) -> None:
    """Laço da conversa. ``read_line`` devolve ``None`` no fim da entrada."""
    screen.info("Apura no terminal. Escreva uma mensagem como no WhatsApp. /ajuda mostra os comandos.")
    screen.prompt()
    while (line := read_line()) is not None:
        text = line.strip()
        if not text:
            screen.prompt()
            continue
        command, _, argument = text.partition(" ")
        if command in {"/sair", "/exit", "/quit"}:
            break
        if command in {"/ajuda", "/help"}:
            screen.info("Escreva uma mensagem e aperte Enter. Para colar um texto longo, use /arquivo CAMINHO.")
            print_examples(screen)
        elif command == "/exemplos":
            print_examples(screen)
        elif command == "/link":
            screen.info("Você> https://exemplo.com/noticia")
            simulator.send("https://exemplo.com/noticia")
        elif command == "/midia":
            screen.info("Você> [imagem]")
            simulator.send("", num_media=1)
        elif command == "/logs":
            set_logs(True)
            screen.info("Logs do chatbot ligados (aparecem abaixo; note que não têm telefone nem texto).")
        elif command == "/arquivo":
            content = read_file_text(argument)
            if content is None:
                screen.info("Não consegui ler esse arquivo (precisa ser texto UTF-8 de até 20 KB).")
            else:
                screen.info(f"Você> [conteúdo do arquivo, {len(content)} caracteres]")
                simulator.send(content)
        elif re.fullmatch(r"/\d+", command) and 1 <= int(command[1:]) <= len(EXAMPLES):
            example = EXAMPLES[int(command[1:]) - 1][1]
            screen.info(f"Você> {example}")
            simulator.send(example)
        elif text.startswith("/"):
            screen.info("Comando desconhecido. /ajuda mostra os comandos.")
        else:
            simulator.send(text)
        screen.prompt()
    wait_for_later(screen)


def main() -> None:
    parser = argparse.ArgumentParser(description="Conversa com o chatbot do Apura no terminal.")
    parser.add_argument("--fake-api", action="store_true", help="usa a API de mentirinha (não precisa do back end)")
    parser.add_argument("--logs", action="store_true", help="mostra os logs do chatbot")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    root_logger = logging.getLogger()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("   [log] %(levelname)s %(name)s %(message)s"))
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO if args.logs else logging.CRITICAL)
    logging.getLogger("werkzeug").setLevel(logging.ERROR)  # os pedidos da API de mentirinha não interessam

    def set_logs(on: bool) -> None:
        root_logger.setLevel(logging.INFO if on else logging.CRITICAL)

    api_url = start_fake_api() if args.fake_api else None
    settings = build_settings(fake_api_url=api_url)
    screen = Screen(color=sys.stdout.isatty())
    if api_url:
        screen.info(f"Usando a API de mentirinha em {api_url}")
    else:
        screen.info(f"Usando a API em {settings.apura_api_base_url}")

    simulator = Simulator(settings, screen)

    def read_line() -> str | None:
        try:
            return input()
        except EOFError:
            return None

    run(simulator, screen, read_line=read_line, set_logs=set_logs)


if __name__ == "__main__":
    main()
