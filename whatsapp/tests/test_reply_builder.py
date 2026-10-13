import pytest

from services.errors import ApuraApiError
from services.reply_builder import (
    FOOTER,
    build_error_messages,
    build_result_messages,
    effective_status,
    format_datetime,
    format_decimal,
    parse_analysis,
)
from tests import payloads

MAX = 1600


def render(raw, **kwargs) -> str:
    """Resposta completa, com as mensagens unidas por linha em branco."""
    blocks = build_result_messages(parse_analysis(raw), **kwargs)
    assert all(0 < len(block) <= MAX for block in blocks)
    return "\n\n".join(blocks)


class TestStatusVemPrimeiro:
    """RF16: a interface apresenta primeiro um status em linguagem simples."""

    @pytest.mark.parametrize(
        ("factory", "label"),
        [
            (payloads.low, "Poucos sinais de risco"),
            (payloads.make_analysis, "Requer atenção"),
            (payloads.high, "Alto risco"),
            (payloads.inconclusive, "Análise inconclusiva"),
        ],
    )
    def test_primeira_linha_e_o_status(self, factory, label):
        first_line = render(factory()).splitlines()[0]
        assert first_line == f"*Status: {label}*"

    def test_a_primeira_mensagem_comeca_pelo_status_mesmo_quando_a_resposta_e_dividida(self):
        raw = payloads.make_analysis(limitations=[f"Limitação número {i}: " + "texto " * 40 for i in range(12)])
        blocks = build_result_messages(parse_analysis(raw))
        assert len(blocks) > 1
        assert blocks[0].startswith("*Status: Requer atenção*")


class TestIndiceDeRisco:
    def test_mostra_o_indice_com_uma_casa_e_diz_que_nao_e_probabilidade(self):
        text = render(payloads.make_analysis(risk_index=48.31))
        assert "Índice de risco: 48,3 de 100." in text
        assert "não a chance de a notícia ser falsa" in text

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (0, "0"),
            (25, "25"),
            (25.0, "25"),
            (25.04, "25"),
            (25.05, "25,1"),
            (60, "60"),
            (60.01, "60"),
            (100, "100"),
            (48.31, "48,3"),
            (0.25, "0,3"),
        ],
    )
    def test_formata_como_a_interface_web(self, value, expected):
        assert format_decimal(value) == expected


class TestAnaliseInconclusiva:
    """RF14 e RF16: inconclusiva tem prioridade e nunca vira baixo ou alto risco."""

    def test_nao_mostra_indice_nem_conclui_nada(self):
        text = render(payloads.inconclusive())
        assert "Índice de risco: não calculado" in text
        assert "não deve ser usada para dizer que a notícia é verdadeira nem que é falsa" in text
        assert "de 100" not in text
        for label in ("Poucos sinais de risco", "Requer atenção", "Alto risco"):
            assert label not in text

    def test_lista_o_motivo_da_abstencao_uma_so_vez(self):
        message = "O modelo não teve segurança estatística suficiente para indicar um nível de risco."
        text = render(payloads.inconclusive())
        assert "*Por que ficou inconclusiva*" in text
        assert text.count(message) == 1

    @pytest.mark.parametrize(
        "overrides",
        [
            {
                "abstention": [
                    {"code": "insufficient_evidence", "message": "Não foram encontradas evidências suficientes."}
                ]
            },
            {"risk_index": None},
        ],
    )
    def test_abstencao_ou_falta_de_indice_forcam_inconclusiva_mesmo_com_outro_status(self, overrides):
        raw = payloads.make_analysis(**overrides)  # status continua "requer_atencao"
        assert effective_status(parse_analysis(raw)) == "analise_inconclusiva"
        assert render(raw).startswith("*Status: Análise inconclusiva*")


