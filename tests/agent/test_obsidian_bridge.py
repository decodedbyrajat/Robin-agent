import tempfile
from pathlib import Path
import pytest
from agent.obsidian_bridge import ObsidianBridge, ObsidianNote


def test_frontmatter_parsing_and_serialization():
    content = """---
title: System Topology
status: active
tags:
  - architecture
  - backend
---

# Architecture Overview

> [!abstract] Executive Summary
> This note describes the system components.

Here is a reference to [[Database Schema|DB]] and #infrastructure.
"""
    fm, body = ObsidianBridge.parse_frontmatter(content)
    assert fm["title"] == "System Topology"
    assert fm["status"] == "active"
    assert fm["tags"] == ["architecture", "backend"]
    assert "# Architecture Overview" in body

    # Serialization check
    serialized = ObsidianBridge.serialize_frontmatter(fm, body)
    assert serialized.startswith("---")
    assert "title: System Topology" in serialized
    assert "  - architecture" in serialized


def test_wikilinks_and_callout_extraction():
    text = """> [!tip] Safety Rule
Always snapshot before updating.

Refer to [[00 🧭 Dashboard]] and [[01 🚀 Projects/Robin Agent Architecture|Architecture]].
"""
    callouts = ObsidianBridge.extract_callouts(text)
    assert len(callouts) == 1
    assert callouts[0][0] == "tip"
    assert callouts[0][1] == "Safety Rule"

    wikilinks = ObsidianBridge.extract_wikilinks(text)
    assert len(wikilinks) == 2
    assert "00 🧭 Dashboard" in wikilinks
    assert "01 🚀 Projects/Robin Agent Architecture" in wikilinks


def test_vault_read_write_search():
    with tempfile.TemporaryDirectory() as temp_dir:
        bridge = ObsidianBridge(vault_path=temp_dir)
        assert bridge.is_vault_available()

        # Write a note
        note_path = bridge.write_note(
            relative_path="01 Projects/Demo.md",
            title="Demo Project",
            body="This is a test project with #demo tag and [[Other Note]].\n\n> [!abstract] Goals\nBuild Phase 3.",
            tags=["demo", "phase3"],
        )
        assert Path(note_path).exists()

        # Read note back
        note = bridge.read_note("01 Projects/Demo.md")
        assert note is not None
        assert note.title == "Demo Project"
        assert "demo" in note.tags
        assert "phase3" in note.tags
        assert "Other Note" in note.wikilinks
        assert len(note.callouts) == 1
        assert note.callouts[0][0] == "abstract"

        # Search vault
        search_results = bridge.search_vault("phase 3")
        assert len(search_results) == 1
        assert search_results[0].title == "Demo Project"

        # Search with tag filter
        tagged_results = bridge.search_vault("test", tag="demo")
        assert len(tagged_results) == 1

        # Search with non-matching tag
        empty_results = bridge.search_vault("test", tag="production")
        assert len(empty_results) == 0
