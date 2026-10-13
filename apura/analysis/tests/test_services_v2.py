"""
Testes dos serviços de raspagem, checagem de fatos e síntese LLM.
"""

from unittest.mock import MagicMock, patch
from django.test import SimpleTestCase

from analysis.services.factcheck import _extract_query_keywords, search_fact_checks
from analysis.services.llm import synthesize_explanation
from analysis.services.preprocessing import InputValidationError
from analysis.services.scraper import ScrapedArticle, scrape_url, validate_url_safety


class ScraperTests(SimpleTestCase):
    def test_ssrf_safety_blocks_private_ip(self):
        with self.assertRaises(InputValidationError) as ctx:
            validate_url_safety("http://127.0.0.1:8000/teste")
        self.assertEqual(ctx.exception.code, "forbidden_url")

    def test_ssrf_safety_blocks_localhost(self):
        with self.assertRaises(InputValidationError) as ctx:
            validate_url_safety("http://localhost:3000/teste")
        self.assertEqual(ctx.exception.code, "forbidden_url")

    def test_ssrf_safety_blocks_invalid_scheme(self):
        with self.assertRaises(InputValidationError) as ctx:
            validate_url_safety("file:///etc/passwd")
        self.assertEqual(ctx.exception.code, "invalid_url_scheme")

    @patch("analysis.services.scraper.requests.get")
    def test_scrape_url_extracts_article(self, mock_get):
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Título da Matéria Importante</title>
            <meta property="og:title" content="Título da Matéria Importante" />
            <meta property="og:description" content="Subtítulo da matéria com resumo detalhado." />
        </head>
        <body>
            <article>
                <p>O governo anunciou hoje medidas para o desenvolvimento econômico do país durante cerimônia oficial na capital.</p>
                <p>As novas diretrizes entram em vigor a partir do próximo mês e beneficiam pequenos e médios empreendedores.</p>
            </article>
        </body>
        </html>
        """
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = html
        mock_resp.headers = {"Content-Type": "text/html; charset=utf-8"}
        mock_resp.url = "https://noticias.globo.com/materia-123"
        mock_get.return_value = mock_resp

        article = scrape_url("https://noticias.globo.com/materia-123")
        self.assertIn("Título da Matéria", article.title)
        self.assertTrue(len(article.body) > 50)
        self.assertEqual(article.domain, "noticias.globo.com")


class FactCheckTests(SimpleTestCase):
    def test_extract_query_keywords(self):
        claim = "URGENTE: vacina experimental causa nova doença rara e grave"
        kw = _extract_query_keywords(claim)
        self.assertIn("vacina", kw)
        self.assertIn("experimental", kw)
        self.assertNotIn("e", kw.split())

    @patch("analysis.services.factcheck._search_google_fact_check")
    def test_search_fact_checks_found(self, mock_gfc):
        mock_gfc.return_value = [
            {
                "id": "gfc-1",
                "relation": "conflicting",
                "publisher": "Agência Lupa",
                "title": "É falso que vacina causa doença",
                "excerpt": "Alegação desmentida por especialistas.",
                "published_at": "2024-01-01",
                "url": "https://lupa.uol.com.br/artigo",
                "relation_reason": "Classificado como Falso.",
            }
        ]
        with patch.dict("django.conf.settings.FAKE_EYES", {"GOOGLE_FACT_CHECK_API_KEY": "dummy-key"}):
            res = search_fact_checks("vacina causa doenca")
            self.assertEqual(res["status"], "found")
            self.assertEqual(len(res["sources"]), 1)
            self.assertEqual(res["conflict_score"], 1.0)


@patch("analysis.services.llm._call_gemini", return_value=None)
@patch("analysis.services.llm._call_groq", return_value=None)
class LLMSynthesisTests(SimpleTestCase):
    def test_deterministic_synthesis_high_risk(self, mock_groq, mock_gemini):
        sources = [
            {
                "publisher": "Fato ou Fake",
                "relation": "conflicting",
                "title": "É #FAKE boato sobre substância milagrosa",
                "excerpt": "Médicos desmentem eficácia.",
            }
        ]
        exp = synthesize_explanation(
            title="Substancia cura doencas em 24h",
            body="Compartilhe antes que derrubem este artigo...",
            model_fake_prob=0.95,
            model_confidence=0.95,
            model_label="falsa",
            linguistic_indicators={"sensational_terms": ["cura", "milagrosa"]},
            sources=sources,
        )
        self.assertEqual(exp.verdict_tendency, "alto_risco_falsa")
        self.assertIn("alta probabilidade de ser falsa", exp.summary)
        self.assertTrue(any("BERTimbau" in p for p in exp.key_points))
        self.assertTrue(any("checagens" in p for p in exp.key_points))

    def test_deterministic_synthesis_low_risk(self, mock_groq, mock_gemini):
        exp = synthesize_explanation(
            title="Campanha de vacinação começa na próxima semana",
            body="Ministério da Saúde divulgou o calendário oficial para todos os estados.",
            model_fake_prob=0.08,
            model_confidence=0.92,
            model_label="verdadeira",
            linguistic_indicators={"sensational_terms": []},
            sources=[],
        )
        self.assertEqual(exp.verdict_tendency, "baixo_risco_verdadeira")
        self.assertIn("baixos sinais de falsidade", exp.summary)
