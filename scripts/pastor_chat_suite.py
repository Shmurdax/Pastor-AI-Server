#!/usr/bin/env python3
"""Send one multi-turn pastor chat as grokbot1@gmail.com and score it.

Run on christian-ai-test from the repo root:

  python scripts/pastor_chat_suite.py

The script posts every prompt to the running chat API with one session id,
then scores each reply against the sermon excerpts that request used.
Off the pod, set PASTOR_TEST_BASE_URL and PASTOR_TEST_TOKEN. No password
is stored in the repo.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from pastor_chat_score import grade_turn, load_cases, render_scorecard  # noqa: E402


ACCOUNT = "grokbot1@gmail.com"
CASES_PATH = Path(__file__).resolve().parent / "pastor_chat_cases.yaml"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
REPORT_PATH = Path(os.environ.get("PASTOR_CHAT_SUITE_OUT", "/tmp/pastor_chat_suite.json"))


def main() -> int:
    try:
        turns = load_cases(CASES_PATH)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    try:
        base_url, token, user = resolve_auth()
    except AuthError as exc:
        print(exc, file=sys.stderr)
        return 2

    session_id = f"ai-testing-{uuid.uuid4().hex[:16]}"
    previous_active = read_active_session(base_url, token)
    rows = []
    try:
        for turn in turns:
            rows.append(run_turn(base_url, token, session_id, turn))
    finally:
        restore_note = restore_active_session(base_url, token, user, previous_active)

    passed = sum(1 for row in rows if row["pass"])
    report = {
        "account": ACCOUNT,
        "base_url": base_url,
        "session_id": session_id,
        "previous_active_session_id": previous_active,
        "restored_active_session": restore_note,
        "passed": passed,
        "total": len(rows),
        "turns": rows,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(render_scorecard(report), end="")
    return 0 if passed == len(rows) else 1


class AuthError(RuntimeError):
    pass


def resolve_auth() -> tuple[str, str, object | None]:
    base_url = os.environ.get("PASTOR_TEST_BASE_URL", "").strip().rstrip("/")
    token = os.environ.get("PASTOR_TEST_TOKEN", "").strip()
    if base_url or token:
        if not base_url or not token:
            raise AuthError(
                "Set both PASTOR_TEST_BASE_URL and PASTOR_TEST_TOKEN, "
                "or unset both and run on christian-ai-test."
            )
        return base_url, token, None
    user, minted = django_token()
    return DEFAULT_BASE_URL, minted, user


def django_token():
    app_dir = ROOT / "backend" / "app"
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    os.chdir(app_dir)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pastor_ai.settings")
    try:
        from pastor_ai.workspace_env import load_workspace_env

        load_workspace_env()
    except Exception:
        pass
    try:
        import django
        from django.contrib.auth import get_user_model

        django.setup()
        User = get_user_model()
        user = User.objects.get(username=ACCOUNT)
    except User.DoesNotExist as exc:
        raise AuthError(f"{ACCOUNT} is not a user on this database.") from exc
    except Exception as exc:
        raise AuthError(
            "This checkout cannot reach the christian-ai-test chat. "
            "Run python scripts/pastor_chat_suite.py on that pod, or set "
            "PASTOR_TEST_BASE_URL and PASTOR_TEST_TOKEN. No replies were graded."
        ) from exc
    profile = getattr(user, "profile", None)
    if profile is None or not profile.has_premium_access:
        raise AuthError(f"{ACCOUNT} does not have premium access, so chat will reject the suite.")
    from rest_framework.authtoken.models import Token

    minted, _created = Token.objects.get_or_create(user=user)
    return user, minted.key


def run_turn(base_url: str, token: str, session_id: str, turn: dict) -> dict:
    try:
        status, payload = post_json(
            base_url,
            "/api/chat/",
            token,
            {
                "query": turn["query"],
                "session_id": session_id,
                "include_passages": True,
            },
        )
    except urllib.error.URLError as exc:
        return failed_row(turn, f"could not reach {base_url}: {exc.reason}")
    if status == 403:
        return failed_row(turn, "chat returned 403. The account needs premium access.")
    if status != 200 or not isinstance(payload, dict):
        detail = payload if isinstance(payload, dict) else {}
        return failed_row(turn, f"chat returned {status}: {detail.get('error') or detail}")
    answer = str(payload.get("answer") or "")
    pipeline = str(payload.get("pipeline") or "")
    passages = payload.get("passages") if isinstance(payload.get("passages"), list) else []
    graded = grade_turn(turn, answer, pipeline, passages)
    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    return {
        "id": turn["id"],
        "anaphoric": bool(turn.get("anaphoric")),
        "query": turn["query"],
        "pipeline": pipeline,
        "sources": sources,
        "passage_titles": [
            str(item.get("title") or "")
            for item in passages
            if isinstance(item, dict)
        ],
        "answer": answer,
        "pass": graded["pass"],
        "reasons": graded["reasons"],
        "accuracy": graded["accuracy"],
        "unsupported_sentences": graded["unsupported_sentences"],
        "missing_scripture": graded["missing_scripture"],
    }


def failed_row(turn: dict, reason: str) -> dict:
    return {
        "id": turn["id"],
        "anaphoric": bool(turn.get("anaphoric")),
        "query": turn["query"],
        "pipeline": "",
        "sources": [],
        "passage_titles": [],
        "answer": "",
        "pass": False,
        "reasons": [reason],
        "accuracy": 0,
        "unsupported_sentences": [],
        "missing_scripture": [],
    }


def read_active_session(base_url: str, token: str) -> str:
    try:
        status, payload = request_json(base_url, "/api/chat/history/", token, method="GET")
    except urllib.error.URLError:
        return ""
    if status != 200 or not isinstance(payload, dict):
        return ""
    return str(payload.get("active_session_id") or "")


def restore_active_session(base_url: str, token: str, user, previous_active: str) -> str:
    if user is not None:
        try:
            from core.models import UserChatHistory

            row = UserChatHistory.objects.filter(user=user).first()
            if row is None:
                return "no history row"
            row.active_session_id = previous_active or ""
            row.save(update_fields=["active_session_id", "updated_at"])
            return previous_active or ""
        except Exception as exc:
            return f"could not restore: {exc}"
    try:
        status, payload = request_json(base_url, "/api/chat/history/", token, method="GET")
        if status != 200 or not isinstance(payload, dict):
            return f"history GET returned {status}"
        if not previous_active:
            return "left the test chat active; the history API cannot clear an empty previous session"
        put_status, _put_payload = request_json(
            base_url,
            "/api/chat/history/",
            token,
            method="PUT",
            body={
                "entries": payload.get("entries") or [],
                "active_session_id": previous_active,
                "schema_version": payload.get("schema_version") or 1,
                "deleted_session_ids": [],
            },
        )
        if put_status != 200:
            return f"history PUT returned {put_status}"
        return previous_active
    except urllib.error.URLError as exc:
        return f"could not restore: {exc.reason}"


def post_json(base_url: str, path: str, token: str, body: dict) -> tuple[int, object]:
    return request_json(base_url, path, token, method="POST", body=body)


def request_json(
    base_url: str,
    path: str,
    token: str,
    *,
    method: str,
    body: dict | None = None,
) -> tuple[int, object]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        base_url + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Token {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        payload = {"error": raw[:500]}
    return status, payload


if __name__ == "__main__":
    sys.exit(main())
