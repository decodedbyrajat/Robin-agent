"""Unit tests for agent.routing.intent_router.

Live-model classification is in tests/integration/test_intent_router_live.py
(skipped unless mistral:7b-instruct is available on a local Ollama).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent.routing.intent_router import (
    IntentRouter,
    RouteDecision,
    _parse,
)


def _make_response(content: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}]
    }


class _FakeTransport(httpx.BaseTransport):
    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(json.loads(request.content.decode()))
        if not self._responses:
            return httpx.Response(500, json={"error": "no more responses"})
        body = self._responses.pop(0)
        return httpx.Response(200, json=_make_response(body))


def _router_with(transport: _FakeTransport, log_path: Path) -> IntentRouter:
    client = httpx.Client(transport=transport, base_url="http://x")
    return IntentRouter(
        base_url="http://x",
        log_path=log_path,
        client=client,
    )


# ── _parse ────────────────────────────────────────────────────────────


def test_parse_valid_low_complexity_routes_devstral():
    raw = '{"intent":"chat","complexity":"low","route_to":"devstral"}'
    decision = _parse(raw)
    assert decision is not None
    assert decision.intent == "chat"
    assert decision.complexity == "low"
    assert decision.route_to == "devstral"


def test_parse_high_complexity_forces_kimi_route_even_if_model_says_devstral():
    raw = '{"intent":"delegation","complexity":"high","route_to":"devstral"}'
    decision = _parse(raw)
    assert decision is not None
    assert decision.route_to == "kimi"


def test_parse_strips_code_fences():
    raw = '```json\n{"intent":"code","complexity":"medium","route_to":"devstral"}\n```'
    decision = _parse(raw)
    assert decision is not None
    assert decision.intent == "code"


def test_parse_extracts_first_json_object_from_prose():
    raw = 'Sure! {"intent":"tool_use","complexity":"low","route_to":"devstral"} done.'
    decision = _parse(raw)
    assert decision is not None
    assert decision.intent == "tool_use"


def test_parse_invalid_json_returns_none():
    assert _parse("not json at all") is None


def test_parse_unknown_intent_returns_none():
    raw = '{"intent":"banana","complexity":"low","route_to":"devstral"}'
    assert _parse(raw) is None


# ── IntentRouter.classify ──────────────────────────────────────────────


def test_classify_writes_log_entry(tmp_path: Path):
    log_path = tmp_path / "router.jsonl"
    transport = _FakeTransport(
        ['{"intent":"chat","complexity":"low","route_to":"devstral"}']
    )
    router = _router_with(transport, log_path)

    decision = router.classify("hello there")

    assert decision.route_to == "devstral"
    assert decision.fallback is False
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["decision"]["route_to"] == "devstral"
    assert len(entry["prompt_sha"]) == 12


def test_classify_retries_once_on_bad_json_then_succeeds(tmp_path: Path):
    log_path = tmp_path / "router.jsonl"
    transport = _FakeTransport(
        [
            "I think this is a chat prompt.",  # invalid first response
            '{"intent":"chat","complexity":"low","route_to":"devstral"}',
        ]
    )
    router = _router_with(transport, log_path)

    decision = router.classify("hi")

    assert decision.route_to == "devstral"
    assert decision.fallback is False
    assert len(transport.calls) == 2
    # second call must contain the reinforcement clause
    second_system = transport.calls[1]["messages"][0]["content"]
    assert "ONLY a single-line JSON object" in second_system


def test_classify_falls_back_after_two_bad_responses(tmp_path: Path):
    log_path = tmp_path / "router.jsonl"
    transport = _FakeTransport(["nope", "still nope"])
    router = _router_with(transport, log_path)

    decision = router.classify("anything")

    assert decision.fallback is True
    assert decision.route_to == "devstral"
    assert decision.intent == "chat"
    assert decision.complexity == "medium"


def test_classify_empty_prompt_short_circuits_to_fallback(tmp_path: Path):
    log_path = tmp_path / "router.jsonl"
    transport = _FakeTransport([])
    router = _router_with(transport, log_path)

    decision = router.classify("   ")

    assert decision.fallback is True
    assert transport.calls == []


def test_route_decision_is_frozen():
    d = RouteDecision(
        intent="chat",
        complexity="low",
        route_to="devstral",
        latency_ms=10,
    )
    with pytest.raises(Exception):
        d.intent = "code"  # type: ignore[misc]
