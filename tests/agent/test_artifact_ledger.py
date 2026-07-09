"""Tests for the compaction artifact ledger.

Large tool outputs are spilled to disk and referenced in-context via
"Full output saved to: <path>" blocks. Compression used to destroy those
references (pruning replaces tool results with one-liners; summarization is
lossy), leaving the post-compaction model unaware that ground truth was
still readable on disk. compress() now harvests the paths deterministically
and appends them to the compaction summary.
"""

import pytest
from unittest.mock import patch

from agent.context_compressor import ContextCompressor, _collect_artifact_paths


PERSISTED_BLOCK = (
    "<persisted-output>\n"
    "This tool result was too large (120,000 characters, 117.2 KB).\n"
    "Full output saved to: /tmp/robin-results/{tid}.txt\n"
    "Use the read_file tool with offset and limit to access specific sections "
    "of this output.\n\n"
    "Preview (first 100 chars):\nsome preview text\n...\n"
    "</persisted-output>"
)


def _persisted(tid):
    return PERSISTED_BLOCK.format(tid=tid)


class TestCollectArtifactPaths:
    def test_extracts_paths_from_tool_messages(self):
        msgs = [
            {"role": "user", "content": "run the tests"},
            {"role": "tool", "content": _persisted("aaa")},
            {"role": "tool", "content": _persisted("bbb")},
        ]
        paths = _collect_artifact_paths(msgs)
        assert paths == [
            "/tmp/robin-results/aaa.txt",
            "/tmp/robin-results/bbb.txt",
        ]

    def test_dedupes_and_keeps_latest_order(self):
        msgs = [
            {"role": "tool", "content": _persisted("aaa")},
            {"role": "tool", "content": _persisted("bbb")},
            {"role": "tool", "content": _persisted("aaa")},
        ]
        paths = _collect_artifact_paths(msgs)
        assert paths == [
            "/tmp/robin-results/bbb.txt",
            "/tmp/robin-results/aaa.txt",
        ]

    def test_caps_at_limit(self):
        msgs = [
            {"role": "tool", "content": _persisted(f"t{i}")} for i in range(30)
        ]
        paths = _collect_artifact_paths(msgs, limit=20)
        assert len(paths) == 20
        assert paths[-1] == "/tmp/robin-results/t29.txt"

    def test_ignores_non_string_and_plain_content(self):
        msgs = [
            {"role": "user", "content": ["multimodal", "content"]},
            {"role": "assistant", "content": None},
            {"role": "user", "content": "no artifacts here"},
        ]
        assert _collect_artifact_paths(msgs) == []


class TestCompressCarriesArtifacts:
    def _compressor(self):
        with patch(
            "agent.context_compressor.get_model_context_length",
            return_value=100000,
        ):
            return ContextCompressor(
                model="test/model",
                quiet_mode=True,
                protect_first_n=2,
                protect_last_n=2,
            )

    def test_summary_includes_dropped_artifact_paths(self):
        c = self._compressor()
        msgs = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "analyze the logs"},
            {"role": "assistant", "content": "running analysis"},
            {"role": "tool", "content": _persisted("dropped1")},
            {"role": "assistant", "content": "more work"},
            {"role": "user", "content": "continue"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "keep going"},
            {"role": "assistant", "content": "sure"},
            {"role": "user", "content": "latest message"},
        ]
        # client=None -> summary falls back to the static marker; the
        # artifact block must be appended regardless.
        result = c.compress(msgs)
        joined = "\n".join(
            m.get("content") for m in result if isinstance(m.get("content"), str)
        )
        assert "/tmp/robin-results/dropped1.txt" in joined
        assert "Artifacts on disk" in joined

    def test_paths_still_visible_in_tail_are_not_repeated(self):
        c = self._compressor()
        msgs = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "analyze"},
            {"role": "assistant", "content": "working"},
            {"role": "user", "content": "go on"},
            {"role": "assistant", "content": "still working"},
            {"role": "user", "content": "go on"},
            {"role": "assistant", "content": "nearly done"},
            # Tail (protected) contains the persisted block already:
            {"role": "tool", "content": _persisted("tailvisible")},
            {"role": "user", "content": "latest"},
        ]
        result = c.compress(msgs)
        joined = "\n".join(
            m.get("content") for m in result if isinstance(m.get("content"), str)
        )
        # Path appears exactly once (in the tail), not duplicated in the summary
        assert joined.count("/tmp/robin-results/tailvisible.txt") == 1