class TestConteudo:
    def test_mostra_alegacao_explicacao_limitacoes_e_recomendacoes_da_api(self):
        raw = payloads.make_analysis()
        text = render(raw)
        assert "*Alegação analisada* (resumo automático)" in text
        assert "“Todas as linhas de ônibus deixarão de funcionar no próximo domingo.”" in text
        for line in raw["explanation"]:
            assert f"• {line}" in text
        assert "*Limitações*" in text
        for line in raw["limitations"]:
            assert f"• {line}" in text
        assert "*O que fazer agora*" in text
        for line in raw["recommendations"]:
            assert f"• {line}" in text

    def test_ordem_das_secoes_segue_o_rf16_ao_rf18(self):
        text = render(payloads.make_analysis())
        positions = [
            text.index("*Status:"),
            text.index("*Alegação analisada*"),
            text.index("*O que o Apura encontrou*"),
            text.index("*Limitações*"),
            text.index("*O que fazer agora*"),
            text.index(FOOTER),
        ]
        assert positions == sorted(positions)

    @pytest.mark.parametrize("factory", [payloads.low, payloads.make_analysis, payloads.high, payloads.inconclusive])
    def test_nunca_afirma_verificacao_humana(self, factory):
        text = render(factory())
        assert "Não houve verificação humana" in text
        assert "Análise feita por computador" in text

    def test_data_da_analise_no_horario_de_brasilia(self):
        assert "Data da análise: 08/10/2026 08:53" in render(payloads.make_analysis())  # 11:53 UTC

    def test_data_sem_fuso_e_tratada_como_utc(self):
        raw = payloads.make_analysis(created_at="2026-10-08T11:53:00")
        assert "08/10/2026 08:53" in render(raw)

    def test_link_da_pagina_completa_so_aparece_quando_configurado(self):
        assert "Detalhes completos" not in render(payloads.make_analysis())
        text = render(payloads.make_analysis(), web_base_url="https://apura.exemplo.org")
        assert f"Detalhes completos: https://apura.exemplo.org/resultado/{payloads.ANALYSIS_ID}" in text

    def test_aviso_extra_entra_nas_limitacoes_sem_duplicar(self):
        note = "Aviso extra."
        raw = payloads.make_analysis(limitations=[note])
        text = render(raw, extra_limitations=(note,))
        assert text.count(f"• {note}") == 1

    def test_sem_alegacao_a_secao_e_omitida(self):
        raw = payloads.make_analysis(claim={"summary": "", "confirmed_by_user": False})
        assert "*Alegação analisada*" not in render(raw)

    def test_sem_recomendacoes_na_api_nao_inventa_nenhuma(self):
        assert "*O que fazer agora*" not in render(payloads.make_analysis(recommendations=[]))


class TestFontes:
    """PROPOSTA: o formato das fontes ainda não existe na API (Etapa 3)."""

    def source(self, **fields):
        return {
            "relation": "compatible",
            "publisher": "Agência Exemplo",
            "title": "Prefeitura nega suspensão",
            "url": "https://exemplo.org/materia",
            **fields,
        }

    def test_lista_fonte_com_relacao_e_link(self):
        raw = payloads.make_analysis(evidence={"enabled": True, "sources": [self.source()]})
        text = render(raw)
        assert "*Fontes*" in text
        assert "• Agência Exemplo: Prefeitura nega suspensão (compatível com a alegação)" in text
        assert "https://exemplo.org/materia" in text

    def test_aceita_a_relacao_em_portugues(self):
        raw = payloads.make_analysis(evidence={"enabled": True, "sources": [self.source(relation="conflitante")]})
        assert "(conflitante com a alegação)" in render(raw)

    def test_fonte_sem_relacao_com_a_alegacao_nao_aparece(self):
        raw = payloads.make_analysis(evidence={"enabled": True, "sources": [self.source(relation="")]})
        assert "*Fontes*" not in render(raw)

    @pytest.mark.parametrize(
        "url", ["javascript:alert(1)", "data:text/html,x", "ftp://x.org", "//x.org", "exemplo.org/a"]
    )
    def test_link_que_nao_e_http_nao_e_enviado(self, url):
        raw = payloads.make_analysis(evidence={"enabled": True, "sources": [self.source(url=url)]})
        text = render(raw)
        assert url not in text
        assert "Agência Exemplo" in text

    def test_sem_fontes_nao_mostra_a_secao(self):
        assert "*Fontes*" not in render(payloads.make_analysis())

    @pytest.mark.parametrize(
        "evidence",
        [{"enabled": True, "sources": [], "failed": True}, {"enabled": True, "sources": [], "error": {"code": "x"}}],
    )
    def test_falha_na_consulta_de_fontes_vira_limitacao_visivel(self, evidence):
        text = render(payloads.make_analysis(evidence=evidence))
        assert "Não foi possível consultar as fontes." in text
        assert "é limitada" in text


class TestTamanho:
    def test_resposta_comum_cabe_em_uma_mensagem_ou_duas(self):
        blocks = build_result_messages(parse_analysis(payloads.make_analysis()))
        assert 1 <= len(blocks) <= 2

    def test_resposta_enorme_e_dividida_sem_passar_de_1600(self):
        raw = payloads.make_analysis(explanation=["Fator " + "x" * 300 for _ in range(20)])
        blocks = build_result_messages(parse_analysis(raw))
        assert len(blocks) > 1
        assert all(len(block) <= MAX for block in blocks)


