import logging
import threading

import pytest

from config import TWILIO_BODY_LIMIT, Settings
from services import messages
from services.errors import ApuraApiError
from services.replies import Incoming, ReplyService, interpret
from tests import payloads
from tests.conftest import BOT_NUMBER, USER_NUMBER, FakeClient, FakeSender

TEXT = "Urgente! Compartilhe antes que apaguem: todas as linhas de ônibus param no domingo."


def incoming(body=TEXT, media=0):
    return Incoming(body=body, num_media=media, from_number=USER_NUMBER, to_number=BOT_NUMBER)


def service(client, sender=None, **settings):
    values = {"twilio_auth_token": "x", "sync_wait_seconds": 2.0, **settings}
    return ReplyService(settings=Settings(**values), client=client, sender=sender)


class TestInterpret:
    def test_arquivo_anexado_nao_e_analisado_mesmo_com_legenda(self):
        intent = interpret(incoming("legenda da foto " * 5, media=1), url_input_enabled=False)
        assert intent.kind == "media"
        assert intent.reply == (messages.MEDIA_NOT_SUPPORTED,)

    @pytest.mark.parametrize("body", ["", "   ", "\n", "👍", "???", "🙂🙂"])
    def test_mensagem_sem_texto_pede_o_texto(self, body):
        intent = interpret(incoming(body), url_input_enabled=False)
        assert intent.kind == "empty"
        assert intent.reply == (messages.NO_TEXT,)

    @pytest.mark.parametrize(
        "body", ["oi", "Olá!", "BOM DIA", "boa tarde 🙂", "ajuda", "Menu", "Como funciona?", "começar"]
    )
    def test_cumprimento_ou_pedido_de_ajuda_explica_como_usar(self, body):
        intent = interpret(incoming(body), url_input_enabled=False)
        assert intent.kind == "help"
        assert "Cole aqui o texto" in intent.reply[0]

    def test_ajuda_diz_a_verdade_sobre_links(self):
        off = interpret(incoming("oi"), url_input_enabled=False).reply[0]
        on = interpret(incoming("oi"), url_input_enabled=True).reply[0]
        assert "não analiso links" in off
        assert "enviar só o link" in on

    def test_ajuda_nunca_promete_verificacao_humana_nem_veredito(self):
        text = interpret(incoming("oi"), url_input_enabled=False).reply[0]
        assert "Não é uma verificação humana" in text
        assert "não diz se a notícia é verdadeira ou falsa" in text

    def test_link_com_a_entrada_por_link_desligada_nao_chama_a_api(self):
        intent = interpret(incoming("https://exemplo.com/noticia"), url_input_enabled=False)
        assert intent.kind == "link_unavailable"
        assert "ainda não está disponível" in intent.reply[0]

    def test_link_com_a_entrada_ligada_vai_como_link(self):
        intent = interpret(incoming(" https://exemplo.com/noticia "), url_input_enabled=True)
        assert (intent.kind, intent.url, intent.text) == ("link", "https://exemplo.com/noticia", None)

    def test_endereco_sem_http_ganha_https(self):
        intent = interpret(incoming("g1.globo.com/politica/x.ghtml"), url_input_enabled=True)
        assert (intent.kind, intent.url) == ("link", "https://g1.globo.com/politica/x.ghtml")

    @pytest.mark.parametrize(
        "body",
        [
            "olha isso https://exemplo.com/noticia",
            "https://exemplo.com/noticia\n\nÉ verdade?",
            "Viu essa? (https://exemplo.com/noticia).",
        ],
    )
    def test_link_com_comentario_curto_vai_como_link(self, body):
        # É assim que se compartilha no WhatsApp; o comentário sozinho nem poderia ser analisado
        intent = interpret(incoming(body), url_input_enabled=True)
        assert (intent.kind, intent.url, intent.text) == ("link", "https://exemplo.com/noticia", None)

    def test_link_com_comentario_curto_e_links_desligados_avisa_sem_chamar_a_api(self):
        intent = interpret(incoming("olha isso https://exemplo.com/noticia"), url_input_enabled=False)
        assert intent.kind == "link_unavailable"

    def test_texto_com_link_no_meio_continua_sendo_texto(self):
        body = f"{TEXT} Veja https://exemplo.com/x"
        intent = interpret(incoming(body), url_input_enabled=True)
        assert (intent.kind, intent.text) == ("text", body)

    def test_comentario_curto_com_dois_links_continua_sendo_texto(self):
        body = "compare https://a.exemplo.com/x e https://b.exemplo.com/y"
        assert interpret(incoming(body), url_input_enabled=True).kind == "text"

    def test_texto_vai_exatamente_como_chegou(self):
        body = f"  {TEXT}\n\nSegunda linha.  "
        assert interpret(incoming(body), url_input_enabled=False).text == body


