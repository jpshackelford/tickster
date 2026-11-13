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


def _start_now_help() -> str:
    return _issue_list_help().partition("Which issues can I start now?")[2]


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
    text = _start_now_help() if source == "help" else _recipe_section()
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


def _examples_block(help_text: str) -> list[str]:
    block = help_text.partition("Examples")[2].partition("Which issues can I start now?")[0]
    return [line.strip() for line in block.splitlines() if line.strip().startswith("tkt ")]


def _command_and_question(line: str) -> tuple[str, str]:
    command, _, question = line.partition("  ")
    return command, question.strip()


NO_PR_RECIPE = "tkt issue list --all --created-since 14 --no-pr --title"


def test_issue_list_help_has_question_shaped_examples():
    lines = _examples_block(_issue_list_help())
    assert len(lines) >= 4
    for line in lines:
        command, question = _command_and_question(line)
        assert command.startswith("tkt issue list")
        assert question.endswith("?")


def test_issue_list_help_examples_parse(monkeypatch):
    for line in _examples_block(_issue_list_help()):
        command, _ = _command_and_question(line)
        namespace = _parse_issue_list(monkeypatch, command.split()[1:])
        assert namespace.command == "issue"
        assert namespace.issue_command == "list"


def test_issue_list_help_has_the_no_pr_and_json_recipes():
    commands = [_command_and_question(line)[0] for line in _examples_block(_issue_list_help())]
    assert NO_PR_RECIPE in commands
    assert "tkt issue list --repo octocat/hello-world --all-authors --format json" in commands


def test_root_epilog_has_the_no_pr_recipe(monkeypatch):
    assert NO_PR_RECIPE in EXAMPLES
    namespace = _parse_issue_list(monkeypatch, NO_PR_RECIPE.split()[1:])
    assert namespace.created_since == 14
    assert namespace.pr_filter == "no-pr"
    assert namespace.all_states


def test_usage_recipes_parse_with_the_real_parser(monkeypatch):
    commands = [
        argv[: argv.index("|")] if "|" in argv else argv
        for argv in _commands(_recipe_section_all())
    ]
    assert NO_PR_RECIPE.split()[1:] in commands
    for argv in commands:
        namespace = _parse_issue_list(monkeypatch, argv)
        assert namespace.command in {"issue", "pr"}


def _recipe_section_all() -> str:
    usage = (Path(__file__).parent.parent / "doc" / "usage.md").read_text()
    _, _, rest = usage.partition("\n## Recipes\n")
    return rest.partition("\n## ")[0]


def _flat(text: str) -> str:
    return " ".join(text.split())


@pytest.mark.parametrize(
    "phrase",
    [
        "--created-since DAYS Only issues created since the start of the UTC day N days ago",
        "Linked = a PR closes or mentions the issue, in any state",
        "one document on stdout and nothing else: schema, filters, total_count, has_more and items",
    ],
)
def test_option_help_states_the_field_or_definition(phrase):
    assert phrase in _flat(_issue_list_help())


def test_all_flag_is_explained_wherever_the_recipe_uses_it():
    assert "Without --all, --open or --closed, only open issues are listed" in _flat(
        _issue_list_help()
    )
    assert "--all includes closed issues. Without it" in _flat(_issue_list_help())
    root = io.StringIO()
    with contextlib.redirect_stdout(root), pytest.raises(SystemExit):
        main(["--help"])
    assert "(--all adds closed ones)" in _flat(root.getvalue())
    assert "leave it out and only open issues are listed" in _flat(_recipe_section_all())


def test_recipes_in_usage_name_the_linked_definition():
    assert "closes or mentions" in _flat(_recipe_section_all())
