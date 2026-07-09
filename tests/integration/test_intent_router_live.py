"""Live integration test for the intent router.

Requires mistral:7b-instruct available on a local Ollama at
http://localhost:11434. Skipped automatically otherwise.

Asserts route_to (load-bearing field). intent/complexity vary by prompt
phrasing and are not strictly asserted — see router.jsonl for analysis.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agent.routing.intent_router import IntentRouter

OLLAMA_URL = "http://localhost:11434"
ROUTER_MODEL = "mistral:7b-instruct"


def _ollama_has_model() -> bool:
    try:
        resp = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=2.0)
        resp.raise_for_status()
        names = {m["name"] for m in resp.json().get("models", [])}
        return ROUTER_MODEL in names
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _ollama_has_model(),
    reason=f"requires {ROUTER_MODEL} on local Ollama",
)


CASES = [
    ("write a python function to dedupe a list", "devstral"),
    ("what's the weather like today", "devstral"),
    ("list files in ~/Downloads modified this week", "devstral"),
    (
        "design a fault-tolerant distributed scheduler with leader election "
        "and split-brain recovery, including failure detection, quorum, and "
        "lease renewal semantics",
        "kimi",
    ),
    (
        "summarize the last 6 months of my project notes and propose next "
        "quarter's roadmap with prioritized initiatives, risk analysis, "
        "and resource tradeoffs",
        "kimi",
    ),
]


def test_live_routing_five_prompts(tmp_path: Path):
    log_path = tmp_path / "router.jsonl"
    router = IntentRouter(
        base_url=f"{OLLAMA_URL}/v1",
        model=ROUTER_MODEL,
        log_path=log_path,
    )
    try:
        results = [(p, router.classify(p)) for p, _ in CASES]
    finally:
        router.close()

    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 5

    mismatches = []
    for (prompt, expected), (_, decision) in zip(CASES, results):
        if decision.route_to != expected:
            mismatches.append(
                {
                    "prompt": prompt[:60],
                    "expected": expected,
                    "got": decision.route_to,
                    "intent": decision.intent,
                    "complexity": decision.complexity,
                    "fallback": decision.fallback,
                }
            )

    print("\n=== router.jsonl ===")
    for line in lines:
        print(json.dumps(json.loads(line), indent=2))

    assert not mismatches, f"routing mismatches: {mismatches}"