class TestRespostaImediata:
    def test_analisa_e_responde_no_proprio_webhook(self):
        client = FakeClient(payloads.make_analysis())
        blocks = service(client).handle(incoming())
        assert client.calls == [{"text": TEXT, "url": None}]
        assert blocks[0].startswith("*Status: Requer atenção*")

    def test_mensagem_estatica_nao_chama_a_api(self):
        client = FakeClient(payloads.make_analysis())
        service(client).handle(incoming("oi"))
        service(client).handle(incoming("", media=0))
        service(client).handle(incoming("foto", media=1))
        assert client.calls == []

    def test_link_chama_a_api_com_o_link_quando_a_entrada_esta_ligada(self):
        client = FakeClient(payloads.make_analysis(input_type="url"))
        service(client, url_input_enabled=True).handle(incoming("https://exemplo.com/noticia"))
        assert client.calls == [{"text": None, "url": "https://exemplo.com/noticia"}]

    def test_erro_da_api_vira_mensagem_com_o_problema_e_a_saida(self):
        error = ApuraApiError("text_insufficient", details={"length": 12, "min_chars": 50})
        blocks = service(FakeClient(error)).handle(incoming("texto curto"))
        assert "Seu texto tem 12 caracteres." in blocks[0]
        assert "Cole o parágrafo completo" in blocks[0]

    def test_pagina_sem_texto_nao_fala_do_texto_da_pessoa(self):
        # A API valida o texto que ELA extraiu da página; a pessoa mandou só um link
        error = ApuraApiError("text_insufficient", details={"length": 12, "min_chars": 50})
        blocks = service(FakeClient(error)).handle(incoming("https://exemplo.com/noticia"))
        assert "Não conseguimos abrir essa página" in blocks[0]
        assert "Seu texto" not in blocks[0]

    def test_pagina_longa_demais_pede_o_trecho_principal(self):
        error = ApuraApiError("text_too_long", details={"length": 30000, "max_chars": 20000})
        blocks = service(FakeClient(error)).handle(incoming("https://exemplo.com/noticia"))
        assert "longa demais" in blocks[0]
        assert "Seu texto" not in blocks[0]

    def test_defeito_inesperado_nao_derruba_a_conversa(self):
        blocks = service(FakeClient(RuntimeError("boom"))).handle(incoming())
        assert "Tente de novo em instantes" in blocks[0]

    def test_resposta_da_api_fora_do_formato_vira_incompatibilidade(self):
        blocks = service(FakeClient({"api_version": "v1"})).handle(incoming())
        assert "precisa ser atualizado" in blocks[0]

    def test_texto_no_limite_da_twilio_avisa_que_pode_ter_ficado_texto_de_fora(self):
        body = "a" * TWILIO_BODY_LIMIT
        text = "\n\n".join(service(FakeClient(payloads.make_analysis())).handle(incoming(body)))
        assert "até 1.600 caracteres por mensagem" in text

    def test_texto_menor_que_o_limite_nao_leva_o_aviso(self):
        text = "\n\n".join(service(FakeClient(payloads.make_analysis())).handle(incoming(TEXT)))
        assert "até 1.600 caracteres" not in text


