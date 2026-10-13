import logging
import xml.etree.ElementTree as ET

import pytest

from services.errors import ApuraApiError
from tests import payloads
from tests.conftest import AUTH_TOKEN, USER_NUMBER, WEBHOOK, FakeClient, FakeSender, incoming, sign

TEXT = "Urgente! Compartilhe antes que apaguem: todas as linhas de ônibus param no domingo."


def post(app, body=TEXT, *, headers=None, data=None, **kwargs):
    form = data if data is not None else incoming(body)
    return app.test_client().post("/mensagem", data=form, headers=sign(form) if headers is None else headers, **kwargs)


def messages_of(response):
    return [element.text for element in ET.fromstring(response.data).iter("Message")]  # noqa: S314


class TestWebhook:
    def test_responde_em_twiml_com_o_resultado(self, make_app):
        response = post(make_app(FakeClient(payloads.make_analysis())))
        assert response.status_code == 200
        assert response.mimetype == "application/xml"
        [first, *_] = messages_of(response)
        assert first.startswith("*Status: Requer atenção*")

    def test_resposta_longa_vira_varias_mensagens_de_no_maximo_1600_caracteres(self, make_app):
        raw = payloads.make_analysis(explanation=["Fator " + "x" * 300 for _ in range(20)])
        blocks = messages_of(post(make_app(FakeClient(raw))))
        assert len(blocks) > 1
        assert all(len(block) <= 1600 for block in blocks)

    def test_erro_da_api_chega_como_mensagem_simples(self, make_app):
        client = FakeClient(ApuraApiError("api_unavailable", code="analysis_unavailable"))
        [text] = messages_of(post(make_app(client)))
        assert "O serviço de análise está indisponível." in text
        assert "analysis_unavailable" not in text

    def test_cumprimento_recebe_a_explicacao_sem_chamar_a_api(self, make_app):
        client = FakeClient(payloads.make_analysis())
        [text] = messages_of(post(make_app(client), "Oi"))
        assert "um segundo olhar sobre a notícia" in text
        assert client.calls == []

    def test_corpo_ausente_nao_quebra(self, make_app):
        form = {"From": USER_NUMBER, "To": "whatsapp:+14155238886"}
        [text] = messages_of(post(make_app(FakeClient()), data=form))
        assert "Não recebi texto" in text

    def test_numero_de_arquivos_invalido_nao_quebra(self, make_app):
        form = incoming(TEXT, NumMedia="abc")
        response = post(make_app(FakeClient(payloads.make_analysis())), data=form)
        assert response.status_code == 200

    def test_arquivo_anexado_recebe_aviso(self, make_app):
        form = incoming(
            "legenda " * 10, NumMedia="1", MediaUrl0="https://api.twilio.com/x", MediaContentType0="image/jpeg"
        )
        [text] = messages_of(post(make_app(FakeClient()), data=form))
        assert "só analiso texto" in text

    def test_texto_com_caracteres_especiais_e_xml_vai_escapado(self, make_app):
        raw = payloads.make_analysis(claim={"summary": "A < B & C > D", "confirmed_by_user": False})
        [text] = messages_of(post(make_app(FakeClient(raw))))
        assert "“A < B & C > D”" in text  # volta igual depois de ler o XML

    def test_get_no_webhook_nao_e_permitido(self, make_app):
        assert make_app(FakeClient()).test_client().get("/mensagem").status_code == 405

    def test_corpo_gigante_e_recusado_antes_de_ser_lido(self, make_app):
        form = incoming("a" * 100_000)
        assert post(make_app(FakeClient()), data=form).status_code == 413


