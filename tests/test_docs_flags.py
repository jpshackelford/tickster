"""The 1.x date flags stay out of the docs and ``--help`` except where they are named on purpose."""

import contextlib
import io
import re
from pathlib import Path

import pytest

from src.__main__ import main

ROOT = Path(__file__).resolve().parent.parent
OLD_FLAG = re.compile(r"--(?:since|after|before|date-field)\b(?!-(?:snapshot|time|sha)\b)")
UPGRADE_HEADING = "## Upgrading to 2.0"
ALLOWED_LINES = ("tkt pr changes --since SHA: what changed",)

HELP_COMMANDS = [
    [],
    ["issue"],
    ["issue", "list"],
    ["issue", "show"],
    ["pr"],
    ["pr", "list"],
    ["pr", "show"],
    ["pr", "changes"],
    ["pr", "checks"],
    ["pr", "steps"],
    ["review"],
    ["board"],
    ["board", "scan"],
    ["repo"],
    ["snapshot"],
    ["norms"],
]


def _without_upgrade_section(text: str) -> str:
    start = text.find(UPGRADE_HEADING)
    if start == -1:
        return text
    end = text.find("\n## ", start + len(UPGRADE_HEADING))
    return text[:start] + ("" if end == -1 else text[end:])


def _old_flag_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if OLD_FLAG.search(line) and not any(allowed in line for allowed in ALLOWED_LINES)
    ]


def _help_text(argv: list[str]) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), pytest.raises(SystemExit) as exit_info:
        main([*argv, "--help"])
    assert exit_info.value.code == 0
    return out.getvalue()


DOCS = [ROOT / "README.md", *sorted((ROOT / "doc").glob("*.md"))]


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
def test_docs_have_no_old_date_flags(path):
    text = _without_upgrade_section(path.read_text())

    assert _old_flag_lines(text) == []


@pytest.mark.parametrize("argv", HELP_COMMANDS, ids=lambda a: " ".join(a) or "tkt")
def test_help_has_no_old_date_flags(argv):
    assert _old_flag_lines(_help_text(argv)) == []


def test_guard_pattern_flags_old_spellings_and_keeps_new_ones():
    old = "--since 14 --after D --before D --date-field F --since=3"
    new = "--since-time T --since-sha S --created-since 14 --updated-after D"

    assert len(OLD_FLAG.findall(old)) == 5
    assert OLD_FLAG.findall(new) == []


def test_usage_guide_has_upgrade_and_recipe_sections():
    usage = (ROOT / "doc" / "usage.md").read_text()
    headings = re.findall(r"^## .*$", usage, flags=re.MULTILINE)
    recipes = usage[usage.index("## Recipes") :]

    assert UPGRADE_HEADING in headings
    assert "## Recipes" in headings
    assert "- [Upgrading to 2.0](#upgrading-to-20)" in usage
    assert "- [Recipes](#recipes)" in usage
    assert "tkt issue list --all --created-since 14 --title" in recipes.split("\n## ")[0]


def test_upgrade_section_names_every_stub_message():
    usage = (ROOT / "doc" / "usage.md").read_text()
    start = usage.index(UPGRADE_HEADING)
    section = usage[start : usage.index("\n## ", start + 1)]

    for message in (
        "--since was removed: use --created-since N, --updated-since N or --closed-since N",
        "--after was removed: use --created-after D, --updated-after D or --closed-after D",
        "--before was removed: use --created-before D, --updated-before D or --closed-before D",
        "--date-field was removed: put the field in the flag name, for example --created-since N",
        "--since was removed on show: use --since-time TS",
        "--since was removed on pr changes: use --since-sha SHA",
        "--since was removed: use --updated-since DAYS",
    ):
        assert message in section


OLD_ROW_NAMES = ("ci_status", "is_draft", "head_sha", "unresolved_thread_count")


@pytest.mark.parametrize("doc", ["usage.md", "automation.md"])
def test_the_old_row_field_names_appear_nowhere_in_the_docs(doc):
    text = (ROOT / "doc" / doc).read_text()
    assert [name for name in OLD_ROW_NAMES if f"`{name}`" in text] == []