class TestResultadoEnviadoDepois:
    """A Twilio espera 15 s; a API pode levar 30 s (RNF01). Depois do prazo, avisa e envia depois."""

    def slow(self, result=None):
        client = FakeClient(result if result is not None else payloads.make_analysis())
        client.release.clear()
        return client

    def test_demora_vira_aviso_imediato_e_o_resultado_chega_depois(self):
        client, sender = self.slow(), FakeSender()
        reply = service(client, sender, sync_wait_seconds=0.05).handle(incoming())

        assert reply == [messages.ACK]
        assert sender.sent == []  # ainda não terminou

        client.release.set()
        assert sender.done.wait(timeout=5)
        [sent] = sender.sent
        assert sent["to"] == USER_NUMBER  # responde à pessoa...
        assert sent["from_"] == BOT_NUMBER  # ...a partir do número que ela escreveu
        assert sent["bodies"][0].startswith("*Status: Requer atenção*")

    def test_demora_com_link_avisa_que_recebeu_o_link(self):
        client, sender = self.slow(payloads.make_analysis(input_type="url")), FakeSender()
        reply = service(client, sender, sync_wait_seconds=0.05).handle(incoming("https://exemplo.com/noticia"))
        assert reply == [messages.ACK_LINK]
        client.release.set()
        assert sender.done.wait(timeout=5)

    def test_o_conteudo_enviado_depois_e_o_mesmo_da_resposta_imediata(self):
        fast = service(FakeClient(payloads.make_analysis())).handle(incoming())
        client, sender = self.slow(), FakeSender()
        service(client, sender, sync_wait_seconds=0.05).handle(incoming())
        client.release.set()
        assert sender.done.wait(timeout=5)
        assert sender.sent[0]["bodies"] == fast

    def test_erro_depois_do_prazo_tambem_e_entregue(self):
        client, sender = self.slow(ApuraApiError("timeout")), FakeSender()
        service(client, sender, sync_wait_seconds=0.05).handle(incoming())
        client.release.set()
        assert sender.done.wait(timeout=5)
        assert "limite é de 30 segundos" in sender.sent[0]["bodies"][0]

    def test_sem_credenciais_da_twilio_nao_promete_o_que_nao_pode_cumprir(self):
        client = self.slow()
        reply = service(client, None, sync_wait_seconds=0.05).handle(incoming())
        client.release.set()
        assert reply == [messages.LATER_UNAVAILABLE]
        assert "Envie o texto de novo" in reply[0]

    def test_falha_no_envio_e_registrada_sem_texto_nem_telefone(self, caplog):
        client, sender = self.slow(), FakeSender(error=RuntimeError(f"falhou para {USER_NUMBER}: {TEXT}"))
        with caplog.at_level(logging.DEBUG):
            service(client, sender, sync_wait_seconds=0.05).handle(incoming())
            client.release.set()
            assert sender.done.wait(timeout=5)
            # a thread registra o erro logo depois de o falso lançar a exceção
            for _ in range(100):
                if "resultado_nao_entregue" in caplog.text:
                    break
                threading.Event().wait(0.02)
        assert "resultado_nao_entregue error_class=RuntimeError" in caplog.text
        assert USER_NUMBER not in caplog.text
        assert "ônibus" not in caplog.text

    def test_so_a_primeira_resposta_usa_o_webhook(self):
        client, sender = self.slow(), FakeSender()
        replies = service(client, sender, sync_wait_seconds=0.05)
        assert replies.handle(incoming()) == [messages.ACK]
        client.release.set()
        assert sender.done.wait(timeout=5)
        assert len(sender.sent) == 1


class TestPrivacidade:
    def test_repr_da_mensagem_recebida_esconde_texto_e_telefone(self):
        text = repr(incoming(TEXT))
        assert TEXT not in text
        assert USER_NUMBER not in text
        assert "chars=" in text

    def test_logs_de_uma_analise_nao_tem_texto_nem_telefone(self, caplog):
        with caplog.at_level(logging.DEBUG):
            service(FakeClient(payloads.make_analysis())).handle(incoming())
            service(FakeClient(ApuraApiError("text_insufficient", api_message=TEXT))).handle(incoming())
            service(FakeClient(RuntimeError(TEXT))).handle(incoming())
        assert caplog.text
        for secret in (TEXT, "ônibus", USER_NUMBER, BOT_NUMBER, "5511987654321"):
            assert secret not in caplog.text
        assert "mensagem_recebida" in caplog.text
        assert "kind=text" in caplog.text
        assert "analise_concluida" in caplog.text
