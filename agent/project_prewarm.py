"""Project context pre-warming for Robin agent.

Automatically inspects the working directory to detect project structure,
manifests (package.json, pyproject.toml, Cargo.toml, go.mod), git status,
and README excerpts. Injected into the system prompt when no dedicated
guidance files (ROBIN.md, AGENTS.md, CLAUDE.md) are present.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _get_git_branch(cwd_path: Path) -> Optional[str]:
    """Fast non-subprocess git branch detection via .git/HEAD."""
    try:
        curr = cwd_path
        while curr != curr.parent:
            git_dir = curr / ".git"
            if git_dir.is_dir():
                head_file = git_dir / "HEAD"
                if head_file.is_file():
                    content = head_file.read_text(encoding="utf-8").strip()
                    if content.startswith("ref: refs/heads/"):
                        return content.replace("ref: refs/heads/", "")
                    return content[:8]  # detached HEAD commit hash
                break
            curr = curr.parent
    except Exception as e:
        logger.debug("Failed to read git branch: %s", e)
    return None


def _inspect_package_json(cwd_path: Path) -> Optional[str]:
    pkg_file = cwd_path / "package.json"
    if not pkg_file.is_file():
        return None
    try:
        data = json.loads(pkg_file.read_text(encoding="utf-8"))
        name = data.get("name", "unnamed")
        version = data.get("version", "")
        scripts = list((data.get("scripts") or {}).keys())
        deps = list((data.get("dependencies") or {}).keys())
        dev_deps = list((data.get("devDependencies") or {}).keys())

        parts = [f"Node.js / JS / TS Project (`{name}` {version})"]
        if scripts:
            parts.append(f"- **Scripts:** {', '.join(scripts[:8])}")
        if deps:
            sample_deps = ", ".join(deps[:10]) + ("..." if len(deps) > 10 else "")
            parts.append(f"- **Dependencies ({len(deps)}):** {sample_deps}")
        if dev_deps:
            sample_dev = ", ".join(dev_deps[:8]) + ("..." if len(dev_deps) > 8 else "")
            parts.append(f"- **Dev Dependencies ({len(dev_deps)}):** {sample_dev}")
        return "\n".join(parts)
    except Exception as e:
        logger.debug("Error parsing package.json: %s", e)
        return "Node.js Project (package.json present)"


def _inspect_python_project(cwd_path: Path) -> Optional[str]:
    pyproject = cwd_path / "pyproject.toml"
    setup_py = cwd_path / "setup.py"
    reqs = cwd_path / "requirements.txt"

    if not (pyproject.is_file() or setup_py.is_file() or reqs.is_file()):
        return None

    parts = ["Python Project"]
    if pyproject.is_file():
        try:
            content = pyproject.read_text(encoding="utf-8")
            name_match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
            if name_match:
                parts[0] = f"Python Project (`{name_match.group(1)}` via pyproject.toml)"
        except Exception:
            pass

    if reqs.is_file():
        try:
            lines = [l.strip() for l in reqs.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
            if lines:
                parts.append(f"- **Requirements:** {len(lines)} packages listed in requirements.txt ({', '.join(lines[:8])}{'...' if len(lines) > 8 else ''})")
        except Exception:
            pass

    return "\n".join(parts)


def _inspect_cargo_project(cwd_path: Path) -> Optional[str]:
    cargo = cwd_path / "Cargo.toml"
    if not cargo.is_file():
        return None
    try:
        content = cargo.read_text(encoding="utf-8")
        name_match = re.search(r'name\s*=\s*["\']([^"\']+)["\']', content)
        name = name_match.group(1) if name_match else "Rust crate"
        return f"Rust Project (`{name}` via Cargo.toml)"
    except Exception:
        return "Rust Project (Cargo.toml)"


def _inspect_go_project(cwd_path: Path) -> Optional[str]:
    gomod = cwd_path / "go.mod"
    if not gomod.is_file():
        return None
    try:
        content = gomod.read_text(encoding="utf-8")
        mod_match = re.search(r'module\s+([^\s\n]+)', content)
        mod_name = mod_match.group(1) if mod_match else "Go module"
        return f"Go Project (`{mod_name}` via go.mod)"
    except Exception:
        return "Go Project (go.mod)"


def _get_top_level_layout(cwd_path: Path) -> list[str]:
    try:
        entries = []
        for item in sorted(cwd_path.iterdir()):
            if item.name.startswith("."):
                continue
            if item.is_dir():
                entries.append(f"{item.name}/")
            elif item.is_file():
                entries.append(item.name)
        return entries[:25]
    except Exception:
        return []


def _get_readme_summary(cwd_path: Path, max_chars: int = 1200) -> Optional[str]:
    for name in ["README.md", "readme.md", "README", "README.rst"]:
        readme_file = cwd_path / name
        if readme_file.is_file():
            try:
                text = readme_file.read_text(encoding="utf-8").strip()
                if not text:
                    continue
                if len(text) > max_chars:
                    text = text[:max_chars].rsplit("\n", 1)[0] + "\n..."
                return f"### README Excerpt (`{name}`)\n```markdown\n{text}\n```"
            except Exception:
                pass
    return None


def build_prewarm_summary(cwd_path: Path, max_chars: int = 3000) -> str:
    """Build a concise, pre-warmed context summary of the working directory."""
    if not cwd_path.is_dir():
        return ""

    sections = []
    
    # 1. Project Type
    proj_type = (
        _inspect_package_json(cwd_path)
        or _inspect_python_project(cwd_path)
        or _inspect_cargo_project(cwd_path)
        or _inspect_go_project(cwd_path)
    )
    if proj_type:
        sections.append(f"### Project Type\n{proj_type}")

    # 2. Git Info
    branch = _get_git_branch(cwd_path)
    if branch:
        sections.append(f"**Git Branch:** `{branch}`")

    # 3. Top-level Directory Structure
    layout = _get_top_level_layout(cwd_path)
    if layout:
        sections.append(f"**Directory Layout:** {', '.join(layout)}")

    # 4. Readme Summary
    readme = _get_readme_summary(cwd_path)
    if readme:
        sections.append(readme)

    if not sections:
        return ""

    content = "## Auto-Detected Project Overview\n\n" + "\n\n".join(sections)
    if len(content) > max_chars:
        content = content[:max_chars] + "\n..."
    return content
