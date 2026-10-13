"""Envio pela API REST da Twilio, usando o SDK de verdade com a rede interceptada."""

import logging
from urllib.parse import parse_qs

import pytest
import responses
from twilio.rest import Client

from config import Settings
from services.twilio_io import TwilioSender, build_sender
from tests.conftest import BOT_NUMBER, USER_NUMBER

SID = "AC" + "0" * 32
MESSAGES_URL = f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json"


def sender(pauses):
    return TwilioSender(Client(SID, "token-de-teste"), pause_seconds=0.6, sleep=pauses.append)


@responses.activate
def test_envia_cada_bloco_pela_api_da_twilio_na_ordem_com_uma_pausa_curta():
    responses.post(MESSAGES_URL, json={"sid": "SM" + "1" * 32, "status": "queued"}, status=201)
    pauses: list[float] = []

    sender(pauses).send_all(to=USER_NUMBER, from_=BOT_NUMBER, bodies=["primeira", "segunda", "terceira"])

    bodies = []
    for call in responses.calls:
        form = parse_qs(call.request.body)
        assert form["To"] == [USER_NUMBER]
        assert form["From"] == [BOT_NUMBER]
        bodies.append(form["Body"][0])
    assert bodies == ["primeira", "segunda", "terceira"]
    assert pauses == [0.6, 0.6]  # entre as mensagens, nunca antes da primeira


@responses.activate
def test_usa_as_credenciais_da_conta():
    responses.post(MESSAGES_URL, json={"sid": "SM" + "1" * 32}, status=201)
    sender([]).send(to=USER_NUMBER, from_=BOT_NUMBER, body="oi")
    assert responses.calls[0].request.headers["Authorization"].startswith("Basic ")


@responses.activate
def test_falha_da_twilio_sobe_para_quem_chamou_e_o_log_nao_tem_telefone(caplog):
    responses.post(
        MESSAGES_URL, json={"code": 21211, "message": f"Invalid 'To' Phone Number: {USER_NUMBER}"}, status=400
    )
    with caplog.at_level(logging.DEBUG), pytest.raises(Exception, match=r"21211|Unable to create record"):
        sender([]).send(to=USER_NUMBER, from_=BOT_NUMBER, body="texto privado da pessoa")
    assert "envio_falhou error_class=TwilioRestException" in caplog.text
    assert USER_NUMBER not in caplog.text
    assert "texto privado" not in caplog.text


def test_sem_credenciais_o_envio_posterior_fica_desligado():
    assert build_sender(Settings(twilio_auth_token="x")) is None


def test_com_credenciais_cria_o_remetente():
    assert build_sender(Settings(twilio_account_sid=SID, twilio_auth_token="x")) is not None
