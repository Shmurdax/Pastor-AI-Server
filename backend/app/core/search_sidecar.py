"""Shared GPU process for sermon embed + rerank.

Gunicorn keeps CUDA hidden so its workers cannot allocate against vLLM.
Chat still calls the same BGE embedder and the same cross-encoder; those
models live in one process started by ``run_search_sidecar``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional
from urllib import error as urlerror
from urllib import request as urlrequest

logger = logging.getLogger(__name__)

DEFAULT_EMBED_MODEL = "BAAI/bge-base-en-v1.5"
DEFAULT_RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
MAX_TEXTS = 64
MAX_PAIRS = 64
MAX_TEXT_CHARS = 8000

EncodeFn = Callable[[list[str]], list[list[float]]]
PredictFn = Callable[[list[list[str]]], list[float]]


def sidecar_url(env: Optional[dict] = None) -> str:
    source = env if env is not None else os.environ
    return str(source.get("SEARCH_SIDECAR_URL") or "").strip().rstrip("/")


def _post_json(url: str, payload: dict, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"search sidecar {exc.code}: {detail}") from exc
    except urlerror.URLError as exc:
        raise RuntimeError(f"search sidecar unavailable: {exc.reason}") from exc
    parsed = json.loads(body or "{}")
    if not isinstance(parsed, dict):
        raise RuntimeError("search sidecar returned a non-object")
    return parsed


class SidecarEmbeddings:
    """LangChain-shaped embedder that forwards to the GPU search process."""

    def __init__(self, base_url: str, timeout: float = 60.0):
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def embed_documents(self, texts):
        rows = [str(text) for text in (texts or [])]
        if not rows:
            return []
        body = _post_json(f"{self._base}/embed", {"texts": rows}, self._timeout)
        vectors = body.get("vectors")
        if not isinstance(vectors, list):
            raise RuntimeError("search sidecar embed response missing vectors")
        return vectors

    def embed_query(self, text: str):
        vectors = self.embed_documents([text])
        if not vectors:
            raise RuntimeError("search sidecar returned no query vector")
        return vectors[0]


class SidecarReranker:
    """Cross-encoder stand-in. ``predict`` returns raw logits, same as the local model."""

    def __init__(self, base_url: str, timeout: float = 120.0):
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def predict(self, pairs):
        rows = [[str(pair[0]), str(pair[1])] for pair in (pairs or [])]
        if not rows:
            return []
        body = _post_json(f"{self._base}/rerank", {"pairs": rows}, self._timeout)
        scores = body.get("scores")
        if not isinstance(scores, list):
            raise RuntimeError("search sidecar rerank response missing scores")
        return [float(score) for score in scores]


def _as_text_list(raw, *, field: str, limit: int) -> list[str]:
    if not isinstance(raw, list):
        raise ValueError(f"{field} must be a list")
    if len(raw) > limit:
        raise ValueError(f"{field} exceeds {limit}")
    texts: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError(f"{field} entries must be strings")
        texts.append(item[:MAX_TEXT_CHARS])
    return texts


def embed_payload(payload: dict, encode: EncodeFn) -> dict:
    texts = _as_text_list(payload.get("texts") or [], field="texts", limit=MAX_TEXTS)
    if not texts:
        return {"vectors": []}
    vectors = encode(texts)
    return {"vectors": vectors}


def rerank_payload(payload: dict, predict: PredictFn) -> dict:
    raw_pairs = payload.get("pairs") or []
    if not isinstance(raw_pairs, list):
        raise ValueError("pairs must be a list")
    if len(raw_pairs) > MAX_PAIRS:
        raise ValueError(f"pairs exceeds {MAX_PAIRS}")
    pairs: list[list[str]] = []
    for pair in raw_pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            raise ValueError("each pair must be [query, passage]")
        if not isinstance(pair[0], str) or not isinstance(pair[1], str):
            raise ValueError("pair entries must be strings")
        pairs.append([pair[0][:MAX_TEXT_CHARS], pair[1][:MAX_TEXT_CHARS]])
    if not pairs:
        return {"scores": []}
    scores = [float(score) for score in predict(pairs)]
    return {"scores": scores}


def _torch_dtype():
    import torch

    name = (os.getenv("SEARCH_TORCH_DTYPE") or "float16").strip().lower()
    if name in {"float32", "fp32"}:
        return torch.float32
    return torch.float16


def load_models():
    """Load one BGE embedder and one cross-encoder on CUDA. Returns (encode, predict)."""
    import torch
    from sentence_transformers import CrossEncoder, SentenceTransformer

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is not available for the sermon search sidecar")

    dtype = _torch_dtype()
    embed_name = (os.getenv("EMBEDDING_MODEL_NAME") or DEFAULT_EMBED_MODEL).strip()
    rerank_name = (os.getenv("RERANK_MODEL") or DEFAULT_RERANK_MODEL).strip()

    def _load(cls, name: str):
        try:
            return cls(name, device="cuda", model_kwargs={"torch_dtype": dtype})
        except TypeError:
            logger.warning("%s has no model_kwargs; loading on cuda without an explicit dtype", cls.__name__)
            model = cls(name, device="cuda")
            inner = getattr(model, "model", None)
            if dtype == torch.float16 and inner is not None and hasattr(inner, "half"):
                inner.half()
            return model

    logger.info("Loading embedder %s on cuda dtype=%s", embed_name, dtype)
    embedder = _load(SentenceTransformer, embed_name)
    logger.info("Loading reranker %s on cuda dtype=%s", rerank_name, dtype)
    reranker = _load(CrossEncoder, rerank_name)
    lock = threading.Lock()

    def encode(texts: list[str]) -> list[list[float]]:
        with lock:
            vectors = embedder.encode(
                list(texts),
                normalize_embeddings=True,
                batch_size=int(os.getenv("EMBEDDING_BATCH_SIZE", "32")),
                show_progress_bar=False,
            )
        return [list(map(float, row)) for row in vectors]

    def predict(pairs: list[list[str]]) -> list[float]:
        with lock:
            raw = reranker.predict(pairs, batch_size=8, show_progress_bar=False)
        if hasattr(raw, "tolist"):
            raw = raw.tolist()
        if isinstance(raw, (float, int)):
            return [float(raw)]
        return [float(score) for score in list(raw)]

    # Pay CUDA startup before the first chat.
    encode(["warmup"])
    predict([["warmup", "warmup passage"]])
    logger.info("Sermon search models ready")
    return encode, predict


def make_handler(encode: EncodeFn, predict: PredictFn):
    class SearchHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path != "/health":
                self._send(404, {"ok": False})
                return
            self._send(200, {"ok": True, "device": "cuda"})

        def do_POST(self):  # noqa: N802
            path = self.path.split("?", 1)[0]
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length) if length else b""
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                self._send(400, {"error": "invalid json"})
                return
            if not isinstance(payload, dict):
                self._send(400, {"error": "json object required"})
                return
            try:
                if path == "/embed":
                    body = embed_payload(payload, encode)
                elif path == "/rerank":
                    body = rerank_payload(payload, predict)
                else:
                    self._send(404, {"error": "not found"})
                    return
            except ValueError as exc:
                self._send(400, {"error": str(exc)})
                return
            except Exception as exc:
                logger.exception("Search sidecar request failed")
                self._send(500, {"error": str(exc)})
                return
            self._send(200, body)

        def log_message(self, fmt: str, *args) -> None:
            logger.info("%s - %s", self.address_string(), fmt % args)

    return SearchHandler


def serve(host: str, port: int, encode: EncodeFn, predict: PredictFn) -> None:
    server = ThreadingHTTPServer((host, port), make_handler(encode, predict))
    logger.info("Sermon search sidecar listening on %s:%s", host, port)
    server.serve_forever()
