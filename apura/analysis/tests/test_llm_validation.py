"""Validação da fronteira entre a resposta externa e a explicação utilizada."""

from copy import deepcopy
import json
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from analysis.services import llm
from analysis.services.llm_schema import validate_llm_payload
from analysis.tests.llm_fixtures import valid_llm_payload


class LLMResponseValidationTests(SimpleTestCase):
    def test_wrong_field_types_and_limits_are_rejected(self):
        invalid_fields = (
            ("summary", None), ("summary", 42), ("summary", []), ("summary", "   "), ("summary", "x" * 4001),
            ("summary", "\ud800"),
            ("key_points", None), ("key_points", 42), ("key_points", "AB"), ("key_points", [42]),
            ("key_points", ["x"] * 11), ("key_points", ["x" * 1001]),
            ("verdict_tendency", "desconhecido"), ("discourse_type", "desconhecido"),
            ("discourse_label", 42), ("uncertainty_warning", {}),
            ("semantic_comparison", None), ("semantic_comparison", []),
            ("semantic_comparison.consensus_summary", 42), ("semantic_comparison.claim_analyzed", False),
            ("semantic_comparison.consensus_status", "desconhecido"),
            ("lexical_analysis", None), ("lexical_analysis", []),
            ("lexical_analysis.hedging_detected", 1), ("lexical_analysis.hedging_detected", "false"),
            ("lexical_analysis.hedging_terms", "texto"), ("lexical_analysis.hedging_terms", [None]),
            ("lexical_analysis.hedging_terms", ["x"] * 21), ("lexical_analysis.hedging_terms", ["x" * 201]),
            ("lexical_analysis.rhetorical_devices", [False]), ("lexical_analysis.formality_gap_warning", 42),
        )
        for path, value in invalid_fields:
            with self.subTest(path=path, value_type=type(value).__name__):
                payload = valid_llm_payload()
                target = payload
                keys = path.split(".")
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                with self.assertRaises(ValueError):
                    llm._parse_llm_json(payload, provider="teste")

    def test_root_and_required_fields_are_checked(self):
        for payload in (None, [], "texto", 42, {}, {"summary": "Resumo"}, {"key_points": []}):
            with self.subTest(payload_type=type(payload).__name__), self.assertRaises(ValueError):
                llm._parse_llm_json(payload, provider="teste")

    def test_missing_optional_fields_have_neutral_defaults(self):
        result = llm._parse_llm_json({"summary": "Resumo", "key_points": []}, provider="teste")
        self.assertEqual(result.semantic_comparison["consensus_status"], "nao_verificado")
        self.assertEqual(result.semantic_comparison["consensus_summary"], "")
        self.assertEqual(result.lexical_analysis["hedging_terms"], [])
        self.assertEqual(result.verdict_tendency, "inconclusiva")

    def test_valid_response_does_not_mutate_input(self):
        payload = valid_llm_payload()
        original = deepcopy(payload)
        result = llm._parse_llm_json(payload, provider="teste", source_domain="sensacionalista.com.br")
        self.assertEqual(result.discourse_type, "satira")
        self.assertEqual(payload, original)

    def test_unknown_fields_are_not_forwarded(self):
        payload = valid_llm_payload()
        payload["semantic_comparison"]["extra"] = {"arbitrary": 42}
        payload["lexical_analysis"]["extra"] = [42]
        result = llm._parse_llm_json(payload, provider="teste")
        self.assertNotIn("extra", result.semantic_comparison)
        self.assertNotIn("extra", result.lexical_analysis)

    def test_expanded_legacy_text_keeps_type_validation_without_new_input_limits(self):
        payload = valid_llm_payload()
        payload["summary"] = "[e-mail removido] " * 300
        with self.assertRaises(ValueError):
            validate_llm_payload(payload)
        self.assertEqual(validate_llm_payload(payload, check_limits=False)["summary"], payload["summary"].strip())
        payload["key_points"] = "AB"
        with self.assertRaises(ValueError):
            validate_llm_payload(payload, check_limits=False)

    def test_each_provider_rejects_json_with_wrong_internal_types(self):
        payload = valid_llm_payload()
        payload["semantic_comparison"]["consensus_summary"] = 42
        content = json.dumps(payload)
        for provider, envelope in (
            (llm._call_groq, {"choices": [{"message": {"content": content}}]}),
            (llm._call_openai, {"choices": [{"message": {"content": content}}]}),
            (llm._call_gemini, {"candidates": [{"content": {"parts": [{"text": content}]}}]}),
        ):
            response = Mock(status_code=200)
            response.json.return_value = envelope
            with self.subTest(provider=provider.__name__), patch.object(llm.requests, "post", return_value=response) as post:
                self.assertIsNone(provider("prompt de teste", "dummy-key"))
                self.assertEqual(post.call_count, 1)


class GeminiAndSatireTests(SimpleTestCase):
    def test_gemini_usa_modelo_disponivel_com_raciocinio_minimo(self):
        # Os modelos 1.5, 2.0 e 2.5 respondem 404 para chaves novas
        response = Mock(status_code=200)
        response.json.return_value = {"candidates": [{"content": {"parts": [{"text": json.dumps(valid_llm_payload())}]}}]}
        with patch.object(llm.requests, "post", return_value=response) as post:
            result = llm._call_gemini("prompt", "chave")
        self.assertEqual(result.provider, "Google Gemini (gemini-flash-lite-latest)")
        url = post.call_args.args[0]
        self.assertIn("/models/gemini-flash-lite-latest:generateContent", url)
        self.assertEqual(post.call_args.kwargs["json"]["generationConfig"]["thinkingConfig"], {"thinkingLevel": "minimal"})

    def test_resumo_que_nega_satira_nao_vira_satira(self):
        # Caso real (Groq, Agência Brasil): o resumo descartava a sátira e o código a detectava
        payload = valid_llm_payload()
        payload["summary"] = "Não há indícios de teor conspiratório, opinativo ou satírico."
        result = llm._parse_llm_json(payload, provider="teste", source_domain="agenciabrasil.ebc.com.br")
        self.assertEqual(result.discourse_type, "factual")

    def test_satira_indicada_pela_ia_continua_sendo_satira(self):
        payload = valid_llm_payload()
        payload["discourse_type"] = "satira"
        result = llm._parse_llm_json(payload, provider="teste")
        self.assertEqual(result.discourse_type, "satira")
        self.assertEqual(result.semantic_comparison["consensus_status"], "diverge_consenso")
