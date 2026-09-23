"""GPU sermon-search sidecar client and HTTP contract."""

from __future__ import annotations

import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

from core.embeddings_utils import QueryPrefixedEmbeddings, get_embeddings
from core.rerank import get_reranker
from core.search_sidecar import (
    SidecarEmbeddings,
    SidecarReranker,
    embed_payload,
    make_handler,
    rerank_payload,
    sidecar_url,
)


def _encode(texts):
    return [[float(len(text)), 0.25] for text in texts]


def _predict(pairs):
    return [float(len(pair[1])) for pair in pairs]


class SearchSidecarContractTests(unittest.TestCase):
    def test_embed_and_rerank_payloads(self):
        self.assertEqual(embed_payload({"texts": []}, _encode), {"vectors": []})
        self.assertEqual(embed_payload({"texts": ["ab"]}, _encode)["vectors"], [[2.0, 0.25]])
        self.assertEqual(rerank_payload({"pairs": []}, _predict), {"scores": []})
        self.assertEqual(rerank_payload({"pairs": [["q", "abc"]]}, _predict)["scores"], [3.0])

    def test_rejects_oversized_batches(self):
        with self.assertRaises(ValueError):
            embed_payload({"texts": ["x"] * 65}, _encode)
        with self.assertRaises(ValueError):
            rerank_payload({"pairs": [["q", "p"]] * 65}, _predict)

    def test_http_roundtrip(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(_encode, _predict))
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{port}"
        try:
            from urllib.request import urlopen

            with urlopen(f"{base}/health", timeout=5) as resp:
                self.assertEqual(json.loads(resp.read().decode())["ok"], True)
            emb = SidecarEmbeddings(base)
            self.assertEqual(emb.embed_query("grace"), [5.0, 0.25])
            self.assertEqual(SidecarReranker(base).predict([["q", "ab"]]), [2.0])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_chat_uses_sidecar_without_hiding_cuda(self):
        import core.embeddings_utils as embeddings
        import core.rerank as rerank

        embeddings._EMBEDDINGS = None
        rerank._RERANKER = None
        rerank._RERANKER_FAILED = False
        env = {
            "SEARCH_SIDECAR_URL": "http://127.0.0.1:8012",
            "CUDA_VISIBLE_DEVICES": "0",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            client = get_embeddings(force_new=True)
            model = get_reranker(force_new=True)
            self.assertEqual(os.environ.get("CUDA_VISIBLE_DEVICES"), "0")
        self.assertIsInstance(client, QueryPrefixedEmbeddings)
        self.assertIsInstance(client._inner, SidecarEmbeddings)
        self.assertIsInstance(model, SidecarReranker)
        self.assertEqual(sidecar_url(env), "http://127.0.0.1:8012")
        embeddings._EMBEDDINGS = None
        rerank._RERANKER = None

    def test_query_prefix_is_applied_before_the_sidecar(self):
        import core.embeddings_utils as embeddings

        embeddings._EMBEDDINGS = None
        captured = {}

        def fake_post(url, payload, timeout):
            captured["url"] = url
            captured["payload"] = payload
            return {"vectors": [[0.1, 0.2]]}

        with mock.patch.dict(os.environ, {"SEARCH_SIDECAR_URL": "http://127.0.0.1:8012"}, clear=False):
            with mock.patch("core.search_sidecar._post_json", side_effect=fake_post):
                vector = get_embeddings(force_new=True).embed_query("grace")
        self.assertEqual(vector, [0.1, 0.2])
        self.assertTrue(str(captured["url"]).endswith("/embed"))
        sent = captured["payload"]["texts"][0]
        self.assertTrue(sent.lower().startswith("represent this sentence"))
        self.assertTrue(sent.endswith("grace"))
        embeddings._EMBEDDINGS = None
