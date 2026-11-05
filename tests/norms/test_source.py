from datetime import date

import pytest

from src.norms import source as norms_source
from src.norms.gitfetch import GitFetchError, strip_credentials
from src.norms.source import Fetched, SourceError, fetch_source, parse_source, render_copy
from tests.norms.conftest import ISSUE_EXAMPLE, git
from tests.norms.test_github import V1, FakeGitHub

TODAY = date(2026, 11, 5)


class TestParseSource:
    def test_github_repo_defaults_to_norms_path(self):
        s = parse_source("github:octo/hello")
        assert (s.kind, s.repo, s.path) == ("github", "octo/hello", ".agents/tickster.toml")

    def test_github_inline_path(self):
        s = parse_source("github:octo/hello/presets/strict.toml")
        assert (s.repo, s.path) == ("octo/hello", "presets/strict.toml")

    def test_github_path_flag(self):
        assert parse_source("github:octo/hello", path="p/x.toml").path == "p/x.toml"

    def test_github_path_twice_is_an_error(self):
        with pytest.raises(SourceError, match="not both"):
            parse_source("github:octo/hello/a.toml", path="b.toml")

    def test_github_needs_owner_and_repo(self):
        with pytest.raises(SourceError, match="github:owner/repo"):
            parse_source("github:octo")

    @pytest.mark.parametrize(
        "url",
        [
            "https://host/org/repo.git",
            "ssh://git@host/org/repo.git",
            "git@host:org/repo.git",
            "git://host/org/repo.git",
            "file:///srv/git/repo.git",
        ],
    )
    def test_git_url_forms(self, url):
        s = parse_source(url, path="x/y.toml")
        assert (s.kind, s.url, s.path) == ("git", url, "x/y.toml")

    @pytest.mark.parametrize(
        ("source", "name"),
        [
            ("ext::sh -c id", "ext"),
            ("http://host/repo.git", "http"),
            ("ftp://host/repo.git", "ftp"),
            ("fd::17/repo", "fd"),
        ],
    )
    def test_other_transports_are_rejected(self, source, name):
        with pytest.raises(SourceError, match=f"transport '{name}' is not allowed"):
            parse_source(source)

    def test_leading_dash_is_rejected(self):
        with pytest.raises(SourceError, match="cannot start with '-'"):
            parse_source("--upload-pack=evil")
        with pytest.raises(SourceError, match="cannot start with '-'"):
            parse_source("-oProxyCommand=evil")

    def test_ref_leading_dash_is_rejected(self):
        with pytest.raises(SourceError, match="--ref"):
            parse_source("file:///x.git", ref="--upload-pack=evil")

    @pytest.mark.parametrize("path", ["/etc/passwd", "../x.toml", "a/../../x", "-x"])
    def test_bad_paths_are_rejected(self, path):
        with pytest.raises(SourceError, match="--path"):
            parse_source("file:///x.git", path=path)

    def test_local_file_and_dir(self, tmp_path):
        f = tmp_path / "n.toml"
        f.write_text("schema = 1\n")
        assert parse_source(str(f)).local == f
        assert parse_source(str(tmp_path)).local == tmp_path / ".agents" / "tickster.toml"

    def test_local_rejects_ref_and_path(self, tmp_path):
        with pytest.raises(SourceError, match="do not apply"):
            parse_source(str(tmp_path), ref="main")
        with pytest.raises(SourceError, match="do not apply"):
            parse_source(str(tmp_path), path="x")

    def test_unknown_source(self, tmp_path):
        with pytest.raises(SourceError, match="not a github: source"):
            parse_source(str(tmp_path / "nope"))


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://user:pw@host/o/r.git", "https://host/o/r.git"),
        ("https://token@host/o/r.git", "https://host/o/r.git"),
        ("ssh://git@host/o/r.git", "ssh://git@host/o/r.git"),
        ("ssh://git:pw@host/o/r.git", "ssh://git@host/o/r.git"),
        ("git@host:o/r.git", "git@host:o/r.git"),
        ("file:///srv/r.git", "file:///srv/r.git"),
        ("https://host/o/r.git", "https://host/o/r.git"),
    ],
)
def test_strip_credentials(url, expected):
    assert strip_credentials(url) == expected


def test_label_never_contains_credentials():
    assert parse_source("https://user:s3cret@host/o/r.git").label == "https://host/o/r.git"


