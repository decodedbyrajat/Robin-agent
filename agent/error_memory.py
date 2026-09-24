"""Error Pattern Memory — learns from past tool errors and applies fixes.

Stores (error_signature → solution) pairs in a lightweight SQLite database.
When a tool call fails with a recognized error pattern, the solution is
injected as a system message before the next API call, helping the model
avoid repeating the same mistake.

This is a form of "procedural memory" — the agent learns HOW to handle
specific error types from its own past experience.

Usage:
    from agent.error_memory import ErrorMemory

    emem = ErrorMemory()  # opens ~/.robin/error_patterns.db

    # After a tool error:
    emem.record_error("terminal", "Permission denied: /etc/hosts", 
                       solution="Use sudo or write to a user-owned path")

    # Before next API call, check if we've seen this error:
    hint = emem.lookup("terminal", "Permission denied: /etc/hosts")
    if hint:
        messages.append({"role": "system", "content": hint})
"""

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = os.path.expanduser("~/.robin/error_patterns.db")

# Common error patterns and their canonical signatures.
# We strip variable parts (paths, IDs, timestamps) to match similar errors.
_STRIP_PATTERNS = [
    (re.compile(r"/[\w/.-]+"), "<PATH>"),           # file paths
    (re.compile(r"\b\d{4,}\b"), "<NUM>"),            # long numbers
    (re.compile(r"0x[0-9a-fA-F]+"), "<HEX>"),        # hex addresses
    (re.compile(r"\b[0-9a-f]{8,}\b"), "<HASH>"),     # hashes/IDs
    (re.compile(r"line \d+"), "line <N>"),            # line numbers
    (re.compile(r"port \d+"), "port <N>"),            # ports
]


