#!/usr/bin/env python3
"""Compare CHAT_HYDE off vs on for hard retrieval questions.

Run on the christian-ai-test pod from backend/app with Django env loaded:

  cd /workspace/pastor-ai/backend/app
  source /workspace/pastor-ai/venv/bin/activate
  python /workspace/pastor-ai/scripts/hyde_live_suite.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


CASES = [
    {
        "id": "trinity",
        "query": "What is the Trinity?",
        "expect_any_title": [
            "Why Receive the Holy Spirit",
            "Nextsteps 101",
            "An Update Is Available",
            "Ten Strategies for Dealing with Difficulty",
            "Works, Hope, Faith & Patience",
        ],
        "expect_any_word": ["trinity", "triune", "godhead", "father", "spirit"],
    },
    {
        "id": "holy_spirit_person",
        "query": "Is the Holy Spirit a person of God?",
        "expect_any_title": [
            "Why Receive the Holy Spirit",
            "Symbols of the Holy Spirit",
            "Traits of the Spirit Filled Life",
            "Fruit of the Spirit",
        ],
        "expect_any_word": ["spirit", "person", "trinity", "father"],
    },
    {
        "id": "godhead",
        "query": "Explain the Godhead from the sermon notes.",
        "expect_any_title": [
            "Why Receive the Holy Spirit",
            "Nextsteps 101",
            "The Giver and His Gifts Full",
        ],
        "expect_any_word": ["godhead", "trinity", "father", "spirit", "son"],
    },
    {
        "id": "repentance",
        "query": "What does Pastor Don teach about repentance?",
        "expect_any_title": [
            "Nextsteps 101",
            "Let a Man Examine Himself",
            "Discipleship 101",
            "It Is Time for the Cross",
            "It Is Time for Renewal",
        ],
        "expect_any_word": ["repent", "sin", "turn", "confess"],
    },
    {
        "id": "baptism",
        "query": "What do the notes say about water baptism?",
        "expect_any_title": [
            "Nextsteps 101",
            "Discipleship 101",
            "Why Receive the Holy Spirit",
        ],
        "expect_any_word": ["baptism", "baptize", "water", "immerse"],
    },
    {
        "id": "faith_works",
        "query": "How do faith and works fit together?",
        "expect_any_title": [
            "Works, Hope, Faith & Patience",
            "Faith Lift",
            "Body Soul Spirit Saving Grace Devo",
            "Know Your Why",
            "Facing the Giants of Life",
            "Kings and Priests Full",
            "It Is Time for the Cross",
        ],
        "expect_any_word": ["faith", "works", "hope", "patience", "justify", "sanctif"],
    },
]


def _contains_any(haystack: str, needles: list[str]) -> bool:
    lowered = haystack.lower()
    return any(needle.lower() in lowered for needle in needles)


def _run_case(case: dict, *, hyde_on: bool) -> dict:
    os.environ["CHAT_HYDE"] = "1" if hyde_on else "0"
    # Import after env so hyde_enabled reads the toggle.
    from core.basic_chat import retrieve_passages

    result = retrieve_passages(case["query"], include_debug=True)
    titles = [item["title"] for item in result["passages"]]
    blob = "\n".join(f"{item['title']}\n{item['text']}" for item in result["passages"])
    title_hit = _contains_any("\n".join(titles), case["expect_any_title"])
    word_hit = _contains_any(blob, case["expect_any_word"])
    hyde_words = _contains_any(result.get("hyde_text") or "", case["expect_any_word"])
    return {
        "id": case["id"],
        "query": case["query"],
        "hyde_on": hyde_on,
        "hyde_text": result.get("hyde_text") or "",
        "query_titles": result.get("query_titles") or [],
        "hyde_titles": result.get("hyde_titles") or [],
        "merged_titles": titles,
        "title_hit": title_hit,
        "word_hit": word_hit,
        "hyde_text_relevant": (not hyde_on) or hyde_words or not (result.get("hyde_text") or ""),
        "pass": title_hit and word_hit and ((not hyde_on) or bool(result.get("hyde_text"))),
    }


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

    rows = []
    for case in CASES:
        off = _run_case(case, hyde_on=False)
        on = _run_case(case, hyde_on=True)
        improved = on["title_hit"] and (
            (not off["title_hit"])
            or any(
                title in on["merged_titles"] and title not in off["merged_titles"]
                for title in case["expect_any_title"]
            )
            or on["merged_titles"][:1] != off["merged_titles"][:1]
        )
        rows.append(
            {
                "id": case["id"],
                "query": case["query"],
                "off": off,
                "on": on,
                "improved_or_held": improved or (on["pass"] and off["pass"]),
            }
        )

    out = {
        "cases": rows,
        "passed": sum(1 for row in rows if row["on"]["pass"]),
        "total": len(rows),
        "hyde_generated": sum(1 for row in rows if row["on"]["hyde_text"]),
    }
    path = Path(os.environ.get("HYDE_LIVE_OUT", "/tmp/hyde_live_suite.json"))
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"passed": out["passed"], "total": out["total"], "out": str(path)}, indent=2))
    for row in rows:
        mark = "PASS" if row["on"]["pass"] else "FAIL"
        print(
            f"{mark} {row['id']}: hyde_titles={row['on']['hyde_titles'][:3]} "
            f"merged={row['on']['merged_titles'][:3]}"
        )
        if row["on"]["hyde_text"]:
            print(f"  hyde: {row['on']['hyde_text'][:160]}...")
    return 0 if out["passed"] == out["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
