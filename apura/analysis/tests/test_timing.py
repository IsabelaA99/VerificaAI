"""Regressões de latência: rede travada, orçamento compartilhado e capacidade."""

import threading
import time
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from analysis.services import factcheck, llm, timing
from analysis.services.timing import Deadline, DeadlineExceeded, ServiceBusy


class DeadlineTests(SimpleTestCase):
    def test_slow_task_does_not_hold_caller_until_it_finishes(self):
        release = threading.Event()
        deadline = Deadline.after(0.05)
        future = deadline.submit(release.wait, 2)
        started = time.monotonic()
        try:
            with self.assertRaises(DeadlineExceeded):
                deadline.result(future)
            self.assertLess(time.monotonic() - started, 0.8)
            self.assertFalse(future.done())
        finally:
            release.set()
            future.result(timeout=2)

    def test_expired_deadline_does_not_start_another_task(self):
        fn = Mock()
        with self.assertRaises(DeadlineExceeded):
            Deadline.after(0).call(fn)
        fn.assert_not_called()

    def test_busy_workers_reject_work_instead_of_growing_a_queue(self):
        release = threading.Event()
        with patch.object(timing, "_slots", threading.BoundedSemaphore(1)):
            future = Deadline.after(2).submit(release.wait, 2)
            try:
                with self.assertRaises(ServiceBusy):
                    Deadline.after(2).submit(lambda: None)
            finally:
                release.set()
                future.result(timeout=2)


class SourceDeadlineTests(SimpleTestCase):
    def test_fallback_queries_run_together_and_keep_source_order(self):
        barrier = threading.Barrier(3)

        def search(name):
            def run(query):
                barrier.wait(timeout=1)
                return [{"url": f"https://example.org/{name}", "title": name}]
            return run

        with patch.object(factcheck, "_search_comprova", side_effect=search("comprova")), \
             patch.object(factcheck, "_search_boatos", side_effect=search("boatos")), \
             patch.object(factcheck, "_search_wikipedia", side_effect=search("wiki")):
            failures = []
            sources = factcheck._search_fact_check_fallback(
                "alegacao", deadline=Deadline.after(2), failures=failures,
            )
        self.assertEqual([s["title"] for s in sources], ["comprova", "boatos", "wiki"])
        self.assertEqual(failures, [])

    def test_slow_sources_return_available_results_and_mark_failure(self):
        release = threading.Event()
        finished = threading.Event()

        def slow(query):
            release.wait(timeout=2)
            finished.set()
            return []

        source = {"url": "https://example.org/check", "title": "Vacina causa autismo",
                  "relation": "conflicting", "publisher": "Agência"}
        with patch.dict("django.conf.settings.FAKE_EYES", {"GOOGLE_FACT_CHECK_API_KEY": ""}), \
             patch.object(factcheck, "_search_comprova", return_value=[source]), \
             patch.object(factcheck, "_search_boatos", side_effect=slow), \
             patch.object(factcheck, "_search_wikipedia", return_value=[]):
            try:
                started = time.monotonic()
                result = factcheck.search_fact_checks("Vacina causa autismo", deadline=Deadline.after(0.1))
                self.assertLess(time.monotonic() - started, 0.8)
                self.assertTrue(result["failed"])
                self.assertEqual(result["conflict_score"], 1.0)
                self.assertEqual(len(result["sources"]), 1)
            finally:
                release.set()
                self.assertTrue(finished.wait(timeout=2))


class LLMDeadlineTests(SimpleTestCase):
    def test_slow_provider_uses_local_explanation_without_trying_other_providers(self):
        release = threading.Event()
        finished = threading.Event()

        def slow(*args, **kwargs):
            release.wait(timeout=2)
            finished.set()
            return None

        with patch.dict("django.conf.settings.FAKE_EYES", {
            "GROQ_API_KEY": "test", "GEMINI_API_KEY": "test", "OPENAI_API_KEY": "test",
        }), patch.object(llm, "_call_groq", side_effect=slow), \
             patch.object(llm, "_call_gemini") as gemini, \
             patch.object(llm, "_call_openai") as openai:
            try:
                started = time.monotonic()
                result = llm.synthesize_explanation(
                    title="Governo anuncia medidas", body="Medidas para o setor de saúde.",
                    model_fake_prob=0.1, model_confidence=0.9, model_label="verdadeira",
                    linguistic_indicators={}, sources=[], deadline=Deadline.after(0.05),
                )
                self.assertLess(time.monotonic() - started, 0.8)
                self.assertIn("Motor Analítico", result.provider)
                gemini.assert_not_called()
                openai.assert_not_called()
            finally:
                release.set()
                self.assertTrue(finished.wait(timeout=2))

    def test_model_retries_share_one_budget(self):
        clock = [0.0]

        def unavailable(*args, **kwargs):
            clock[0] += kwargs["timeout"]
            return Mock(status_code=404)

        with patch.object(timing.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(llm.requests, "post", side_effect=unavailable) as post:
            result = llm._call_groq("prompt", "test", deadline=Deadline.after(7))
        self.assertIsNone(result)
        self.assertEqual([c.kwargs["timeout"] for c in post.call_args_list], [5, 2])

    def test_rate_limit_does_not_retry_every_model(self):
        for provider in (llm._call_groq, llm._call_gemini):
            with self.subTest(provider=provider.__name__), \
                 patch.object(llm.requests, "post", return_value=Mock(status_code=429)) as post:
                self.assertIsNone(provider("prompt", "test"))
                self.assertEqual(post.call_count, 1)
