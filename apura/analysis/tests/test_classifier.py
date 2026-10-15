"""
Testes do fatiamento (RF12) com o tokenizer real e, opcionalmente, do modelo real.

O teste com o modelo completo só roda com RUN_MODEL_TESTS=1 (carrega ~436 MB).
"""

import os
import unittest
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from analysis.services.classifier import plan_chunks

MODEL_DIR = Path(settings.FAKE_EYES["MODEL_PATH"])


@unittest.skipUnless((MODEL_DIR / "tokenizer.json").exists(), "tokenizer local ausente")
class ChunkingTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from transformers import AutoTokenizer

        cls.tok = AutoTokenizer.from_pretrained(str(MODEL_DIR))

    def _long_body(self):
        parts = [f"Parágrafo número {i} descreve fatos ocorridos na cidade durante a semana." for i in range(60)]
        return " ".join(["INICIO"] + parts[:30] + ["MEIO"] + parts[30:] + ["FIM"])

    def test_short_text_single_chunk(self):
        plan = plan_chunks(self.tok, "Título", "Sub", "Um texto curto de teste.", 128, 16)
        self.assertEqual(len(plan.windows), 1)
        self.assertEqual(plan.tokens_analyzed, plan.tokens_total)

    def test_windows_respect_max_len_and_cover_all(self):
        plan = plan_chunks(self.tok, "Título da notícia", "Subtítulo", self._long_body(), 128, 16)
        self.assertGreater(len(plan.windows), 1)
        self.assertTrue(all(len(w) <= 128 for w in plan.windows))
        self.assertEqual(plan.tokens_analyzed, plan.tokens_total)
        self.assertFalse(plan.prefix_truncated)

    def test_title_beginning_middle_end_are_analyzed(self):
        title = "Título exclusivo"
        plan = plan_chunks(self.tok, title, "", self._long_body(), 128, 16)
        decoded = [self.tok.decode(w) for w in plan.windows]
        self.assertTrue(all(title in d for d in decoded), "título deve estar em todos os trechos")
        joined = " ".join(decoded)
        for marker in ("INICIO", "MEIO", "FIM"):
            self.assertIn(marker, joined)

    def test_deterministic(self):
        a = plan_chunks(self.tok, "T", "S", self._long_body(), 128, 16)
        b = plan_chunks(self.tok, "T", "S", self._long_body(), 128, 16)
        self.assertEqual(a.windows, b.windows)

    def test_long_prefix_is_truncated_and_flagged(self):
        plan = plan_chunks(self.tok, "palavra " * 200, "", "Corpo do texto.", 128, 16)
        self.assertTrue(plan.prefix_truncated)
        self.assertTrue(all(len(w) <= 128 for w in plan.windows))

    def test_matches_reference_sep_format(self):
        # Formato do README do modelo V4: f"{titulo} [SEP] {subtitulo} [SEP] {texto}"
        for title, sub, body in [
            ("Título da notícia", "Subtítulo explicativo", "Um texto curto de teste."),
            ("Título da notícia", "", "Um texto curto de teste."),
            ("", "", "Um texto curto de teste."),
        ]:
            ref = self.tok(f"{title} [SEP] {sub} [SEP] {body}".strip())["input_ids"]
            plan = plan_chunks(self.tok, title, sub, body, 128, 16)
            self.assertEqual(plan.windows, [ref])

    def test_first_window_matches_reference_truncation(self):
        # Só a primeira janela é pontuada: deve ser a entrada da referência truncada
        # em 128 tokens, mesmo com o corte no meio de "Pará ##grafo".
        title, sub = "Título da notícia", "Subtítulo"
        body = self._long_body().split(" ", 1)[1]
        ref = self.tok(f"{title} [SEP] {sub} [SEP] {body}", truncation=True, max_length=128)["input_ids"]
        plan = plan_chunks(self.tok, title, sub, body, 128, 16)
        self.assertEqual(self.tok.convert_ids_to_tokens(ref[-2:]), ["Pará", "[SEP]"])
        self.assertEqual(plan.windows[0], ref)

    def test_literal_special_tokens_in_input_are_neutralized(self):
        plan = plan_chunks(self.tok, "Título [CLS]", "", "Texto [SEP] colado [SEP] pelo usuário.", 128, 16)
        window = plan.windows[0]
        self.assertEqual(window.count(self.tok.sep_token_id), 3)
        self.assertEqual(window.count(self.tok.cls_token_id), 1)

    def test_no_window_starts_with_subword(self):
        plan = plan_chunks(self.tok, "T", "", self._long_body(), 128, 16)
        body_ids = self.tok("" + self._long_body(), add_special_tokens=False)["input_ids"]
        tokens = self.tok.convert_ids_to_tokens(body_ids)
        for start, _ in plan.body_spans:
            self.assertFalse(tokens[start].startswith("##"))


@unittest.skipUnless(os.environ.get("RUN_MODEL_TESTS") == "1", "defina RUN_MODEL_TESTS=1 para rodar")
class RealModelTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from analysis.services.classifier import BertFakeNewsClassifier

        cls.clf = BertFakeNewsClassifier()

    def test_readme_example_is_fake(self):
        res = self.clf.classify(
            "URGENTE: Nova substância milagrosa cura todas as doenças em 24h!",
            "Médicos tentam esconder a receita secreta da população.",
            "Compartilhe imediatamente antes que derrubem este artigo.",
        )
        self.assertEqual(res.label, "falsa")
        self.assertGreater(res.fake_probability, 0.5)

    def test_reproducible(self):
        args = ("Governo anuncia medidas", "", "O Ministério da Fazenda divulgou hoje o novo pacote econômico.")
        a, b = self.clf.classify(*args), self.clf.classify(*args)
        self.assertAlmostEqual(a.fake_probability, b.fake_probability, places=4)
        self.assertTrue(a.model_sha256)

    def test_long_text_matches_reference_truncation(self):
        # Inferência de referência do V4 (tests/test_model_v4_accuracy.py do repositório
        # do modelo): f"{titulo} [SEP] {subtitulo} [SEP] {texto}" truncado em 128 tokens.
        title = "Governo vai confiscar a poupança de todos os brasileiros"
        subtitle = "Mensagem diz que os bancos já receberam a ordem"
        body = " ".join(["O governo vai tirar o dinheiro de todos os brasileiros e ninguém fala nada sobre isso."] * 15)
        res = self.clf.classify(title, subtitle, body)

        torch = self.clf._torch
        inputs = self.clf.tokenizer(
            f"{title} [SEP] {subtitle} [SEP] {body}", truncation=True, max_length=128, return_tensors="pt"
        ).to(self.clf.device)
        with torch.inference_mode():
            ref = torch.softmax(self.clf.model(**inputs).logits.float(), dim=-1)[0, self.clf.fake_index].item()

        self.assertAlmostEqual(res.fake_probability, ref, places=4)
        self.assertEqual(res.chunks_analyzed, 1)
        self.assertGreater(res.chunks_total, 1)
        self.assertLess(res.tokens_analyzed, res.tokens_total)
        self.assertFalse(res.fully_analyzed)
