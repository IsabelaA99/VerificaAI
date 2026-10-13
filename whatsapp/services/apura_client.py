"""Cliente da API v1 do Apura (substitui o ``gemini_service.py`` do RosaIA).

O chatbot não analisa nada sozinho: envia o texto à API (``POST /api/v1/analyses/``) e conta o
que ela devolve. Regras:

- Só a opção escolhida vai no corpo da requisição, texto OU link (RF24).
- O número de telefone nunca é enviado à API, nem como identificador de visitante: o cabeçalho
  ``X-Visitor-Id`` não é usado (RNF10, dados pessoais desnecessários).
- Prazo de 30 s (RNF01). Passou disso, a falha vira o cenário controlado "timeout".
- A resposta é conferida antes de ser usada; se não estiver no formato da v1, vira
  "incompatible_api" em vez de mostrar um resultado errado (RF29).
"""

from __future__ import annotations

from typing import Any

import requests

from services.errors import (
    classify_failure,
    incompatible_api_failure,
    network_failure,
    timeout_failure,
)

SUPPORTED_API_VERSIONS = ("v1",)
USER_AGENT = "apura-whatsapp/0.1"


def _retry_after(value: str | None) -> int | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return int(-(-seconds // 1)) if seconds > 0 else None


class ApuraClient:
    """Fala com a API do Apura. Uma instância pode ser usada por várias threads."""

    def __init__(
        self,
        base_url: str,
        *,
        connect_timeout: float = 5.0,
        read_timeout: float = 30.0,
        session: requests.Session | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = (connect_timeout, read_timeout)
        self._session = session or requests.Session()
        self._session.headers.update({"Accept": "application/json", "User-Agent": USER_AGENT})

    def analyze(self, *, text: str | None = None, url: str | None = None) -> dict[str, Any]:
        """Pede uma análise. Devolve o corpo JSON da API ou lança ``ApuraApiError``."""
        if (text is None) == (url is None):
            raise ValueError("Informe texto OU link, nunca os dois nem nenhum.")
        payload = {"input_type": "text", "text": text} if text is not None else {"input_type": "url", "url": url}

        try:
            response = self._session.post(f"{self._base_url}/v1/analyses/", json=payload, timeout=self._timeout)
        except requests.Timeout as exc:
            raise timeout_failure() from exc
        except requests.RequestException as exc:
            raise network_failure() from exc

        body = self._read_json(response)
        if not response.ok:
            raise classify_failure(response.status_code, body, _retry_after(response.headers.get("Retry-After")))
        if not isinstance(body, dict):
            raise incompatible_api_failure("A resposta não é um objeto JSON.")
        if body.get("api_version") not in SUPPORTED_API_VERSIONS:
            raise incompatible_api_failure(f"Versão de API não suportada: {body.get('api_version') or 'ausente'}.")
        return body

    @staticmethod
    def _read_json(response: requests.Response) -> Any:
        # Páginas de erro do nginx ou do gunicorn vêm em HTML: tratadas pelo status, não pelo corpo.
        try:
            return response.json()
        except ValueError:
            return None
