#!/usr/bin/env python3
"""Check one-box study/sermon routing, including the live classifier.

Run on christian-ai-test from the repo root:

  cd /workspace/pastor-ai/backend/app
  source /workspace/pastor-ai/venv/bin/activate
  python /workspace/pastor-ai/scripts/study_draft_route_suite.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


# expect is the pipeline a pastor should get. "unsure" cases still have a
# preferred pipeline; the classifier is what decides them.
CASES = [
    {"id": "trinity_q", "query": "What is the Trinity?", "expect": "pastoral_chat"},
    {
        "id": "explain_notes",
        "query": "Explain the Trinity from the notes.",
        "expect": "pastoral_chat",
    },
    {
        "id": "godhead_notes",
        "query": "Explain the Godhead from the sermon notes.",
        "expect": "pastoral_chat",
    },
    {
        "id": "pastor_repentance",
        "query": "What does Pastor Don teach about repentance?",
        "expect": "pastoral_chat",
    },
    {
        "id": "sermons_mention",
        "query": "Do the sermons talk about the Trinity?",
        "expect": "pastoral_chat",
    },
    {"id": "tell_love", "query": "Tell me about love", "expect": "pastoral_chat"},
    {
        "id": "presentation",
        "query": "make a presentation about love",
        "expect": "pastoral_chat",
    },
    {
        "id": "talk_grace",
        "query": "talk about grace for a minute",
        "expect": "pastoral_chat",
    },
    {
        "id": "what_is_study",
        "query": "What is a Bible study?",
        "expect": "pastoral_chat",
    },
    {
        "id": "write_study",
        "query": "Write an in-depth Bible study on repentance",
        "expect": "study_sermon_draft",
    },
    {
        "id": "sermon_notes",
        "query": "Please draft sermon notes for Sunday on baptism",
        "expect": "study_sermon_draft",
    },
    {
        "id": "three_point",
        "query": "Give me a 3 point sermon on faith",
        "expect": "study_sermon_draft",
    },
    {
        "id": "sunday_notes",
        "query": "I need notes for Sunday on the Holy Spirit",
        "expect": "study_sermon_draft",
    },
    {
        "id": "put_together",
        "query": "Can you put together a lesson on James 2?",
        "expect": "study_sermon_draft",
    },
    {
        "id": "stand_up",
        "query": "I need something I can stand up and teach Wednesday on forgiveness",
        "expect": "study_sermon_draft",
    },
    {
        "id": "prep_wednesday",
        "query": "Help me prep Wednesday's message on baptism",
        "expect": "study_sermon_draft",
    },
    {
        "id": "labeled",
        "query": (
            "Living water\n"
            "Subtitle: Thirst and the gift of God\n"
            "Primary Biblical Texts: John 4:14\n"
            "Supporting Biblical Texts: Isaiah 55:1"
        ),
        "expect": "study_sermon_draft",
    },
    {
        "id": "small_group",
        "query": "Build me something for small group about prayer",
        "expect": "study_sermon_draft",
    },
    {
        "id": "outlines_topic",
        "query": "Tell me about sermon outlines in general",
        "expect": "pastoral_chat",
    },
]


def main() -> int:
    app_dir = Path(__file__).resolve().parents[1] / "backend" / "app"
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    os.chdir(app_dir)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pastor_ai.settings")
    try:
        from pastor_ai.workspace_env import load_workspace_env

        load_workspace_env()
    except Exception:
        pass
    import django

    django.setup()
    from core.basic_chat import resolve_chat_route

    rows = []
    for case in CASES:
        route = resolve_chat_route(case["query"])
        rows.append(
            {
                "id": case["id"],
                "expect": case["expect"],
                "pipeline": route.pipeline,
                "source": route.source,
                "confidence": round(route.confidence, 2),
                "format": route.format,
                "topic": route.topic,
                "reason": route.reason,
                "pass": route.pipeline == case["expect"],
            }
        )
    passed = sum(1 for row in rows if row["pass"])
    out = {"passed": passed, "total": len(rows), "cases": rows}
    path = Path(os.environ.get("DRAFT_ROUTE_OUT", "/tmp/study_draft_route_suite.json"))
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"passed": passed, "total": len(rows), "out": str(path)}, indent=2))
    for row in rows:
        mark = "PASS" if row["pass"] else "FAIL"
        print(
            f"{mark} {row['id']}: got={row['pipeline']} expect={row['expect']} "
            f"source={row['source']} conf={row['confidence']} reason={row['reason']}"
        )
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
