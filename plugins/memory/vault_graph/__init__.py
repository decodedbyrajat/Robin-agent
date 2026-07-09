"""Vault-graph memory provider — Obsidian vault recall via graphify.

Queries the graphify knowledge graph built over the user's Obsidian vault
(``<vault>/graphify-out/graph.json``) and injects a small, token-budgeted
subgraph as recall context when — and only when — the user's message
overlaps the vault's vocabulary.

Design constraints this provider works within:

* graphify is installed as a uv tool (its venv is not importable from
  Robin's interpreter), so queries shell out to the ``graphify`` CLI.
* Subprocess spawns cost ~1s, so every query is gated by an in-memory
  vocabulary check built from the graph's node labels at initialize().
  A message like "hey" shares no terms with the vault and costs nothing.
* ``queue_prefetch()`` warms the cache on a background thread after each
  turn; ``prefetch()`` serves cached results and only falls back to a
  bounded synchronous query on a cold cache.
* No tools are exposed (``get_tool_schemas() -> []``), so activating this
  provider adds zero always-on tokens to the request.

Activate with ``memory.provider: vault_graph`` in config.yaml.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

from agent.memory_provider import MemoryProvider

logger = logging.getLogger(__name__)

_DEFAULT_VAULT = "~/Documents/Obsidian Vault"
_QUERY_TIMEOUT_S = 6
_CACHE_TTL_S = 300
_MAX_INJECT_CHARS = 2400
_STOPWORDS = frozenset(
    "the a an and or but of to in on for with about what how why when where "
    "who is are was were be been do does did can could should would you your "
    "my me i we they it this that these those from as at by not no yes please "
    "tell show give make just like know remember recall".split()
)


def _terms(text: str) -> set:
    return {
        w for w in re.findall(r"[a-z0-9][a-z0-9_-]{2,}", (text or "").lower())
        if w not in _STOPWORDS
    }


class VaultGraphMemoryProvider(MemoryProvider):
    """Recall provider backed by the graphify graph of the Obsidian vault."""

    def __init__(self, config: dict | None = None):
        config = config or {}
        raw_vault = (
            config.get("vault_path")
            or os.environ.get("OBSIDIAN_VAULT_PATH")
            or _DEFAULT_VAULT
        )
        # .env values often carry shell-style escapes/quotes for the space in
        # "Mobile Documents" — normalize before treating it as a path.
        raw_vault = raw_vault.strip().strip("'\"").replace("\\ ", " ")
        self._vault = Path(os.path.expandvars(raw_vault)).expanduser()
        self._graph_path = self._vault / "graphify-out" / "graph.json"
        self._budget = int(config.get("budget_tokens", 500))
        self._graphify_exe = shutil.which("graphify") or str(
            Path.home() / ".local" / "bin" / "graphify"
        )
        self._vocab: set = set()
        self._vocab_mtime: float = 0.0
        self._cache: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    # -- Identity / availability -----------------------------------------

    @property
    def name(self) -> str:
        return "vault_graph"

    def is_available(self) -> bool:
        return self._graph_path.is_file() and Path(self._graphify_exe).exists()

    # -- Lifecycle ---------------------------------------------------------

    def initialize(self, session_id: str, **kwargs) -> None:
        self._load_vocab()

    def _load_vocab(self) -> None:
        """Index node labels so irrelevant queries never spawn a subprocess."""
        try:
            mtime = self._graph_path.stat().st_mtime
            if mtime == self._vocab_mtime and self._vocab:
                return
            if self._graph_path.stat().st_size > 20_000_000:
                logger.debug("vault_graph: graph.json too large for vocab index")
                return
            data = json.loads(self._graph_path.read_text(encoding="utf-8"))
            vocab: set = set()
            for node in data.get("nodes", []):
                vocab |= _terms(str(node.get("label", "")))
                vocab |= _terms(str(node.get("id", "")))
            self._vocab = vocab
            self._vocab_mtime = mtime
            logger.debug("vault_graph: vocab loaded (%d terms)", len(vocab))
        except Exception as e:
            logger.debug("vault_graph: vocab load failed: %s", e)

    # -- Recall --------------------------------------------------------------

    def _relevant(self, query: str) -> bool:
        if not self._vocab:
            self._load_vocab()
        return bool(self._vocab and (_terms(query) & self._vocab))

    def _run_query(self, query: str) -> str:
        try:
            proc = subprocess.run(
                [
                    self._graphify_exe, "query", query,
                    "--budget", str(self._budget),
                ],
                cwd=str(self._vault),
                capture_output=True,
                text=True,
                timeout=_QUERY_TIMEOUT_S,
            )
        except Exception as e:
            logger.debug("vault_graph: query failed: %s", e)
            return ""
        out = (proc.stdout or "").strip()
        if proc.returncode != 0 or not out or "0 nodes found" in out:
            return ""
        if len(out) > _MAX_INJECT_CHARS:
            out = out[:_MAX_INJECT_CHARS] + "\n... (truncated)"
        return (
            "## Obsidian vault recall (graphify)\n"
            "Relevant subgraph from the user's notes — node lines include the "
            "source note path (src=); read a note only if you need its full text.\n"
            + out
        )

    def _cached_or_query(self, query: str) -> str:
        key = " ".join(sorted(_terms(query)))
        if not key:
            return ""
        now = time.time()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < _CACHE_TTL_S:
                return hit[1]
        result = self._run_query(query)
        with self._lock:
            self._cache[key] = (now, result)
            if len(self._cache) > 50:
                oldest = min(self._cache, key=lambda k: self._cache[k][0])
                self._cache.pop(oldest, None)
        return result

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if not query or not self._relevant(query):
            return ""
        return self._cached_or_query(query)

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        if not query or not self._relevant(query):
            return
        threading.Thread(
            target=self._cached_or_query, args=(query,), daemon=True
        ).start()

    # -- Everything else is a no-op ---------------------------------------

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        pass

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return []

    def shutdown(self) -> None:
        pass


def register(ctx) -> None:
    """Register the vault-graph memory provider with the plugin system."""
    ctx.register_memory_provider(VaultGraphMemoryProvider())
