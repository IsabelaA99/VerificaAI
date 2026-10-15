"""Proteção de dados pessoais em consultas externas e resultados."""

from django.test import SimpleTestCase

from analysis.services.llm import _build_prompt
from analysis.services.privacy import sanitize_analysis_data


class AnalysisPrivacyTests(SimpleTestCase):
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
