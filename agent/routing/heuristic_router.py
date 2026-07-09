"""Heuristic router for ROBIN.

Routes user prompts to kimi (reasoning) or qwen3 (execution) using
regex pattern matching — zero latency, no LLM classifier required.

Priority order:
  1. Robin domain keywords (execution)      → qwen3
  2. Question/reasoning start words         → kimi
  3. Action verb at start + short message   → qwen3
  4. Synthesis/analysis verbs               → kimi
  5. Default                                → kimi

Note: Domain/action checks are intentionally evaluated BEFORE the synthesis
scan so that injected memory/RAG context (which may contain words like
'review', 'recommend', 'suggest') does not false-route execution commands
to Kimi. An explicit 'reminder'/'calendar'/'add' signal is always stronger.
"""

from __future__ import annotations

import re
import time
from typing import Final

from agent.routing.intent_router import RouteDecision

# ── Memory/RAG preamble strippers ─────────────────────────────────────────────
# Robin injects Obsidian RAG context and memory blobs into the user message
# before sending to the API. These blocks contain words like 'review',
# 'recommend', 'suggest' that would otherwise false-trigger _KIMI_SYNTHESIS.
# Strip them before routing so only the actual user intent is classified.

_MEMORY_BLOCK_RE: Final = re.compile(
    r"(\[MEMORY[^\]]*\].*?\[/MEMORY[^\]]*\]"   # [MEMORY]...[/MEMORY]
    r"|\[MEMORY[^\]]*\].*?\[END MEMORY\]"        # [MEMORY]...[END MEMORY]
    r"|\[RAG[^\]]*\].*?\[/RAG[^\]]*\]"          # [RAG_CONTEXT]...[/RAG_CONTEXT]
    r"|<[a-z0-9-]*context>.*?</[a-z0-9-]*context>" # <context>... or <memory-context>...
    r"|\[CONTEXT SUMMARY\].*?(?=\n\n|\Z)"        # [CONTEXT SUMMARY]...
    r"|## (Memory|Context|Background)[^\n]*\n.*?(?=\n##|\Z)"  # ## Memory sections
    r")",
    re.DOTALL | re.IGNORECASE,
)

_MEMORY_HEADER_RE: Final = re.compile(
    r"^\s*(\[MEMORY[^\]]*\]|\[RAG[^\]]*\]|<[a-z0-9-]*context>|---+\s*memory\s*---+)",
    re.IGNORECASE | re.MULTILINE,
)


def _strip_injected_context(text: str) -> str:
    """Remove memory/RAG preamble injected by Robin before the user's actual message.

    When the Obsidian RAG or memory provider prepends context to the user
    message, words like 'review', 'recommend', 'suggest' inside that context
    can falsely trigger _KIMI_SYNTHESIS routing.  We strip known preamble
    markers and fall back to taking only the last paragraph if a header is
    detected but the block boundary is ambiguous.
    """
    cleaned = _MEMORY_BLOCK_RE.sub("", text).strip()

    # Fallback: if the cleaned text still starts with a known header marker,
    # take everything after the last blank-line break (the actual user turn).
    if _MEMORY_HEADER_RE.match(cleaned):
        parts = re.split(r"\n{2,}", cleaned)
        cleaned = parts[-1].strip() if parts else cleaned

    return cleaned or text  # never return empty string


# ── Kimi patterns (reasoning, synthesis, planning) ────────────────────────────

_KIMI_QUESTION_START: Final = re.compile(
    r"^(what\b|why\b|how\b|should\b|would\b|could\b|is\s+it\b|are\s+(there|you)\b"
    r"|do\s+you\s+(think|know)\b"
    r"|explain\b|help\s+me\s+(understand|think|decide|plan|figure)\b"
    r"|tell\s+me\s+(about|why|how|what)\b"
    r"|can\s+you\s+(explain|help|think|suggest|recommend|advise)\b"
    r"|thoughts?\s+on\b|opinion\s+on\b)",
    re.IGNORECASE,
)