class TestAssinaturaDaTwilio:
    def test_sem_assinatura_e_proibido_e_a_api_nao_e_chamada(self, make_app):
        client = FakeClient(payloads.make_analysis())
        response = post(make_app(client), headers={})
        assert response.status_code == 403
        assert response.data == b""
        assert client.calls == []

    def test_assinatura_errada_e_proibida(self, make_app):
        client = FakeClient(payloads.make_analysis())
        assert post(make_app(client), headers={"X-Twilio-Signature": "AAAA"}).status_code == 403
        assert client.calls == []

    def test_assinatura_de_outro_token_e_proibida(self, make_app):
        form = incoming(TEXT)
        headers = sign(form, token="outro-token")
        assert post(make_app(FakeClient(payloads.make_analysis())), data=form, headers=headers).status_code == 403

    def test_corpo_alterado_depois_de_assinado_e_proibido(self, make_app):
        signed = incoming(TEXT)
        headers = sign(signed)
        tampered = {**signed, "Body": TEXT + " (alterado)"}
        assert post(make_app(FakeClient(payloads.make_analysis())), data=tampered, headers=headers).status_code == 403

    def test_url_diferente_da_assinada_e_proibida(self, make_app):
        form = incoming(TEXT)
        headers = sign(form, url="http://outro-site.example/mensagem")
        assert post(make_app(FakeClient(payloads.make_analysis())), data=form, headers=headers).status_code == 403

    def test_url_publica_configurada_vale_atras_de_proxy(self, make_app):
        public = "https://bot.exemplo.org/mensagem"
        form = incoming(TEXT)
        app = make_app(FakeClient(payloads.make_analysis()), public_webhook_url=public)
        assert post(app, data=form, headers=sign(form, url=public)).status_code == 200
        assert post(app, data=form, headers=sign(form, url=WEBHOOK)).status_code == 403

    def test_sem_url_publica_usa_o_esquema_informado_pelo_proxy(self, make_app):
        form = incoming(TEXT)
        headers = {**sign(form, url="https://localhost/mensagem"), "X-Forwarded-Proto": "https"}
        assert post(make_app(FakeClient(payloads.make_analysis())), data=form, headers=headers).status_code == 200

    def test_validacao_desligada_aceita_sem_assinatura_so_em_desenvolvimento(self, make_app):
        app = make_app(FakeClient(payloads.make_analysis()), validate_signature=False)
        assert post(app, headers={}).status_code == 200

    def test_assinatura_invalida_vai_para_o_log_sem_dados_pessoais(self, make_app, caplog):
        with caplog.at_level(logging.DEBUG):
            post(make_app(FakeClient()), headers={"X-Twilio-Signature": "AAAA"})
        assert "assinatura_invalida" in caplog.text
        assert USER_NUMBER not in caplog.text
        assert AUTH_TOKEN not in caplog.text


class TestSaude:
    def test_responde_ok_sem_depender_de_ninguem(self, make_app):
        response = make_app(FakeClient()).test_client().get("/saude")
        assert response.status_code == 200
        assert response.get_json() == {"status": "ok", "service": "apura-whatsapp"}


class TestPrivacidadeDeBordaABorda:
    @pytest.mark.parametrize(
        "result",
        [
            payloads.make_analysis(),
            ApuraApiError("text_insufficient", details={"length": 3, "min_chars": 50}),
            RuntimeError(TEXT),
        ],
        ids=["sucesso", "erro_da_api", "defeito_inesperado"],
    )
    def test_nenhum_log_tem_telefone_texto_ou_segredo(self, make_app, caplog, result):
        with caplog.at_level(logging.DEBUG):
            post(make_app(FakeClient(result), FakeSender()))
        for secret in (TEXT, "ônibus", USER_NUMBER, "5511987654321", AUTH_TOKEN, "ACtest"):
            assert secret not in caplog.text

    def test_biblioteca_da_twilio_nao_registra_a_url_com_o_account_sid(self, make_app, caplog):
        from twilio.http.http_client import TwilioHttpClient

        make_app(FakeClient())
        url = "https://api.twilio.com/2010-04-01/Accounts/ACtest/Messages.json"
        with caplog.at_level(logging.DEBUG):
            TwilioHttpClient().log_request({"method": "POST", "url": url, "params": None, "headers": {}})
        assert "ACtest" not in caplog.text


class TestDefeitoInesperado:
    def test_defeito_na_rota_responde_com_aviso_simples_e_registra_so_a_classe(self, make_app, caplog, monkeypatch):
        from services.replies import ReplyService

        def explode(self, _incoming):
            raise ValueError(TEXT)

        monkeypatch.setattr(ReplyService, "handle", explode)
        with caplog.at_level(logging.DEBUG):
            response = post(make_app(FakeClient()))
        assert response.status_code == 200
        assert "Tente de novo em instantes" in messages_of(response)[0]
        assert "erro_inesperado_rota error_class=ValueError" in caplog.text
        assert TEXT not in caplog.text
