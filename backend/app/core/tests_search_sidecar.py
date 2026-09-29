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
            batched = SidecarEmbeddings(base).embed_documents(["a"] * 65)
            self.assertEqual(len(batched), 65)
            self.assertEqual(batched[0], [1.0, 0.25])
            self.assertEqual(batched[64], [1.0, 0.25])
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
        embeddings._LOCAL_EMBEDDINGS = None
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
        embeddings._LOCAL_EMBEDDINGS = None

    def test_ingest_skips_sidecar_when_cuda_is_down(self):
        import core.embeddings_utils as embeddings

        embeddings._EMBEDDINGS = None
        embeddings._LOCAL_EMBEDDINGS = None
        fake_model = mock.Mock()
        local = QueryPrefixedEmbeddings(fake_model)
        with mock.patch.dict(
            os.environ,
            {"SEARCH_SIDECAR_URL": "http://127.0.0.1:8012", "EMBEDDING_DEVICE": "cpu"},
            clear=False,
        ):
            with mock.patch("core.embeddings_utils._load_local_embeddings", return_value=local) as loader:
                client = get_embeddings(force_new=True, allow_sidecar=False)
        self.assertIs(client, local)
        self.assertNotIsInstance(client._inner, SidecarEmbeddings)
        loader.assert_called_once()
        embeddings._EMBEDDINGS = None
        embeddings._LOCAL_EMBEDDINGS = None

    def test_sidecar_embed_documents_batches_over_max_texts(self):
        posts = []

        def fake_post(url, payload, timeout):
            posts.append(payload["texts"])
            return {"vectors": [[float(len(text)), 0.1] for text in payload["texts"]]}

        with mock.patch("core.search_sidecar._post_json", side_effect=fake_post):
            vectors = SidecarEmbeddings("http://127.0.0.1:8012").embed_documents(["ab"] * 65)
        self.assertEqual(len(posts), 2)
        self.assertEqual(len(posts[0]), 64)
        self.assertEqual(len(posts[1]), 1)
        self.assertEqual(len(vectors), 65)
