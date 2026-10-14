"""Prazos de parede e execução limitada das etapas sem acesso ao banco.

Timeouts HTTP não limitam DNS, redirects nem inferência. A thread da API só
aguarda até o prazo; uma tarefa já iniciada pode terminar depois, mas nunca
persiste uma análise. O limite de slots impede acumular tarefas abandonadas.
"""

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
import threading
import time


class DeadlineExceeded(Exception):
    pass


class ServiceBusy(Exception):
    pass


_WORKERS = 8
_executor = ThreadPoolExecutor(max_workers=_WORKERS, thread_name_prefix="analysis")
_slots = threading.BoundedSemaphore(_WORKERS)


@dataclass(frozen=True)
class Deadline:
    expires_at: float

    @classmethod
    def after(cls, seconds: float):
        return cls(time.monotonic() + max(0.0, seconds))

    @property
    def remaining(self) -> float:
        return max(0.0, self.expires_at - time.monotonic())

    def check(self):
        if self.remaining <= 0:
            raise DeadlineExceeded("Prazo da etapa esgotado")

    def child(self, seconds: float, reserve: float = 0.0):
        return Deadline(min(self.expires_at - reserve, time.monotonic() + seconds))

    def timeout(self, maximum: float) -> float:
        self.check()
        return min(maximum, self.remaining)

    def submit(self, fn, *args, **kwargs):
        self.check()
        slots = _slots
        if not slots.acquire(blocking=False):
            raise ServiceBusy("Capacidade de análise ocupada")

        def run():
            self.check()
            return fn(*args, **kwargs)

        try:
            future = _executor.submit(run)
        except BaseException:
            slots.release()
            raise
        future.add_done_callback(lambda _: slots.release())
        return future

    def result(self, future):
        try:
            self.check()
            return future.result(timeout=self.remaining)
        except FutureTimeout as exc:
            future.cancel()
            raise DeadlineExceeded("Prazo da etapa esgotado") from exc
        except DeadlineExceeded:
            future.cancel()
            raise

    def call(self, fn, *args, **kwargs):
        return self.result(self.submit(fn, *args, **kwargs))
