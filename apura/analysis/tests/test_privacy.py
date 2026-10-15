"""Proteção de dados pessoais em consultas externas e resultados."""

from django.test import SimpleTestCase

from analysis.services.llm import _build_prompt
from analysis.services.privacy import sanitize_analysis_data


class AnalysisPrivacyTests(SimpleTestCase):
    def test_structural_fields_with_phone_like_digits_are_preserved(self):
        record = {
            "id": "00000000-0000-4000-8000-5252043214c0",
            "created_at": "2026-10-15T14:30:00Z",
            "status": {"code": "alto_risco", "label": "Alto risco"},
            "versions": {
                "model": "model-5252043214", "model_sha256": "ab5252043214cd",
                "rules": "rules-5252043214", "calibrator": "cal-5252043214",
                "schema": "schema-5252043214", "code": "ab5252043214cd",
            },
            "classification": {
                "model_version": "model-5252043214", "model_sha256": "ab5252043214cd",
                "fake_probability": 0.9, "fully_analyzed": True,
            },
            "rules": {"version": "rules-5252043214"},
            "calibrator": {"version": "cal-5252043214"},
            "llm_analysis": {"provider": "provider-5252043214", "discourse_type": "factual"},
            "evidence": {"sources": [{
                "id": "src-5252043214", "relation": "contextual", "published_at": "2026-10-15",
            }]},
        }
        self.assertEqual(sanitize_analysis_data(record), record)

    def test_nested_narrative_fields_still_mask_personal_data(self):
        record = {
            "claim": {"summary": "Contato maria@exemplo.com"},
            "explanation": ["CPF 123.456.789-09"],
            "llm_analysis": {
                "semantic_comparison": {
                    "consensus_status": "nao_verificado", "claim_analyzed": "Telefone (11) 98765-4321",
                },
                "lexical_analysis": {
                    "hedging_detected": True,
                    "notes": [{"text": "Contato maria@exemplo.com"}],
                },
            },
        }
        result = sanitize_analysis_data(record)
        self.assertEqual(result["claim"]["summary"], "Contato [e-mail removido]")
        self.assertEqual(result["explanation"], ["CPF [CPF removido]"])
        semantic = result["llm_analysis"]["semantic_comparison"]
        self.assertEqual(semantic["consensus_status"], "nao_verificado")
        self.assertEqual(semantic["claim_analyzed"], "Telefone [telefone removido]")
        lexical = result["llm_analysis"]["lexical_analysis"]
        self.assertTrue(lexical["hedging_detected"])
        self.assertEqual(lexical["notes"], [{"text": "Contato [e-mail removido]"}])
        self.assertEqual(record["claim"]["summary"], "Contato maria@exemplo.com")

    def test_external_llm_prompt_uses_masked_content(self):
        prompt = _build_prompt(
            title="Notícia enviada por maria@exemplo.com",
            body="Contato (11) 98765-4321 e CPF 123.456.789-09. " * 60,
            model_fake_prob=0.5,
            model_confidence=0.5,
            model_label="falsa",
            linguistic_indicators={"sensational_terms": []},
            sources=[{
                "publisher": "Agência", "relation": "contextual",
                "title": "Checagem de maria@exemplo.com", "excerpt": "Telefone (11) 98765-4321",
            }],
        )
        for personal_data in ("maria@exemplo.com", "(11) 98765-4321", "123.456.789-09"):
            self.assertNotIn(personal_data, prompt)
        self.assertIn("[e-mail removido]", prompt)
        self.assertIn("[CPF removido]", prompt)
        self.assertIn("[telefone removido]", prompt)

    def test_public_source_url_remains_usable(self):
        record = {"sources": [{"url": "https://exemplo.org/checagem?id=42", "title": "Checagem"}]}
        self.assertEqual(sanitize_analysis_data(record), record)

    def test_nested_encoded_personal_data_removes_source_url(self):
        record = {"sources": [{"url": "https://exemplo.org/?email=maria%2540exemplo.com"}]}
        self.assertEqual(sanitize_analysis_data(record)["sources"][0]["url"], "")
