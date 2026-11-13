"""Every ``tkt ...`` example in the ``--help`` epilog is accepted by the real parser."""

import argparse
import contextlib
import io
import re
from pathlib import Path

import pytest

from src.__main__ import main


class _Parsed(Exception):
    def __init__(self, namespace: argparse.Namespace) -> None:
        self.namespace = namespace


def _epilog_examples() -> list[str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), pytest.raises(SystemExit):
        main(["--help"])
    _, _, examples = out.getvalue().partition("Examples:")
    return [
        line.strip().split("  ")[0]
        for line in examples.splitlines()
        if line.strip().startswith("tkt ")
    ]


EXAMPLES = _epilog_examples()


def test_epilog_lists_examples():
    assert len(EXAMPLES) >= 5


@pytest.mark.parametrize("example", EXAMPLES)
def test_epilog_example_parses(example, monkeypatch):
    original = argparse.ArgumentParser.parse_args

    def parse_then_stop(self, args=None, namespace=None):
        raise _Parsed(original(self, args, namespace))

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", parse_then_stop)
    argv = example.split()[1:]

    with pytest.raises(_Parsed) as parsed:
        main(argv)

    assert parsed.value.namespace.command == argv[0]


def _commands(text: str) -> list[list[str]]:
    joined = text.replace("\\\n", " ")
    return [line.split()[1:] for line in joined.splitlines() if line.strip().startswith("tkt ")]


def _issue_list_help() -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), pytest.raises(SystemExit):
        main(["issue", "list", "--help"])
    return out.getvalue()


def _recipe_section() -> str:
    usage = (Path(__file__).parent.parent / "doc" / "usage.md").read_text()
    _, _, rest = usage.partition("### Which issues can I start now?")
    return rest.partition("\n### ")[0]


def _parse_issue_list(monkeypatch, argv: list[str]) -> argparse.Namespace:
    original = argparse.ArgumentParser.parse_args

    def parse_then_stop(self, args=None, namespace=None):
        raise _Parsed(original(self, args, namespace))

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", parse_then_stop)
    with pytest.raises(_Parsed) as parsed:
        main(argv)
    return parsed.value.namespace


def test_issue_list_help_shows_the_start_now_recipe():
    help_text = _issue_list_help().replace("\\\n", " ")
    assert (
        "tkt issue list --all-authors -l ready --not-label hold --unblocked --no-pr "
        "--sort rank,blocking,number --limit 2 --format json" in " ".join(help_text.split())
    )


@pytest.mark.parametrize("source", ["help", "usage"])
def test_start_now_recipe_commands_parse(monkeypatch, source):
    text = _issue_list_help() if source == "help" else _recipe_section()
    commands = _commands(text)
    assert len(commands) == 2
    for argv in commands:
        namespace = _parse_issue_list(monkeypatch, argv)
        assert namespace.issue_command == "list"
        assert namespace.output_format == "json"


def test_usage_recipe_names_only_flags_of_issue_list():
    flags = set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", _recipe_section()))
    assert {"--unblocked", "--blocked", "--no-pr", "--not-label", "--sort"} <= flags
    help_text = _issue_list_help()
    assert [flag for flag in sorted(flags) if flag not in help_text] == []
