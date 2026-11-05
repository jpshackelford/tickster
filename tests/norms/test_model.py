import re

import pytest

from src.norms.model import (
    Actors,
    Labels,
    Norms,
    any_glob_match,
    glob_match,
    pattern_matches,
)


@pytest.mark.parametrize(
    ("glob", "text", "expected"),
    [
        ("docs/**", "docs/a/b.md", True),
        ("docs/**", "src/docs/a.md", False),
        ("**/*.md", "README.md", True),
        ("**/*.md", "a/b/c.md", True),
        ("*.md", "a/b.md", False),
        ("codecov/*", "codecov/patch", True),
        ("codecov/*", "codecov/patch/x", False),
        ("file?.py", "file1.py", True),
        ("file?.py", "file12.py", False),
        ("a.b", "axb", False),
    ],
)
def test_glob_match(glob, text, expected):
    assert glob_match(glob, text) is expected


def test_glob_match_case_insensitive_option():
    assert glob_match("All-Hands-*", "all-hands-bot", ignore_case=True)
    assert not glob_match("All-Hands-*", "all-hands-bot")


def test_any_glob_match_empty_is_false():
    assert not any_glob_match((), "anything")


def test_pattern_matches_only_first_200_chars():
    pattern = re.compile("needle")
    assert pattern_matches(pattern, "x" * 190 + "needle")
    assert not pattern_matches(pattern, "x" * 200 + "needle")


def test_norms_defaults_keep_stale_fallback():
    norms = Norms()
    assert norms.has_stale_label(["Stale"])
    assert not norms.has_stale_label(["bug"])


def test_empty_stale_list_disables():
    assert not Norms(labels=Labels(stale=())).has_stale_label(["stale"])


def test_actor_helpers_use_globs_case_insensitively():
    norms = Norms(actors=Actors(agent_logins=("My-Agent*",), bots=("ci-runner",)))
    assert norms.is_agent("my-agent-2")
    assert not norms.is_agent("someone")
    assert norms.is_listed_bot("CI-Runner")
