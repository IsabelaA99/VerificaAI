"""API do Apura de mentirinha, só para testar o chatbot sem o back end real.

Responde no formato REAL da API v1 (as mesmas respostas dos testes, em ``tests/payloads.py``).
Ela NÃO analisa nada: escolhe o resultado pelas palavras do texto enviado, para você provocar cada
situação de propósito.

    python tools/fake_apura_api.py              # http://127.0.0.1:8000/api

O chatbot então usa ``APURA_API_BASE_URL=http://127.0.0.1:8000/api`` (o padrão do ``.env.example``).

Palavras que escolhem o resultado (maiúsculas e minúsculas não importam; vale a primeira que aparecer
na ordem desta lista):

    menos de 50 caracteres     erro: texto curto demais (400)
    mais de 5.000 caracteres   erro: texto longo demais (400)
    "english"                  erro: idioma não suportado (400)
    "teste de limite"          erro: muitas solicitações (429, espere 20 s)
    "indisponível"             erro: serviço fora do ar (503)
    "urgente"                  Alto risco
    "biblioteca"               Poucos sinais de risco
    "ouvi dizer"               Análise inconclusiva
    "fontes"                   Requer atenção, com fontes (formato PROPOSTO, a API real ainda não tem)
    "demorado"                 espera 16 s antes de responder (para ver o aviso "estou analisando")
    qualquer outro texto       Requer atenção

Um link (``input_type=url``) recebe 501, como na API real hoje (Etapa 2 ainda não existe).
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request

# Permite rodar "python tools/fake_apura_api.py" de qualquer pasta e reaproveitar os payloads dos testes.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests import payloads  # noqa: E402 - depende do sys.path acima

FAKE_NOTE = "[API de mentirinha: esta explicação é fixa e não vem de um modelo.]"
MIN_CHARS = 50
MAX_CHARS = 5000
SLOW_SECONDS = 16.0  # maior que SYNC_WAIT_SECONDS (12) e menor que o prazo da API (30)
THROTTLE_WAIT_SECONDS = 20

SOURCES_DEMO = [
    {
        "relation": "compatible",
        "publisher": "Portal de Dados Abertos (exemplo)",
        "title": "Painel semanal de vacinação",
        "url": "https://exemplo.com/dados-abertos/vacinacao",
    },
    {
        "relation": "contextual",
        "publisher": "Agência de checagem (exemplo)",
        "title": "Como ler os números da vacinação",
        "url": "https://exemplo.com/checagem/vacinacao",
    },
]


def _claim_summary(text: str) -> str:
    """Primeira frase do texto, em até 140 caracteres (a API real também resume a alegação)."""
    flat = re.sub(r"\s+", " ", text).strip()
    first = re.split(r"(?<=[.!?])\s", flat, maxsplit=1)[0]
    return first if len(first) <= 140 else first[:139].rstrip() + "…"


def _fresh(analysis: dict[str, Any], text: str) -> dict[str, Any]:
    """Dá a cada resposta um identificador e uma data novos, e usa a primeira frase do texto como alegação."""
    analysis["id"] = str(uuid.uuid4())
    analysis["created_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    analysis["claim"] = {"summary": _claim_summary(text), "confirmed_by_user": False}
    analysis["explanation"] = [FAKE_NOTE, *analysis["explanation"]]
    return analysis


def _with_sources() -> dict[str, Any]:
    analysis = payloads.make_analysis()
    analysis["evidence"] = {"enabled": True, "sources": [dict(source) for source in SOURCES_DEMO]}
    # Com fontes, a limitação "consulta a fontes ainda não habilitada" deixaria de ser verdade.
    analysis["limitations"] = [text for text in analysis["limitations"] if "fontes externas" not in text]
    return analysis


def pick_result(text: str) -> tuple[int, dict[str, Any], dict[str, str]]:
    """Escolhe (status HTTP, corpo, cabeçalhos extras) conforme as regras do cabeçalho deste arquivo."""
    size = len(text.strip())
    lowered = text.lower()

    if size < MIN_CHARS:
        body = payloads.error(
            "text_too_short",
            f"O conteúdo tem {size} caracteres; o mínimo é {MIN_CHARS}.",
            "Acrescente mais contexto, como o parágrafo completo da notícia.",
            field="text",
            details={"length": size, "min_chars": MIN_CHARS},
        )
        return 400, body, {}
    if size > MAX_CHARS:
        body = payloads.error(
            "text_too_long",
            f"O conteúdo tem {size} caracteres; o máximo é {MAX_CHARS}.",
            f"Envie apenas o trecho com a alegação principal (até {MAX_CHARS:,} caracteres).".replace(",", "."),
            field="text",
            details={"length": size, "max_chars": MAX_CHARS},
        )
        return 400, body, {}
    if "english" in lowered:
        return 400, payloads.UNSUPPORTED_LANGUAGE, {}
    if "teste de limite" in lowered:
        return 429, payloads.THROTTLED, {"Retry-After": str(THROTTLE_WAIT_SECONDS)}
    if "indisponível" in lowered or "indisponivel" in lowered:
        return 503, payloads.ANALYSIS_UNAVAILABLE, {}
    if "urgente" in lowered:
        return 201, _fresh(payloads.high(), text), {}
    if "biblioteca" in lowered:
        return 201, _fresh(payloads.low(), text), {}
    if "ouvi dizer" in lowered:
        return 201, _fresh(payloads.inconclusive(), text), {}
    if "fontes" in lowered:
        return 201, _fresh(_with_sources(), text), {}
    return 201, _fresh(payloads.make_analysis(), text), {}


def create_fake_api(*, slow_seconds: float = SLOW_SECONDS) -> Flask:
    app = Flask(__name__)

    @app.post("/api/v1/analyses/")
    def create_analysis() -> Response:
        data = request.get_json(silent=True)
        data = data if isinstance(data, dict) else {}

        if data.get("input_type") == "url":
            return _reply(501, payloads.URL_UNAVAILABLE, {})

        text = data.get("text")
        text = text if isinstance(text, str) else ""
        if "demorado" in text.lower():
            time.sleep(slow_seconds)
        status, body, headers = pick_result(text)
        return _reply(status, body, headers)

    @app.get("/api/v1/health/")
    def health() -> Response:
        return jsonify({"status": "ok", "service": "apura-fake-api"})

    return app


def _reply(status: int, body: dict[str, Any], headers: dict[str, str]) -> Response:
    response = jsonify(body)
    response.status_code = status
    for name, value in headers.items():
        response.headers[name] = value
    return response


def main() -> None:
    parser = argparse.ArgumentParser(description="API do Apura de mentirinha, para testar o chatbot.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    print(f"API de mentirinha em http://{args.host}:{args.port}/api  (Ctrl+C para parar)")
    create_fake_api().run(host=args.host, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
