"""Regression test — duplicate user messages after failed-turn persistence.

When a turn fails with a non-retryable API error, run_conversation persists
the session with the user message appended but no assistant reply. The
gateway creates a fresh AIAgent per message, so the retry loads that history
and appended the same user message again — each failed attempt added one
more copy ("hey", "hey", "hey" observed in real session dumps).

run_conversation now collapses the trailing run of identical dangling user
messages before appending, so retries reuse the dangling tail instead of
duplicating it.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def _make_agent():
    """Create a minimal AIAgent with a mocked client (test_1630 pattern)."""
    with (
        patch("run_agent.get_tool_definitions", return_value=[]),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("run_agent.OpenAI"),
    ):
        from run_agent import AIAgent
        a = AIAgent(
            api_key="test-key-12345",
            base_url="https://openrouter.ai/api/v1",
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )
    a.client = MagicMock()
    a._cached_system_prompt = "You are helpful."
    a._use_prompt_caching = False
    a.tool_delay = 0
    a.compression_enabled = False
    return a


def _mock_completion(text="Hello!"):
    msg = MagicMock()
    msg.content = text
    msg.tool_calls = None
    msg.reasoning_content = None
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    completion = MagicMock()
    completion.choices = [choice]
    completion.usage = MagicMock(
        prompt_tokens=10, completion_tokens=5, total_tokens=15
    )
    return completion


def _user_messages(messages, content):
    return [
        m for m in messages
        if m.get("role") == "user" and m.get("content") == content
    ]


class TestDanglingUserMessageDedupe:
    def test_retry_reuses_dangling_user_message(self):
        """History ending with the same dangling user message (no assistant
        reply) must not get a second copy appended."""
        agent = _make_agent()
        agent.client.chat.completions.create.return_value = _mock_completion()

        history = [{"role": "user", "content": "hey"}]
        result = agent.run_conversation("hey", conversation_history=history)

        assert len(_user_messages(result["messages"], "hey")) == 1

    def test_damaged_history_with_multiple_copies_heals(self):
        """Sessions already damaged by earlier failed attempts collapse to
        a single copy of the dangling user message."""
        agent = _make_agent()
        agent.client.chat.completions.create.return_value = _mock_completion()

        history = [
            {"role": "user", "content": "hey"},
            {"role": "user", "content": "hey"},
        ]
        result = agent.run_conversation("hey", conversation_history=history)

        assert len(_user_messages(result["messages"], "hey")) == 1

    def test_genuine_repeat_after_assistant_reply_is_kept(self):
        """A real repeated message (assistant reply in between) must NOT be
        deduplicated."""
        agent = _make_agent()
        agent.client.chat.completions.create.return_value = _mock_completion()

        history = [
            {"role": "user", "content": "yes"},
            {"role": "assistant", "content": "Are you sure?"},
        ]
        result = agent.run_conversation("yes", conversation_history=history)

        # Original history copy plus the new turn = 2 total "yes" user turns
        assert len(_user_messages(result["messages"], "yes")) == 2

    def test_different_new_message_appends_normally(self):
        """A dangling user message followed by a DIFFERENT new message keeps
        both (no false-positive dedupe)."""
        agent = _make_agent()
        agent.client.chat.completions.create.return_value = _mock_completion()

        history = [{"role": "user", "content": "hey"}]
        result = agent.run_conversation(
            "what's the weather", conversation_history=history
        )

        assert len(_user_messages(result["messages"], "hey")) == 1
        assert len(_user_messages(result["messages"], "what's the weather")) == 1
