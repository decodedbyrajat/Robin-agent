"""Episodic Memory System for Robin.

Stores rich, structured problem-solving episodes (goals, approaches,
tool chains, pitfalls, lessons learned, and outcomes) in SQLite with
FTS5 full-text indexing.

Provides the agent with experiential recall: "How did we solve a similar
problem in the past?" rather than just flat declarative facts.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path.home() / ".robin" / "episodic_memory.db"


@dataclass
class Episode:
    episode_id: str
    timestamp: float
    goal: str
    outcome: str  # "success", "failure", "partial"
    approach: str = ""
    lessons_learned: str = ""
    tools_used: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    context_summary: str = ""
    duration_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: tuple) -> Episode:
        tools = json.loads(row[6]) if row[6] else []
        tags = json.loads(row[7]) if row[7] else []
        return cls(
            episode_id=row[0],
            timestamp=row[1],
            goal=row[2],
            outcome=row[3],
            approach=row[4] or "",
            lessons_learned=row[5] or "",
            tools_used=tools,
            tags=tags,
            context_summary=row[8] or "",
            duration_seconds=row[9] or 0.0,
        )


class EpisodicMemory:
    """Persistent SQLite database of past problem-solving episodes."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        try:
            with self._get_conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS episodes (
                        episode_id TEXT PRIMARY KEY,
                        timestamp REAL,
                        goal TEXT,
                        outcome TEXT,
                        approach TEXT,
                        lessons_learned TEXT,
                        tools_used TEXT,
                        tags TEXT,
                        context_summary TEXT,
                        duration_seconds REAL
                    )
                """)
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
                        episode_id UNINDEXED,
                        goal,
                        approach,
                        lessons_learned,
                        context_summary,
                        content='episodes',
                        content_rowid='rowid'
                    )
                """)
                # Triggers to keep FTS index synced
                conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON episodes BEGIN
                        INSERT INTO episodes_fts(rowid, episode_id, goal, approach, lessons_learned, context_summary)
                        VALUES (new.rowid, new.episode_id, new.goal, new.approach, new.lessons_learned, new.context_summary);
                    END;
                """)
                conn.commit()
        except Exception as e:
            logger.warning("Could not initialize episodic memory DB: %s", e)

    def record_episode(
        self,
        goal: str,
        outcome: str = "success",
        approach: str = "",
        lessons_learned: str = "",
        tools_used: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        context_summary: str = "",
        duration_seconds: float = 0.0,
    ) -> str:
        """Record a completed task episode into memory."""
        import uuid
        ep_id = str(uuid.uuid4())[:8]
        ts = time.time()
        tools_json = json.dumps(tools_used or [])
        tags_json = json.dumps(tags or [])

        try:
            with self._get_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO episodes (
                        episode_id, timestamp, goal, outcome, approach,
                        lessons_learned, tools_used, tags, context_summary, duration_seconds
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ep_id, ts, goal, outcome, approach,
                        lessons_learned, tools_json, tags_json, context_summary, duration_seconds
                    ),
                )
                conn.commit()
            logger.info("Recorded episode %s: %s (%s)", ep_id, goal[:40], outcome)
        except Exception as e:
            logger.warning("Failed to record episode: %s", e)

        return ep_id

    def search_episodes(
        self,
        query: str,
        outcome_filter: Optional[str] = None,
        limit: int = 3,
    ) -> List[Episode]:
        """Search episodes using full-text search with optional outcome filtering."""
        if not query.strip():
            return []

        # Sanitize query for FTS5
        clean_terms = [t for t in query.split() if t.isalnum()]
        if not clean_terms:
            return []
        fts_query = " OR ".join(clean_terms)

        results: List[Episode] = []
        try:
            with self._get_conn() as conn:
                sql = """
                    SELECT e.episode_id, e.timestamp, e.goal, e.outcome, e.approach,
                           e.lessons_learned, e.tools_used, e.tags, e.context_summary, e.duration_seconds
                    FROM episodes e
                    JOIN episodes_fts f ON e.episode_id = f.episode_id
                    WHERE episodes_fts MATCH ?
                """
                params = [fts_query]
                if outcome_filter:
                    sql += " AND e.outcome = ?"
                    params.append(outcome_filter)

                sql += " ORDER BY rank LIMIT ?"
                params.append(limit)

                cursor = conn.execute(sql, params)
                for row in cursor.fetchall():
                    results.append(Episode.from_row(row))
        except Exception as e:
            logger.debug("Episodic search error: %s", e)

        return results

    def format_for_prompt(self, episodes: List[Episode]) -> str:
        """Format matching episodes as prompt context."""
        if not episodes:
            return ""

        parts = ["## Relevant Past Problem-Solving Experiences"]
        for ep in episodes:
            status_icon = "✅" if ep.outcome == "success" else "⚠️"
            parts.append(
                f"### {status_icon} Past Case: {ep.goal}\n"
                f"- **Approach:** {ep.approach}\n"
                f"- **Lessons Learned:** {ep.lessons_learned}\n"
                f"- **Key Tools:** {', '.join(ep.tools_used) if ep.tools_used else 'N/A'}"
            )

        return "\n\n".join(parts)
