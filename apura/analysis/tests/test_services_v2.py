"""
Testes dos serviços de raspagem, checagem de fatos e síntese LLM.
"""

from unittest.mock import MagicMock, patch
import requests
from django.test import SimpleTestCase

from analysis.services.factcheck import _claim_match_level, _extract_query_keywords, search_fact_checks
from analysis.services.llm import synthesize_explanation
from analysis.services.preprocessing import InputValidationError
from analysis.services.scraper import ScrapedArticle, scrape_url, validate_url_safety


class ScraperTests(SimpleTestCase):
    @staticmethod
    def dns_result(ip):
        return [(2, 1, 6, "", (ip, 443))]

    @staticmethod
    def html_response():
        response = MagicMock()
        response.status = 200
        response.headers = {"Content-Type": "text/html; charset=utf-8"}
        response.data = b"""
        <html><head><title>Titulo da Materia</title></head><body><article>
        <p>O governo anunciou hoje medidas para o desenvolvimento economico do pais durante uma cerimonia oficial.</p>
        <p>As novas diretrizes entram em vigor no proximo mes e beneficiam pequenos empreendedores.</p>
        </article></body></html>
        """
        return response

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

    @patch("analysis.services.scraper.socket.getaddrinfo")
    def test_ssrf_safety_rejects_mixed_public_and_private_dns(self, getaddrinfo):
        getaddrinfo.return_value = self.dns_result("8.8.8.8") + self.dns_result("127.0.0.1")
        with self.assertRaises(InputValidationError) as ctx:
            validate_url_safety("https://noticias.globo.com/materia-123")
        self.assertEqual(ctx.exception.code, "forbidden_url")

    @patch("analysis.services.scraper.socket.getaddrinfo")
    @patch("analysis.services.scraper.urllib3.HTTPSConnectionPool")
    def test_scrape_url_extracts_article(self, pool_class, getaddrinfo):
        getaddrinfo.return_value = self.dns_result("8.8.8.8")
        pool = pool_class.return_value.__enter__.return_value
        pool.urlopen.return_value = self.html_response()
        article = scrape_url("https://noticias.globo.com/materia-123")
        self.assertIn("Titulo da Materia", article.title)
        self.assertTrue(len(article.body) > 50)
        self.assertEqual(article.domain, "noticias.globo.com")
        pool_class.assert_called_once()
        self.assertEqual(pool_class.call_args.args, ("8.8.8.8", 443))
        self.assertEqual(pool_class.call_args.kwargs["server_hostname"], "noticias.globo.com")
        self.assertEqual(pool_class.call_args.kwargs["assert_hostname"], "noticias.globo.com")
        self.assertEqual(pool_class.call_args.kwargs["cert_reqs"], "CERT_REQUIRED")
        self.assertEqual(pool.urlopen.call_args.kwargs["headers"]["Host"], "noticias.globo.com")
        self.assertFalse(pool.urlopen.call_args.kwargs["redirect"])
        getaddrinfo.assert_called_once()

    @patch("analysis.services.scraper.socket.getaddrinfo")
    @patch("analysis.services.scraper.urllib3.HTTPConnectionPool")
    @patch("analysis.services.scraper.urllib3.HTTPSConnectionPool")
    def test_redirect_to_private_address_is_blocked_before_request(self, https_pool, http_pool, getaddrinfo):
        getaddrinfo.return_value = self.dns_result("8.8.8.8")
        first = MagicMock(status=302, headers={"Location": "http://127.0.0.1/admin"}, data=b"")
        https_pool.return_value.__enter__.return_value.urlopen.return_value = first

        with self.assertRaises(InputValidationError) as ctx:
            scrape_url("https://noticias.globo.com/materia-123")

        self.assertEqual(ctx.exception.code, "forbidden_url")
        http_pool.assert_not_called()
        getaddrinfo.assert_called_once()

    @patch("analysis.services.scraper.socket.getaddrinfo")
    @patch("analysis.services.scraper.urllib3.HTTPSConnectionPool")
    def test_dns_change_cannot_change_connected_address(self, pool_class, getaddrinfo):
        getaddrinfo.side_effect = [self.dns_result("8.8.8.8"), self.dns_result("127.0.0.1")]
        pool_class.return_value.__enter__.return_value.urlopen.return_value = self.html_response()

        scrape_url("https://noticias.globo.com/materia-123")

        pool_class.assert_called_once()
        self.assertEqual(pool_class.call_args.args[0], "8.8.8.8")
        getaddrinfo.assert_called_once()

    @patch("analysis.services.scraper.socket.getaddrinfo")
    @patch("analysis.services.scraper.urllib3.HTTPSConnectionPool")
    def test_public_redirect_is_checked_and_followed(self, pool_class, getaddrinfo):
        getaddrinfo.side_effect = [self.dns_result("8.8.8.8"), self.dns_result("1.1.1.1")]
        first = MagicMock(status=302, headers={"Location": "https://outra.example/materia"}, data=b"")
        pool_class.return_value.__enter__.return_value.urlopen.side_effect = [first, self.html_response()]

        article = scrape_url("https://noticias.globo.com/materia-123")

        self.assertEqual(article.url, "https://outra.example/materia")
        self.assertEqual(article.domain, "outra.example")
        self.assertEqual(getaddrinfo.call_count, 2)
        self.assertEqual([call.args[0] for call in pool_class.call_args_list], ["8.8.8.8", "1.1.1.1"])


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

    @patch("analysis.services.factcheck.requests.get")
    def test_http_errors_are_failures_not_empty_searches(self, request_get):
        request_get.return_value.status_code = 503
        with patch.dict("django.conf.settings.FAKE_EYES", {"GOOGLE_FACT_CHECK_API_KEY": "dummy-key"}):
            result = search_fact_checks("Vacina causa autismo")
        self.assertEqual(result["status"], "none")
        self.assertTrue(result["failed"])
        self.assertEqual(result["sources"], [])

    @patch("analysis.services.factcheck._search_fact_check_fallback", return_value=[])
    @patch("analysis.services.factcheck.requests.get")
    def test_network_and_invalid_json_are_reported_as_failures(self, request_get, fallback):
        with patch.dict("django.conf.settings.FAKE_EYES", {"GOOGLE_FACT_CHECK_API_KEY": "dummy-key"}):
            request_get.side_effect = requests.ConnectionError("offline")
            self.assertTrue(search_fact_checks("Vacina causa autismo")["failed"])
            request_get.side_effect = None
            request_get.return_value.status_code = 200
            request_get.return_value.json.side_effect = ValueError("invalid JSON")
            self.assertTrue(search_fact_checks("Vacina causa autismo")["failed"])
        self.assertEqual(fallback.call_count, 2)

    @patch("analysis.services.factcheck._search_wikipedia", return_value=[])
    @patch("analysis.services.factcheck._search_boatos", return_value=[])
    @patch("analysis.services.factcheck._search_comprova", return_value=[])
    @patch("analysis.services.factcheck._search_google_fact_check", return_value=[])
    def test_completed_search_without_results_is_not_a_failure(self, mock_gfc, comprova, boatos, wiki):
        with patch.dict("django.conf.settings.FAKE_EYES", {"GOOGLE_FACT_CHECK_API_KEY": "dummy-key"}):
            result = search_fact_checks("Vacina causa autismo")
        self.assertEqual(result["status"], "none")
        self.assertFalse(result["failed"])
        mock_gfc.assert_called_once()
        comprova.assert_called_once()
        boatos.assert_called_once()
        wiki.assert_called_once()

    @patch("analysis.services.factcheck._search_wikipedia", return_value=[])
    @patch("analysis.services.factcheck._search_boatos", return_value=None)
    @patch("analysis.services.factcheck._search_comprova")
    def test_partial_fallback_keeps_sources_and_reports_failure(self, comprova, boatos, wiki):
        comprova.return_value = [{
            "url": "https://example.org/checagem", "title": "É falso que vacina causa autismo",
            "relation": "conflicting", "publisher": "Projeto Comprova",
        }]
        with patch.dict("django.conf.settings.FAKE_EYES", {"GOOGLE_FACT_CHECK_API_KEY": ""}):
            result = search_fact_checks("Vacina causa autismo")
        self.assertEqual(result["status"], "found")
        self.assertTrue(result["failed"])
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(result["conflict_score"], 1.0)

    def test_claim_match_requires_same_terms_order_polarity_and_numbers(self):
        self.assertEqual(_claim_match_level("Vacina causa autismo", "Vacina causa autismo"), "same")
        self.assertEqual(_claim_match_level("Vacina causa autismo", "Vacina não causa autismo"), "related")
        self.assertEqual(_claim_match_level("Não há provas da vacina", "Há provas da não vacina"), "related")
        self.assertEqual(_claim_match_level("Governo acusa empresa", "Empresa acusa governo"), "related")
        self.assertEqual(_claim_match_level("100 escolas fecharam", "200 escolas fecharam"), "related")
        self.assertEqual(_claim_match_level("Vacina causa autismo", "Vacina causa gripe"), "related")
        self.assertEqual(_claim_match_level("Vacina causa autismo", "Vacina causa autismo em animais"), "related")
        self.assertEqual(_claim_match_level("Escolas fecham hoje", "Escolas fecham amanhã"), "related")
        self.assertEqual(_claim_match_level("Vacina e remédio curam doença", "Vacina ou remédio curam doença"), "related")
        self.assertEqual(_claim_match_level("Vacina causa autismo", "Terremoto atingiu a cidade"), "unrelated")

    @patch("analysis.services.factcheck.requests.get")
    def test_google_checked_claim_takes_precedence_over_review_title(self, request_get):
        response = request_get.return_value
        response.status_code = 200
        response.json.return_value = {"claims": [{
            "text": "Vacina causa gripe",
            "claimReview": [{"title": "É #FAKE que vacina causa autismo", "textualRating": "Falso"}],
        }]}
        with patch.dict("django.conf.settings.FAKE_EYES", {"GOOGLE_FACT_CHECK_API_KEY": "dummy-key"}), \
             patch("analysis.services.factcheck._search_fact_check_fallback", return_value=[]):
            result = search_fact_checks("Vacina causa autismo")
        self.assertEqual(result["sources"][0]["relation"], "contextual")
        self.assertIsNone(result["conflict_score"])

    @patch("analysis.services.factcheck._search_fact_check_fallback", return_value=[])
    @patch("analysis.services.factcheck._search_google_fact_check")
    def test_google_result_about_other_claim_cannot_affect_risk(self, mock_gfc, fallback):
        mock_gfc.return_value = [{
            "id": "gfc-1", "_checked_claim": "Vacina causa gripe",
            "relation": "conflicting", "publisher": "Agência de checagem",
            "title": "É falso que vacina causa gripe", "relation_reason": "Falso.",
        }]
        with patch.dict("django.conf.settings.FAKE_EYES", {"GOOGLE_FACT_CHECK_API_KEY": "dummy-key"}):
            result = search_fact_checks("Vacina causa autismo")
        self.assertEqual(result["sources"][0]["relation"], "contextual")
        self.assertIsNone(result["conflict_score"])
        self.assertNotIn("_checked_claim", result["sources"][0])
        fallback.assert_not_called()

    @patch("analysis.services.factcheck._search_fact_check_fallback", return_value=[])
    @patch("analysis.services.factcheck._search_google_fact_check")
    def test_unrelated_google_result_is_discarded_and_fallback_runs(self, mock_gfc, fallback):
        mock_gfc.return_value = [{
            "id": "gfc-1", "_checked_claim": "Terremoto atingiu a cidade",
            "relation": "conflicting", "publisher": "Agência de checagem",
            "title": "É falso que houve terremoto", "relation_reason": "Falso.",
        }]
        with patch.dict("django.conf.settings.FAKE_EYES", {"GOOGLE_FACT_CHECK_API_KEY": "dummy-key"}):
            result = search_fact_checks("Vacina causa autismo")
        self.assertEqual(result["status"], "none")
        self.assertIsNone(result["conflict_score"])
        fallback.assert_called_once()

    @patch("analysis.services.factcheck._search_fact_check_fallback")
    def test_fallback_verdict_needs_same_claim_and_wikipedia_is_context(self, fallback):
        fallback.return_value = [
            {"id": "src-1", "relation": "conflicting", "publisher": "Projeto Comprova",
             "title": "É falso que vacina causa autismo", "relation_reason": "Falso."},
            {"id": "src-2", "relation": "conflicting", "publisher": "Boatos.org",
             "title": "É falso que vacina causa gripe", "relation_reason": "Falso."},
            {"id": "src-3", "relation": "conflicting", "publisher": "Wikipédia (Consenso Enciclopédico)",
             "title": "Vacina causa autismo", "relation_reason": "Teoria da conspiração."},
        ]
        with patch.dict("django.conf.settings.FAKE_EYES", {"GOOGLE_FACT_CHECK_API_KEY": ""}):
            result = search_fact_checks("Vacina causa autismo")
        self.assertEqual([source["relation"] for source in result["sources"]],
                         ["conflicting", "contextual", "contextual"])
        self.assertEqual(result["conflict_score"], 1.0)


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
