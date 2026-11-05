import base64
import json

import httpx
import pytest

from src.norms import github
from src.norms.store import github_loader, load_repo_norms

REPO = "octo/hello"
V1 = 'schema = 1\n[labels]\nstale = ["old"]\n'
V2 = 'schema = 1\n[labels]\nstale = ["newer"]\n'


class FakeGitHub:
    """A tiny contents/commits API with one file on the default branch."""

    def __init__(self, text: str | None, sha: str = "blob1"):
        self.text = text
        self.sha = sha
        self.requests: list[httpx.Request] = []

    def etag(self) -> str:
        return f'"{self.sha}"'

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/commits/HEAD") or "/commits/" in path:
            return httpx.Response(200, text="c" * 40)
        if self.text is None:
            return httpx.Response(404, json={"message": "Not Found"})
        if request.headers.get("if-none-match") == self.etag():
            return httpx.Response(304)
        body = {
            "sha": self.sha,
            "encoding": "base64",
            "content": base64.b64encode(self.text.encode()).decode(),
        }
        return httpx.Response(200, json=body, headers={"etag": self.etag()})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))


def test_reads_default_branch_without_sending_a_ref():
    api = FakeGitHub(V1)
    file = github.fetch_default_branch_file(REPO, "tok", client=api.client())
    assert file is not None
    assert file.text == V1
    assert file.blob_sha == "blob1"
    request = api.requests[0]
    assert request.url.path == f"/repos/{REPO}/contents/.agents/tickster.toml"
    assert "ref" not in request.url.params
    assert request.headers["authorization"] == "Bearer tok"


def test_unchanged_blob_is_served_from_cache_via_304():
    api = FakeGitHub(V1)
    github.fetch_default_branch_file(REPO, "tok", client=api.client())
    again = github.fetch_default_branch_file(REPO, "tok", client=api.client())
    assert again is not None and again.text == V1
    assert api.requests[1].headers["if-none-match"] == '"blob1"'
    assert json.loads(github.cache_path(REPO).read_text())["sha"] == "blob1"


def test_changed_blob_sha_replaces_the_cached_file():
    api = FakeGitHub(V1)
    github.fetch_default_branch_file(REPO, "tok", client=api.client())
    api.text, api.sha = V2, "blob2"
    file = github.fetch_default_branch_file(REPO, "tok", client=api.client())
    assert file is not None
    assert (file.text, file.blob_sha) == (V2, "blob2")
    assert json.loads(github.cache_path(REPO).read_text())["text"] == V2


def test_same_sha_with_new_etag_keeps_cached_text():
    api = FakeGitHub(V1)
    github.fetch_default_branch_file(REPO, "tok", client=api.client())
    cache = json.loads(github.cache_path(REPO).read_text())
    cache["etag"] = '"stale-etag"'
    github.cache_path(REPO).write_text(json.dumps(cache))
    file = github.fetch_default_branch_file(REPO, "tok", client=api.client())
    assert file is not None and file.text == V1
    assert json.loads(github.cache_path(REPO).read_text())["etag"] == '"blob1"'


def test_missing_file_returns_none_and_drops_cache():
    api = FakeGitHub(V1)
    github.fetch_default_branch_file(REPO, "tok", client=api.client())
    api.text = None
    assert github.fetch_default_branch_file(REPO, "tok", client=api.client()) is None
    assert not github.cache_path(REPO).exists()


def test_server_error_raises():
    client = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(500)))
    with pytest.raises(httpx.HTTPStatusError):
        github.fetch_default_branch_file(REPO, "tok", client=client)


def test_non_inline_content_is_an_error():
    def handler(_r):
        return httpx.Response(200, json={"sha": "s", "encoding": "none", "content": ""})

    with pytest.raises(httpx.HTTPError, match="not returned inline"):
        github.fetch_default_branch_file(
            REPO, "tok", client=httpx.Client(transport=httpx.MockTransport(handler))
        )


def test_resolve_commit_and_fetch_file_at_use_the_ref():
    api = FakeGitHub(V1)
    client = api.client()
    sha = github.resolve_commit(REPO, None, "tok", client=client)
    assert sha == "c" * 40
    assert api.requests[0].url.path.endswith("/commits/HEAD")
    assert api.requests[0].headers["accept"] == "application/vnd.github.sha"
    github.resolve_commit(REPO, "v1", "tok", client=client)
    assert api.requests[1].url.path.endswith("/commits/v1")
    text = github.fetch_file_at(REPO, "presets/a.toml", sha, "tok", client=client)
    assert text == V1
    assert api.requests[2].url.params["ref"] == sha
    api.text = None
    assert github.fetch_file_at(REPO, "x.toml", sha, "tok", client=client) is None


def test_load_repo_norms_parses_and_reports_blob():
    api = FakeGitHub(V1, sha="abc")
    found = load_repo_norms(REPO, "tok", client=api.client())
    assert found.blob_sha == "abc"
    assert found.text == V1
    assert found.result is not None and found.result.norms is not None
    assert found.result.norms.labels.stale == ("old",)
    assert load_repo_norms(REPO, "tok", client=FakeGitHub(None).client()).result is None


def test_github_loader_returns_norms_and_warns_on_unknown_keys(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    api = FakeGitHub("schema = 1\nfuture = 1\n")
    norms = github_loader(REPO, client=api.client())
    assert norms is not None
    err = capsys.readouterr().err
    assert "octo/hello" in err and "future" in err


def test_github_loader_newer_schema_is_not_fatal(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    api = FakeGitHub("schema = 99\n")
    assert github_loader(REPO, client=api.client()) is None
    assert "unknown (config schema 99; this tkt understands 1)" in capsys.readouterr().err


def test_github_loader_without_file_is_silent(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    assert github_loader(REPO, client=FakeGitHub(None).client()) is None
    assert capsys.readouterr().err == ""


def test_github_loader_survives_api_errors(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    client = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(500)))
    assert github_loader(REPO, client=client) is None
    assert "could not read" in capsys.readouterr().err


def test_github_loader_ignores_non_repo_names():
    assert github_loader("not-a-repo") is None
