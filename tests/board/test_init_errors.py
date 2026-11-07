"""``tkt board init`` ends in one ``Error:`` line when GitHub fails (#75)."""

import httpx
import pytest

from src.board.cli import init
from tests.board.test_cli_smoke import mock_config_dir  # noqa: F401
from tests.board.test_graphql_retry import Handler, make_client

USER_OK = {"data": {"user": {"id": "U_1"}}}


def failing_on_mutation(failure: httpx.Response | Exception) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if "createProjectV2" in request.content.decode():
            if isinstance(failure, Exception):
                raise failure
            return failure
        return httpx.Response(200, json=USER_OK)

    return handler


@pytest.fixture
def run_init(mock_config_dir, monkeypatch, capsys):  # noqa: F811, ARG001
    def run(handler: Handler, **kwargs) -> tuple[int, str]:
        monkeypatch.setattr(init, "GitHubClient", lambda: make_client(handler))
        monkeypatch.setattr(init, "get_github_username", lambda: "bob")
        code = init.cmd_init(**kwargs)
        return code, capsys.readouterr().out

    return run


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (httpx.Response(502), "Error: GitHub returned HTTP 502 for POST /graphql"),
        (httpx.ReadTimeout("slow"), "Error: request to GitHub failed: ReadTimeout"),
        (
            httpx.Response(200, json={"data": None, "errors": [{"message": "boom"}]}),
            "Error: GraphQL errors: ['boom']",
        ),
    ],
)
def test_create_failure_is_one_error_line(run_init, failure, expected):
    code, out = run_init(failing_on_mutation(failure), create_name="X")

    assert code == 1
    assert expected in out
    assert "Traceback" not in out and "mozilla" not in out.lower()


def test_lookup_failure_by_project_number_is_one_error_line(run_init):
    code, out = run_init(lambda _: httpx.Response(502), project_number=5)

    assert code == 1
    assert "Error: GitHub returned HTTP 502" in out


def test_unknown_user_is_one_error_line(run_init):
    code, out = run_init(
        lambda _: httpx.Response(200, json={"data": {"user": None}}), create_name="X"
    )

    assert code == 1
    assert "Error: GitHub user not found: bob" in out
