"""Tests for the vault_graph memory provider."""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from plugins.memory.vault_graph import VaultGraphMemoryProvider, _terms


def _make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "Vault"
    out = vault / "graphify-out"
    out.mkdir(parents=True)
    graph = {
        "nodes": [
            {"id": "memory_robin_user_profile", "label": "User Profile"},
            {"id": "tts_engine_decision", "label": "TTS Engine Decision"},
            {"id": "security_lab", "label": "Security Lab"},
        ],
        "links": [],
    }
    (out / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
    return vault


def _provider(tmp_path, **config):
    vault = _make_vault(tmp_path)
    p = VaultGraphMemoryProvider(config={"vault_path": str(vault), **config})
    # Pretend the graphify CLI exists so is_available() passes in CI
    p._graphify_exe = "/bin/echo"
    return p


class TestTerms:
    def test_extracts_and_filters_stopwords(self):
        assert "profile" in _terms("what do you know about the user Profile?")
        assert "the" not in _terms("the a an")

    def test_short_tokens_dropped(self):
        assert _terms("go to db") == set()


class TestAvailability:
    def test_available_when_graph_and_cli_exist(self, tmp_path):
        p = _provider(tmp_path)
        assert p.is_available() is True

    def test_unavailable_without_graph(self, tmp_path):
        p = VaultGraphMemoryProvider(config={"vault_path": str(tmp_path)})
        p._graphify_exe = "/bin/echo"
        assert p.is_available() is False


class TestRelevanceGate:
    def test_irrelevant_query_never_spawns_subprocess(self, tmp_path):
        p = _provider(tmp_path)
        p.initialize("s1")
        with patch.object(p, "_run_query") as rq:
            assert p.prefetch("hey") == ""
            assert p.prefetch("hello how are you") == ""
            rq.assert_not_called()

    def test_relevant_query_runs(self, tmp_path):
        p = _provider(tmp_path)
        p.initialize("s1")
        with patch.object(p, "_run_query", return_value="## recall") as rq:
            out = p.prefetch("what was the TTS engine decision?")
            assert out == "## recall"
            rq.assert_called_once()


class TestCache:
    def test_same_terms_hit_cache(self, tmp_path):
        p = _provider(tmp_path)
        p.initialize("s1")
        with patch.object(p, "_run_query", return_value="## recall") as rq:
            p.prefetch("TTS engine decision")
            p.prefetch("decision engine TTS")  # same term set, reordered
            assert rq.call_count == 1

    def test_expired_cache_requeries(self, tmp_path):
        p = _provider(tmp_path)
        p.initialize("s1")
        with patch.object(p, "_run_query", return_value="## recall") as rq:
            p.prefetch("TTS engine decision")
            key = next(iter(p._cache))
            p._cache[key] = (time.time() - 9999, "## stale")
            p.prefetch("TTS engine decision")
            assert rq.call_count == 2


class TestQueryExecution:
    def test_zero_nodes_returns_empty(self, tmp_path):
        p = _provider(tmp_path)
        completed = MagicMock(returncode=0, stdout="Traversal: BFS | 0 nodes found", stderr="")
        with patch("plugins.memory.vault_graph.subprocess.run", return_value=completed):
            assert p._run_query("security lab") == ""

    def test_output_is_wrapped_and_capped(self, tmp_path):
        p = _provider(tmp_path)
        completed = MagicMock(returncode=0, stdout="NODE x\n" * 2000, stderr="")
        with patch("plugins.memory.vault_graph.subprocess.run", return_value=completed):
            out = p._run_query("security lab")
        assert out.startswith("## Obsidian vault recall")
        assert len(out) < 3000

    def test_subprocess_failure_is_silent(self, tmp_path):
        p = _provider(tmp_path)
        with patch(
            "plugins.memory.vault_graph.subprocess.run",
            side_effect=OSError("no exe"),
        ):
            assert p._run_query("security lab") == ""


class TestLoader:
    def test_load_via_plugin_system(self):
        from plugins.memory import load_memory_provider
        provider = load_memory_provider("vault_graph")
        assert provider is not None
        assert provider.name == "vault_graph"
        assert provider.get_tool_schemas() == []
