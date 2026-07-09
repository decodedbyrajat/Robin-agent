"""Tests for the Nous-Robin-3/4 non-agentic warning detector.

Prior to this check, the warning fired on any model whose name contained
``"robin"`` anywhere (case-insensitive). That false-positived on unrelated
local Modelfiles such as ``robin-brain:qwen3-14b-ctx16k`` — a tool-capable
Qwen3 wrapper that happens to live under the "robin" tag namespace.

``is_nous_robin_non_agentic`` should only match the actual
Robin-3 / Robin-4 chat family.
"""

from __future__ import annotations

import pytest

from robin_cli.model_switch import (
    _ROBIN_MODEL_WARNING,
    _check_robin_model_warning,
    is_nous_robin_non_agentic,
)


@pytest.mark.parametrize(
    "model_name",
    [
        "NousResearch/Robin-3-Llama-3.1-70B",
        "NousResearch/Robin-3-Llama-3.1-405B",
        "robin-3",
        "Robin-3",
        "robin-4",
        "robin-4-405b",
        "robin_4_70b",
        "openrouter/robin3:70b",
        "openrouter/nousresearch/robin-4-405b",
        "NousResearch/Robin3",
        "robin-3.1",
    ],
)
def test_matches_real_nous_robin_chat_models(model_name: str) -> None:
    assert is_nous_robin_non_agentic(model_name), (
        f"expected {model_name!r} to be flagged as Nous Robin 3/4"
    )
    assert _check_robin_model_warning(model_name) == _ROBIN_MODEL_WARNING


@pytest.mark.parametrize(
    "model_name",
    [
        # Kyle's local Modelfile — qwen3:14b under a custom tag
        "robin-brain:qwen3-14b-ctx16k",
        "robin-brain:qwen3-14b-ctx32k",
        "robin-honcho:qwen3-8b-ctx8k",
        # Plain unrelated models
        "qwen3:14b",
        "qwen3-coder:30b",
        "qwen2.5:14b",
        "claude-opus-4-6",
        "anthropic/claude-sonnet-4.5",
        "gpt-5",
        "openai/gpt-4o",
        "google/gemini-2.5-flash",
        "deepseek-chat",
        # Non-chat Robin models we don't warn about
        "robin-llm-2",
        "robin2-pro",
        "nous-robin-2-mistral",
        # Edge cases
        "",
        "robin",  # bare "robin" isn't the 3/4 family
        "robin-brain",
        "brain-robin-3-impostor",  # "3" not preceded by /: boundary
    ],
)
def test_does_not_match_unrelated_models(model_name: str) -> None:
    assert not is_nous_robin_non_agentic(model_name), (
        f"expected {model_name!r} NOT to be flagged as Nous Robin 3/4"
    )
    assert _check_robin_model_warning(model_name) == ""


def test_none_like_inputs_are_safe() -> None:
    assert is_nous_robin_non_agentic("") is False
    # Defensive: the helper shouldn't crash on None-ish falsy input either.
    assert _check_robin_model_warning("") == ""