_KIMI_SYNTHESIS: Final = re.compile(
    r"\b(summarize|summarise|analyze|analyse|prioritize|prioritise"
    r"|compare|evaluate|assess|recommend|suggest|advise|advice"
    r"|draft\s+a\b|write\s+(a\s+)?(message|reply|email|response|letter|report)"
    r"|plan\s+for\b|strategy\b|review\b|decide\b|reflect\b"
    r"|help\s+me\s+(prioritize|decide|plan|think|understand|figure)"
    r"|thoughts?\s+on\b|what\s+should\s+i\b)\b",
    re.IGNORECASE,
)

# ── Qwen3 patterns (execution, skill invocation) ──────────────────────────────

# Robin skill domains — any of these strongly imply tool execution
_QWEN_DOMAIN: Final = re.compile(
    r"\b(calendar|reminder|reminders|appointment|appointments"
    r"|cron(\s+job)?|cron_job|scheduled?\s+(a\s+)?(job|task|run)"
    r"|event\b|meeting\b"
    r"|gmail|inbox|email\s+(me|send|check|list|read|forward)"
    r"|note\b|notes\b|obsidian"
    r"|skill\b|skills\b|alarm\b)\b",
    re.IGNORECASE,
)

# Action verbs at the start of a message
_QWEN_ACTION_START: Final = re.compile(
    r"^(add\b|create\b|set\b|make\b|schedule\b|book\b|cancel\b|delete\b|remove\b"
    r"|send\b|forward\b|run\b|execute\b|mark\b|move\b|enable\b|disable\b"
    r"|update\b|edit\b|change\b|list\s+my\b|show\s+my\b|check\s+my\b"
    r"|get\s+my\b|fetch\b|read\s+my\b|open\b|close\b)\b",
    re.IGNORECASE,
)

_SHORT_COMMAND_MAX_CHARS: Final[int] = 140


def _decision(intent: str, complexity: str, route: str, latency_ms: int = 0) -> RouteDecision:
    return RouteDecision(
        intent=intent,  # type: ignore[arg-type]
        complexity=complexity,  # type: ignore[arg-type]
        route_to=route,  # type: ignore[arg-type]
        latency_ms=latency_ms,
        fallback=False,
    )


class HeuristicRouter:
    """Pattern-based router — no LLM calls, deterministic, ~0ms latency."""

    def classify(self, prompt: str) -> RouteDecision:
        start = time.perf_counter()
        # Strip injected memory/RAG preamble so context words don't pollute routing
        text = _strip_injected_context(prompt.strip())
        route = self._route(text)
        latency_ms = int((time.perf_counter() - start) * 1000)
        return RouteDecision(
            intent=route.intent,
            complexity=route.complexity,
            route_to=route.route_to,
            latency_ms=latency_ms,
            fallback=False,
        )

    def _route(self, text: str) -> RouteDecision:
        # 1. Robin domain keyword → qwen3 (execution)
        #    Checked first: a strong domain signal ('reminder'/'calendar') means
        #    a tool call is almost certainly needed, even if phrased as a question.
        if _QWEN_DOMAIN.search(text):
            return _decision("tool_use", "low", "deepseek")

        # 2. Question / reasoning start → kimi
        if _KIMI_QUESTION_START.match(text):
            return _decision("chat", "high", "kimi")

        # 3. Action verb at start + short concrete command → qwen3
        if _QWEN_ACTION_START.match(text) and len(text) <= _SHORT_COMMAND_MAX_CHARS:
            return _decision("tool_use", "low", "deepseek")

        # 4. Synthesis verb anywhere → kimi
        if _KIMI_SYNTHESIS.search(text):
            return _decision("delegation", "high", "kimi")

        # 5. Default: send to kimi for reasoning
        return _decision("chat", "medium", "kimi")
