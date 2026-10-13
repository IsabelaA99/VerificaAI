"""Registro de eventos sem dados pessoais (RNF10: logs técnicos não contêm texto bruto nem dados
pessoais desnecessários).

O RosaIA escrevia no log o número de telefone e o texto de cada mensagem. Aqui isso é impossível
por construção: só campos de uma lista fixa são aceitos, e qualquer outro é descartado.
"""

from __future__ import annotations

import logging
from typing import Any

# Campos técnicos permitidos. Nenhum deles carrega texto digitado, telefone ou nome.
ALLOWED_FIELDS = frozenset(
    {
        "kind",  # tipo da mensagem recebida: texto, link, ajuda, arquivo, vazia
        "scenario",  # cenário de erro (RF27)
        "code",  # código estável de erro da API
        "http_status",
        "status",  # status da análise (poucos_sinais_de_risco, ...)
        "outcome",
        "duration_ms",
        "chars",  # quantidade de caracteres, nunca o conteúdo
        "blocks",  # quantidade de mensagens enviadas
        "analysis_id",  # UUID da análise, que não identifica a pessoa
        "error_class",
        "origin",
    }
)


def log_event(logger: logging.Logger, event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    """Escreve ``evento campo=valor ...`` com apenas os campos permitidos."""
    parts = [event]
    for key in sorted(fields):
        if key in ALLOWED_FIELDS and fields[key] is not None:
            parts.append(f"{key}={fields[key]}")
    logger.log(level, " ".join(parts), stacklevel=2)


def origin_of(exc: BaseException) -> str:
    """Onde a exceção nasceu (arquivo:linha:função), sem a mensagem, que poderia ter texto."""
    tb = exc.__traceback__
    if tb is None:
        return "desconhecida"
    while tb.tb_next is not None:
        tb = tb.tb_next
    frame = tb.tb_frame.f_code
    return f"{frame.co_filename.rsplit('/', 1)[-1]}:{tb.tb_lineno}:{frame.co_name}"