class TestLeituraDaResposta:
    """RF29: resposta fora do formato esperado vira 'incompatible_api', nunca um resultado errado."""

    def broken(self, **overrides):
        return {**payloads.make_analysis(), **overrides}

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            [],
            "texto",
            {**payloads.make_analysis(), "api_version": "v2"},
            {**payloads.make_analysis(), "id": ""},
            {**payloads.make_analysis(), "id": 7},
            {**payloads.make_analysis(), "created_at": "ontem"},
            {**payloads.make_analysis(), "created_at": None},
            {**payloads.make_analysis(), "status": {"code": "talvez"}},
            {**payloads.make_analysis(), "status": "requer_atencao"},
            {**payloads.make_analysis(), "risk_index": 101},
            {**payloads.make_analysis(), "risk_index": -1},
            {**payloads.make_analysis(), "risk_index": "48"},
            {**payloads.make_analysis(), "risk_index": True},
        ],
    )
    def test_formato_inesperado_e_recusado(self, raw):
        with pytest.raises(ApuraApiError) as info:
            parse_analysis(raw)
        assert info.value.scenario == "incompatible_api"

    def test_campos_opcionais_ausentes_nao_quebram(self):
        minimal = {
            "id": "abc",
            "api_version": "v1",
            "created_at": "2026-10-08T11:53:00Z",
            "status": {"code": "poucos_sinais_de_risco"},
            "risk_index": 10,
        }
        text = render(minimal)
        assert text.startswith("*Status: Poucos sinais de risco*")
        assert "Não houve verificação humana" in text

    def test_itens_que_nao_sao_texto_sao_ignorados(self):
        raw = payloads.make_analysis(explanation=["Válido.", 3, None, "", "  "], limitations="não é lista")
        analysis = parse_analysis(raw)
        assert analysis.explanation == ("Válido.",)
        assert analysis.limitations == ()


class TestMensagensDeErro:
    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (
                ApuraApiError("text_insufficient", details={"length": 12, "min_chars": 50}),
                "Seu texto tem 12 caracteres.",
            ),
            (ApuraApiError("text_insufficient"), "pelo menos 50 caracteres"),
            (
                ApuraApiError("text_too_long", details={"length": 5320, "max_chars": 5000}),
                "Seu texto tem 5.320 caracteres e o limite é 5.000.",
            ),
            (ApuraApiError("unsupported_language"), "só analisa textos em português"),
            (ApuraApiError("url_unavailable"), "análise por link ainda não está disponível"),
            (ApuraApiError("api_unavailable"), "O problema não está no seu texto"),
            (ApuraApiError("timeout"), "limite é de 30 segundos"),
            (ApuraApiError("rate_limited", retry_after_seconds=12), "Aguarde cerca de 12 segundos"),
            (ApuraApiError("rate_limited", retry_after_seconds=1), "Aguarde cerca de 1 segundo e"),
            (ApuraApiError("rate_limited"), "Aguarde um instante"),
            (ApuraApiError("invalid_url"), "http:// ou https://"),
            (ApuraApiError("page_unreachable"), "colar aqui o texto da notícia"),
            (ApuraApiError("evidence_failure"), "consultar as fontes"),
            (ApuraApiError("incompatible_api"), "precisa ser atualizado"),
            (ApuraApiError("text_unreadable"), "corrompido"),
            (ApuraApiError("unknown"), "Tente de novo em instantes"),
            (
                ApuraApiError("rejected", api_message="Título longo demais.", api_action="Encurte."),
                "Título longo demais. Encurte.",
            ),
            (ApuraApiError("rejected"), "Confira o conteúdo"),
        ],
    )
    def test_cada_cenario_diz_o_problema_e_a_saida(self, error, expected):
        assert expected in "\n".join(build_error_messages(error))

    def test_erro_nunca_mostra_codigo_tecnico_nem_o_nome_antigo_do_produto(self):
        # A API ainda diz "Fake Eyes" no erro de idioma; o chatbot usa texto próprio, com o nome Apura.
        error = ApuraApiError(
            "unsupported_language",
            code="unsupported_language",
            api_message="O conteúdo não parece estar em português.",
            api_action="O Fake Eyes analisa apenas textos em português.",
        )
        text = "\n".join(build_error_messages(error))
        assert "Fake Eyes" not in text
        assert "unsupported_language" not in text
        assert "Apura" in text


def test_format_datetime_cai_para_utc_sem_banco_de_fusos(monkeypatch):
    from zoneinfo import ZoneInfoNotFoundError

    import services.reply_builder as module

    def missing(_name):
        raise ZoneInfoNotFoundError

    monkeypatch.setattr(module, "ZoneInfo", missing)
    analysis = parse_analysis(payloads.make_analysis())
    assert format_datetime(analysis.created_at) == "08/10/2026 11:53 (UTC)"
