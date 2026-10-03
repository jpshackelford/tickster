"""End-to-end CLI smoke tests for snapshot flag wiring in `tkt`."""

from __future__ import annotations

import pytest

from src.__main__ import main


@pytest.mark.parametrize(
    "argv",
    [
        ["pr", "list", "--snapshot", "x", "--watch", "y"],
        ["pr", "list", "--diff", "x", "--watch", "y"],
        ["issue", "list", "--snapshot", "x", "--watch", "y"],
        ["review", "--snapshot", "x", "--watch", "y"],
    ],
)
def test_watch_mutex_errors_cleanly_via_argparse(argv, capsys):
    # Expect argparse's SystemExit(2), not a bare Python traceback.
    with pytest.raises(SystemExit) as exc:
        main(argv)
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "--watch cannot be combined with --snapshot or --diff" in err
    # Should carry the standard argparse "usage:" preamble, proving it went
    # through parser.error rather than a raised ValueError bubbling up.
    assert "usage:" in err


def test_diff_include_unchanged_flag_parses(capsys):
    # Rename check: the new spelling parses. We expect this to fail *past*
    # argparse (missing GITHUB_TOKEN / network), but not with "unrecognized
    # arguments". Argparse exits 2 for unknown flags, so just assert the
    # error (if any) is not about our flag.
    try:
        main(["pr", "list", "--diff-include-unchanged", "--snapshot", "x"])
    except SystemExit:
        pass
    except Exception:
        pass
    captured = capsys.readouterr()
    assert "unrecognized arguments" not in captured.err
    assert "--diff-include-unchanged" not in captured.err or "unrecognized" not in captured.err