class TestFetchGitHub:
    @pytest.fixture(autouse=True)
    def token(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")

    def test_default_branch_file(self):
        api = FakeGitHub(V1)
        fetched = fetch_source(parse_source("github:octo/hello"), None, client=api.client())
        assert fetched == Fetched(V1, "github:octo/hello", ".agents/tickster.toml", "c" * 40)
        assert api.requests[0].url.path.endswith("/commits/HEAD")
        assert api.requests[1].url.path.endswith("/contents/.agents/tickster.toml")
        assert api.requests[1].url.params["ref"] == "c" * 40

    def test_explicit_path_and_ref(self):
        api = FakeGitHub(V1)
        source = parse_source("github:octo/hello/presets/strict.toml")
        fetched = fetch_source(source, "v1", client=api.client())
        assert api.requests[0].url.path.endswith("/commits/v1")
        assert api.requests[1].url.path.endswith("/contents/presets/strict.toml")
        assert fetched.path == "presets/strict.toml"

    def test_missing_file(self):
        api = FakeGitHub(None)
        # commits endpoint answers; contents 404s
        with pytest.raises(SourceError, match="not found in octo/hello"):
            fetch_source(parse_source("github:octo/hello"), None, client=api.client())


class TestFetchGit:
    def test_default_branch(self, source_repo):
        fetched = fetch_source(parse_source(source_repo["url"]), None)
        assert fetched.commit == source_repo["second"]
        assert 'stale = ["second"]' in fetched.text

    def test_path_flag(self, source_repo):
        fetched = fetch_source(parse_source(source_repo["url"], path="presets/small.toml"), None)
        assert 'stale = ["wontfix"]' in fetched.text
        assert fetched.path == "presets/small.toml"

    @pytest.mark.parametrize("ref", ["v1", None])
    def test_tag_and_branch_refs(self, source_repo, ref):
        fetched = fetch_source(parse_source(source_repo["url"], ref=ref), ref or "feature")
        assert fetched.commit == (source_repo["first"] if ref == "v1" else source_repo["second"])

    def test_commit_sha_ref(self, source_repo):
        fetched = fetch_source(parse_source(source_repo["url"]), source_repo["first"])
        assert fetched.commit == source_repo["first"]
        assert "Manual Test Results" in fetched.text

    def test_unknown_ref(self, source_repo):
        with pytest.raises(GitFetchError):
            fetch_source(parse_source(source_repo["url"]), "no-such-ref")

    def test_missing_path(self, source_repo):
        with pytest.raises(GitFetchError, match="not found in the source"):
            fetch_source(parse_source(source_repo["url"], path="nope.toml"), None)

    def test_error_text_hides_credentials(self, tmp_path):
        url = f"file://user:s3cret@{tmp_path}/missing.git"
        with pytest.raises(GitFetchError) as exc:
            fetch_source(parse_source(url), None)
        assert "s3cret" not in str(exc.value)


class TestFetchLocal:
    def test_file_inside_a_git_repo_records_head(self, tmp_path):
        git(tmp_path, "init", "-q", "-b", "main")
        f = tmp_path / "n.toml"
        f.write_text("schema = 1\n")
        git(tmp_path, "add", ".")
        git(tmp_path, "commit", "-qm", "x")
        fetched = fetch_source(parse_source(str(f)), None)
        assert fetched.commit == git(tmp_path, "rev-parse", "HEAD")

    def test_file_outside_git_has_no_commit(self, tmp_path):
        f = tmp_path / "n.toml"
        f.write_text("schema = 1\n")
        assert fetch_source(parse_source(str(f)), None).commit is None

    def test_vanished_file(self, tmp_path):
        source = parse_source(str(tmp_path))
        with pytest.raises(SourceError, match="does not exist"):
            fetch_source(source, None)


class TestRenderCopy:
    def fetched(self, text, commit="5ff5fbb" + "0" * 33):
        return Fetched(text, "github:octo/hello", ".agents/tickster.toml", commit)

    def test_header_and_verbatim_body(self):
        text, notes = render_copy(self.fetched(ISSUE_EXAMPLE), TODAY)
        assert text.splitlines()[0] == (
            "# copied from github:octo/hello (.agents/tickster.toml @ 5ff5fbb) on 2026-11-05"
        )
        assert text.endswith(ISSUE_EXAMPLE)
        assert notes == []

    def test_no_commit_omits_the_sha(self):
        text, _ = render_copy(self.fetched("schema = 1\n", commit=None), TODAY)
        assert text.splitlines()[0] == (
            "# copied from github:octo/hello (.agents/tickster.toml) on 2026-11-05"
        )

    def test_previous_copy_header_is_replaced(self):
        once, _ = render_copy(self.fetched("schema = 1\n"), TODAY)
        twice, _ = render_copy(self.fetched(once), date(2027, 1, 1))
        assert twice.count("# copied from") == 1
        assert "2027-01-01" in twice

    def test_newer_schema_is_refused(self):
        with pytest.raises(
            SourceError, match=r"unknown \(config schema 2; this tkt understands 1\)"
        ):
            render_copy(self.fetched("schema = 2\n"), TODAY)

    def test_older_schema_is_migrated_and_written_at_current(self):
        def step(d):
            d = dict(d)
            d["ci"] = {"ignore_checks": d.pop("ignore_ci", [])}
            return d

        steps = {1: step}
        src = 'schema = 1\n# a comment\nignore_ci = ["x/*"]\n'
        text, notes = render_copy(self.fetched(src), TODAY, current_schema=2, migrations=steps)
        assert "schema = 2" in text
        assert '"x/*"' in text.split("[ci]")[1]
        assert "ignore_ci" not in text
        assert any("migrated from schema 1 to 2" in n.message for n in notes)

    def test_missing_migration_is_refused(self):
        with pytest.raises(SourceError, match="no migration"):
            render_copy(self.fetched("schema = 1\n"), TODAY, current_schema=2, migrations={})

    @pytest.mark.parametrize(
        "text", ["nope", "[labels]\nstale = []\n", "schema = 1\n[actors]\nbots = 5\n"]
    )
    def test_invalid_source_is_refused(self, text):
        with pytest.raises(SourceError):
            render_copy(self.fetched(text), TODAY)

    def test_unknown_keys_are_kept_with_a_warning(self):
        text, notes = render_copy(self.fetched("schema = 1\nfuture = 1\n"), TODAY)
        assert "future = 1" in text
        assert [n.key for n in notes] == ["future"]


def test_module_exposes_source_error():
    assert issubclass(norms_source.SourceError, ValueError)
