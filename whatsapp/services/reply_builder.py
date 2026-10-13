"""Monta a resposta do WhatsApp a partir do resultado da API (RF16, RF17, RF18).

Ordem da resposta, igual à da interface web:
  1. status em linguagem simples e índice de risco (RF16: o status vem primeiro);
  2. alegação analisada e por que o resultado saiu assim (RF17);
  3. fontes, quando existirem, e limitações (RF17);
  4. ações seguras e aviso de que não houve verificação humana (RF18).

Todo o texto sobre a análise (explicação, limitações, recomendações, motivos de abstenção) vem da
própria API, que é a fonte única. Este módulo só organiza.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from services import messages
from services.errors import ApuraApiError, incompatible_api_failure
from utils.message_utils import split_message

STATUS_LOW = "poucos_sinais_de_risco"
STATUS_ATTENTION = "requer_atencao"
STATUS_HIGH = "alto_risco"
STATUS_INCONCLUSIVE = "analise_inconclusiva"

# Rótulos e frases curtas por status (mesmo texto da interface web).
STATUS_INFO: dict[str, tuple[str, str]] = {
    STATUS_LOW: (
        "Poucos sinais de risco",
        "Menos sinais de alerta. Confira a fonte antes de assumir que tudo está comprovado.",
    ),
    STATUS_ATTENTION: (
        "Requer atenção",
        "Há pontos a esclarecer. Uma pausa e mais contexto ajudam a decidir.",
    ),
    STATUS_HIGH: (
        "Alto risco",
        "Indícios fortes de risco. Evite repassar e procure referências verificáveis.",
    ),
    STATUS_INCONCLUSIVE: (
        "Análise inconclusiva",
        "Não há informação suficiente. A ausência de evidência não comprova falsidade.",
    ),
}

# PROPOSTA — o formato de uma fonte ainda não existe na API (Etapa 3; hoje "sources" é sempre uma
# lista vazia). Mesmos campos que a interface web assume: relation, publisher, title, url.
RELATION_ALIASES = {
    "compatible": "compatible",
    "compativel": "compatible",
    "conflicting": "conflicting",
    "conflitante": "conflicting",
    "contextual": "contextual",
    "insufficient": "insufficient",
    "insuficiente": "insufficient",
}
RELATION_LABELS = {
    "compatible": "compatível com a alegação",
    "conflicting": "conflitante com a alegação",
    "contextual": "traz contexto",
    "insufficient": "insuficiente para confirmar ou contestar",
}

FOOTER = (
    "Análise feita por computador, como apoio à leitura crítica. "
    "Não houve verificação humana. Confira a fonte original antes de compartilhar."
)


@dataclass(frozen=True)
class Source:
    relation: str
    publisher: str
    title: str
    url: str


@dataclass(frozen=True)
class Analysis:
    id: str
    created_at: datetime
    status_code: str
    risk_index: float | None
    claim_summary: str
    explanation: tuple[str, ...]
    abstention: tuple[str, ...]
    limitations: tuple[str, ...]
    recommendations: tuple[str, ...]
    sources: tuple[Source, ...]
    evidence_failed: bool


def _strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _safe_http_url(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip()
    return candidate if candidate.lower().startswith(("http://", "https://")) and " " not in candidate else ""


def _parse_sources(evidence: Any) -> tuple[tuple[Source, ...], bool]:
    if not isinstance(evidence, dict):
        return (), False
    # PROPOSTA: sinal de falha na consulta de evidências (RF27, cenário 6).
    failed = evidence.get("failed") is True or isinstance(evidence.get("error"), dict)
    parsed: list[Source] = []
    raw_sources = evidence.get("sources")
    for raw in raw_sources if isinstance(raw_sources, list) else []:
        if not isinstance(raw, dict):
            continue
        relation = RELATION_ALIASES.get(str(raw.get("relation") or "").lower())
        # Sem relação demonstrável com a alegação, a fonte não aparece (RF08).
        if not relation:
            continue
        parsed.append(
            Source(
                relation=relation,
                publisher=str(raw.get("publisher") or "").strip(),
                title=str(raw.get("title") or "").strip(),
                url=_safe_http_url(raw.get("url")),
            )
        )
    return tuple(parsed), failed


def parse_analysis(raw: Any) -> Analysis:
    """Lê a resposta da API v1. Lança ``ApuraApiError`` (incompatible_api) se faltar algo essencial."""
    if not isinstance(raw, dict):
        raise incompatible_api_failure("A resposta não é um objeto JSON.")
    if raw.get("api_version") != "v1":
        raise incompatible_api_failure("Versão de API não suportada.")

    analysis_id = raw.get("id")
    if not isinstance(analysis_id, str) or not analysis_id.strip():
        raise incompatible_api_failure("A resposta não traz o identificador da análise.")

    created_raw = raw.get("created_at")
    try:
        created_at = datetime.fromisoformat(created_raw) if isinstance(created_raw, str) else None
    except ValueError:
        created_at = None
    if created_at is None:
        raise incompatible_api_failure("A resposta não traz uma data válida.")
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)

    status = raw.get("status")
    status_code = status.get("code") if isinstance(status, dict) else None
    if status_code not in STATUS_INFO:
        raise incompatible_api_failure("A resposta traz um status desconhecido.")

    risk_raw = raw.get("risk_index")
    risk_index: float | None = None
    if risk_raw is not None:
        if isinstance(risk_raw, bool) or not isinstance(risk_raw, int | float) or not 0 <= risk_raw <= 100:
            raise incompatible_api_failure("O índice de risco está fora do intervalo de 0 a 100.")
        risk_index = float(risk_raw)

    claim = raw.get("claim")
    summary_raw = claim.get("summary") if isinstance(claim, dict) else None
    claim_summary = summary_raw.strip() if isinstance(summary_raw, str) else ""

    abstention_raw = raw.get("abstention")
    abstention = tuple(
        item["message"].strip()
        for item in (abstention_raw if isinstance(abstention_raw, list) else [])
        if isinstance(item, dict) and isinstance(item.get("message"), str) and item["message"].strip()
    )
    sources, evidence_failed = _parse_sources(raw.get("evidence"))

    return Analysis(
        id=analysis_id.strip(),
        created_at=created_at,
        status_code=status_code,
        risk_index=risk_index,
        claim_summary=claim_summary,
        explanation=_strings(raw.get("explanation")),
        abstention=abstention,
        limitations=_strings(raw.get("limitations")),
        recommendations=_strings(raw.get("recommendations")),
        sources=sources,
        evidence_failed=evidence_failed,
    )


def effective_status(analysis: Analysis) -> str:
    """RF16: o status inconclusivo tem prioridade quando qualquer condição do RF14 ocorre.

    A API já decide isso. Esta checagem impede que um resultado com motivo de abstenção (ou sem
    índice) apareça como baixo, médio ou alto risco.
    """
    if analysis.status_code == STATUS_INCONCLUSIVE:
        return STATUS_INCONCLUSIVE
    if analysis.abstention or analysis.risk_index is None:
        return STATUS_INCONCLUSIVE
    return analysis.status_code


def format_decimal(value: float) -> str:
    """48.31 -> '48,3'; 25.0 -> '25' (pt-BR, uma casa, arredondando para cima no meio)."""
    rounded = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    text = f"{rounded:f}"
    if text.endswith(".0"):
        text = text[:-2]
    return text.replace(".", ",")


def format_datetime(value: datetime) -> str:
    """'08/10/2026 08:53', no horário de Brasília."""
    try:
        local = value.astimezone(ZoneInfo("America/Sao_Paulo"))
        suffix = ""
    except ZoneInfoNotFoundError:  # sem o banco de fusos horários instalado
        local = value.astimezone(UTC)
        suffix = " (UTC)"
    return local.strftime("%d/%m/%Y %H:%M") + suffix


def _bullets(items: tuple[str, ...] | list[str]) -> list[str]:
    return [f"• {item}" for item in items]


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def build_result_messages(
    analysis: Analysis,
    *,
    web_base_url: str = "",
    extra_limitations: tuple[str, ...] = (),
) -> list[str]:
    """Texto da resposta, já dividido em mensagens de no máximo 1600 caracteres."""
    code = effective_status(analysis)
    label, summary = STATUS_INFO[code]
    inconclusive = code == STATUS_INCONCLUSIVE

    sections: list[str] = []

    # 1. Status primeiro (RF16).
    status_lines = [f"*Status: {label}*", summary]
    if inconclusive:
        status_lines.append(
            "Índice de risco: não calculado nesta análise. Ela não chegou a uma conclusão e não deve ser "
            "usada para dizer que a notícia é verdadeira nem que é falsa."
        )
    elif analysis.risk_index is not None:
        status_lines.append(
            f"Índice de risco: {format_decimal(analysis.risk_index)} de 100. "
            "É um indicador de risco, não a chance de a notícia ser falsa."
        )
    sections.append("\n".join(status_lines))

    # 2. Alegação analisada (resumo automático: ainda não há como a pessoa confirmar, RF06).
    if analysis.claim_summary:
        sections.append(f"*Alegação analisada* (resumo automático)\n“{analysis.claim_summary}”")

    # 3. Por que o resultado saiu assim (RF17).
    reasons = list(analysis.explanation)
    if inconclusive:
        reasons = _unique([*analysis.abstention, *analysis.explanation])
    if reasons:
        title = "Por que ficou inconclusiva" if inconclusive else "O que o Apura encontrou"
        sections.append("\n".join([f"*{title}*", *_bullets(reasons)]))

    # 4. Fontes, quando existirem (RF17, RF18).
    if analysis.sources:
        lines = ["*Fontes*"]
        for source in analysis.sources:
            name = ": ".join(part for part in (source.publisher, source.title) if part) or "Fonte sem identificação"
            lines.append(f"• {name} ({RELATION_LABELS[source.relation]})")
            if source.url:
                lines.append(f"  {source.url}")
        sections.append("\n".join(lines))

    # 5. Limitações (RF17, RF18).
    limitations = list(analysis.limitations)
    if analysis.evidence_failed:
        limitations.insert(0, messages.EVIDENCE_FAILURE_NOTE)
    limitations.extend(extra_limitations)
    if limitations:
        sections.append("\n".join(["*Limitações*", *_bullets(_unique(limitations))]))

    # 6. Ações seguras (RF18).
    if analysis.recommendations:
        sections.append("\n".join(["*O que fazer agora*", *_bullets(analysis.recommendations)]))

    # 7. Rodapé: nunca afirma verificação humana (RF18), com data da análise.
    footer = [FOOTER, f"Data da análise: {format_datetime(analysis.created_at)}"]
    if web_base_url:
        footer.append(f"Detalhes completos: {web_base_url}/resultado/{analysis.id}")
    sections.append("\n".join(footer))

    return split_message("\n\n".join(sections))


def build_error_messages(error: ApuraApiError) -> list[str]:
    return split_message(messages.error_text(error))
