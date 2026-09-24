"""Obsidian Bidirectional Knowledge Bridge for Robin.

Connects Robin Agent's episodic memory, persistent facts, and session lifecycle
directly to the user's Obsidian Vault.

Features:
  - Robust YAML frontmatter parser and generator (without raw PyYAML dependencies)
  - Extraction and indexing of Obsidian Callouts (> [!type]), tags (#tag), and Wikilinks ([[Note]])
  - Bidirectional search across vault notes
  - Automated sync for persistent agent memory (03 🧠 Agent Memory/) and active session contexts
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_VAULT_PATH = Path(
    os.environ.get(
        "OBSIDIAN_VAULT_PATH",
        "/Users/shanu/Library/Mobile Documents/iCloud~md~obsidian/Documents/Vault",
    )
)


@dataclass
class ObsidianNote:
    path: str
    relative_path: str
    title: str
    frontmatter: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    wikilinks: List[str] = field(default_factory=list)
    callouts: List[Tuple[str, str]] = field(default_factory=list)  # (type, content)
    body: str = ""
    modified_time: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ObsidianBridge:
    """Interface for querying, indexing, and synchronizing with an Obsidian Vault."""

    def __init__(self, vault_path: Optional[Path | str] = None) -> None:
        raw_path = Path(vault_path) if vault_path else DEFAULT_VAULT_PATH
        self.vault_path: Path = raw_path.resolve()

    def is_vault_available(self) -> bool:
        """Check if the configured vault directory exists on disk."""
        return self.vault_path.exists() and self.vault_path.is_dir()

    # --- Markdown & Frontmatter Parsing ---

    @staticmethod
    def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
        """Extract YAML frontmatter and body from markdown content."""
        if not content.startswith("---"):
            return {}, content

        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}, content

        raw_yaml = parts[1].strip()
        body = parts[2].lstrip("\n")
        frontmatter: Dict[str, Any] = {}

        current_key: Optional[str] = None
        for line in raw_yaml.splitlines():
            line_str = line.strip()
            if not line_str or line_str.startswith("#"):
                continue

            # List item under current key
            if line_str.startswith("- ") and current_key:
                val = line_str[2:].strip().strip("\"'")
                if not isinstance(frontmatter.get(current_key), list):
                    frontmatter[current_key] = []
                frontmatter[current_key].append(val)
                continue

            # Key: Value pair
            if ":" in line_str:
                k, v = line_str.split(":", 1)
                k = k.strip()
                v = v.strip().strip("\"'")
                current_key = k
                if not v:
                    frontmatter[k] = []
                else:
                    frontmatter[k] = v

        return frontmatter, body

    @staticmethod
    def serialize_frontmatter(frontmatter: Dict[str, Any], body: str) -> str:
        """Combine frontmatter dictionary and body into a valid Obsidian markdown string."""
        if not frontmatter:
            return body

        lines = ["---"]
        for k, v in frontmatter.items():
            if isinstance(v, list):
                lines.append(f"{k}:")
                for item in v:
                    lines.append(f"  - {item}")
            else:
                lines.append(f"{k}: {v}")
        lines.append("---")
        lines.append("")
        lines.append(body.lstrip("\n"))
        return "\n".join(lines)

    @staticmethod
    def extract_wikilinks(text: str) -> List[str]:
        """Extract all target notes referenced in [[Note Name]] or [[Note Name|Alias]]."""
        raw_matches = re.findall(r"\[\[(.*?)\]\]", text)
        links: List[str] = []
        for match in raw_matches:
            target = match.split("|")[0].split("#")[0].strip()
            if target and target not in links:
                links.append(target)
        return links

    @staticmethod
    def extract_tags(text: str, frontmatter_tags: Optional[List[str]] = None) -> List[str]:
        """Extract markdown tags (#tag/subtag) along with frontmatter tags."""
        found_tags: List[str] = list(frontmatter_tags or [])
        # Match markdown inline tags (exclude hex codes and markdown headers)
        inline = re.findall(r"(?:^|\s)#([a-zA-Z0-9_\-\/]+)", text)
        for t in inline:
            clean = t.strip()
            if clean and clean not in found_tags:
                found_tags.append(clean)
        return found_tags

    @staticmethod
    def extract_callouts(text: str) -> List[Tuple[str, str]]:
        """Extract Obsidian callout blocks (> [!type] Title)."""
        callouts: List[Tuple[str, str]] = []
        pattern = re.compile(r"^>\s*\[!([a-zA-Z0-9_\-]+)\]\s*(.*)$", re.MULTILINE)
        for match in pattern.finditer(text):
            c_type = match.group(1).strip()
            c_title = match.group(2).strip()
            callouts.append((c_type, c_title))
        return callouts

    # --- File & Note Operations ---

    def read_note(self, relative_path: str) -> Optional[ObsidianNote]:
        """Read and parse an Obsidian note by relative path."""
        target_path = (self.vault_path / relative_path).resolve()
        if not target_path.exists() or not target_path.is_file():
            return None

        try:
            content = target_path.read_text(encoding="utf-8")
            fm, body = self.parse_frontmatter(content)
            title = fm.get("title") or target_path.stem
            tags = self.extract_tags(body, fm.get("tags") if isinstance(fm.get("tags"), list) else None)
            wikilinks = self.extract_wikilinks(content)
            callouts = self.extract_callouts(content)

            return ObsidianNote(
                path=str(target_path),
                relative_path=str(target_path.relative_to(self.vault_path)),
                title=title,
                frontmatter=fm,
                tags=tags,
                wikilinks=wikilinks,
                callouts=callouts,
                body=body,
                modified_time=target_path.stat().st_mtime,
            )
        except Exception as e:
            logger.warning("Failed to read Obsidian note at %s: %s", relative_path, e)
            return None

    def write_note(
        self,
        relative_path: str,
        title: str,
        body: str,
        frontmatter: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
    ) -> str:
        """Write or update an Obsidian note formatted with frontmatter."""
        target_path = self.vault_path / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)

        fm = dict(frontmatter or {})
        fm["title"] = title
        if tags:
            fm["tags"] = tags

        content = self.serialize_frontmatter(fm, body)
        target_path.write_text(content, encoding="utf-8")
        return str(target_path)

    def list_notes(self, subdirectory: str = "") -> List[ObsidianNote]:
        """List and parse notes within a vault subdirectory."""
        if not self.is_vault_available():
            return []

        search_dir = self.vault_path / subdirectory if subdirectory else self.vault_path
        notes: List[ObsidianNote] = []

        if not search_dir.exists():
            return []

        for md_file in search_dir.glob("**/*.md"):
            rel_path = str(md_file.relative_to(self.vault_path))
            note = self.read_note(rel_path)
            if note:
                notes.append(note)

        return sorted(notes, key=lambda n: n.relative_path)

    def search_vault(self, query: str, tag: Optional[str] = None) -> List[ObsidianNote]:
        """Search notes by content query and optional tag filter."""
        results: List[ObsidianNote] = []
        q = query.lower()

        for note in self.list_notes():
            if tag and not any(tag.lower() == t.lower() or t.lower().startswith(tag.lower() + "/") for t in note.tags):
                continue

            if q in note.title.lower() or q in note.body.lower() or any(q in t.lower() for t in note.tags):
                results.append(note)

        return results

    # --- Agent Memory & Synchronization Helpers ---

    def sync_agent_memory(self, filename: str, content: str, title: Optional[str] = None) -> str:
        """Synchronize an agent memory document into '03 🧠 Agent Memory/'."""
        rel_path = f"03 🧠 Agent Memory/{filename}"
        note_title = title or filename.replace(".md", "")
        return self.write_note(
            relative_path=rel_path,
            title=note_title,
            body=content,
            frontmatter={
                "type": "agent-memory",
                "tags": ["robin/memory", "agent/persistent-memory"],
            },
        )
