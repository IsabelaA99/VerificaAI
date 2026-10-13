import json

import pytest
import requests
import responses

from services.apura_client import ApuraClient
from services.errors import ApuraApiError
from tests import payloads

BASE = "http://api.test/api"
ENDPOINT = f"{BASE}/v1/analyses/"


@pytest.fixture
def client():
    return ApuraClient(BASE, connect_timeout=1, read_timeout=2)


def failure(client, **kwargs) -> ApuraApiError:
    with pytest.raises(ApuraApiError) as info:
        client.analyze(**kwargs)
    return info.value


@responses.activate
def test_envia_so_o_texto_e_o_tipo_da_entrada(client):
    responses.post(ENDPOINT, json=payloads.make_analysis(), status=201)
    client.analyze(text="Texto da notícia\ncom duas linhas  ")
    request = responses.calls[0].request
    assert json.loads(request.body) == {"input_type": "text", "text": "Texto da notícia\ncom duas linhas  "}


@responses.activate
def test_envia_so_o_link_quando_a_entrada_e_um_link(client):
    responses.post(ENDPOINT, json=payloads.make_analysis(input_type="url"), status=201)
    client.analyze(url="https://exemplo.com/noticia")
    assert json.loads(responses.calls[0].request.body) == {"input_type": "url", "url": "https://exemplo.com/noticia"}


@responses.activate
def test_nunca_envia_identificador_de_visitante_nem_telefone(client):
    responses.post(ENDPOINT, json=payloads.make_analysis(), status=201)
    client.analyze(text="a" * 60)
    headers = {name.lower() for name in responses.calls[0].request.headers}
    assert "x-visitor-id" not in headers
    assert not {"cookie", "authorization"} & headers


@responses.activate
def test_identifica_o_chatbot_e_pede_json(client):
    responses.post(ENDPOINT, json=payloads.make_analysis(), status=201)
    client.analyze(text="a" * 60)
    headers = responses.calls[0].request.headers
    assert headers["Accept"] == "application/json"
    assert headers["User-Agent"].startswith("apura-whatsapp/")


@pytest.mark.parametrize("kwargs", [{}, {"text": "a", "url": "https://x.co"}])
def test_exige_texto_ou_link_nunca_os_dois_nem_nenhum(client, kwargs):
    with pytest.raises(ValueError, match="texto OU link"):
        client.analyze(**kwargs)


@responses.activate
def test_devolve_o_corpo_da_api_quando_da_certo(client):
    body = payloads.make_analysis()
    responses.post(ENDPOINT, json=body, status=201)
    assert client.analyze(text="a" * 60) == body


@responses.activate
@pytest.mark.parametrize(
    ("status", "body", "scenario"),
    [
        (400, payloads.TEXT_TOO_SHORT, "text_insufficient"),
        (400, payloads.TEXT_TOO_LONG, "text_too_long"),
        (400, payloads.UNSUPPORTED_LANGUAGE, "unsupported_language"),
        (400, payloads.error("empty_input", "vazio", "cole", field="text"), "text_insufficient"),
        (400, payloads.error("unreadable_input", "ilegível", "confira", field="text"), "text_unreadable"),
        (501, payloads.URL_UNAVAILABLE, "url_unavailable"),
        (503, payloads.ANALYSIS_UNAVAILABLE, "api_unavailable"),
        (429, payloads.THROTTLED, "rate_limited"),
        (400, payloads.error("validation_error", "x", "y", field="text"), "text_insufficient"),
        (400, payloads.error("validation_error", "x", "y", field="url"), "invalid_url"),
        (400, payloads.error("validation_error", "x", "y", field="title"), "rejected"),
        # Códigos PROPOSTOS para as Etapas 2 e 3 (ainda não existem no back end).
        (400, payloads.error("invalid_url", "x", "y", field="url"), "invalid_url"),
        (422, payloads.error("page_unreachable", "x", "y", field="url"), "page_unreachable"),
        (502, payloads.error("evidence_unavailable", "x", "y"), "evidence_failure"),
        # Sem código conhecido, decide pelo status HTTP.
        (429, {"detail": "Request was throttled."}, "rate_limited"),
        (504, {"detail": "x"}, "timeout"),
        (404, {"detail": "x"}, "not_found"),
        (500, {"detail": "x"}, "api_unavailable"),
        (418, {"detail": "x"}, "rejected"),
    ],
)
def test_classifica_cada_erro_da_api_no_cenario_certo(client, status, body, scenario):
    responses.post(ENDPOINT, json=body, status=status)
    assert failure(client, text="a" * 60).scenario == scenario


@responses.activate
def test_guarda_os_detalhes_do_erro_para_montar_a_mensagem(client):
    responses.post(ENDPOINT, json=payloads.TEXT_TOO_SHORT, status=400)
    error = failure(client, text="curto")
    assert error.code == "text_too_short"
    assert error.details == {"length": 12, "min_chars": 50}
    assert error.field == "text"


@responses.activate
def test_le_o_tempo_de_espera_pedido_pela_api(client):
    responses.post(ENDPOINT, json=payloads.THROTTLED, status=429, headers={"Retry-After": "12"})
    assert failure(client, text="a" * 60).retry_after_seconds == 12


@responses.activate
def test_retry_after_invalido_e_ignorado(client):
    responses.post(
        ENDPOINT, json=payloads.THROTTLED, status=429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}
    )
    assert failure(client, text="a" * 60).retry_after_seconds is None


@responses.activate
def test_pagina_de_erro_em_html_do_proxy_vira_indisponibilidade(client):
    responses.post(ENDPOINT, body="<html><h1>502 Bad Gateway</h1></html>", status=502, content_type="text/html")
    assert failure(client, text="a" * 60).scenario == "api_unavailable"


@responses.activate
def test_estouro_do_prazo_vira_o_cenario_timeout(client):
    responses.post(ENDPOINT, body=requests.Timeout("lento"))
    assert failure(client, text="a" * 60).scenario == "timeout"


@responses.activate
def test_api_fora_do_ar_vira_indisponibilidade(client):
    responses.post(ENDPOINT, body=requests.ConnectionError("recusada"))
    assert failure(client, text="a" * 60).scenario == "api_unavailable"


@responses.activate
@pytest.mark.parametrize(
    "body",
    [
        "isto não é json",
        "[1, 2, 3]",
        json.dumps({**payloads.make_analysis(), "api_version": "v2"}),
        json.dumps({k: v for k, v in payloads.make_analysis().items() if k != "api_version"}),
    ],
)
def test_resposta_de_sucesso_que_nao_e_da_v1_vira_incompatibilidade(client, body):
    responses.post(ENDPOINT, body=body, status=201, content_type="application/json")
    assert failure(client, text="a" * 60).scenario == "incompatible_api"


def test_a_mensagem_da_excecao_nunca_carrega_texto_da_api():
    error = ApuraApiError("rejected", api_message="trecho do texto do usuário", api_action="x")
    assert str(error) == "rejected"
