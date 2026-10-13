"""Testes de integração da API v1 com classificador simulado (RF29)."""

from unittest.mock import patch
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from analysis.models import Analysis
from analysis.services import classifier as classifier_service
from analysis.services.classifier import ClassificationResult
from analysis.services.scraper import ScrapedArticle

PT_TEXT = (
    "O Ministério da Saúde anunciou nesta segunda-feira uma nova campanha de vacinação "
    "contra a gripe, que será realizada em todos os estados do país até o fim do mês."
)


class FakeClassifier:
    def __init__(self, fake_p: float, chunks=None):
        self.fake_p = fake_p
        self.chunks = chunks or [fake_p]

    def info(self):
        return {"model_version": "fake", "model_sha256": "abc"}

    def classify(self, title, subtitle, body, temperature=1.0):
        return ClassificationResult(
            label="falsa" if self.fake_p >= 0.5 else "verdadeira",
            fake_probability=self.fake_p, confidence=max(self.fake_p, 1 - self.fake_p),
            chunk_fake_probabilities=self.chunks, chunk_disagreement=0.0,
            chunks_total=len(self.chunks), chunks_analyzed=len(self.chunks),
            tokens_total=40, tokens_analyzed=40, prefix_truncated=False,
            aggregation="mean_fake_probability", model_version="test-model",
            model_sha256="deadbeef", device="cpu", latency_ms=1.0,
        )


class AnalysisApiTests(TestCase):
    def setUp(self):
        self.groq_patch = patch("analysis.services.llm._call_groq", return_value=None)
        self.gemini_patch = patch("analysis.services.llm._call_gemini", return_value=None)
        self.fact_patch = patch(
            "analysis.services.pipeline.factcheck.search_fact_checks",
            return_value={"status": "none", "enabled": True, "sources": [], "conflict_score": None},
        )
        self.groq_patch.start()
        self.gemini_patch.start()
        self.fact_patch.start()
        self.client = APIClient()
        self.url = reverse("api-v1:analysis-create")

    def tearDown(self):
        self.groq_patch.stop()
        self.gemini_patch.stop()
        self.fact_patch.stop()
        classifier_service.set_classifier(None)

    def _post(self, payload):
        return self.client.post(self.url, payload, format="json")

    def test_high_risk_result(self):
        classifier_service.set_classifier(FakeClassifier(0.98))
        resp = self._post({"input_type": "text", "text": PT_TEXT})
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body["api_version"], "v1")
        self.assertEqual(body["status"]["code"], "alto_risco")
        self.assertIsNotNone(body["risk_index"])
        self.assertEqual(body["versions"]["model"], "test-model")
        self.assertTrue(
            "evidence_conflict" in body["risk"]["signals_missing"]
            or "evidence_conflict" in body["risk"]["signals_used"]
        )
        self.assertTrue(body["limitations"])

    def test_low_risk_result(self):
        classifier_service.set_classifier(FakeClassifier(0.02))
        body = self._post({"text": PT_TEXT}).json()
        self.assertEqual(body["status"]["code"], "poucos_sinais_de_risco")

    def test_inconclusive_has_priority_and_no_index(self):
        classifier_service.set_classifier(FakeClassifier(0.55))
        body = self._post({"text": PT_TEXT}).json()
        self.assertEqual(body["status"]["code"], "analise_inconclusiva")
        self.assertIsNone(body["risk_index"])
        self.assertEqual(body["abstention"][0]["code"], "low_confidence")

    def test_raw_text_is_not_persisted(self):
        classifier_service.set_classifier(FakeClassifier(0.9))
        resp = self._post({"text": PT_TEXT + " Contato: maria@exemplo.com"})
        analysis = Analysis.objects.get(pk=resp.json()["id"])
        stored = str(analysis.__dict__)
        self.assertNotIn("todos os estados do país até o fim do mês", stored)
        self.assertNotIn("maria@exemplo.com", stored)

    def test_get_detail(self):
        classifier_service.set_classifier(FakeClassifier(0.9))
        created = self._post({"text": PT_TEXT}).json()
        resp = self.client.get(reverse("api-v1:analysis-detail", args=[created["id"]]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], created["id"])

    def test_validation_error_structure(self):
        classifier_service.set_classifier(FakeClassifier(0.9))
        resp = self._post({"text": "curto demais"})
        self.assertEqual(resp.status_code, 400)
        err = resp.json()["error"]
        self.assertEqual(err["code"], "text_too_short")
        self.assertEqual(err["field"], "text")
        self.assertTrue(err["action"])
        self.assertEqual(Analysis.objects.count(), 0)

    def test_missing_text_field(self):
        resp = self._post({"input_type": "text"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["field"], "text")

    @patch("analysis.services.pipeline.scrape_url")
    def test_url_analysis_success(self, mock_scrape):
        mock_scrape.return_value = ScrapedArticle(
            url="https://noticias.exemplo.com/materia",
            domain="noticias.exemplo.com",
            title="Nova medida econômica anunciada hoje",
            subtitle="Governo detalha pacote para o setor produtivo",
            body=PT_TEXT,
        )
        classifier_service.set_classifier(FakeClassifier(0.9))
        resp = self._post({"input_type": "url", "url": "https://noticias.exemplo.com/materia"})
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["input_type"], "url")
        self.assertEqual(body["status"]["code"], "alto_risco")
        self.assertTrue(body["claim"]["summary"])

    def test_url_invalid_scheme(self):
        resp = self._post({"input_type": "url", "url": "ftp://servidor.com/arquivo"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["error"]["field"], "url")

    def test_model_failure_returns_controlled_503(self):
        class Broken(FakeClassifier):
            def classify(self, *a, **k):
                raise RuntimeError("boom")

        classifier_service.set_classifier(Broken(0.5))
        resp = self._post({"text": PT_TEXT})
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["error"]["code"], "analysis_unavailable")
        self.assertEqual(Analysis.objects.count(), 0)

    def test_not_found(self):
        resp = self.client.get("/api/v1/analyses/00000000-0000-0000-0000-000000000000/")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["error"]["code"], "analysis_not_found")

    def test_health(self):
        resp = self.client.get(reverse("api-v1:health"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["rules_version"], "rules-v1.0.0")
