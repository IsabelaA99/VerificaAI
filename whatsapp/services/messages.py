"""Textos que a pessoa lê no WhatsApp (substitui o ``context.py`` do RosaIA, que guardava o
prompt do Gemini).

Princípios, na mesma linha da interface web:

- Linguagem simples, uma frase para o problema e uma para a saída (Nielsen: ajudar a pessoa a
  reconhecer, diagnosticar e se recuperar de erros). Nada de código técnico na tela.
- Sempre dizer o que está acontecendo (Nielsen: visibilidade do estado do sistema), por isso o
  aviso de "estou analisando" quando a resposta demora.
- Conversa curta e direta, sem fingir ser uma pessoa (Erika Hall, *Conversational Design*).
- O WhatsApp só tem negrito (*assim*) e itálico (_assim_). Nada de cor: o significado está
  sempre nas palavras.
- O chatbot nunca diz que uma notícia é "verdadeira" ou "falsa": mostra sinais de risco (RF16).
"""

from __future__ import annotations

from typing import Any

from services.errors import ApuraApiError

MIN_TEXT_CHARS = 50  # RF01, aplicado pela API. Usado só para o texto de ajuda.


def format_int(value: Any) -> str:
    """1600 -> '1.600' (pt-BR)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return ""
    return f"{int(value):,}".replace(",", ".")


def welcome(*, url_input_enabled: bool) -> str:
    link_line = (
        "Você também pode enviar só o link da notícia."
        if url_input_enabled
        else "Por enquanto não analiso links: cole o texto da notícia."
    )
    return (
        "*Apura* — um segundo olhar sobre a notícia.\n\n"
        "Cole aqui o texto de uma notícia ou de uma mensagem que você recebeu. "
        "Eu faço uma análise automática e mostro quais sinais de risco apareceram.\n\n"
        f"Envie o texto completo, em português, com pelo menos {MIN_TEXT_CHARS} caracteres. {link_line}\n\n"
        "O resultado é um apoio à leitura crítica. Não é uma verificação humana e não diz se a "
        "notícia é verdadeira ou falsa."
    )


NO_TEXT = "Não recebi texto nessa mensagem. Cole aqui o texto da notícia que você quer analisar."

MEDIA_NOT_SUPPORTED = "Recebi um arquivo, mas por enquanto só analiso texto. Copie o texto da notícia e cole aqui."

ACK = "Recebi o texto e estou analisando. Pode levar até 30 segundos. Envio o resultado aqui assim que terminar."

ACK_LINK = (
    "Recebi o link. Estou abrindo a página e analisando a notícia. Pode levar até 30 segundos. "
    "Envio o resultado aqui assim que terminar."
)

# Sem as credenciais da Twilio não há como enviar o resultado depois do prazo do webhook.
LATER_UNAVAILABLE = (
    "A análise está demorando mais do que o WhatsApp permite esperar. Envie o texto de novo em alguns instantes."
)

UNEXPECTED = "Algo não saiu como esperado. Não foi possível concluir agora. Tente de novo em instantes."

EVIDENCE_FAILURE_NOTE = (
    "Não foi possível consultar as fontes. Esta análise considera só o texto enviado e por isso é "
    "limitada: ela pode mudar quando as fontes estiverem disponíveis."
)

BODY_AT_TWILIO_LIMIT_NOTE = (
    f"O WhatsApp entrega ao Apura até {format_int(1600)} caracteres por mensagem. "
    "Se o seu texto era maior, parte dele pode não ter sido analisada."
)


def link_not_available() -> str:
    return "*A análise por link ainda não está disponível.*\nPor enquanto, cole aqui o texto da notícia."


def error_text(error: ApuraApiError) -> str:
    """Texto do erro em português simples: o problema e a saída possível (RF27)."""
    d = error.details
    scenario = error.scenario

    if scenario == "invalid_url":
        return (
            "*Esse endereço não parece válido.*\nUse o endereço completo da notícia, começando com http:// ou https://."
        )
    if scenario == "page_unreachable":
        return (
            "*Não conseguimos abrir essa página.*\n"
            "Ela pode estar fora do ar, pedir assinatura, bloquear acessos automáticos ou não ter texto. "
            "Nenhuma análise foi feita só com o endereço. Você pode colar aqui o texto da notícia."
        )
    if scenario == "page_too_long":
        return (
            "*A notícia dessa página é longa demais para analisar de uma vez.*\n"
            "Copie e cole aqui só o trecho com a alegação principal."
        )
    if scenario == "text_insufficient":
        minimum = format_int(d.get("min_chars")) or format_int(MIN_TEXT_CHARS)
        length = format_int(d.get("length"))
        has = f"Seu texto tem {length} caracteres. " if length else ""
        return (
            "*Precisamos de um pouco mais de texto.*\n"
            f"{has}Para analisar, o conteúdo precisa ter pelo menos {minimum} caracteres. "
            "Cole o parágrafo completo ou a mensagem inteira."
        )
    if scenario == "text_too_long":
        maximum = format_int(d.get("max_chars"))
        length = format_int(d.get("length"))
        if length and maximum:
            has = f"Seu texto tem {length} caracteres e o limite é {maximum}. "
        elif maximum:
            has = f"O limite é de {maximum} caracteres. "
        else:
            has = ""
        return f"*O texto passou do limite.*\n{has}Envie só o trecho com a alegação principal."
    if scenario == "text_unreadable":
        return (
            "*Não conseguimos ler esse texto.*\n"
            "O conteúdo parece corrompido ou sem texto suficiente. Confira se ele foi colado corretamente."
        )
    if scenario == "unsupported_language":
        return (
            "*O Apura só analisa textos em português.*\n"
            "O conteúdo enviado não parece estar em português. Envie um texto em português."
        )
    if scenario == "url_unavailable":
        return link_not_available()
    if scenario == "api_unavailable":
        return (
            "*O serviço de análise está indisponível.*\n"
            "Não foi possível concluir a análise agora. O problema não está no seu texto. "
            "Tente de novo em instantes."
        )
    if scenario == "evidence_failure":
        return "*Não foi possível consultar as fontes.*\nTente de novo em instantes."
    if scenario == "timeout":
        return (
            "*A análise demorou mais do que o esperado.*\n"
            "O limite é de 30 segundos e a resposta não chegou a tempo. Envie o texto de novo."
        )
    if scenario == "rate_limited":
        seconds = error.retry_after_seconds
        wait = (
            f"Aguarde cerca de {seconds} {'segundo' if seconds == 1 else 'segundos'} e envie de novo."
            if seconds
            else "Aguarde um instante e envie de novo."
        )
        return f"*Muitas solicitações em pouco tempo.*\n{wait}"
    if scenario == "incompatible_api":
        return (
            "*Não consegui ler a resposta do serviço.*\n"
            "O serviço mudou de versão e este chatbot precisa ser atualizado. Tente de novo mais tarde."
        )
    if scenario == "rejected":
        detail = " ".join(part for part in (error.api_message, error.api_action) if part)
        return f"*Não foi possível enviar esse conteúdo.*\n{detail or 'Confira o conteúdo e tente de novo.'}"
    return "*Algo não saiu como esperado.*\nNão foi possível concluir agora. Tente de novo em instantes."
