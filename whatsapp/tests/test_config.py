import pytest

from config import ConfigError, Settings


def env(**values):
    return {"TWILIO_AUTH_TOKEN": "segredo", **values}


def test_padroes_servem_para_desenvolvimento():
    settings = Settings.from_env(env())
    assert settings.apura_api_base_url == "http://localhost:8000/api"
    assert settings.api_timeout_seconds == 30  # RNF01
    assert settings.sync_wait_seconds == 12
    assert settings.url_input_enabled is True  # a API abre a página (scraper do back end)
    assert settings.validate_signature is True
    assert settings.can_reply_later is False


def test_le_as_variaveis_e_tira_a_barra_final():
    settings = Settings.from_env(
        env(
            APURA_API_BASE_URL="https://api.exemplo.org/api/",
            WEB_BASE_URL="https://apura.exemplo.org/",
            TWILIO_ACCOUNT_SID="ACxxx",
            URL_INPUT_ENABLED="true",
            MAX_WORKERS="4",
        )
    )
    assert settings.apura_api_base_url == "https://api.exemplo.org/api"
    assert settings.web_base_url == "https://apura.exemplo.org"
    assert settings.url_input_enabled is True
    assert settings.max_workers == 4
    assert settings.can_reply_later is True


def test_sem_token_da_twilio_nao_inicia_com_validacao_ligada():
    with pytest.raises(ConfigError, match="TWILIO_AUTH_TOKEN"):
        Settings.from_env({})


def test_validacao_pode_ser_desligada_so_de_forma_explicita():
    settings = Settings.from_env({"TWILIO_VALIDATE_SIGNATURE": "false"})
    assert settings.validate_signature is False


@pytest.mark.parametrize("value", ["15", "20", "0.5", "0"])
def test_espera_sincrona_precisa_ficar_abaixo_dos_15_segundos_da_twilio(value):
    with pytest.raises(ConfigError, match="SYNC_WAIT_SECONDS"):
        Settings.from_env(env(SYNC_WAIT_SECONDS=value))


def test_espera_sincrona_de_14_segundos_e_aceita():
    assert Settings.from_env(env(SYNC_WAIT_SECONDS="14")).sync_wait_seconds == 14


@pytest.mark.parametrize(
    ("name", "value"),
    [("URL_INPUT_ENABLED", "talvez"), ("APURA_API_TIMEOUT_SECONDS", "muito"), ("MAX_WORKERS", "x")],
)
def test_valor_invalido_diz_qual_variavel_corrigir(name, value):
    with pytest.raises(ConfigError, match=name):
        Settings.from_env(env(**{name: value}))


@pytest.mark.parametrize("name", ["APURA_API_BASE_URL", "PUBLIC_WEBHOOK_URL", "WEB_BASE_URL"])
def test_enderecos_precisam_de_esquema(name):
    with pytest.raises(ConfigError, match=name):
        Settings.from_env(env(**{name: "exemplo.org"}))


def test_todos_os_problemas_aparecem_de_uma_vez():
    with pytest.raises(ConfigError) as info:
        Settings.from_env({"APURA_API_BASE_URL": "x", "SYNC_WAIT_SECONDS": "30"})
    message = str(info.value)
    assert "APURA_API_BASE_URL" in message
    assert "SYNC_WAIT_SECONDS" in message
    assert "TWILIO_AUTH_TOKEN" in message
