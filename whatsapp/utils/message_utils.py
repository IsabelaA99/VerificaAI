"""Funções de texto do chatbot: dividir respostas longas e interpretar o que a pessoa enviou."""

from __future__ import annotations

import re
import unicodedata

# A Twilio aceita até 1600 caracteres por mensagem (Programmable Messaging).
MAX_MESSAGE_CHARS = 1600


def _split_long_line(line: str, max_chars: int) -> list[str]:
    """Quebra uma linha maior que o limite, de preferência entre palavras."""
    parts: list[str] = []
    current = ""
    for word in line.split(" "):
        # Palavra maior que o limite (um link enorme, por exemplo): corte duro, sem perder nada.
        while len(word) > max_chars:
            if current:
                parts.append(current)
                current = ""
            parts.append(word[:max_chars])
            word = word[max_chars:]
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            parts.append(current)
            current = word
    if current:
        parts.append(current)
    return parts


def _split_long_paragraph(paragraph: str, max_chars: int) -> list[str]:
    """Quebra um parágrafo maior que o limite, de preferência entre linhas."""
    parts: list[str] = []
    current = ""
    for line in paragraph.split("\n"):
        pieces = _split_long_line(line, max_chars) if len(line) > max_chars else [line]
        for piece in pieces:
            candidate = piece if not current else f"{current}\n{piece}"
            if len(candidate) <= max_chars:
                current = candidate
            else:
                parts.append(current)
                current = piece
    if current:
        parts.append(current)
    return parts


def split_message(text: str, max_chars: int = MAX_MESSAGE_CHARS) -> list[str]:
    """Divide uma resposta em blocos de no máximo ``max_chars`` caracteres.

    Mantém a função e a assinatura do RosaIA (``split_message(text, max_chars=1600)``), com três
    correções: nunca devolve bloco vazio, nunca ultrapassa o limite (o RosaIA deixava passar um
    parágrafo grande demais) e prefere cortar entre seções, em vez de no meio de uma lista.
    """
    if max_chars < 1:
        raise ValueError("max_chars deve ser pelo menos 1.")

    paragraphs = [
        "\n".join(line.rstrip() for line in block.strip().split("\n"))
        for block in re.split(r"\n[ \t]*\n", text.replace("\r\n", "\n").strip())
        if block.strip()
    ]

    pieces: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            pieces.append(paragraph)
        else:
            pieces.extend(_split_long_paragraph(paragraph, max_chars))

    blocks: list[str] = []
    buffer = ""
    for piece in pieces:
        candidate = piece if not buffer else f"{buffer}\n\n{piece}"
        if len(candidate) <= max_chars:
            buffer = candidate
        else:
            blocks.append(buffer)
            buffer = piece
    if buffer:
        blocks.append(buffer)
    return blocks


def normalize_command(text: str) -> str:
    """Minúsculas, sem acentos, sem pontuação nem emoji: "Olá!! 🙂" vira "ola"."""
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    letters_only = re.sub(r"[^a-z0-9]+", " ", without_marks.lower())
    return letters_only.strip()


_SCHEME_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_BARE_ADDRESS = re.compile(r"(?:www\.)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:[/?#]\S*)?", re.IGNORECASE)


def as_link(text: str) -> tuple[str, bool] | None:
    """Se a mensagem inteira é um link, devolve (link, tem_http). Senão, ``None``.

    "Mensagem inteira" importa: um texto de notícia que contém um link no meio continua sendo
    texto. Um endereço sem http(s):// (ex.: "g1.globo.com/politica") é reconhecido como link
    incompleto para a pessoa saber o que corrigir.
    """
    candidate = text.strip()
    if not candidate or re.search(r"\s", candidate):
        return None
    if _SCHEME_URL.fullmatch(candidate):
        return candidate, True
    if _BARE_ADDRESS.fullmatch(candidate):
        return candidate, False
    return None
