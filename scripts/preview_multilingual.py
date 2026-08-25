#!/usr/bin/env python3
"""Lightweight local preview server for multilingual display-page testing.

Serves the Flutter web build and mocks POST /api/chat/ so language switching
can be verified without vLLM / Qdrant / Postgres.
"""

from __future__ import annotations

import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(os.environ.get("FRONTEND_BUILD_DIR", "/workspace/frontend/build/web")).resolve()
HOST = os.environ.get("PREVIEW_HOST", "127.0.0.1")
PORT = int(os.environ.get("PREVIEW_PORT", "8765"))

SAMPLE_SOURCES = [
    "Faith That Overcomes",
    "Walking in Grace",
]

REPLY_BY_LANG = {
    "en": (
        "This is a local preview reply in English. "
        "Your question was received and the chat API language setting is English. "
        "In production, Pastor Don's assistant would answer from sermon notes here."
    ),
    "es": (
        "Esta es una respuesta de vista previa en español. "
        "Tu pregunta fue recibida y el idioma de la API de chat es español. "
        "En producción, el asistente del Pastor Don respondería desde las notas del sermón."
    ),
    "fr": (
        "Ceci est une réponse d'aperçu en français. "
        "Votre question a été reçue et la langue de l'API de chat est le français. "
        "En production, l'assistant du pasteur Don répondrait à partir des notes de sermon."
    ),
    "pt": (
        "Esta é uma resposta de prévia em português. "
        "Sua pergunta foi recebida e o idioma da API de chat é português. "
        "Em produção, o assistente do Pastor Don responderia a partir das anotações do sermão."
    ),
    "de": (
        "Dies ist eine lokale Vorschau-Antwort auf Deutsch. "
        "Ihre Frage wurde empfangen und die Chat-API-Sprache ist Deutsch. "
        "In der Produktion würde Pastor Dons Assistent hier aus Predigtnotizen antworten."
    ),
    "ko": (
        "이것은 한국어로 된 로컬 미리보기 응답입니다. "
        "질문이 접수되었고 채팅 API 언어는 한국어입니다. "
        "실제 환경에서는 Pastor Don의 어시스턴트가 설교 노트를 바탕으로 답변합니다."
    ),
    "zh": (
        "这是中文本地预览回复。"
        "已收到您的问题，聊天 API 语言设置为中文。"
        "在正式环境中，Pastor Don 的助手会根据讲道笔记在此作答。"
    ),
}


def normalize_language(raw) -> str:
    if raw is None:
        return "en"
    text = str(raw).strip().lower().replace("_", "-")
    if not text:
        return "en"
    short = text.split("-", 1)[0]
    return short if short in REPLY_BY_LANG else "en"


class Handler(BaseHTTPRequestHandler):
    server_version = "PastorAIPreview/1.0"

    def log_message(self, fmt, *args):
        print(f"[preview] {self.address_string()} - {fmt % args}")

    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        self._send(code, data, "application/json; charset=utf-8")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-API-Key, Accept")
        self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            body = {}

        if path in {"/api/chat/", "/chat/"}:
            lang = normalize_language(body.get("language") or body.get("locale"))
            query = (body.get("query") or "").strip()
            answer = REPLY_BY_LANG[lang]
            if query:
                answer = f"{answer}\n\n> {query}"
            self._json(
                200,
                {
                    "answer": answer,
                    "sources": SAMPLE_SOURCES,
                    "language": lang,
                },
            )
            return

        if path == "/api/translate/":
            lang = normalize_language(body.get("language") or body.get("locale"))
            texts = body.get("texts")
            if texts is None and body.get("text") is not None:
                texts = [body.get("text")]
            if not isinstance(texts, list):
                texts = []
            # Preview mock: swap to the canned reply for the target language when
            # the source looks like one of our preview replies; otherwise tag it.
            out = []
            for t in texts:
                src = str(t or "")
                matched = False
                for sample in REPLY_BY_LANG.values():
                    if sample in src or src in sample:
                        # Keep any trailing quoted user question after the canned body.
                        suffix = ""
                        if "\n\n>" in src:
                            suffix = src[src.index("\n\n>") :]
                        out.append(REPLY_BY_LANG[lang] + suffix)
                        matched = True
                        break
                if not matched:
                    out.append(REPLY_BY_LANG[lang] if not src.strip() else f"{REPLY_BY_LANG[lang]}\n\n> {src.strip()[:200]}")
            self._json(200, {"texts": out, "language": lang})
            return

        if path.startswith("/api/"):
            self._json(200, {"ok": True, "mock": True, "path": path})
            return

        self._json(404, {"error": "not found", "path": path})

    def do_GET(self):
        path = urlparse(self.path).path
        if path in {"/api/chat/", "/chat/"}:
            self.send_response(404)
            self.end_headers()
            return

        if path.startswith("/api/"):
            self._json(200, {"ok": True, "mock": True, "path": path})
            return

        rel = unquote(path.lstrip("/"))
        if not rel or rel.endswith("/"):
            rel = "index.html"
        candidate = (ROOT / rel).resolve()
        try:
            candidate.relative_to(ROOT)
        except ValueError:
            self._send(403, b"Forbidden", "text/plain")
            return

        if not candidate.is_file():
            # Flutter web SPA fallback
            candidate = ROOT / "index.html"
        if not candidate.is_file():
            self._send(404, b"Missing Flutter build. Run: flutter build web", "text/plain")
            return

        data = candidate.read_bytes()
        ctype = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        if candidate.suffix == ".js":
            ctype = "application/javascript"
        elif candidate.suffix == ".json":
            ctype = "application/json"
        self._send(200, data, ctype)


def main():
    if not (ROOT / "index.html").is_file():
        raise SystemExit(f"Flutter build not found at {ROOT}. Run: flutter build web")
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Serving multilingual preview at http://{HOST}:{PORT}/")
    print(f"Static root: {ROOT}")
    print("Mock chat: POST /api/chat/ with {query, language}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
