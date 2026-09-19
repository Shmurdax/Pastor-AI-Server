#!/usr/bin/env python3
"""Create grokbot1, run 3x10 topical sermon-note chats, and score RAG + context.

Same harness as eval_sermon_notes_chats.py, but the three threads are common
pastoral topics (prayer, marriage, stewardship) rather than Bible stories.

Run on the production CPU pod (needs Django, Qdrant, and gunicorn):

  export EVAL_EMAIL=grokbot1@gmail.com
  export EVAL_PASSWORD=testuser1
  /workspace/pastor-ai/venv/bin/python scripts/eval_sermon_topic_chats.py \\
      --base-url http://127.0.0.1:8000 \\
      --out /workspace/pastor-ai/logs/grokbot_topic_eval.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path

import requests

CHATS = [
    {
        "id": "prayer-life",
        "title": "Prayer sermon notes (a praying church)",
        "thread_terms": [
            "prayer",
            "pray",
            "intercession",
            "petition",
            "ask",
            "closet",
        ],
        "forbidden_drift": [
            "husband and wife",
            "malachi 3",
            "tithe and offering",
            "prodigal son",
            "jonah and nineveh",
        ],
        "queries": [
            "Help me create Christian sermon notes on prayer as a way of life for the local church. Give a sermon title, one-sentence big idea, and a three-point outline for preaching.",
            "Using that same prayer sermon outline, add congregational notes and a short illustration for point 1 that stays with private prayer and the secret place, not a different discipleship topic.",
            "For the big idea of these prayer notes, which NKJV verse should I preach as the anchor, and how does it serve a sermon on prayer rather than a different pastoral topic?",
            "Write a four-sentence sermon introduction for these prayer notes that names dry prayer lives without shaming people who feel like they do not know how to pray.",
            "Expand point 2 of the outline we already built into preacher notes on intercession for others, still as part of this prayer sermon.",
            "Add a gospel connection section to these same notes: how does prayer prepare a congregation to see Christ, without switching to a new sermon topic?",
            "Give five small-group discussion questions that follow the three points we already wrote for this prayer sermon, not a generic leadership talk.",
            "Draft a closing invitation and benediction that returns to the big idea and title we started with in this chat.",
            "How should I handle unanswered prayer inside this same sermon so it supports the outline instead of becoming a second sermon on suffering?",
            "Recap the full sermon notes we have built together in this chat as a one-page teaching manuscript: title, big idea, outline, illustration, gospel connection, and closing.",
        ],
    },
    {
        "id": "covenant-marriage",
        "title": "Marriage sermon notes (covenant love in the home)",
        "thread_terms": [
            "marriage",
            "husband",
            "wife",
            "covenant",
            "ephesians",
            "love",
        ],
        "forbidden_drift": [
            "prayer closet",
            "malachi 3",
            "tithe and offering",
            "prodigal son",
            "jonah and nineveh",
        ],
        "queries": [
            "Help me create Christian sermon notes on covenant marriage for a Sunday congregation. Give a title, big idea, and three-point preaching outline that includes husbands, wives, and Christlike love.",
            "Add notes under point 2 of that marriage outline on serving a spouse when feelings fade, not a dating-and-romance pep talk.",
            "Which NKJV verses should I print in the notes as the spine of this marriage sermon, and why those lines rather than a different family topic?",
            "Write an opening illustration for this marriage sermon that helps both married and single listeners stay inside a covenant-marriage message.",
            "Expand the Christ-and-the-church section of these notes: how do I preach Ephesians 5 without turning this into a different sermon on church government?",
            "Add a gospel connection that stays inside covenant marriage for this same sermon manuscript.",
            "Give a pastoral prayer I can pray after the notes on hard marriages, still closing this same sermon rather than starting a counseling series.",
            "Create a simple fill-in outline for listeners that matches the three points we already named in this chat.",
            "What should I cut from these marriage notes if I only have 25 minutes, without dropping the big idea we started with?",
            "Recap the complete marriage sermon notes from this conversation: title, big idea, outline, spouse-serving notes, gospel connection, and close.",
        ],
    },
    {
        "id": "stewardship-generosity",
        "title": "Stewardship sermon notes (generosity and treasure)",
        "thread_terms": [
            "steward",
            "generous",
            "giving",
            "tithe",
            "treasure",
            "money",
        ],
        "forbidden_drift": [
            "prayer closet",
            "husband love your wives",
            "prodigal son",
            "jonah and nineveh",
            "secret place of prayer",
        ],
        "queries": [
            "Help me create Christian sermon notes on biblical stewardship and generosity. Give a title, big idea, and a three-point outline a pastor could preach on a giving Sunday without making it a fundraising pitch.",
            "Add pastoral notes for preaching cheerful giving, keeping it inside this stewardship sermon rather than a prosperity message.",
            "Which NKJV verses should I have the congregation read aloud in this stewardship sermon, and why those lines?",
            "Write a contemporary application paragraph for laying up treasure in heaven that does not turn these notes into a personal-finance seminar.",
            "Expand the trust-in-God-not-money section of the outline we already have so anxious givers are addressed without abandoning stewardship.",
            "Add a Lord's-table or gospel invitation paragraph that uses Christ's generosity, still as part of these same sermon notes.",
            "Give three congregational testimonies or prayer prompts that map onto the three points of this stewardship sermon.",
            "Draft a children's-moment summary of these notes that still names giving and trusting God with what we have.",
            "How do I preach that God owns it all as the landing of the sermon we have been building, not a new topic on creation?",
            "Recap the full stewardship sermon notes from this chat: title, big idea, three points, applications, gospel invitation, and closing charge.",
        ],
    },
]


def _django_setup() -> None:
    app_dir = Path("/workspace/pastor-ai/backend/app")
    if app_dir.is_dir():
        sys.path.insert(0, str(app_dir))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pastor_ai.settings")
    import django

    django.setup()


def ensure_eval_user(email: str, password: str, name: str) -> None:
    from django.contrib.auth.models import User
    from django.utils import timezone

    from api.models import Profile
    from core.persist_db import dump_persistent_postgres

    user = User.objects.filter(username=email).first()
    if user is None:
        first, _, last = name.partition(" ")
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=first or "Grok",
            last_name=last or "Bot",
        )
        created = True
    else:
        user.set_password(password)
        user.email = email
        user.save()
        created = False
    profile = user.profile
    profile.email_verified = True
    profile.subscription_status = Profile.SubscriptionStatus.ACTIVE
    profile.billing_period = Profile.BillingPeriod.MONTHLY
    profile.cancel_at_period_end = False
    profile.current_period_end = timezone.now() + timedelta(days=365)
    profile.save()
    dump_persistent_postgres()
    print(
        json.dumps(
            {
                "setup": "ok",
                "created": created,
                "email": email,
                "premium": profile.has_premium_access,
                "period_end": profile.current_period_end.isoformat(),
            }
        ),
        flush=True,
    )


def login(base_url: str, email: str, password: str) -> str:
    res = requests.post(
        f"{base_url.rstrip('/')}/api/auth/login/",
        json={"email": email, "password": password},
        timeout=60,
    )
    res.raise_for_status()
    token = res.json()["token"]
    me = requests.get(
        f"{base_url.rstrip('/')}/api/auth/me/",
        headers={"Authorization": f"Token {token}"},
        timeout=30,
    )
    me.raise_for_status()
    print(json.dumps({"login": "ok", "user": me.json().get("user")}), flush=True)
    return token


def warmup(base_url: str, token: str) -> None:
    try:
        requests.post(
            f"{base_url.rstrip('/')}/api/chat/warmup/",
            headers={"Authorization": f"Token {token}"},
            json={},
            timeout=120,
        )
    except requests.RequestException as exc:
        print(json.dumps({"warmup": "error", "detail": str(exc)}), flush=True)


def chat_once(base_url: str, token: str, query: str, session_id: str) -> dict:
    payload = {
        "query": query,
        "session_id": session_id,
        "language": "en",
        "regenerate": False,
    }
    headers = {"Authorization": f"Token {token}", "Accept": "application/json"}
    url = f"{base_url.rstrip('/')}/api/chat/"
    res = requests.post(url, headers=headers, json=payload, timeout=480)
    if res.status_code == 429:
        time.sleep(8)
        res = requests.post(url, headers=headers, json=payload, timeout=480)
    res.raise_for_status()
    return res.json()


def retrieve_docs(query: str, prior_user: list[str], prior_ai: list[str]):
    from langchain_qdrant import QdrantVectorStore
    from qdrant_client import QdrantClient

    from core.chat_retrieval import (
        apply_retrieval_threshold,
        expand_search_queries,
        extract_used_quotes,
        extract_used_verse_refs,
        filter_hits_by_topic,
        is_video_chunk,
        retain_title_matches,
        search_queries_on_store,
        select_diverse_docs,
        topic_anchor_query,
    )
    from core.embeddings_utils import get_embeddings
    from core.grounding import lookup_nkjv_verses, verse_refs_for_lookup
    from core.qdrant_utils import (
        ensure_sermon_collection,
        get_collection_name,
        get_qdrant_url,
    )
    from core.views import (
        RETRIEVAL_BIBLE_RATIO,
        RETRIEVAL_CANDIDATE_MULTIPLIER,
        RETRIEVAL_K,
        RETRIEVAL_MAX_PER_BIBLE_BOOK,
        RETRIEVAL_MAX_PER_SOURCE,
        RETRIEVAL_THRESHOLD,
        RETRIEVAL_VIDEO_RATIO,
        _doc_source_name,
        _is_bible_source,
    )

    topic_query = topic_anchor_query(query, prior_user)
    search_queries = expand_search_queries(
        query, prior_user, prior_ai_texts=prior_ai, limit=7
    )
    client = QdrantClient(url=get_qdrant_url())
    collection_name = get_collection_name()
    ensure_sermon_collection(client, collection_name)
    vectorstore = QdrantVectorStore(
        client=client,
        collection_name=collection_name,
        embedding=get_embeddings(),
        content_payload_key="text",
        metadata_payload_key="metadata",
    )
    candidate_k = max(RETRIEVAL_K * RETRIEVAL_CANDIDATE_MULTIPLIER, 24)
    scored_hits = search_queries_on_store(
        vectorstore, search_queries, k_per_query=candidate_k
    )
    scored_hits = filter_hits_by_topic(
        scored_hits, topic_query, retrieval_k=RETRIEVAL_K
    )
    before_threshold = scored_hits
    scored_hits = apply_retrieval_threshold(
        scored_hits, threshold=RETRIEVAL_THRESHOLD, retrieval_k=RETRIEVAL_K
    )
    scored_hits = retain_title_matches(before_threshold, scored_hits, topic_query)
    used_quotes = extract_used_quotes(prior_ai)
    used_verses = extract_used_verse_refs(prior_ai)
    docs = select_diverse_docs(
        scored_hits,
        k=RETRIEVAL_K,
        bible_ratio=RETRIEVAL_BIBLE_RATIO,
        video_ratio=RETRIEVAL_VIDEO_RATIO,
        max_per_source=RETRIEVAL_MAX_PER_SOURCE,
        max_per_bible_book=RETRIEVAL_MAX_PER_BIBLE_BOOK,
        used_quotes=used_quotes,
        used_verses=used_verses,
        is_bible=lambda doc: _is_bible_source(_doc_source_name(doc)),
        is_video=is_video_chunk,
        source_key=lambda doc: (
            str((getattr(doc, "metadata", None) or {}).get("file_hash") or "")
            or _doc_source_name(doc)
        ),
        query=topic_query,
        pin_query=query,
    )
    refs = verse_refs_for_lookup(topic_query, docs)
    extra = lookup_nkjv_verses(
        client, collection_name, refs, retrieved_docs=docs
    )
    seen = {
        (getattr(doc, "page_content", None) or "")[:120]
        for doc in docs
        if _is_bible_source(_doc_source_name(doc))
    }
    for doc in extra:
        key = (getattr(doc, "page_content", None) or "")[:120]
        if key and key not in seen:
            docs.append(doc)
            seen.add(key)
    return docs, topic_query, search_queries


def rag_score(answer: str, docs) -> dict:
    from core.grounding import split_docs_for_grounding, verify_answer_grounding

    sermon, bible = split_docs_for_grounding(docs)
    report = verify_answer_grounding(answer, sermon_docs=sermon, nkjv_docs=bible)
    return {
        "ok": bool(report.ok),
        "invented_quotes": list(report.invented_quotes)[:8],
        "invented_scripture": list(report.invented_scripture)[:8],
        "missing_nkjv_refs": list(report.missing_nkjv_refs)[:8],
        "retrieved_doc_count": len(docs or []),
        "sermon_doc_count": len(sermon),
        "bible_doc_count": len(bible),
    }


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9\s']", " ", (text or "").lower())


def context_score(chat: dict, turn: int, answer: str, prior_answers: list[str]) -> dict:
    blob = _norm(answer)
    hits = [term for term in chat["thread_terms"] if term in blob]
    drift = [term for term in chat["forbidden_drift"] if term in blob]
    coverage = len(hits) / max(1, len(chat["thread_terms"]))
    recap_hits = []
    if turn == 10 and prior_answers:
        first = _norm(prior_answers[0])
        seeds = [w for w in first.split() if len(w) > 6][:12]
        recap_hits = [w for w in seeds if w in blob]
    return {
        "thread_term_hits": hits,
        "thread_coverage": round(coverage, 2),
        "drift_terms": drift,
        "stayed_on_topic": coverage >= 0.25 and not drift,
        "recap_seed_hits": recap_hits,
        "recap_seed_hit_count": len(recap_hits),
    }


def synopsis(answer: str) -> str:
    text = re.sub(r"\s+", " ", (answer or "")).strip()
    if len(text) <= 420:
        return text
    return text[:417].rsplit(" ", 1)[0] + "..."


def write_report(results: dict, report_path: Path) -> None:
    lines: list[str] = []
    for chat in results.get("chats") or []:
        lines.append(f"# {chat['title']}")
        lines.append(f"session `{chat['session_id']}`")
        lines.append(f"after 10: {chat.get('after_10')}")
        lines.append("")
        for turn in chat.get("turns") or []:
            rag = turn.get("rag") or {}
            ctx = turn.get("context") or {}
            rag_label = "PASS" if rag.get("ok") else "FAIL"
            flags = []
            if rag.get("invented_quotes"):
                flags.append(f"invented_quotes={len(rag['invented_quotes'])}")
            if rag.get("invented_scripture"):
                flags.append(f"invented_scripture={rag['invented_scripture']}")
            if rag.get("missing_nkjv_refs"):
                flags.append(f"missing_nkjv={rag['missing_nkjv_refs']}")
            if rag.get("error"):
                flags.append(f"error={rag['error']}")
            extra = f" ({'; '.join(flags)}; docs={rag.get('retrieved_doc_count')})"
            ctx_label = "PASS" if ctx.get("stayed_on_topic") else "FLAGGED"
            lines.append(f"## Turn {turn['turn']}")
            lines.append(f"**Query:** {turn['query']}")
            lines.append(f"**RAG:** {rag_label}{extra}")
            lines.append(
                "**Context:** "
                f"{ctx_label} coverage={ctx.get('thread_coverage')} "
                f"hits={ctx.get('thread_term_hits')} drift={ctx.get('drift_terms')} "
                f"recap_seeds={ctx.get('recap_seed_hit_count')}"
            )
            lines.append(f"**Synopsis:** {turn.get('synopsis')}")
            lines.append("")
    totals = results.get("totals") or {}
    lines.append("# Totals")
    lines.append(json.dumps(totals))
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")


def run_eval(base_url: str, token: str, out_path: Path) -> dict:
    warmup(base_url, token)
    results = {"chats": [], "totals": {}}
    rag_ok = 0
    ctx_ok = 0
    total = 0
    for chat in CHATS:
        session_id = str(uuid.uuid4())
        row = {
            "id": chat["id"],
            "title": chat["title"],
            "session_id": session_id,
            "turns": [],
        }
        prior_user: list[str] = []
        prior_ai: list[str] = []
        print(f"=== {chat['title']} session={session_id} ===", flush=True)
        for i, query in enumerate(chat["queries"], start=1):
            started = time.time()
            payload = chat_once(base_url, token, query, session_id)
            answer = str(payload.get("answer") or "")
            sources = payload.get("sources") or []
            elapsed = round(time.time() - started, 1)
            try:
                docs, topic_query, search_queries = retrieve_docs(
                    query, prior_user, prior_ai
                )
                rag = rag_score(answer, docs)
            except Exception as exc:
                topic_query = query
                search_queries = [query]
                rag = {
                    "ok": False,
                    "error": str(exc),
                    "invented_quotes": [],
                    "invented_scripture": [],
                    "missing_nkjv_refs": [],
                    "retrieved_doc_count": 0,
                    "sermon_doc_count": 0,
                    "bible_doc_count": 0,
                }
            ctx = context_score(chat, i, answer, prior_ai)
            total += 1
            rag_ok += int(bool(rag.get("ok")))
            ctx_ok += int(bool(ctx.get("stayed_on_topic")))
            turn = {
                "turn": i,
                "query": query,
                "elapsed_s": elapsed,
                "synopsis": synopsis(answer),
                "answer_chars": len(answer),
                "sources": sources[:8],
                "topic_query": topic_query,
                "search_queries": search_queries,
                "rag": rag,
                "context": ctx,
            }
            row["turns"].append(turn)
            prior_user.append(query)
            prior_ai.append(answer)
            print(
                json.dumps(
                    {
                        "chat": chat["id"],
                        "turn": i,
                        "elapsed_s": elapsed,
                        "rag_ok": rag.get("ok"),
                        "context_ok": ctx.get("stayed_on_topic"),
                        "synopsis": turn["synopsis"][:180],
                    }
                ),
                flush=True,
            )
            time.sleep(1.5)
        last = row["turns"][-1] if row["turns"] else {}
        row["after_10"] = {
            "rag_ok_count": sum(1 for t in row["turns"] if t["rag"].get("ok")),
            "context_ok_count": sum(
                1 for t in row["turns"] if t["context"].get("stayed_on_topic")
            ),
            "final_recap_on_topic": bool(
                last.get("context", {}).get("stayed_on_topic")
            ),
            "final_recap_seed_hits": last.get("context", {}).get("recap_seed_hit_count"),
        }
        results["chats"].append(row)
    results["totals"] = {
        "queries": total,
        "rag_ok": rag_ok,
        "rag_accuracy": round(rag_ok / max(1, total), 3),
        "context_ok": ctx_ok,
        "context_accuracy": round(ctx_ok / max(1, total), 3),
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    report_path = out_path.with_name(out_path.stem + "_report.md")
    write_report(results, report_path)
    print(
        json.dumps(
            {
                "wrote": str(out_path),
                "report": str(report_path),
                "totals": results["totals"],
            }
        ),
        flush=True,
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--email", default=os.environ.get("EVAL_EMAIL", "grokbot1@gmail.com")
    )
    parser.add_argument("--password", default=os.environ.get("EVAL_PASSWORD", ""))
    parser.add_argument("--name", default="Grok Bot")
    parser.add_argument("--skip-setup", action="store_true")
    parser.add_argument(
        "--out",
        default="/workspace/pastor-ai/logs/grokbot_topic_eval.json",
    )
    args = parser.parse_args()
    if not args.password:
        print("EVAL_PASSWORD / --password is required", file=sys.stderr)
        return 2
    _django_setup()
    if not args.skip_setup:
        ensure_eval_user(args.email, args.password, args.name)
    token = login(args.base_url, args.email, args.password)
    run_eval(args.base_url, token, Path(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
