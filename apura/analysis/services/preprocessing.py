"""
Validação, normalização e privacidade da entrada (RF01, RF04, RF05).

Nenhuma função deste módulo registra texto bruto em log.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from django.conf import settings


class InputValidationError(Exception):
    """Erro de validação de entrada com código estável para a API (RF27)."""

    def __init__(self, code: str, message: str, action: str, field: str | None = None, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.field = field
        self.extra = extra


@dataclass(frozen=True)
class NewsInput:
    """Notícia normalizada pronta para inferência."""

    title: str
    subtitle: str
    body: str
    title_inferred: bool  # True quando o título foi derivado do corpo

    @property
    def full_text(self) -> str:
        return "\n".join(p for p in (self.title, self.subtitle, self.body) if p)


# --------------------------------------------------------------------------- #
# Normalização (RF04)
# --------------------------------------------------------------------------- #
_CONTROL_CHARS = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u200b-\u200f\u2028\u2029\ufeff]")
_MULTI_SPACE = re.compile(r"[ \t\u00a0]+")
_MULTI_NEWLINE = re.compile(r"\n{3,}")


def normalize_text(text: str | None) -> str:
    """Normaliza Unicode (NFC), remove caracteres de controle e espaços redundantes."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", str(text))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_CHARS.sub("", text)
    text = _MULTI_SPACE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _MULTI_NEWLINE.sub("\n\n", text)
    return text.strip()


def _letter_ratio(text: str) -> float:
    visible = [c for c in text if not c.isspace()]
    if not visible:
        return 0.0
    return sum(c.isalpha() for c in visible) / len(visible)


# --------------------------------------------------------------------------- #
# Idioma (RF04) — heurística determinística por palavras funcionais
# --------------------------------------------------------------------------- #
_WORD_RE = re.compile(r"[a-zà-öø-ÿ]+", re.IGNORECASE)

_PT_MARKERS = {
    "não", "você", "são", "também", "está", "estão", "isso", "esse", "essa", "muito",
    "pelo", "pela", "pelos", "pelas", "do", "da", "dos", "das", "no", "na", "nos", "nas",
    "um", "uma", "com", "para", "ao", "aos", "às", "foi", "já", "mais", "seu", "sua", "após",
    "então", "há", "quando", "onde", "ainda", "governo", "segundo", "até", "nós", "eles",
}
_ES_MARKERS = {
    "el", "los", "las", "del", "y", "pero", "muy", "también", "está", "es", "fue", "hay",
    "porque", "cuando", "donde", "nosotros", "ellos", "una", "con", "para", "al", "según",
    "gobierno", "más", "sus", "este", "esta", "ese", "esa",
}
_EN_MARKERS = {
    "the", "and", "of", "to", "is", "are", "was", "were", "that", "this", "with", "for",
    "on", "it", "be", "by", "from", "have", "has", "not", "you", "they", "which", "said",
}


def detect_portuguese(text: str) -> tuple[bool, dict[str, float]]:
    """
    Retorna (é_português, pontuações). Considera português quando a proporção de
    marcadores PT é a maior e atinge um mínimo absoluto.
    """
    words = [w.lower() for w in _WORD_RE.findall(text)]
    if not words:
        return False, {"pt": 0.0, "es": 0.0, "en": 0.0}
    total = len(words)
    scores = {
        "pt": sum(w in _PT_MARKERS for w in words) / total,
        "es": sum(w in _ES_MARKERS for w in words) / total,
        "en": sum(w in _EN_MARKERS for w in words) / total,
    }
    # Sinais ortográficos exclusivos do português reforçam a pontuação.
    pt_suffix = sum(w.endswith(("ção", "ções", "ão", "ões", "nh", "lh")) or "ç" in w or "ã" in w or "õ" in w
                    for w in words) / total
    scores["pt"] += pt_suffix
    is_pt = scores["pt"] >= 0.08 and scores["pt"] > scores["es"] and scores["pt"] > scores["en"]
    return is_pt, {k: round(v, 4) for k, v in scores.items()}


# --------------------------------------------------------------------------- #
# Validação completa da entrada por texto (RF01 + RF04)
# --------------------------------------------------------------------------- #
def _infer_title(body: str) -> tuple[str, str]:
    """
    Quando o usuário cola apenas um texto, usa a primeira linha curta como título.
    Se não houver quebra de linha adequada, o título fica vazio (não inventamos conteúdo).
    """
    first, sep, rest = body.partition("\n")
    if sep and 10 <= len(first) <= 200 and rest.strip():
        return first.strip(), rest.strip()
    return "", body


