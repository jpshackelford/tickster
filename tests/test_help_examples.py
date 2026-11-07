"""Every ``tkt ...`` example in the ``--help`` epilog is accepted by the real parser."""

import argparse
import contextlib
import io

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
