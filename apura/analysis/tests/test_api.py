"""Testes de integração da API v1 com classificador simulado (RF29)."""

import importlib
import json
import threading
import time
import uuid
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from analysis.models import Analysis
from analysis.services import classifier as classifier_service
from analysis.services import llm as llm_service
from analysis.services import risk as risk_service
from analysis.services.classifier import ClassificationResult
from analysis.services.llm import LLMExplanation
from analysis.services.scraper import ScrapedArticle
from analysis.services.timing import Deadline

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
        # O throttle usa cache, que não participa do rollback do banco de testes.
        cache.clear()
        self.addCleanup(cache.clear)
        self.groq_patch = patch("analysis.services.llm._call_groq", return_value=None)
        self.gemini_patch = patch("analysis.services.llm._call_gemini", return_value=None)
        self.openai_patch = patch("analysis.services.llm._call_openai", return_value=None)
        self.fact_patch = patch(
            "analysis.services.pipeline.factcheck.search_fact_checks",
            return_value={"status": "none", "enabled": True, "sources": [], "conflict_score": None},
        )
        self.groq_patch.start()
        self.gemini_patch.start()
        self.openai_patch.start()
        self.fact_patch.start()
        self.client = APIClient()
        self.url = reverse("api-v1:analysis-create")

    def tearDown(self):
        self.groq_patch.stop()
        self.gemini_patch.stop()
        self.openai_patch.stop()
        self.fact_patch.stop()
        classifier_service.set_classifier(None)

    def _post(self, payload):
        return self.client.post(self.url, payload, format="json")

    def test_url_in_text_rejected_before_model_search_or_save(self):
        url = "https://noticias.uol.com.br/colunas/thais-bilenky/2026/10/14/ia-da-meta-bandeira-lula-e-flavio-bolsonaro.htm"
        with patch("analysis.services.pipeline.get_classifier") as model, \
             patch("analysis.services.pipeline.factcheck.search_fact_checks") as search:
            response = self._post({"input_type": "text", "text": url})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "url_in_text")
        self.assertEqual(response.json()["error"]["field"], "text")
        model.assert_not_called()
        search.assert_not_called()
        self.assertFalse(Analysis.objects.exists())

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

    def test_contextual_source_is_not_sent_as_checked_evidence_to_llm(self):
        classifier_service.set_classifier(FakeClassifier(0.9))
        sources = [
            {"id": "context-1", "relation": "contextual", "publisher": "Agência", "title": "Tema relacionado"},
            {"id": "checked-1", "relation": "conflicting", "publisher": "Agência", "title": "Mesma alegação"},
        ]
        fact_result = {"status": "found", "enabled": True, "sources": sources, "conflict_score": 1.0}
        with patch("analysis.services.pipeline.factcheck.search_fact_checks", return_value=fact_result), \
             patch("analysis.services.pipeline.llm.synthesize_explanation",
                   wraps=llm_service.synthesize_explanation) as synthesize:
            response = self._post({"text": PT_TEXT})
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(synthesize.call_args.kwargs["sources"], [sources[1]])

    def test_synthesis_consensus_does_not_supply_external_evidence(self):
        classifier_service.set_classifier(FakeClassifier(0.25))
        contextual = {"id": "src-1", "relation": "contextual", "title": "Contexto sobre o tema"}
        for failed in (False, True):
            for sources in ([], [contextual]):
                for consensus in ("conforme_consenso", "diverge_consenso"):
                    with self.subTest(failed=failed, sources=sources, consensus=consensus):
                        explanation = LLMExplanation(
                            summary="Síntese de teste", key_points=[], provider="teste",
                            verdict_tendency="inconclusiva",
                            semantic_comparison={"consensus_status": consensus},
                        )
                        with patch("analysis.services.pipeline.factcheck.search_fact_checks", return_value={
                            "status": "found" if sources else "none", "sources": sources,
                            "conflict_score": None, "failed": failed,
                        }), patch("analysis.services.pipeline.llm.synthesize_explanation", return_value=explanation):
                            response = self._post({"text": PT_TEXT})
                        self.assertEqual(response.status_code, 201, response.content)
                        body = response.json()
                        self.assertIn("evidence_conflict", body["risk"]["signals_missing"])
                        self.assertNotIn("evidence_conflict", body["risk"]["signals_used"])
                        # Sem sinal externo: 100 * (0.6 * 0.25 + 0.15 * 0) / 0.75.
                        self.assertEqual(body["risk_index"], 20.0)
                        self.assertEqual(body["evidence"]["sources"], sources)
                        stored = Analysis.objects.get(pk=body["id"])
                        self.assertEqual(stored.technical["risk"], body["risk"])

    def test_required_evidence_cannot_be_replaced_by_synthesis_or_context(self):
        classifier_service.set_classifier(FakeClassifier(0.25))
        strict_rules = replace(risk_service.load_rules(), require_evidence=True)
        cases = (
            {"status": "none", "sources": [], "conflict_score": None, "failed": False},
            {"status": "none", "sources": [], "conflict_score": None, "failed": True},
            # Um score isolado não comprova que existe uma fonte verificada.
            {"status": "found", "sources": [{"relation": "contextual"}], "conflict_score": 1.0},
        )
        for fact_result in cases:
            for consensus in ("conforme_consenso", "diverge_consenso"):
                with self.subTest(fact_result=fact_result, consensus=consensus):
                    explanation = LLMExplanation(
                        summary="Síntese de teste", key_points=[], provider="teste",
                        verdict_tendency="inconclusiva",
                        semantic_comparison={"consensus_status": consensus},
                    )
                    with patch("analysis.services.pipeline.risk.load_rules", return_value=strict_rules), \
                         patch("analysis.services.pipeline.factcheck.search_fact_checks", return_value=fact_result), \
                         patch("analysis.services.pipeline.llm.synthesize_explanation", return_value=explanation):
                        response = self._post({"text": PT_TEXT})
                    self.assertEqual(response.status_code, 201, response.content)
                    body = response.json()
                    self.assertEqual(body["status"]["code"], "analise_inconclusiva")
                    self.assertIsNone(body["risk_index"])
                    self.assertIn("insufficient_evidence", [item["code"] for item in body["abstention"]])
                    self.assertNotIn("evidence_conflict", body["risk"]["signals_used"])

    def test_verified_sources_keep_their_signal_even_with_partial_lookup(self):
        classifier_service.set_classifier(FakeClassifier(0.9))
        strict_rules = replace(risk_service.load_rules(), require_evidence=True)
        for relation, score, consensus, expected_index in (
            ("compatible", 0.0, "diverge_consenso", 54.0),
            ("conflicting", 1.0, "conforme_consenso", 79.0),
        ):
            for failed in (False, True):
                with self.subTest(relation=relation, failed=failed):
                    source = {"id": "src-1", "relation": relation, "title": "Checagem da mesma alegação"}
                    explanation = LLMExplanation(
                        summary="Síntese de teste", key_points=[], provider="teste",
                        verdict_tendency="inconclusiva",
                        semantic_comparison={"consensus_status": consensus},
                    )
                    with patch("analysis.services.pipeline.risk.load_rules", return_value=strict_rules), \
                         patch("analysis.services.pipeline.factcheck.search_fact_checks", return_value={
                             "status": "found", "sources": [source], "conflict_score": score, "failed": failed,
                         }), patch("analysis.services.pipeline.llm.synthesize_explanation", return_value=explanation):
                        response = self._post({"text": PT_TEXT})
                    self.assertEqual(response.status_code, 201, response.content)
                    body = response.json()
                    self.assertEqual(body["risk"]["signals_used"]["evidence_conflict"], score)
                    self.assertEqual(body["risk_index"], expected_index)
                    self.assertFalse(body["abstention"])
                    self.assertEqual(body["evidence"]["sources"], [source])
                    self.assertEqual(body["evidence"]["failed"], failed)

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

    def test_derived_personal_data_is_masked_in_storage_and_api(self):
        classifier_service.set_classifier(FakeClassifier(0.9))
        email = "maria@exemplo.com"
        cpf = "123.456.789-09"
        phone = "(11) 98765-4321"
        source = {
            "id": "src-1", "relation": "contextual", "publisher": "Agência",
            "title": f"Checagem de {email}", "excerpt": f"Contato: {phone}",
            "url": "https://exemplo.org/checagem?email=maria%40exemplo.com",
            "relation_reason": f"Cita {cpf}",
        }
        explanation = LLMExplanation(
            summary=f"O texto cita {email}", key_points=[f"Documento {cpf}"], provider="teste",
            verdict_tendency="inconclusiva",
            semantic_comparison={"claim_analyzed": email, "consensus_summary": f"Contato {phone}"},
            lexical_analysis={"note": email}, uncertainty_warning=f"Verifique {email}",
        )
        with patch("analysis.services.pipeline.factcheck.search_fact_checks", return_value={
            "status": "found", "sources": [source], "conflict_score": None,
        }) as search, patch("analysis.services.pipeline.llm.synthesize_explanation", return_value=explanation):
            response = self._post({"text": PT_TEXT + f" Contato {phone}", "title": f"Notícia sobre {email}"})

        self.assertEqual(response.status_code, 201, response.content)
        self.assertNotIn(email, search.call_args.args[0])
        analysis = Analysis.objects.get(pk=response.json()["id"])
        stored = json.dumps(analysis.technical, ensure_ascii=False)
        self.assertNotIn(email, stored)
        self.assertNotIn(cpf, stored)
        self.assertNotIn(phone, stored)
        self.assertEqual(analysis.technical["evidence"]["sources"][0]["url"], "")
        for body in (response.json(), self.client.get(reverse("api-v1:analysis-detail", args=[analysis.id])).json()):
            serialized = json.dumps(body, ensure_ascii=False)
            self.assertNotIn(email, serialized)
            self.assertNotIn(cpf, serialized)
            self.assertNotIn(phone, serialized)

    def test_legacy_result_is_masked_on_read_and_by_migration(self):
        classifier_service.set_classifier(FakeClassifier(0.9))
        analysis_id = self._post({"text": PT_TEXT}).json()["id"]
        analysis = Analysis.objects.get(pk=analysis_id)
        analysis.claim_summary = "Contato maria@exemplo.com"
        analysis.technical["llm_analysis"]["summary"] = "Contato maria@exemplo.com"
        analysis.technical["evidence"]["sources"] = [{
            "url": "https://exemplo.org/?email=maria%40exemplo.com", "title": "Contato maria@exemplo.com",
        }]
        analysis.save(update_fields=["claim_summary", "technical"])

        detail_url = reverse("api-v1:analysis-detail", args=[analysis_id])
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("maria@exemplo.com", json.dumps(response.json()))
        self.assertEqual(response.json()["evidence"]["sources"][0]["url"], "")

        migration = importlib.import_module("analysis.migrations.0002_mask_legacy_analysis_data")
        migration.mask_existing_analyses(apps, SimpleNamespace(connection=connection))
        analysis.refresh_from_db()
        self.assertNotIn("maria@exemplo.com", analysis.claim_summary)
        self.assertNotIn("maria@exemplo.com", json.dumps(analysis.technical))
        self.assertEqual(analysis.technical["evidence"]["sources"][0]["url"], "")

    def test_get_detail(self):
        classifier_service.set_classifier(FakeClassifier(0.9))
        created = self._post({"text": PT_TEXT}).json()
        resp = self.client.get(reverse("api-v1:analysis-detail", args=[created["id"]]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], created["id"])

    def test_numeric_uuid_and_model_metadata_survive_post_and_get(self):
        analysis_id = uuid.UUID("00000000-0000-4000-8000-5252043214c0")
        model_hash = "ab5252043214cd" + "a" * 50
        model_version = "model-5252043214"

        class NumericMetadataClassifier(FakeClassifier):
            def classify(self, *args, **kwargs):
                result = super().classify(*args, **kwargs)
                result.model_sha256 = model_hash
                result.model_version = model_version
                return result

        classifier_service.set_classifier(NumericMetadataClassifier(0.9))
        with patch.object(Analysis._meta.get_field("id"), "get_default", return_value=analysis_id):
            response = self._post({"text": PT_TEXT})
        self.assertEqual(response.status_code, 201, response.content)
        created = response.json()
        self.assertEqual(created["id"], str(analysis_id))
        self.assertEqual(created["versions"]["model_sha256"], model_hash)
        self.assertEqual(created["versions"]["model"], model_version)
        analysis = Analysis.objects.get(pk=analysis_id)
        self.assertEqual(analysis.technical["classification"]["model_sha256"], model_hash)
        self.assertEqual(analysis.technical["classification"]["model_version"], model_version)

        detail = self.client.get(reverse("api-v1:analysis-detail", args=[created["id"]]))
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["id"], str(analysis_id))
        self.assertEqual(detail.json()["versions"], created["versions"])

    def test_repair_migration_restores_canonical_metadata_without_unmasking_text(self):
        classifier_service.set_classifier(FakeClassifier(0.9))
        analysis = Analysis.objects.get(pk=self._post({"text": PT_TEXT}).json()["id"])
        analysis.model_version = "model-5252043214"
        analysis.model_sha256 = "ab5252043214cd" + "a" * 50
        analysis.rules_version = "rules-5252043214"
        analysis.calibrator_version = "cal-5252043214"
        original = {
            "classification": {"model_version": analysis.model_version, "model_sha256": analysis.model_sha256},
            "rules": {"version": analysis.rules_version},
            "calibrator": {"version": analysis.calibrator_version},
            "llm_analysis": {"summary": "Contato maria@exemplo.com"},
        }
        legacy = importlib.import_module("analysis.migrations.0002_mask_legacy_analysis_data")
        analysis.technical = legacy.sanitize(original)
        self.assertNotEqual(analysis.technical["classification"]["model_sha256"], analysis.model_sha256)
        analysis.save(update_fields=[
            "model_version", "model_sha256", "rules_version", "calibrator_version", "technical",
        ])

        incomplete = Analysis.objects.get(pk=self._post({"text": PT_TEXT}).json()["id"])
        incomplete.technical = {"classification": {"label": "verdadeira"}, "rules": {"version": "historic-version"}}
        incomplete.save(update_fields=["technical"])

        migration = importlib.import_module("analysis.migrations.0003_restore_technical_metadata")
        migration.restore_technical_metadata(apps, SimpleNamespace(connection=connection))
        analysis.refresh_from_db()
        self.assertEqual(analysis.technical["classification"], original["classification"])
        self.assertEqual(analysis.technical["rules"], original["rules"])
        self.assertEqual(analysis.technical["calibrator"], original["calibrator"])
        self.assertEqual(analysis.technical["llm_analysis"]["summary"], "Contato [e-mail removido]")
        incomplete.refresh_from_db()
        self.assertEqual(incomplete.technical, {
            "classification": {"label": "verdadeira"}, "rules": {"version": "historic-version"},
        })
        repaired = analysis.technical
        migration.restore_technical_metadata(apps, SimpleNamespace(connection=connection))
        analysis.refresh_from_db()
        self.assertEqual(analysis.technical, repaired)

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

    def test_slow_model_returns_504_without_late_persistence(self):
        release = threading.Event()
        finished = threading.Event()

        class Slow(FakeClassifier):
            def classify(self, *args, **kwargs):
                release.wait(timeout=2)
                try:
                    return super().classify(*args, **kwargs)
                finally:
                    finished.set()

        classifier_service.set_classifier(Slow(0.9))
        # O modelo deixa 2 s de reserva; apenas 50 ms ficam disponíveis neste teste.
        with patch("analysis.services.pipeline._request_deadline", side_effect=lambda: Deadline.after(2.05)):
            try:
                started = time.monotonic()
                response = self._post({"text": PT_TEXT})
                self.assertLess(time.monotonic() - started, 0.8)
                self.assertEqual(response.status_code, 504)
                self.assertEqual(response.json()["error"]["code"], "analysis_timeout")
                self.assertEqual(Analysis.objects.count(), 0)
            finally:
                release.set()
                self.assertTrue(finished.wait(timeout=2))
        self.assertEqual(Analysis.objects.count(), 0)

    def test_partial_source_timeout_is_exposed_in_result(self):
        classifier_service.set_classifier(FakeClassifier(0.9))
        self.fact_patch.stop()
        with patch("analysis.services.pipeline.factcheck.search_fact_checks", return_value={
            "status": "none", "sources": [], "conflict_score": None, "failed": True,
        }):
            response = self._post({"text": PT_TEXT})
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["evidence"]["failed"])
        self.assertTrue(any("prazo" in text for text in response.json()["limitations"]))

    def test_health(self):
        resp = self.client.get(reverse("api-v1:health"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["rules_version"], "rules-v1.0.0")

    def test_extension_request_format_and_response(self):
        classifier_service.set_classifier(FakeClassifier(0.1))
        payload = {
            "title": "Notícia raspada da página",
            "content": PT_TEXT,
            "url": "https://g1.globo.com/politica/noticia.ghtml",
            "is_extension": True,
        }
        resp = self.client.post(
            reverse("api-v1:analysis-create"),
            data=payload,
            format="json",
            HTTP_X_CLIENT_SOURCE="browser-extension",
        )
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        res = data["result"]
        self.assertEqual(res["verdict_code"], "SAFE")
        self.assertEqual(res["label"], "Poucos sinais de risco")
        self.assertEqual(res["model_label"], "Verdadeira")
        self.assertIn("score", res)
        self.assertIn("discourse_label", res)
        self.assertIn("training_scope", res)
        self.assertIn("semantic_comparison", res)
        self.assertIn("full_details", res)
        # Verifica se o source_domain foi extraído para identificar a imprensa tradicional
        analysis = Analysis.objects.latest("created_at")
        self.assertEqual((analysis.technical or {}).get("classification", {}).get("training_scope"), "in_domain_press")

    def test_extension_response_masks_pii_and_exposes_source_failure(self):
        classifier_service.set_classifier(FakeClassifier(0.9))
        email = "maria@exemplo.com"
        phone = "(11) 98765-4321"
        self.fact_patch.stop()
        with patch("analysis.services.pipeline.factcheck.search_fact_checks", return_value={
            "status": "none", "sources": [], "conflict_score": None, "failed": True,
        }):
            resp = self.client.post(
                self.url,
                data={"title": f"Notícia sobre {email}", "content": PT_TEXT + f" Contato {phone}"},
                format="json",
                HTTP_X_CLIENT_SOURCE="browser-extension",
            )
        self.assertEqual(resp.status_code, 201, resp.content)
        serialized = json.dumps(resp.json(), ensure_ascii=False)
        self.assertNotIn(email, serialized)
        self.assertNotIn(phone, serialized)
        self.assertTrue(resp.json()["result"]["evidence"]["failed"])

    def test_extension_throttle_exempt(self):
        from rest_framework.test import APIRequestFactory
        from analysis.api.throttling import ExtensionOrAnonThrottle
        factory = APIRequestFactory()
        throttle = ExtensionOrAnonThrottle()
        req_ext = factory.post("/api/v1/analyses/", HTTP_X_CLIENT_SOURCE="browser-extension")
        self.assertTrue(throttle.allow_request(req_ext, None))
