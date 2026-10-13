"""Configuração do chatbot, lida de variáveis de ambiente.

Nenhuma chave fica no código. O arquivo .env (veja .env.example) só existe na máquina de quem
executa e nunca vai para o repositório. Segredos nunca são escritos em log.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

# Documentação da Twilio (webhook de mensagem recebida): o campo Body tem "até 1600 caracteres".
TWILIO_BODY_LIMIT = 1600

# Documentação da Twilio (webhooks, connection overrides): a Twilio espera no máximo 15 s pela
# resposta do webhook (padrão e máximo do parâmetro #rt).
TWILIO_WEBHOOK_TIMEOUT_SECONDS = 15.0

# O prazo da análise é o do RNF01 (30 s); a resposta pode passar dos 15 s da Twilio, e por isso o
# resultado é enviado depois quando demora (veja services/replies.py).
ANALYSIS_DEADLINE_SECONDS = 30.0


class ConfigError(ValueError):
    """Configuração inválida. A mensagem diz o que corrigir."""


def _text(environ: Mapping[str, str], name: str, default: str = "") -> str:
    return (environ.get(name) or default).strip()


def _flag(environ: Mapping[str, str], name: str, default: bool) -> bool:
    raw = _text(environ, name)
    if not raw:
        return default
    if raw.lower() in {"1", "true", "sim", "yes"}:
        return True
    if raw.lower() in {"0", "false", "nao", "não", "no"}:
        return False
    raise ConfigError(f"{name} deve ser 'true' ou 'false' (recebido: {raw!r}).")


def _number(environ: Mapping[str, str], name: str, default: float) -> float:
    raw = _text(environ, name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} deve ser um número (recebido: {raw!r}).") from exc


@dataclass(frozen=True)
class Settings:
    """Todas as opções do chatbot. Os valores padrão servem para desenvolvimento local."""

    # API do Apura. Sem a versão no final: o cliente usa /v1/analyses/ e confere "api_version".
    apura_api_base_url: str = "http://localhost:8000/api"
    api_connect_timeout_seconds: float = 5.0
    api_timeout_seconds: float = ANALYSIS_DEADLINE_SECONDS

    # Quanto o webhook espera pela API antes de avisar que está analisando. Precisa ficar abaixo
    # dos 15 s da Twilio, com folga para a rede e para montar a resposta.
    sync_wait_seconds: float = 12.0
    max_workers: int = 8

    # Entrada por link. A API devolve 501 até a Etapa 2; enquanto desligado, o chatbot responde
    # na hora que o link ainda não é aceito, sem chamar a API.
    url_input_enabled: bool = False

    # Endereço público da interface web (opcional). Quando existe, a resposta termina com o link
    # da página completa do resultado.
    web_base_url: str = ""

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    validate_signature: bool = True
    # URL exata cadastrada no console da Twilio para este webhook. Recomendada atrás de proxy.
    public_webhook_url: str = ""

    port: int = 5000

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ
        settings = cls(
            apura_api_base_url=_text(env, "APURA_API_BASE_URL", cls.apura_api_base_url).rstrip("/"),
            api_connect_timeout_seconds=_number(
                env, "APURA_API_CONNECT_TIMEOUT_SECONDS", cls.api_connect_timeout_seconds
            ),
            api_timeout_seconds=_number(env, "APURA_API_TIMEOUT_SECONDS", cls.api_timeout_seconds),
            sync_wait_seconds=_number(env, "SYNC_WAIT_SECONDS", cls.sync_wait_seconds),
            max_workers=int(_number(env, "MAX_WORKERS", cls.max_workers)),
            url_input_enabled=_flag(env, "URL_INPUT_ENABLED", cls.url_input_enabled),
            web_base_url=_text(env, "WEB_BASE_URL").rstrip("/"),
            twilio_account_sid=_text(env, "TWILIO_ACCOUNT_SID"),
            twilio_auth_token=_text(env, "TWILIO_AUTH_TOKEN"),
            validate_signature=_flag(env, "TWILIO_VALIDATE_SIGNATURE", cls.validate_signature),
            public_webhook_url=_text(env, "PUBLIC_WEBHOOK_URL"),
            port=int(_number(env, "PORT", cls.port)),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        """Falha cedo, na inicialização, com uma frase que diz o que corrigir."""
        problems: list[str] = []
        if not self.apura_api_base_url.startswith(("http://", "https://")):
            problems.append("APURA_API_BASE_URL deve começar com http:// ou https://.")
        if not 0 < self.api_connect_timeout_seconds <= 30:
            problems.append("APURA_API_CONNECT_TIMEOUT_SECONDS deve ficar entre 0 e 30.")
        if not 0 < self.api_timeout_seconds <= 120:
            problems.append("APURA_API_TIMEOUT_SECONDS deve ficar entre 0 e 120.")
        if not 1 <= self.sync_wait_seconds <= TWILIO_WEBHOOK_TIMEOUT_SECONDS - 1:
            problems.append(
                f"SYNC_WAIT_SECONDS deve ficar entre 1 e {TWILIO_WEBHOOK_TIMEOUT_SECONDS - 1:g}: "
                f"a Twilio desiste do webhook em {TWILIO_WEBHOOK_TIMEOUT_SECONDS:g} s."
            )
        if self.max_workers < 1:
            problems.append("MAX_WORKERS deve ser pelo menos 1.")
        if self.validate_signature and not self.twilio_auth_token:
            problems.append(
                "TWILIO_AUTH_TOKEN é obrigatório para validar a assinatura da Twilio. "
                "Só desligue com TWILIO_VALIDATE_SIGNATURE=false em desenvolvimento local."
            )
        if self.public_webhook_url and not self.public_webhook_url.startswith(("http://", "https://")):
            problems.append("PUBLIC_WEBHOOK_URL deve começar com http:// ou https://.")
        if self.web_base_url and not self.web_base_url.startswith(("http://", "https://")):
            problems.append("WEB_BASE_URL deve começar com http:// ou https://.")
        if problems:
            raise ConfigError(" ".join(problems))

    @property
    def can_reply_later(self) -> bool:
        """Só dá para enviar o resultado depois se houver credenciais da API REST da Twilio."""
        return bool(self.twilio_account_sid and self.twilio_auth_token)
