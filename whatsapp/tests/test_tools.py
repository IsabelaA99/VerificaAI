"""Testes das ferramentas de teste manual (``tools/``): a API de mentirinha e o simulador de conversa.

Nada aqui abre porta de rede: a API de mentirinha é chamada pelo cliente de teste do Flask e o
``ApuraClient`` é ligado a ela com o ``responses``.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator

import pytest
import responses
from twilio.twiml.messaging_response import MessagingResponse

from config import Settings
from services import messages
from services.apura_client import ApuraClient
from services.errors import ApuraApiError, classify_failure
from services.reply_builder import (
    STATUS_ATTENTION,
    STATUS_HIGH,
    STATUS_INCONCLUSIVE,
    STATUS_LOW,
    parse_analysis,
)
from tests import payloads
from tests.conftest import FakeClient
from tools import fake_apura_api as fake
from tools import simulate
from tools.simulate import EXAMPLES, Screen, Simulator

LONG_TEXT = "Circula uma mensagem dizendo que a prefeitura vai trocar o horário de todas as linhas de ônibus."

# Para cada exemplo de ``simulate.EXAMPLES`` (na mesma ordem): status HTTP e o que se espera dele.
# Resultado de análise: o status do Apura. Erro: o cenário em que o chatbot o classifica.
EXPECTED_EXAMPLES: list[tuple[int, str]] = [
    (201, STATUS_HIGH),
    (201, STATUS_LOW),
    (201, STATUS_ATTENTION),
    (201, STATUS_INCONCLUSIVE),
    (201, STATUS_ATTENTION),
    (400, "text_insufficient"),
    (400, "unsupported_language"),
    (429, "rate_limited"),
    (503, "api_unavailable"),
    (201, STATUS_ATTENTION),
]


# --------------------------------------------------------------------------- API de mentirinha


def test_every_example_has_an_expectation() -> None:
    assert len(EXAMPLES) == len(EXPECTED_EXAMPLES)


@pytest.mark.parametrize(("example", "expected"), list(zip(EXAMPLES, EXPECTED_EXAMPLES, strict=False)))
def test_examples_provoke_the_situation_they_announce(example: tuple[str, str], expected: tuple[int, str]) -> None:
    _title, text = example
    status, body, headers = fake.pick_result(text)
    expected_status, expected_outcome = expected

    assert status == expected_status
    if status == 201:
        assert parse_analysis(body).status_code == expected_outcome
    else:
        assert (
            classify_failure(status, body, int(headers["Retry-After"]) if "Retry-After" in headers else None).scenario
            == expected_outcome
        )


def test_text_size_limits_follow_the_api_rules() -> None:
    assert fake.pick_result("a" * (fake.MIN_CHARS - 1))[0] == 400
    assert fake.pick_result("a" * fake.MIN_CHARS)[0] == 201
    assert fake.pick_result("a" * fake.MAX_CHARS)[0] == 201

    status, body, _headers = fake.pick_result("a" * (fake.MAX_CHARS + 1))
    assert status == 400
    assert classify_failure(status, body).scenario == "text_too_long"


def test_too_short_error_reports_the_real_length() -> None:
    status, body, _headers = fake.pick_result("curto")
    error = classify_failure(status, body)

    assert error.scenario == "text_insufficient"
    assert error.details == {"length": 5, "min_chars": fake.MIN_CHARS}


def test_throttle_asks_to_wait() -> None:
    status, _body, headers = fake.pick_result(EXAMPLES[7][1])

    assert status == 429
    assert headers == {"Retry-After": str(fake.THROTTLE_WAIT_SECONDS)}


def test_each_answer_gets_a_new_id_and_says_it_is_fake() -> None:
    first = fake.pick_result(LONG_TEXT)[1]
    second = fake.pick_result(LONG_TEXT)[1]

    assert first["id"] != second["id"]
    assert first["explanation"][0] == fake.FAKE_NOTE
    assert parse_analysis(first).explanation[0] == fake.FAKE_NOTE


def test_claim_summary_is_the_first_sentence_and_is_capped() -> None:
    assert fake._claim_summary("Primeira frase. Segunda frase.") == "Primeira frase."
    assert fake._claim_summary("  muito\n espaço   aqui  ") == "muito espaço aqui"

    capped = fake._claim_summary("palavra " * 100)
    assert len(capped) == 140
    assert capped.endswith("…")


def test_sources_example_carries_sources_in_the_proposed_format() -> None:
    analysis = parse_analysis(fake.pick_result(EXAMPLES[4][1])[1])

    assert [source.relation for source in analysis.sources] == ["compatible", "contextual"]
    assert all(source.url.startswith("https://") for source in analysis.sources)
    assert not any("fontes externas" in text for text in analysis.limitations)


def test_inconclusive_example_has_no_risk_index() -> None:
    analysis = parse_analysis(fake.pick_result(EXAMPLES[3][1])[1])

    assert analysis.status_code == STATUS_INCONCLUSIVE
    assert analysis.risk_index is None


class TestFakeApiRoutes:
    @pytest.fixture
    def api(self):
        return fake.create_fake_api(slow_seconds=0.25).test_client()

    def test_text_gets_an_analysis(self, api) -> None:
        reply = api.post("/api/v1/analyses/", json={"input_type": "text", "text": LONG_TEXT})

        assert reply.status_code == 201
        assert reply.get_json()["api_version"] == "v1"

    def test_link_gets_501_like_the_real_api_today(self, api) -> None:
        reply = api.post("/api/v1/analyses/", json={"input_type": "url", "url": "https://exemplo.com/a"})

        assert reply.status_code == 501
        assert classify_failure(501, reply.get_json()).scenario == "url_unavailable"

    @pytest.mark.parametrize("body", [None, "não é json", [1, 2], {"text": 42}])
    def test_garbage_is_treated_as_empty_text(self, api, body) -> None:
        reply = api.post(
            "/api/v1/analyses/",
            data=body if isinstance(body, str) else None,
            json=body if not isinstance(body, str) else None,
        )

        assert reply.status_code == 400

    def test_slow_word_waits_before_answering(self, api, monkeypatch: pytest.MonkeyPatch) -> None:
        slept: list[float] = []
        monkeypatch.setattr(fake.time, "sleep", slept.append)

        api.post("/api/v1/analyses/", json={"input_type": "text", "text": EXAMPLES[9][1]})
        api.post("/api/v1/analyses/", json={"input_type": "text", "text": LONG_TEXT})

        assert slept == [0.25]

    def test_default_delay_is_longer_than_the_chatbot_wait_and_shorter_than_the_api_deadline(self) -> None:
        settings = Settings()

        assert settings.sync_wait_seconds < fake.SLOW_SECONDS < settings.api_timeout_seconds

    def test_health(self, api) -> None:
        assert api.get("/api/v1/health/").get_json()["status"] == "ok"


class TestApuraClientAgainstTheFakeApi:
    """O cliente real do chatbot, conversando com a API de mentirinha (sem rede)."""

    @pytest.fixture
    def client(self) -> Iterator[ApuraClient]:
        api = fake.create_fake_api(slow_seconds=0).test_client()

        def callback(request):
            reply = api.post("/api/v1/analyses/", data=request.body, content_type="application/json")
            headers = {name: value for name, value in reply.headers.items() if name == "Retry-After"}
            return reply.status_code, headers, reply.get_data()

        with responses.RequestsMock() as mock:
            mock.add_callback(
                responses.POST,
                "http://api.test/api/v1/analyses/",
                callback=callback,
                content_type="application/json",
            )
            yield ApuraClient("http://api.test/api")

    def test_returns_an_analysis_the_chatbot_understands(self, client: ApuraClient) -> None:
        analysis = parse_analysis(client.analyze(text=EXAMPLES[0][1]))

        assert analysis.status_code == STATUS_HIGH

    def test_throttle_arrives_with_the_wait_time(self, client: ApuraClient) -> None:
        with pytest.raises(ApuraApiError) as caught:
            client.analyze(text=EXAMPLES[7][1])

        assert caught.value.scenario == "rate_limited"
        assert caught.value.retry_after_seconds == fake.THROTTLE_WAIT_SECONDS

    def test_link_is_refused_as_unavailable(self, client: ApuraClient) -> None:
        with pytest.raises(ApuraApiError) as caught:
            client.analyze(url="https://exemplo.com/noticia")

        assert caught.value.scenario == "url_unavailable"


# --------------------------------------------------------------------------- simulador


def feed(*lines: str) -> Callable[[], str | None]:
    pending = iter(lines)
    return lambda: next(pending, None)


@pytest.fixture
def settings() -> Settings:
    return Settings(validate_signature=False, sync_wait_seconds=2.0)


@pytest.fixture
def client() -> FakeClient:
    return FakeClient(payloads.make_analysis())


@pytest.fixture
def screen() -> Screen:
    return Screen(color=False)


@pytest.fixture
def simulator(settings: Settings, screen: Screen, client: FakeClient) -> Simulator:
    return Simulator(settings, screen, client=client)


class TestTwimlMessages:
    def test_reads_each_message_and_unescapes_entities(self) -> None:
        response = MessagingResponse()
        response.message("Primeira & <segunda>")
        response.message("Terceira")

        assert simulate.twiml_messages(str(response)) == ["Primeira & <segunda>", "Terceira"]

    def test_empty_response_has_no_messages(self) -> None:
        assert simulate.twiml_messages(str(MessagingResponse())) == []


class TestBold:
    def test_turns_whatsapp_bold_into_terminal_bold(self) -> None:
        assert simulate.bold("um *dois* três", enabled=True) == "um \033[1mdois\033[0m três"

    def test_leaves_text_alone_when_color_is_off(self) -> None:
        assert simulate.bold("um *dois* três", enabled=False) == "um *dois* três"

    def test_does_not_bold_across_lines(self) -> None:
        text = "a * b\nc * d"

        assert simulate.bold(text, enabled=True) == text


class TestSimulatorSend:
    def test_shows_the_reply_the_chatbot_would_send(
        self, simulator: Simulator, client: FakeClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        blocks = simulator.send(LONG_TEXT)

        assert blocks[0].startswith("*Status: Requer atenção*")
        assert client.calls == [{"text": LONG_TEXT, "url": None}]
        output = capsys.readouterr().out
        assert "── Apura" in output
        assert "Status: Requer atenção" in output

    def test_long_answers_are_shown_split(self, settings: Settings, screen: Screen, capsys) -> None:
        analysis = payloads.make_analysis(explanation=[f"Sinal {number}: " + "x" * 200 for number in range(12)])
        blocks = Simulator(settings, screen, client=FakeClient(analysis)).send(LONG_TEXT)

        assert len(blocks) > 1
        assert all(len(block) <= 1600 for block in blocks)
        assert f"[mensagem 1 de {len(blocks)}" in capsys.readouterr().out

    def test_image_is_refused_without_calling_the_api(self, simulator: Simulator, client: FakeClient) -> None:
        assert simulator.send("", num_media=1) == [messages.MEDIA_NOT_SUPPORTED]
        assert client.calls == []

    def test_bare_link_is_not_sent_to_the_api_while_links_are_off(
        self, simulator: Simulator, client: FakeClient
    ) -> None:
        simulator.send("https://exemplo.com/noticia")

        assert client.calls == []

    def test_slow_analysis_gets_the_notice_now_and_the_result_later(
        self, screen: Screen, client: FakeClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        slow = Simulator(Settings(validate_signature=False, sync_wait_seconds=0.05), screen, client=client)
        client.release.clear()

        assert slow.send(LONG_TEXT) == [messages.ACK]
        assert screen.pending_later == 1

        client.release.set()
        simulate.wait_for_later(screen, timeout=5)

        assert screen.pending_later == 0
        output = capsys.readouterr().out
        assert "enviado depois" in output
        assert "Status: Requer atenção" in output


class TestRunLoop:
    def test_example_command_sends_that_example(self, simulator: Simulator, screen: Screen, client: FakeClient) -> None:
        simulate.run(simulator, screen, read_line=feed("/3", "/sair"))

        assert client.calls == [{"text": EXAMPLES[2][1], "url": None}]

    def test_example_numbers_outside_the_list_are_unknown(
        self, simulator: Simulator, screen: Screen, client: FakeClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        simulate.run(simulator, screen, read_line=feed("/0", f"/{len(EXAMPLES) + 1}", "/sair"))

        assert client.calls == []
        assert capsys.readouterr().out.count("Comando desconhecido") == 2

    def test_plain_text_is_sent_as_typed(self, simulator: Simulator, screen: Screen, client: FakeClient) -> None:
        simulate.run(simulator, screen, read_line=feed(f"  {LONG_TEXT}  ", "", "/sair"))

        assert client.calls == [{"text": LONG_TEXT, "url": None}]

    def test_quit_stops_the_conversation(self, simulator: Simulator, screen: Screen, client: FakeClient) -> None:
        simulate.run(simulator, screen, read_line=feed("/sair", LONG_TEXT))

        assert client.calls == []

    def test_end_of_input_stops_the_conversation(
        self, simulator: Simulator, screen: Screen, client: FakeClient
    ) -> None:
        simulate.run(simulator, screen, read_line=feed(LONG_TEXT))

        assert len(client.calls) == 1

    def test_help_lists_every_example(
        self, simulator: Simulator, screen: Screen, capsys: pytest.CaptureFixture[str]
    ) -> None:
        simulate.run(simulator, screen, read_line=feed("/ajuda", "/sair"))

        output = capsys.readouterr().out
        for number, (title, _text) in enumerate(EXAMPLES, start=1):
            assert f"/{number}" in output
            assert title in output

    def test_media_and_link_commands(self, simulator: Simulator, screen: Screen, client: FakeClient) -> None:
        simulate.run(simulator, screen, read_line=feed("/midia", "/link", "/sair"))

        assert client.calls == []

    def test_logs_command_turns_logs_on(self, simulator: Simulator, screen: Screen) -> None:
        turned_on: list[bool] = []

        simulate.run(simulator, screen, read_line=feed("/logs", "/sair"), set_logs=turned_on.append)

        assert turned_on == [True]

    def test_file_command_sends_the_file_content(
        self, simulator: Simulator, screen: Screen, client: FakeClient, tmp_path
    ) -> None:
        path = tmp_path / "texto.txt"
        path.write_text(LONG_TEXT, encoding="utf-8")

        simulate.run(simulator, screen, read_line=feed(f"/arquivo {path}", "/sair"))

        assert client.calls == [{"text": LONG_TEXT, "url": None}]

    def test_file_command_explains_when_the_file_cannot_be_read(
        self, simulator: Simulator, screen: Screen, client: FakeClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        simulate.run(simulator, screen, read_line=feed("/arquivo /nao/existe.txt", "/sair"))

        assert client.calls == []
        assert "Não consegui ler esse arquivo" in capsys.readouterr().out


class TestReadFileText:
    def test_reads_utf8(self, tmp_path) -> None:
        path = tmp_path / "a.txt"
        path.write_text("ação ✓", encoding="utf-8")

        assert simulate.read_file_text(str(path)) == "ação ✓"

    def test_accepts_quotes_around_the_path(self, tmp_path) -> None:
        path = tmp_path / "a b.txt"
        path.write_text("oi", encoding="utf-8")

        assert simulate.read_file_text(f'"{path}"') == "oi"
        assert simulate.read_file_text(f"'{path}'") == "oi"

    def test_expands_the_home_folder(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        (tmp_path / "a.txt").write_text("oi", encoding="utf-8")
        monkeypatch.setenv("HOME", str(tmp_path))

        assert simulate.read_file_text("~/a.txt") == "oi"

    def test_refuses_missing_folder_big_and_non_text_files(self, tmp_path) -> None:
        big = tmp_path / "grande.txt"
        big.write_text("x" * (simulate.MAX_FILE_BYTES + 1), encoding="utf-8")
        binary = tmp_path / "binario.bin"
        binary.write_bytes(b"\xff\xfe\x00\x80")

        assert simulate.read_file_text(str(tmp_path / "nao-existe.txt")) is None
        assert simulate.read_file_text(str(tmp_path)) is None
        assert simulate.read_file_text(str(big)) is None
        assert simulate.read_file_text(str(binary)) is None


class TestBuildSettings:
    def test_never_checks_the_twilio_signature_and_leaves_the_environment_alone(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TWILIO_VALIDATE_SIGNATURE", "true")

        settings = simulate.build_settings(fake_api_url=None)

        assert settings.validate_signature is False
        assert os.environ["TWILIO_VALIDATE_SIGNATURE"] == "true"

    def test_fake_api_address_wins_over_the_environment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APURA_API_BASE_URL", "http://outro.exemplo/api")

        assert simulate.build_settings(fake_api_url="http://127.0.0.1:1234/api").apura_api_base_url == (
            "http://127.0.0.1:1234/api"
        )
        assert simulate.build_settings(fake_api_url=None).apura_api_base_url == "http://outro.exemplo/api"
