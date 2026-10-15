"""
Serviço de classificação textual com o BERTimbau V4 (RF11, RF12, RF21).

Estratégia para textos longos (RF12) — documentada e determinística:

1. A entrada segue o formato aprendido no treino:
   ``[CLS] título [SEP] subtítulo [SEP] trecho_do_corpo [SEP]``.
2. O prefixo (título + subtítulo) é repetido em todos os trechos, pois carrega
   o contexto da alegação. Se o prefixo ocupar mais da metade de MAX_LEN, ele é
   truncado em MAX_LEN/2 tokens e isso é sinalizado (``prefix_truncated``).
3. O corpo é dividido em janelas de tokens que cabem no orçamento restante, com
   sobreposição de ``CHUNK_STRIDE`` tokens e cortes alinhados ao início de
   palavras (nunca começando por sub-palavra ``##``).
4. TODAS as janelas são analisadas (o limite de 5.000 caracteres do RF01 garante
   um número pequeno de janelas). Se algum dia o limite ``MAX_CHUNKS`` for
   excedido, a seleção é: primeira, última e janelas igualmente espaçadas, e a
   fração não analisada é informada em ``tokens_analyzed``/``tokens_total``.
5. Agregação: média aritmética de P(falsa) entre as janelas. A dispersão
   (desvio-padrão) é reportada para a regra de abstenção.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import statistics
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from django.conf import settings

logger = logging.getLogger(__name__)

MAX_CHUNKS = 64
FAKE_LABEL = "falsa"
TRUE_LABEL = "verdadeira"


@dataclass
class ClassificationResult:
    label: str  # "falsa" | "verdadeira"
    fake_probability: float  # agregada e calibrada, 0..1
    confidence: float  # max(p, 1 - p)
    chunk_fake_probabilities: list[float]
    chunk_disagreement: float  # desvio-padrão de P(falsa) entre trechos
    chunks_total: int
    chunks_analyzed: int
    tokens_total: int
    tokens_analyzed: int
    prefix_truncated: bool
    aggregation: str
    model_version: str
    model_sha256: str
    device: str
    latency_ms: float
    extra: dict = field(default_factory=dict)

    @property
    def fully_analyzed(self) -> bool:
        return self.tokens_analyzed >= self.tokens_total and not self.prefix_truncated

    def to_dict(self) -> dict:
        data = asdict(self)
        data["fully_analyzed"] = self.fully_analyzed
        return data


class Classifier(Protocol):
    """Contrato do classificador — permite substituir por dublês nos testes."""

    def classify(self, title: str, subtitle: str, body: str, temperature: float = 1.0) -> ClassificationResult: ...

    def info(self) -> dict: ...


# --------------------------------------------------------------------------- #
# Fatiamento (independente do modelo; testável apenas com o tokenizer)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ChunkPlan:
    windows: list[list[int]]  # input_ids completos de cada trecho
    body_spans: list[tuple[int, int]]  # intervalos [início, fim) no corpo tokenizado
    tokens_total: int
    tokens_analyzed: int
    chunks_total: int
    prefix_truncated: bool


def _is_continuation(token: str) -> bool:
    return token.startswith("##")


# Marcadores digitados/colados pelo usuário viram tokens especiais no tokenizer e
# quebrariam a estrutura título [SEP] subtítulo [SEP] corpo; por isso são removidos.
_SPECIAL_TOKEN_RE = re.compile(r"\[(?:CLS|SEP|PAD|MASK|UNK)\]")


def _strip_special_tokens(text: str) -> str:
    return _SPECIAL_TOKEN_RE.sub(" ", text or "").strip()


def plan_chunks(tokenizer, title: str, subtitle: str, body: str, max_len: int, stride: int) -> ChunkPlan:
    """Gera os trechos de entrada de forma determinística (ver docstring do módulo)."""
    cls_id, sep_id = tokenizer.cls_token_id, tokenizer.sep_token_id
    title, subtitle, body = (_strip_special_tokens(t) for t in (title, subtitle, body))

    prefix_text = f"{title} [SEP] {subtitle} [SEP]".strip()
    prefix_ids = tokenizer(prefix_text, add_special_tokens=False)["input_ids"]
    prefix_truncated = False
    max_prefix = max_len // 2
    if len(prefix_ids) > max_prefix:
        prefix_ids = prefix_ids[: max_prefix - 1] + [sep_id]
        prefix_truncated = True

    body_ids = tokenizer(body, add_special_tokens=False)["input_ids"] if body else []
    body_tokens = tokenizer.convert_ids_to_tokens(body_ids) if body_ids else []
    budget = max_len - 2 - len(prefix_ids)  # [CLS] ... [SEP]
    stride = max(0, min(stride, budget // 2))
    n = len(body_ids)

    spans: list[tuple[int, int]] = []
    if n == 0:
        spans.append((0, 0))
    start = 0
    while start < n:
        end = min(start + budget, n)
        if end < n:
            # Recuar o corte para o início de uma palavra, sem encolher demais a janela.
            adj = end
            while adj > start + budget // 2 and _is_continuation(body_tokens[adj]):
                adj -= 1
            end = adj if adj > start + budget // 2 else end
        spans.append((start, end))
        if end >= n:
            break
        nxt = max(end - stride, start + 1)
        while nxt < end and _is_continuation(body_tokens[nxt]):
            nxt += 1
        start = nxt

    chunks_total = len(spans)
    if chunks_total > MAX_CHUNKS:
        idx = sorted({round(i * (chunks_total - 1) / (MAX_CHUNKS - 1)) for i in range(MAX_CHUNKS)})
        spans = [spans[i] for i in idx]

    covered: set[int] = set()
    for s, e in spans:
        covered.update(range(s, e))

    windows = [[cls_id] + prefix_ids + body_ids[s:e] + [sep_id] for s, e in spans]
    return ChunkPlan(
        windows=windows,
        body_spans=spans,
        tokens_total=n,
        tokens_analyzed=len(covered),
        chunks_total=chunks_total,
        prefix_truncated=prefix_truncated,
    )


# --------------------------------------------------------------------------- #
# Classificador BERTimbau
# --------------------------------------------------------------------------- #
def _sha256_file(path: Path, block: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(block):
            digest.update(chunk)
    return digest.hexdigest()


def _select_device(preference: str):
    import torch

    preference = (preference or "auto").lower()
    if preference != "auto":
        return torch.device(preference)
    if torch.backends.mps.is_available():
        return torch.device("mps")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


class BertFakeNewsClassifier:
    """Carrega o modelo uma única vez e realiza inferência em lote sobre os trechos."""

    def __init__(self, cfg: dict | None = None):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        cfg = cfg or settings.FAKE_EYES
        self.max_len = int(cfg["MODEL_MAX_LEN"])
        self.stride = int(cfg["CHUNK_STRIDE"])
        self.version = cfg["MODEL_VERSION"]

        local = Path(cfg["MODEL_PATH"])
        weights = local / "model.safetensors"
        is_lfs_pointer = weights.exists() and weights.stat().st_size < 1024 * 1024

        if local.is_dir() and weights.exists() and not is_lfs_pointer:
            source = str(local)
            self.source = f"local:{local.name}"
            started = time.perf_counter()
            self.sha256 = _sha256_file(weights)
            logger.info("Hash dos pesos calculado em %.1fs", time.perf_counter() - started)
        else:
            source = cfg["MODEL_HUB_ID"]
            self.source = f"hub:{source}"
            self.sha256 = ""
            if is_lfs_pointer:
                logger.warning(
                    "O arquivo %s é um ponteiro Git LFS (%d bytes). "
                    "Execute 'git lfs pull' para baixar os pesos reais. "
                    "Usando fallback do Hugging Face Hub (%s).",
                    weights,
                    weights.stat().st_size,
                    source,
                )
            else:
                logger.warning("Pasta local do modelo não encontrada; usando Hugging Face Hub (%s).", source)

        self.device = _select_device(cfg.get("MODEL_DEVICE", "auto"))
        self.tokenizer = AutoTokenizer.from_pretrained(source)
        self.model = AutoModelForSequenceClassification.from_pretrained(source)
        self.model.to(self.device)
        self.model.eval()
        if not self.sha256:
            self.sha256 = "hub-commit:" + str(getattr(self.model.config, "_commit_hash", "") or "desconhecido")

        label2id = {k.lower(): int(v) for k, v in self.model.config.label2id.items()}
        if FAKE_LABEL not in label2id:
            raise RuntimeError(f"Rótulo '{FAKE_LABEL}' ausente no config do modelo: {label2id}")
        self.fake_index = label2id[FAKE_LABEL]
        self._torch = torch
        self._lock = threading.Lock()  # inferência serializada por processo (MPS não é thread-safe)
        logger.info("Modelo %s carregado (%s) em %s", self.version, self.source, self.device)

    def info(self) -> dict:
        return {
            "model_version": self.version,
            "model_source": self.source,
            "model_sha256": self.sha256,
            "device": str(self.device),
            "max_len": self.max_len,
            "chunk_stride": self.stride,
        }

    def classify(self, title: str, subtitle: str, body: str, temperature: float = 1.0) -> ClassificationResult:
        torch = self._torch
        started = time.perf_counter()
        plan = plan_chunks(self.tokenizer, title, subtitle, body, self.max_len, self.stride)

        width = max(len(w) for w in plan.windows)
        pad_id = self.tokenizer.pad_token_id or 0
        input_ids = [w + [pad_id] * (width - len(w)) for w in plan.windows]
        attention = [[1] * len(w) + [0] * (width - len(w)) for w in plan.windows]

        with self._lock, torch.inference_mode():
            ids_t = torch.tensor(input_ids, device=self.device)
            batch = {
                "input_ids": ids_t,
                "attention_mask": torch.tensor(attention, device=self.device),
                "token_type_ids": torch.zeros_like(ids_t),
            }
            logits = self.model(**batch).logits.float()
            probs = torch.softmax(logits / max(temperature, 1e-6), dim=-1)[:, self.fake_index]
            chunk_probs = [float(p) for p in probs.cpu().tolist()]

        fake_p = sum(chunk_probs) / len(chunk_probs)
        disagreement = statistics.pstdev(chunk_probs) if len(chunk_probs) > 1 else 0.0
        if math.isnan(fake_p):
            raise RuntimeError("Inferência retornou valor inválido.")

        return ClassificationResult(
            label=FAKE_LABEL if fake_p >= 0.5 else TRUE_LABEL,
            fake_probability=round(fake_p, 6),
            confidence=round(max(fake_p, 1 - fake_p), 6),
            chunk_fake_probabilities=[round(p, 6) for p in chunk_probs],
            chunk_disagreement=round(disagreement, 6),
            chunks_total=plan.chunks_total,
            chunks_analyzed=len(plan.windows),
            tokens_total=plan.tokens_total,
            tokens_analyzed=plan.tokens_analyzed,
            prefix_truncated=plan.prefix_truncated,
            aggregation="mean_fake_probability",
            model_version=self.version,
            model_sha256=self.sha256,
            device=str(self.device),
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )


# --------------------------------------------------------------------------- #
# Singleton por processo
# --------------------------------------------------------------------------- #
_instance: Classifier | None = None
_instance_lock = threading.Lock()


def get_classifier() -> Classifier:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = BertFakeNewsClassifier()
    return _instance


def set_classifier(classifier: Classifier | None) -> None:
    """Substitui o classificador (uso em testes)."""
    global _instance
    with _instance_lock:
        _instance = classifier


def is_loaded() -> bool:
    return _instance is not None
