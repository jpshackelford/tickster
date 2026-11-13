"""Parser-level tests for the `tkt board scan` date flag."""

from unittest.mock import patch

import pytest

from src.__main__ import main

REMOVED = "--since was removed: use --updated-since DAYS"


def test_updated_since_reaches_cmd_scan(capsys):
    # A mock is justified: the point under test is argument wiring; the real
    # path is covered by the cmd_scan integration tests.
    with patch("src.board.cli.cmd_scan", return_value=0) as scan:
        assert main(["board", "scan", "--updated-since", "21"]) == 0
    assert scan.call_args.kwargs["since_days"] == 21
    assert capsys.readouterr().out == ""


def test_no_flag_passes_none():
    with patch("src.board.cli.cmd_scan", return_value=0) as scan:
        main(["board", "scan"])
    assert scan.call_args.kwargs["since_days"] is None


def test_updated_since_zero_is_passed_through():
    with patch("src.board.cli.cmd_scan", return_value=0) as scan:
        main(["board", "scan", "--updated-since", "0"])
    assert scan.call_args.kwargs["since_days"] == 0


@pytest.mark.parametrize(
    "argv",
    [
        ["--since", "21"],
        ["--since=21"],
        ["--since"],
        ["--updated-since", "7", "--since", "21"],
    ],
)
def test_since_is_removed(argv, capsys):
    with patch("src.board.cli.cmd_scan", return_value=0) as scan, pytest.raises(SystemExit) as exc:
        main(["board", "scan", *argv])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert REMOVED in captured.err
    scan.assert_not_called()


@pytest.mark.parametrize("value", ["-1", "abc"])
def test_updated_since_rejects_bad_values(value, capsys):
    with patch("src.board.cli.cmd_scan", return_value=0) as scan, pytest.raises(SystemExit) as exc:
        main(["board", "scan", f"--updated-since={value}"])
    assert exc.value.code == 2
    assert "--updated-since" in capsys.readouterr().err
    scan.assert_not_called()


def test_help_lists_updated_since_but_not_since(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["board", "scan", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--updated-since" in out
    assert "--since " not in out
    assert "--since\n" not in out
