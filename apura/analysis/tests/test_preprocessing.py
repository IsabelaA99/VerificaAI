"""Testes de validação, idioma e privacidade (RF01, RF04, RF05)."""

from django.test import SimpleTestCase

from analysis.services.preprocessing import (
    InputValidationError,
    NewsInput,
    build_news_input,
    detect_portuguese,
    is_substantive_claim,
    mask_pii,
    normalize_text,
    summarize_claim,
)

PT_TEXT = (
    "O Ministério da Saúde anunciou nesta segunda-feira uma nova campanha de vacinação "
    "contra a gripe, que será realizada em todos os estados do país até o fim do mês."
)


class ValidationTests(SimpleTestCase):
    def test_url_alone_is_not_news_text(self):
        for text in (
            "https://noticias.uol.com.br/colunas/thais-bilenky/2026/10/14/ia-da-meta-bandeira-lula-e-flavio-bolsonaro.htm",
            "  HTTPS://exemplo.com/noticia\n",
            "www.exemplo.com/noticia",
        ):
            with self.subTest(text=text), self.assertRaises(InputValidationError) as ctx:
                build_news_input(text, title="Título informado")
            self.assertEqual(ctx.exception.code, "url_in_text")
            self.assertEqual(ctx.exception.field, "text")

    def test_news_text_can_include_a_source_url(self):
        text = PT_TEXT + " Fonte: https://exemplo.com/noticia"
        self.assertEqual(build_news_input(text).body, text)

    def test_valid_text(self):
        news = build_news_input(PT_TEXT)
        self.assertEqual(news.body, PT_TEXT)

    def test_too_short(self):
        with self.assertRaises(InputValidationError) as ctx:
            build_news_input("Texto curto demais.")
        self.assertEqual(ctx.exception.code, "text_too_short")

    def test_too_long_is_rejected_not_truncated(self):
        with self.assertRaises(InputValidationError) as ctx:
            build_news_input(PT_TEXT * 150)
        self.assertEqual(ctx.exception.code, "text_too_long")

    def test_empty(self):
        with self.assertRaises(InputValidationError) as ctx:
            build_news_input("   \n\t ")
        self.assertEqual(ctx.exception.code, "empty_input")

    def test_unreadable(self):
        with self.assertRaises(InputValidationError) as ctx:
            build_news_input("12345 67890 !!!! ### $$$ %%% 12345 67890 !!!! ### $$$ %%% 999 888 777")
        self.assertEqual(ctx.exception.code, "unreadable_input")

    def test_english_rejected(self):
        text = ("The government announced on Monday that the new vaccination campaign "
                "will be held in all states of the country until the end of the month.")
        with self.assertRaises(InputValidationError) as ctx:
            build_news_input(text)
        self.assertEqual(ctx.exception.code, "unsupported_language")

    def test_spanish_rejected(self):
        text = ("El gobierno anunció el lunes que la nueva campaña de vacunación se realizará "
                "en todos los estados del país hasta el final del mes, según las autoridades.")
        self.assertFalse(detect_portuguese(text)[0])

    def test_title_inferred_from_first_line(self):
        news = build_news_input("Governo anuncia campanha de vacinação\n" + PT_TEXT)
        self.assertTrue(news.title_inferred)
        self.assertEqual(news.title, "Governo anuncia campanha de vacinação")

    def test_explicit_title_kept(self):
        news = build_news_input(PT_TEXT, title="Título informado")
        self.assertFalse(news.title_inferred)
        self.assertEqual(news.title, "Título informado")


class NormalizationTests(SimpleTestCase):
    def test_nfc_and_spaces(self):
        decomposed = "Noti\u0301cia   com\u200b  espaços\r\n\r\n\r\n\r\nfim"
        self.assertEqual(normalize_text(decomposed), "Notícia com espaços\n\nfim")


class PrivacyTests(SimpleTestCase):
    def test_masks_pii(self):
        masked = mask_pii("Contato: joao@exemplo.com, CPF 123.456.789-09, tel (11) 98765-4321.")
        self.assertNotIn("joao@exemplo.com", masked)
        self.assertNotIn("123.456.789-09", masked)
        self.assertNotIn("98765-4321", masked)

    def test_keeps_years_and_public_names(self):
        text = "Lula e Bolsonaro disputaram as eleições de 2022 e 2018."
        self.assertEqual(mask_pii(text), text)

    def test_summary_is_masked_and_short(self):
        news = build_news_input("Ligue para (11) 98765-4321 e ganhe prêmio\n" + PT_TEXT)
        summary = summarize_claim(news)
        self.assertNotIn("98765-4321", summary)
        self.assertLessEqual(len(summary), 140)


class ClaimSummaryTests(SimpleTestCase):
    """A alegação é o que vai para a busca de checagens: bordão não é alegação."""

    CHAIN = (
        "URGENTE!!! Vacina contra covid causa autismo em crianças, comprovam cientistas. "
        "O governo esconde a verdade e a mídia não quer que você saiba. Compartilhe antes que apaguem!"
    )

    def test_bordao_no_inicio_e_pulado(self):
        self.assertEqual(
            summarize_claim(build_news_input(self.CHAIN)),
            "Vacina contra covid causa autismo em crianças, comprovam cientistas.",
        )

    def test_titulo_que_e_so_bordao_cede_lugar_a_frase_com_conteudo(self):
        news = build_news_input("ATENÇÃO URGENTE!!!\n" + self.CHAIN)
        self.assertTrue(news.title_inferred)
        self.assertFalse(is_substantive_claim(news.title))
        self.assertTrue(summarize_claim(news).startswith("Vacina contra covid"))

    def test_titulo_com_conteudo_continua_sendo_a_alegacao(self):
        news = build_news_input("Ministério anuncia vacinação contra gripe\n" + PT_TEXT)
        self.assertEqual(summarize_claim(news), "Ministério anuncia vacinação contra gripe")

    def test_sem_nenhuma_frase_com_conteudo_mantem_o_comportamento_antigo(self):
        news = NewsInput(title="", subtitle="", body="URGENTE!!! Compartilhe!", title_inferred=False)
        self.assertEqual(summarize_claim(news), "URGENTE!!!")
