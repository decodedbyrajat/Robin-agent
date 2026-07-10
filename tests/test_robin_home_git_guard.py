"""Tests for the ROBIN_HOME-inside-git-worktree guard.

Root cause of the 2026-07-09 credential leak: the gateway ran with
ROBIN_HOME inside the project repo, so auth.json / session logs sat in a
committable path and a routine ``git add -A`` published them. The guard
warns and auto-gitignores the home when it detects this layout.
"""

import subprocess
import sys
from pathlib import Path

import pytest

import robin_constants
from robin_constants import (
    _find_enclosing_git_worktree,
    _guard_home_in_git_worktree,
    get_robin_home,
)


@pytest.fixture(autouse=True)
def _reset_guard_cache():
    robin_constants._home_guard_checked.clear()
    yield
    robin_constants._home_guard_checked.clear()


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


class TestFindEnclosingWorktree:
    def test_finds_repo_root(self, tmp_path):
        repo = _make_repo(tmp_path)
        nested = repo / "a" / "b"
        nested.mkdir(parents=True)
        assert _find_enclosing_git_worktree(nested) == repo.resolve()

    def test_none_outside_repo(self, tmp_path):
        assert _find_enclosing_git_worktree(tmp_path / "nope") is None


class TestGuard:
    def test_home_in_repo_gets_gitignored_and_warns(self, tmp_path, capsys):
        repo = _make_repo(tmp_path)
        home = repo / ".robin"
        home.mkdir()

        _guard_home_in_git_worktree(home)

        gitignore = (repo / ".gitignore").read_text()
        assert ".robin/" in gitignore.splitlines()
        assert "credentials" in capsys.readouterr().err

    def test_already_ignored_home_is_silent(self, tmp_path, capsys):
        repo = _make_repo(tmp_path)
        (repo / ".gitignore").write_text(".robin/\n")
        home = repo / ".robin"
        home.mkdir()

        _guard_home_in_git_worktree(home)

        assert capsys.readouterr().err == ""
        # No duplicate rule appended
        assert (repo / ".gitignore").read_text().count(".robin/") == 1

    def test_home_outside_repo_is_silent(self, tmp_path, capsys):
        home = tmp_path / "robin-home"
        home.mkdir()

        _guard_home_in_git_worktree(home)

        assert capsys.readouterr().err == ""

    def test_missing_home_is_silent(self, tmp_path, capsys):
        repo = _make_repo(tmp_path)

        _guard_home_in_git_worktree(repo / ".robin")  # never created

        assert capsys.readouterr().err == ""
        assert not (repo / ".gitignore").exists()

    def test_checked_once_per_process(self, tmp_path):
        repo = _make_repo(tmp_path)
        home = repo / ".robin"
        home.mkdir()

        _guard_home_in_git_worktree(home)
        (repo / ".gitignore").unlink()
        _guard_home_in_git_worktree(home)  # cached — must not re-append

        assert not (repo / ".gitignore").exists()

    def test_get_robin_home_invokes_guard(self, tmp_path, monkeypatch, capsys):
        repo = _make_repo(tmp_path)
        home = repo / ".robin"
        home.mkdir()
        monkeypatch.setenv("ROBIN_HOME", str(home))

        result = get_robin_home()

        assert result == home
        assert ".robin/" in (repo / ".gitignore").read_text()