def _normalize_error(error_text: str) -> str:
    """Normalize an error message to a canonical signature.

    Strips variable parts (paths, numbers, hashes) so that similar
    errors match the same signature.
    """
    text = error_text.strip()
    # Take only first 500 chars to avoid huge error messages
    text = text[:500]
    for pattern, replacement in _STRIP_PATTERNS:
        text = pattern.sub(replacement, text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    return text


def _error_hash(tool_name: str, normalized_error: str) -> str:
    """Generate a stable hash for an error pattern."""
    key = f"{tool_name}::{normalized_error}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


class ErrorMemory:
    """Persistent error pattern memory backed by SQLite."""

    def __init__(self, db_path: str = _DEFAULT_DB_PATH, max_entries: int = 1000):
        self.db_path = db_path
        self.max_entries = max_entries
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_db()

    def _ensure_db(self) -> None:
        """Create the database and table if they don't exist."""
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, timeout=5)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS error_patterns (
                    error_hash TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    normalized_error TEXT NOT NULL,
                    raw_error TEXT,
                    solution TEXT NOT NULL,
                    hit_count INTEGER DEFAULT 1,
                    success_count INTEGER DEFAULT 0,
                    created_at REAL NOT NULL,
                    last_seen_at REAL NOT NULL,
                    last_solution_at REAL
                )
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_error_tool
                ON error_patterns(tool_name, normalized_error)
            """)
            self._conn.commit()
        except Exception as e:
            logger.warning("Failed to initialize error memory DB: %s", e)
            self._conn = None

    def record_error(
        self,
        tool_name: str,
        error_text: str,
        solution: str,
        raw_error: Optional[str] = None,
    ) -> Optional[str]:
        """Record an error pattern and its solution.

        Returns the error_hash if successfully recorded.
        """
        if not self._conn:
            return None

        try:
            normalized = _normalize_error(error_text)
            ehash = _error_hash(tool_name, normalized)
            now = time.time()

            self._conn.execute(
                """
                INSERT INTO error_patterns
                    (error_hash, tool_name, normalized_error, raw_error,
                     solution, hit_count, created_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(error_hash) DO UPDATE SET
                    solution = excluded.solution,
                    hit_count = hit_count + 1,
                    last_seen_at = excluded.last_seen_at,
                    raw_error = COALESCE(excluded.raw_error, raw_error)
                """,
                (ehash, tool_name, normalized, raw_error or error_text,
                 solution, now, now),
            )
            self._conn.commit()

            # Prune old entries if over limit
            self._prune()

            logger.debug(
                "Recorded error pattern %s for %s: %s → %s",
                ehash, tool_name, normalized[:80], solution[:80],
            )
            return ehash
        except Exception as e:
            logger.warning("Failed to record error pattern: %s", e)
            return None

    def lookup(
        self,
        tool_name: str,
        error_text: str,
    ) -> Optional[str]:
        """Look up a known solution for an error pattern.

        Returns a formatted hint message, or None if no match.
        """
        if not self._conn:
            return None

        try:
            normalized = _normalize_error(error_text)
            ehash = _error_hash(tool_name, normalized)

            row = self._conn.execute(
                """
                SELECT solution, hit_count, success_count
                FROM error_patterns
                WHERE error_hash = ?
                """,
                (ehash,),
            ).fetchone()

            if row:
                solution, hits, successes = row
                # Update last_seen_at
                self._conn.execute(
                    "UPDATE error_patterns SET last_seen_at = ?, "
                    "last_solution_at = ? WHERE error_hash = ?",
                    (time.time(), time.time(), ehash),
                )
                self._conn.commit()

                confidence = ""
                if hits > 3:
                    if successes > 0:
                        rate = successes / hits * 100
                        confidence = f" (worked {rate:.0f}% of the time, {hits} occurrences)"
                    else:
                        confidence = f" (seen {hits} times)"

                return (
                    f"[ERROR PATTERN RECOGNIZED] A similar error has occurred before "
                    f"with {tool_name}. Known solution{confidence}:\n\n"
                    f"{solution}\n\n"
                    f"Apply this fix or an adapted version of it."
                )
            return None
        except Exception as e:
            logger.warning("Failed to lookup error pattern: %s", e)
            return None

    def record_success(self, tool_name: str, error_text: str) -> None:
        """Mark that a previously-seen error was successfully resolved.

        Call this when a tool succeeds after a previous failure with the
        same error pattern, indicating the solution worked.
        """
        if not self._conn:
            return

        try:
            normalized = _normalize_error(error_text)
            ehash = _error_hash(tool_name, normalized)
            self._conn.execute(
                "UPDATE error_patterns SET success_count = success_count + 1 "
                "WHERE error_hash = ?",
                (ehash,),
            )
            self._conn.commit()
        except Exception as e:
            logger.debug("Failed to record success: %s", e)

    def get_stats(self) -> dict:
        """Return summary statistics about the error pattern database."""
        if not self._conn:
            return {"status": "unavailable"}

        try:
            total = self._conn.execute(
                "SELECT COUNT(*) FROM error_patterns"
            ).fetchone()[0]
            top_tools = self._conn.execute(
                "SELECT tool_name, SUM(hit_count) as hits "
                "FROM error_patterns GROUP BY tool_name "
                "ORDER BY hits DESC LIMIT 5"
            ).fetchall()
            return {
                "total_patterns": total,
                "top_tools": {row[0]: row[1] for row in top_tools},
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _prune(self) -> None:
        """Remove oldest entries if over max_entries."""
        try:
            count = self._conn.execute(
                "SELECT COUNT(*) FROM error_patterns"
            ).fetchone()[0]
            if count > self.max_entries:
                excess = count - self.max_entries
                self._conn.execute(
                    "DELETE FROM error_patterns WHERE error_hash IN "
                    "(SELECT error_hash FROM error_patterns "
                    "ORDER BY last_seen_at ASC LIMIT ?)",
                    (excess,),
                )
                self._conn.commit()
        except Exception as e:
            logger.debug("Prune failed: %s", e)

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
