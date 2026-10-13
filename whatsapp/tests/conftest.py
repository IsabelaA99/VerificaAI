from __future__ import annotations

import threading
from typing import Any

import pytest
from twilio.request_validator import RequestValidator

from app import create_app
from config import Settings
from services.errors import ApuraApiError

AUTH_TOKEN = "token-de-teste-nao-secreto"
USER_NUMBER = "whatsapp:+5511987654321"
BOT_NUMBER = "whatsapp:+14155238886"
WEBHOOK = "http://localhost/mensagem"


class FakeClient:
    """Faz o papel do ApuraClient. ``result`` pode ser um dict, uma exceção ou uma função."""

    def __init__(self, result: Any = None) -> None:
        self.result = result
        self.calls: list[dict[str, str | None]] = []
        self.release = threading.Event()
        self.release.set()  # por padrão responde na hora
        self.called = threading.Event()

    def analyze(self, *, text: str | None = None, url: str | None = None) -> dict[str, Any]:
        self.calls.append({"text": text, "url": url})
        self.called.set()
        self.release.wait(timeout=10)
        result = self.result() if callable(self.result) else self.result
        if isinstance(result, BaseException):
            raise result
        return result


class FakeSender:
    """Faz o papel do TwilioSender e avisa quando recebe algo."""

    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[dict[str, Any]] = []
        self.done = threading.Event()
        self.error = error

    def send_all(self, *, to: str, from_: str, bodies: list[str]) -> None:
        self.sent.append({"to": to, "from_": from_, "bodies": list(bodies)})
        self.done.set()
        if self.error:
            raise self.error


@pytest.fixture
def settings() -> Settings:
    return Settings(twilio_account_sid="ACtest", twilio_auth_token=AUTH_TOKEN, sync_wait_seconds=2.0)


@pytest.fixture
def make_app(settings: Settings):
    def factory(client: FakeClient, sender: FakeSender | None = None, **overrides: Any):
        values = {**settings.__dict__, **overrides}
        app = create_app(Settings(**values), client=client, sender=sender if sender is not None else FakeSender())
        app.testing = True
        return app

    return factory


def sign(params: dict[str, str], *, url: str = WEBHOOK, token: str = AUTH_TOKEN) -> dict[str, str]:
    return {"X-Twilio-Signature": RequestValidator(token).compute_signature(url, params)}


def incoming(body: str, **extra: str) -> dict[str, str]:
    return {"Body": body, "From": USER_NUMBER, "To": BOT_NUMBER, "NumMedia": "0", **extra}


def not_found_error() -> ApuraApiError:
    return ApuraApiError("not_found")
