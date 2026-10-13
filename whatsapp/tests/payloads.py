"""Respostas de exemplo no formato REAL da API v1 (verificAI, commit 63a0382).

Espelham ``AnalysisResultSerializer``, ``errors.py`` e as mensagens do back end, e são as mesmas
da interface web (src/test/fixtures.js). Servem só para testes de contrato (RF29).
"""

from __future__ import annotations

import copy
from typing import Any

RECOMMENDATIONS = [
    "Procure a fonte original da informação antes de compartilhar.",
    "Compare com veículos de imprensa e agências de checagem reconhecidas.",
    "Verifique a data de publicação e se o conteúdo não está fora de contexto.",
    "Evite compartilhar enquanto houver dúvida sobre a veracidade.",
]

BASE_LIMITATIONS = [
    "O resultado é um apoio à avaliação e não substitui a verificação em fontes confiáveis.",
    "O índice de risco é um indicador e não representa a probabilidade de a notícia ser falsa.",
    "A consulta a fontes externas ainda não está habilitada; nenhuma evidência foi verificada.",
    "A confiança do modelo ainda não foi calibrada em dados independentes.",
]

ANALYSIS_ID = "7b0f7a48-2f0d-4c64-9a36-3e1d3a0c5a11"


def make_analysis(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": ANALYSIS_ID,
        "api_version": "v1",
        "created_at": "2026-10-08T11:53:00.000000Z",
        "input_type": "text",
        "status": {"code": "requer_atencao", "label": "Requer atenção"},
        "risk_index": 48.31,
        "claim": {
            "summary": "Todas as linhas de ônibus deixarão de funcionar no próximo domingo.",
            "confirmed_by_user": False,
        },
        "explanation": [
            "O padrão de escrita do texto se parece com o de notícias falsas vistas no treinamento do modelo.",
            "Foram encontradas expressões apelativas: “urgente”, “compartilhe”.",
            "Esses indicadores de linguagem são apenas sinais auxiliares e não provam que a notícia é falsa.",
        ],
        "abstention": [],
        "evidence": {"enabled": False, "sources": []},
        "indicators": {"signal": 0.41, "sensational_terms": ["urgente", "compartilhe"]},
        "model": {"label": "falsa", "fake_probability": 0.62, "confidence": 0.86, "calibrated": False},
        "risk": {"value": 48.31, "signals_missing": ["evidence_conflict"]},
        "limitations": list(BASE_LIMITATIONS),
        "recommendations": list(RECOMMENDATIONS),
        "versions": {"model": "bertimbau-fakenews-v4", "rules": "rules-v1.0.0", "schema": "1.0"},
        "duration_ms": 1204.7,
    }
    payload.update(copy.deepcopy(overrides))
    return payload


def low() -> dict[str, Any]:
    return make_analysis(
        status={"code": "poucos_sinais_de_risco", "label": "Poucos sinais de risco"},
        risk_index=18.4,
        claim={
            "summary": "Biblioteca municipal anuncia programação de leitura para sábado.",
            "confirmed_by_user": False,
        },
    )


def high() -> dict[str, Any]:
    return make_analysis(
        status={"code": "alto_risco", "label": "Alto risco"},
        risk_index=88.1,
        claim={"summary": "Órgão público confirma que todos receberão R$ 5.000 amanhã.", "confirmed_by_user": False},
    )


def inconclusive() -> dict[str, Any]:
    message = "O modelo não teve segurança estatística suficiente para indicar um nível de risco."
    return make_analysis(
        status={"code": "analise_inconclusiva", "label": "Análise inconclusiva"},
        risk_index=None,
        abstention=[{"code": "low_confidence", "message": message}],
        explanation=[message],
        claim={"summary": "Ouvi dizer que a praça do bairro será fechada para obras.", "confirmed_by_user": False},
    )


def error(code: str, message: str, action: str, *, field: str | None = None, details: dict | None = None) -> dict:
    body: dict[str, Any] = {"error": {"code": code, "message": message, "action": action, "field": field}}
    if details is not None:
        body["error"]["details"] = details
    return body


TEXT_TOO_SHORT = error(
    "text_too_short",
    "O conteúdo tem 12 caracteres; o mínimo é 50.",
    "Acrescente mais contexto, como o parágrafo completo da notícia.",
    field="text",
    details={"length": 12, "min_chars": 50},
)
TEXT_TOO_LONG = error(
    "text_too_long",
    "O conteúdo tem 5320 caracteres; o máximo é 5000.",
    "Envie apenas o trecho com a alegação principal (até 5.000 caracteres).",
    field="text",
    details={"length": 5320, "max_chars": 5000},
)
UNSUPPORTED_LANGUAGE = error(
    "unsupported_language",
    "O conteúdo não parece estar em português.",
    "O Fake Eyes analisa apenas textos em português.",
    field="text",
)
URL_UNAVAILABLE = error(
    "url_input_unavailable",
    "A análise por endereço (URL) ainda não está disponível nesta versão.",
    "Cole o texto da notícia e selecione a opção de texto.",
    field="url",
)
ANALYSIS_UNAVAILABLE = error(
    "analysis_unavailable",
    "Não foi possível concluir a análise agora.",
    "Tente novamente em alguns instantes.",
)
THROTTLED = error("throttled", "Muitas solicitações.", "Tente novamente em instantes.")
