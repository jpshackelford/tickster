"""`tkt repo` prints its errors to stderr, so stdout holds only results."""

from src.repo.cli.commands import cmd_add, cmd_remove


def test_add_without_repos_is_an_error_on_stderr(capsys):
    assert cmd_add([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "Error: No repos specified"


def test_add_with_an_invalid_repo_name_is_an_error_on_stderr(capsys):
    assert cmd_add(["notarepo"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "Error: Invalid repo format: notarepo (expected owner/repo)"


def test_remove_without_repos_is_an_error_on_stderr(capsys):
    assert cmd_remove([]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "Error: No repos specified"
