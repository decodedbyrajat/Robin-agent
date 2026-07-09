"""Intent router for ROBIN.

Classifies user prompts via a small local LLM (mistral:7b-instruct on Ollama)
and decides whether to handle the prompt locally with devstral:24b or
delegate to the cloud reasoning model (Kimi-K2.6 via Azure).

Output contract is a frozen RouteDecision. The router never mutates inputs,
logs every decision to a JSONL file, and falls back to a deterministic
default when classification fails.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Literal, Optional

import httpx

logger = logging.getLogger(__name__)

Intent = Literal["code", "chat", "tool_use", "delegation"]
Complexity = Literal["low", "medium", "high"]
Route = Literal["deepseek", "kimi"]

VALID_INTENTS: Final[frozenset[str]] = frozenset(
    {"code", "chat", "tool_use", "delegation"}
)
VALID_COMPLEXITY: Final[frozenset[str]] = frozenset({"low", "medium", "high"})
VALID_ROUTES: Final[frozenset[str]] = frozenset({"deepseek", "kimi"})

DEFAULT_BASE_URL: Final[str] = "http://localhost:11434/v1"
DEFAULT_MODEL: Final[str] = "qwen3:1.7b"
DEFAULT_TIMEOUT_S: Final[float] = 8.0

SYSTEM_PROMPT: Final[str] = (
    "You are an intent classifier. Return ONLY a single-line JSON object. "
    'Schema:{"intent":"code|chat|tool_use|delegation",'
    '"complexity":"low|medium|high","route_to":"qwen3|kimi"}. '
    "tool_use=skill calls/calendar/reminders/cron/commands/execution; "
    "code=programming; chat=casual conversation; delegation=planning/synthesis/reasoning. "
    "tool_use → qwen3. code low/medium → qwen3. chat/delegation/code high → kimi. "
    "No prose, no markdown."
)


@dataclass(frozen=True)
class RouteDecision:
    """Immutable classification result."""

    intent: Intent
    complexity: Complexity
    route_to: Route
    latency_ms: int
    fallback: bool = False


def _fallback_decision(latency_ms: int) -> RouteDecision:
    return RouteDecision(
        intent="chat",
        complexity="medium",
        route_to="deepseek",
        latency_ms=latency_ms,
        fallback=True,
    )


def _parse(raw: str) -> Optional[RouteDecision]:
    """Parse a JSON object out of ``raw``. Returns None on any failure."""
    text = raw.strip()
    # Strip code fences if model added them despite instructions.
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    # Take only the first {...} block to be robust to trailing prose.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    intent = obj.get("intent")
    complexity = obj.get("complexity")
    route_to = obj.get("route_to")
    if (
        intent not in VALID_INTENTS
        or complexity not in VALID_COMPLEXITY
        or route_to not in VALID_ROUTES
    ):
        return None
    # Enforce the routing rule even if the model contradicts itself.
    # tool_use always → qwen3 (skill execution, cron, commands)
    # code low/medium → qwen3; code high → kimi
    # chat and delegation → kimi (reasoning, synthesis)
    if intent == "tool_use" or (intent == "code" and complexity != "high"):
        enforced_route: Route = "deepseek"
    else:
        enforced_route = "kimi"
    return RouteDecision(
        intent=intent,  # type: ignore[arg-type]
        complexity=complexity,  # type: ignore[arg-type]
        route_to=enforced_route,
        latency_ms=0,
    )


class IntentRouter:
    """Classify user prompts via mistral:7b-instruct on Ollama."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        log_path: Optional[str | Path] = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        keep_alive: Optional[str] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_s = timeout_s
        self._keep_alive = keep_alive
        self._client = client or httpx.Client(timeout=timeout_s)
        self._log_path: Optional[Path] = (
            Path(os.path.expandvars(str(log_path))) if log_path else None
        )

    def classify(self, prompt: str) -> RouteDecision:
        if not prompt or not prompt.strip():
            decision = _fallback_decision(latency_ms=0)
            self._log(prompt, decision)
            return decision

        start = time.perf_counter()
        raw = self._call(prompt, reinforce=False)
        decision = _parse(raw) if raw is not None else None

        if decision is None:
            raw_retry = self._call(prompt, reinforce=True)
            decision = _parse(raw_retry) if raw_retry is not None else None

        latency_ms = int((time.perf_counter() - start) * 1000)
        if decision is None:
            decision = _fallback_decision(latency_ms=latency_ms)
        else:
            decision = RouteDecision(
                intent=decision.intent,
                complexity=decision.complexity,
                route_to=decision.route_to,
                latency_ms=latency_ms,
                fallback=False,
            )
        self._log(prompt, decision)
        return decision

    def _call(self, prompt: str, *, reinforce: bool) -> Optional[str]:
        system = SYSTEM_PROMPT
        if reinforce:
            system += (
                "\n\nIMPORTANT: Your previous response was not valid JSON. "
                "Return ONLY a single-line JSON object matching the schema, "
                "with no prose, no markdown, no code fences."
            )
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 50,
            "stream": False,
        }
        if self._keep_alive:
            payload["keep_alive"] = self._keep_alive
        try:
            resp = self._client.post(
                f"{self._base_url}/chat/completions", json=payload
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            logger.warning("intent router call failed: %s", exc)
            return None

    def _log(self, prompt: str, decision: RouteDecision) -> None:
        if self._log_path is None:
            return
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": int(time.time()),
                "prompt_sha": hashlib.sha256(
                    prompt.encode("utf-8", errors="replace")
                ).hexdigest()[:12],
                "decision": asdict(decision),
            }
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
        except OSError as exc:
            logger.warning("intent router log write failed: %s", exc)

    def close(self) -> None:
        self._client.close()