def build_news_input(text: str, title: str = "", subtitle: str = "") -> NewsInput:
    """Normaliza e valida a entrada textual, levantando InputValidationError em caso de falha."""
    cfg = settings.FAKE_EYES
    min_chars, max_chars = cfg["MIN_CHARS"], cfg["MAX_CHARS"]

    body = normalize_text(text)
    title = normalize_text(title)
    subtitle = normalize_text(subtitle)

    if not body:
        raise InputValidationError(
            "empty_input", "O texto enviado está vazio.",
            "Cole o conteúdo da notícia no campo de texto.", field="text",
        )

    # Um endereço pode conter palavras em português e passar nas demais
    # validações, mas seus caracteres não são o conteúdo da notícia.
    if re.fullmatch(r"(?:https?://|www\.)\S+", body, flags=re.IGNORECASE):
        raise InputValidationError(
            "url_in_text", "Você colou um link no campo de texto.",
            "Use a aba Inserir link ou cole o conteúdo da notícia em Colar texto.",
            field="text",
        )

    total_len = len(body) + len(title) + len(subtitle)
    if total_len < min_chars:
        raise InputValidationError(
            "text_too_short",
            f"O conteúdo tem {total_len} caracteres; o mínimo é {min_chars}.",
            "Acrescente mais contexto, como o parágrafo completo da notícia.",
            field="text", length=total_len, min_chars=min_chars,
        )
    if total_len > max_chars:
        formatted_max = f"{max_chars:,}".replace(",", ".")
        raise InputValidationError(
            "text_too_long",
            f"O conteúdo tem {total_len} caracteres; o máximo é {max_chars}.",
            f"Envie apenas o trecho com a alegação principal (até {formatted_max} caracteres).",
            field="text", length=total_len, max_chars=max_chars,
        )

    combined = f"{title} {subtitle} {body}"
    if _letter_ratio(combined) < 0.6:
        raise InputValidationError(
            "unreadable_input", "O conteúdo parece corrompido ou não contém texto suficiente.",
            "Verifique se o texto foi colado corretamente.", field="text",
        )

    is_pt, _scores = detect_portuguese(combined)
    if not is_pt:
        raise InputValidationError(
            "unsupported_language", "O conteúdo não parece estar em português.",
            "O Fake Eyes analisa apenas notícias em português. Envie um texto em português.",
            field="text",
        )

    title_inferred = False
    if not title:
        title, body = _infer_title(body)
        title_inferred = bool(title)

    return NewsInput(title=title, subtitle=subtitle, body=body, title_inferred=title_inferred)


# --------------------------------------------------------------------------- #
# Privacidade (RF05) — mascaramento antes de persistir
# --------------------------------------------------------------------------- #
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?55\s?)?\(?\d{2}\)?[\s-]?9?\s?\d{4}[-\s]?\d{4}(?!\d)")


def mask_pii(text: str) -> str:
    """Mascara e-mail, CPF e telefone. Nomes de pessoas públicas são preservados."""
    text = _EMAIL_RE.sub("[e-mail removido]", text)
    text = _CPF_RE.sub("[CPF removido]", text)
    text = _PHONE_RE.sub("[telefone removido]", text)
    return text


# Bordões de corrente: chamam atenção, mas não afirmam nada sobre o mundo.
_SLOGAN_WORDS = {
    "urgente", "atenção", "atencao", "alerta", "importante", "bomba", "compartilhe",
    "compartilhem", "repasse", "repassem", "veja", "leia", "antes", "que", "apaguem", "apague",
}


def is_substantive_claim(text: str) -> bool:
    """
    Se o trecho afirma algo: ao menos três palavras de conteúdo. "URGENTE!!!" ou
    "Compartilhe antes que apaguem!" como alegação levavam a busca de checagens a
    procurar só "URGENTE" e a trazer checagens de outros assuntos.
    """
    words = [w for w in re.findall(r"\w+", text.lower()) if len(w) >= 3 and w not in _SLOGAN_WORDS]
    return len(words) >= 3


def summarize_claim(news: NewsInput, max_len: int = 140) -> str:
    """
    Resumo curto da alegação para histórico (RF20). Até a Etapa 3 (RF06) usamos
    o título, ou a primeira frase do corpo, sempre com PII mascarada. Título ou frase
    que seja só um bordão é pulado em favor da primeira frase com conteúdo.
    """
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", news.body.strip()) if s.strip()]
    candidates = [news.title, *sentences]
    base = next((c for c in candidates if c and is_substantive_claim(c)), None)
    if base is None:
        base = news.title or (sentences[0] if sentences else news.body)
    base = mask_pii(base.strip())
    return base if len(base) <= max_len else base[: max_len - 1].rstrip() + "…"
