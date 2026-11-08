"""The JSON keys of `tkt pr show` and `tkt issue show` match the key tables in doc/usage.md."""

import re
from pathlib import Path

import pytest

from src.actors import ActorClass
from src.norms import store as norms_store
from src.show.issue import build_issue_show
from src.show.models import Entry
from src.show.pr import build_pr_show
from tests.show.builders import issue_node, pr_node

USAGE = Path(__file__).parents[2] / "doc" / "usage.md"
KEY_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|")


def key_tables(heading: str) -> list[set[str]]:
    """The backticked first-column names of each ``Key | Meaning`` table under a ``###`` heading."""
    lines = USAGE.read_text().splitlines()
    try:
        start = lines.index(f"### `{heading}`")
    except ValueError:
        pytest.fail(f"doc/usage.md has no '### `{heading}`' heading; this test finds tables by it")
    tables: list[set[str]] = []
    in_table = False
    for line in lines[start + 1 :]:
        if line.startswith("#"):
            break
        if re.match(r"^\|\s*Key\s*\|", line):
            tables.append(set())
            in_table = True
        elif in_table and (match := KEY_ROW.match(line)):
            tables[-1].add(match.group(1))
        elif not line.startswith("|"):
            in_table = False
    return tables


def assert_same_keys(actual: set[str], documented: set[str], where: str) -> None:
    missing, extra = sorted(actual - documented), sorted(documented - actual)
    assert not missing and not extra, (
        f"{where}: keys in the JSON but not in the doc: {missing}; "
        f"keys in the doc but not in the JSON: {extra}"
    )


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("GITHUB_USERNAME", "alice")
    norms_store.set_loader(lambda _repo: None)


def test_pr_show_top_level_keys_are_documented():
    show = build_pr_show(pr_node([]), "alice", 600)

    tables = key_tables("tkt pr show")

    assert len(tables) == 2, "expected a top-level key table and an event key table"
    assert_same_keys(set(show.to_dict()), tables[0], "tkt pr show")


def test_issue_show_top_level_keys_are_documented():
    show = build_issue_show(issue_node([]), "alice", 600)

    tables = key_tables("tkt issue show")

    assert len(tables) == 1, "expected one top-level key table"
    assert_same_keys(set(show.to_dict()), tables[0], "tkt issue show")


def test_event_keys_are_documented():
    entry = Entry("2026-11-05T10:00:00Z", "comment", "c", "bob", ActorClass.HUMAN, "commented")

    tables = key_tables("tkt pr show")

    assert_same_keys(set(entry.to_dict()), tables[1], "events")
