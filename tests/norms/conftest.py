"""Shared fixtures for norms tests."""

import subprocess
from pathlib import Path

import pytest

from src.board import config as board_config

ISSUE_EXAMPLE = """\
schema = 1

[actors]
agent_logins = ["all-hands-bot", "openhands-agent"]
agent_disclosure = 'created by an AI agent \\(OpenHands\\)'
bots = []

[labels]
stale = ["stale"]

[review]
count_reviews_from = ["humans", "agents"]
rerequest_labels = ["review-this"]

[ci]
ignore_checks = ["codecov/*"]

[commits]
ignore_paths = ["docs/**", "**/*.md"]
min_changed_lines = 0

[reports.manual_test]
required = true
only_paths = []
marker = '^#+ *Manual Test Results'
fail = '❌ *FAIL'

[reports.manual_test.impact_line]
pattern = 'manual[- ]test impact:\\s*(none|re-?run)'
from = ["agents", "author"]
unassessed = "rerun"

[reports.docs_review]
required = false
marker = '^## Docs review'
"""


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture(autouse=True)
def tkt_home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "tkt-home"
    monkeypatch.setattr(board_config, "TKT_HOME", home)
    return home


@pytest.fixture
def work_tree(tmp_path, monkeypatch) -> Path:
    """An empty git work tree, entered as the current directory."""
    root = tmp_path / "target"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    monkeypatch.chdir(root)
    return root


@pytest.fixture
def source_repo(tmp_path) -> dict:
    """A bare repo reachable as file:// holding a norms file and a preset, with a tag and a branch."""
    work = tmp_path / "source-work"
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    (work / ".agents").mkdir()
    (work / "presets").mkdir()
    (work / ".agents" / "tickster.toml").write_text(ISSUE_EXAMPLE)
    (work / "presets" / "small.toml").write_text('schema = 1\n[labels]\nstale = ["wontfix"]\n')
    git(work, "add", ".")
    git(work, "commit", "-qm", "first")
    first = git(work, "rev-parse", "HEAD")
    git(work, "tag", "v1")
    (work / ".agents" / "tickster.toml").write_text('schema = 1\n[labels]\nstale = ["second"]\n')
    git(work, "commit", "-qam", "second")
    git(work, "branch", "feature", "HEAD")
    second = git(work, "rev-parse", "HEAD")
    bare = tmp_path / "source.git"
    git(tmp_path, "clone", "-q", "--bare", str(work), str(bare))
    return {"url": f"file://{bare}", "bare": bare, "first": first, "second": second}
