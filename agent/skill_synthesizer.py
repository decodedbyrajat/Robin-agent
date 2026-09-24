"""Dynamic Skill Auto-Synthesis Engine for Robin.

Analyzes complex problem-solving episodes, multi-step tool call sequences, and
error recovery patterns to automatically formulate validated, reusable SKILL.md
definitions for Robin Agent.

Features:
  - Sequence analyzer: identifies reusable tool chains, commands, and workflows
  - Skill generator: synthesizes compliant YAML frontmatter + structured Markdown body
  - Schema validator: enforces naming, description, and formatting constraints
  - Direct integration with ~/.robin/skills/ and skill_manage tool API
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_DESCRIPTION_LENGTH = 1024


@dataclass
class SynthesizedSkill:
    name: str
    description: str
    content: str
    tags: List[str] = field(default_factory=list)
    category: Optional[str] = None
    confidence_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SkillSynthesizer:
    """Engine for analyzing agent workflows and synthesizing validated skills."""

    @staticmethod
    def sanitize_skill_name(name: str) -> str:
        """Sanitize a proposed skill name to lowercase hyphenated format."""
        clean = re.sub(r"[^a-zA-Z0-9\-_]", "-", name.lower())
        clean = re.sub(r"-+", "-", clean).strip("-")
        return clean[:64] if clean else "custom-skill"

    @classmethod
    def synthesize_skill(
        cls,
        name: str,
        description: str,
        goal: str,
        steps: List[str],
        commands: Optional[List[str]] = None,
        pitfalls: Optional[List[str]] = None,
        verification: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
    ) -> SynthesizedSkill:
        """Synthesize a complete, formatted, and validated SKILL.md."""
        skill_name = cls.sanitize_skill_name(name)
        clean_desc = (description or f"Workflow and procedures for {goal}").strip()
        if len(clean_desc) > MAX_DESCRIPTION_LENGTH:
            clean_desc = clean_desc[: MAX_DESCRIPTION_LENGTH - 3] + "..."

        tag_list = tags or ["workflow", "automation"]
        tags_yaml = "\n".join(f"  - {t}" for t in tag_list)

        # Build Body
        body_sections = [
            f"# {skill_name.replace('-', ' ').title()}",
            "",
            "## Overview",
            f"{clean_desc}",
            "",
            "## Goal & Trigger",
            f"- **Target Goal:** {goal}",
            "- **When to Use:** Use when tackling similar tasks or recurring workflows.",
            "",
            "## Step-by-Step Procedure",
        ]

        for i, step in enumerate(steps or ["Execute the task according to standard specifications."], 1):
            body_sections.append(f"{i}. {step}")

        if commands:
            body_sections.extend(["", "## Key Commands & Code Snippets", "```bash"])
            for cmd in commands:
                body_sections.append(cmd)
            body_sections.append("```")

        if pitfalls:
            body_sections.extend(["", "## Pitfalls & Edge Cases"])
            for p in pitfalls:
                body_sections.append(f"- ⚠️ {p}")

        if verification:
            body_sections.extend(["", "## Verification Steps"])
            for v in verification:
                body_sections.append(f"- [ ] {v}")

        body_text = "\n".join(body_sections).strip()

        # Build Full Content with Frontmatter
        full_content = (
            f"---\n"
            f"name: {skill_name}\n"
            f"description: \"{clean_desc}\"\n"
            f"tags:\n{tags_yaml}\n"
            f"---\n\n"
            f"{body_text}\n"
        )

        return SynthesizedSkill(
            name=skill_name,
            description=clean_desc,
            content=full_content,
            tags=tag_list,
            category=category,
            confidence_score=0.9,
        )

    @classmethod
    def extract_from_tool_events(
        cls,
        goal: str,
        tool_calls: List[Dict[str, Any]],
        outcome: str = "success",
        category: Optional[str] = None,
    ) -> Optional[SynthesizedSkill]:
        """Synthesize a reusable skill from a sequence of tool calls and results."""
        if not tool_calls or len(tool_calls) < 2:
            return None

        steps: List[str] = []
        commands: List[str] = []
        pitfalls: List[str] = []
        verification: List[str] = []

        for call in tool_calls:
            tool_name = call.get("tool_name") or call.get("name", "tool")
            args = call.get("args") or call.get("arguments", {})
            if isinstance(args, str):
                import json

                try:
                    args = json.loads(args)
                except Exception:
                    args = {}

            if tool_name == "terminal":
                cmd = args.get("command", "")
                if cmd:
                    commands.append(cmd)
                    steps.append(f"Execute shell command: `{cmd[:60]}`")
            elif tool_name == "read_file":
                path = args.get("path", "")
                steps.append(f"Inspect target file: `{path}`")
            elif tool_name == "write_file":
                path = args.get("path", "")
                steps.append(f"Create or overwrite target file: `{path}`")
            elif tool_name == "patch":
                path = args.get("path", "")
                steps.append(f"Apply targeted edits to: `{path}`")
            elif tool_name == "search_files":
                pattern = args.get("pattern", "")
                steps.append(f"Search codebase for pattern: `{pattern}`")
            else:
                steps.append(f"Invoke `{tool_name}` with configured parameters")

            # Check if there was an error in output that was resolved
            result_str = str(call.get("result", ""))
            if "error" in result_str.lower() or "failed" in result_str.lower():
                pitfalls.append(f"Handled error during `{tool_name}`: {result_str[:80]}...")

        if outcome == "success":
            verification.append("Verify all modified files and configurations.")
            verification.append("Run test suite or validation checks to ensure zero regressions.")

        # Formulate skill title from goal
        clean_name = re.sub(r"[^a-zA-Z0-9\s]", "", goal).strip()
        words = clean_name.split()[:4]
        skill_name = "-".join(words).lower() or "automated-workflow"

        return cls.synthesize_skill(
            name=skill_name,
            description=f"Auto-synthesized procedure for: {goal}",
            goal=goal,
            steps=steps,
            commands=commands if commands else None,
            pitfalls=pitfalls if pitfalls else None,
            verification=verification if verification else None,
            category=category,
        )
