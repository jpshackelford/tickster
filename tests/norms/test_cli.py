from datetime import date

import httpx
import pytest

from src.__main__ import main
from src.norms import source as norms_source
from src.norms.cli import cmd_check, cmd_init, cmd_show, cmd_upgrade
from src.norms.cli.commands import unmatched_globs
from src.norms.schema import MIGRATIONS, parse_norms
from tests.norms.conftest import ISSUE_EXAMPLE, git
from tests.norms.test_github import V1, FakeGitHub

TODAY = date(2026, 11, 5)


def norms_file(root):
    return root / ".agents" / "tickster.toml"


class TestInitTemplate:
    def test_writes_a_file_that_passes_strict_check(self, work_tree, capsys):
        assert cmd_init() == 0
        assert norms_file(work_tree).exists()
        assert cmd_check(strict=True) == 0
        out = capsys.readouterr()
        assert "ok (schema 1)" in out.out
        assert "Next steps" in out.out
        assert "commit" in out.out.lower()
        assert out.err == ""

    def test_template_documents_every_setting(self, work_tree):
        cmd_init()
        text = norms_file(work_tree).read_text()
        for key in (
            "agent_logins",
            "agent_disclosure",
            "bots",
            "stale",
            "count_reviews_from",
            "rerequest_labels",
            "ignore_checks",
            "ignore_paths",
            "min_changed_lines",
            "reports.manual_test",
            "impact_line",
            "only_paths",
        ):
            assert key in text

    def test_second_init_refuses_and_changes_nothing(self, work_tree, capsys):
        cmd_init()
        target = norms_file(work_tree)
        target.write_text("schema = 1\n# mine\n")
        assert cmd_init() == 1
        assert "already exists" in capsys.readouterr().err
        assert target.read_text() == "schema = 1\n# mine\n"

    def test_force_overwrites(self, work_tree):
        cmd_init()
        norms_file(work_tree).write_text("schema = 1\n# mine\n")
        assert cmd_init(force=True) == 0
        assert "# mine" not in norms_file(work_tree).read_text()

    def test_refusal_comes_before_any_fetch(self, work_tree, capsys):  # noqa: ARG002
        cmd_init()
        assert cmd_init(source="ext::sh -c id") == 1
        assert "already exists" in capsys.readouterr().err

    def test_outside_a_git_repo_exits_non_zero(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        assert cmd_init() == 1
        assert "not inside a git work tree" in capsys.readouterr().err
        assert not (tmp_path / ".agents").exists()

    def test_writes_at_the_work_tree_root_from_a_subdirectory(self, work_tree, monkeypatch):
        sub = work_tree / "a" / "b"
        sub.mkdir(parents=True)
        monkeypatch.chdir(sub)
        assert cmd_init() == 0
        assert norms_file(work_tree).exists()
        assert not (sub / ".agents").exists()

    def test_ref_and_path_need_from(self, work_tree, capsys):
        assert cmd_init(ref="main") == 1
        assert "--from" in capsys.readouterr().err
        assert not norms_file(work_tree).exists()

    def test_cli_wiring(self, work_tree, capsys):  # noqa: ARG002
        assert main(["norms", "init"]) == 0
        assert main(["norms", "init"]) == 1
        assert main(["norms", "check", "--strict"]) == 0
        assert main(["norms", "init", "--force"]) == 0
        capsys.readouterr()


class TestInitFrom:
    def test_local_file(self, work_tree, tmp_path):
        src = tmp_path / "preset.toml"
        src.write_text(ISSUE_EXAMPLE)
        assert cmd_init(source=str(src), today=TODAY) == 0
        text = norms_file(work_tree).read_text()
        assert text.splitlines()[0].startswith(f"# copied from {src} ({src}")
        assert "on 2026-11-05" in text.splitlines()[0]
        assert text.endswith(ISSUE_EXAMPLE)

    def test_local_directory_with_norms_file(self, work_tree, tmp_path):
        other = tmp_path / "other"
        (other / ".agents").mkdir(parents=True)
        (other / ".agents" / "tickster.toml").write_text(ISSUE_EXAMPLE)
        git(other, "init", "-q", "-b", "main")
        git(other, "add", ".")
        git(other, "commit", "-qm", "x")
        head = git(other, "rev-parse", "HEAD")
        assert cmd_init(source=str(other), today=TODAY) == 0
        header = norms_file(work_tree).read_text().splitlines()[0]
        assert f"@ {head[:7]}" in header

    def test_missing_local_source(self, work_tree, tmp_path, capsys):
        assert cmd_init(source=str(tmp_path / "nope")) == 1
        assert "not a github: source" in capsys.readouterr().err
        assert not norms_file(work_tree).exists()

    def test_file_url_default_branch(self, work_tree, source_repo):
        assert cmd_init(source=source_repo["url"], today=TODAY) == 0
        text = norms_file(work_tree).read_text()
        assert text.splitlines()[0] == (
            f"# copied from {source_repo['url']} (.agents/tickster.toml @ "
            f"{source_repo['second'][:7]}) on 2026-11-05"
        )
        assert 'stale = ["second"]' in text

    @pytest.mark.parametrize("ref", ["v1", "FIRST"])
    def test_file_url_with_tag_or_commit(self, work_tree, source_repo, ref):
        ref = source_repo["first"] if ref == "FIRST" else ref
        assert cmd_init(source=source_repo["url"], ref=ref, today=TODAY) == 0
        text = norms_file(work_tree).read_text()
        assert f"@ {source_repo['first'][:7]}" in text.splitlines()[0]
        assert "Manual Test Results" in text

    def test_file_url_with_branch(self, work_tree, source_repo):
        assert cmd_init(source=source_repo["url"], ref="feature") == 0
        assert f"@ {source_repo['second'][:7]}" in norms_file(work_tree).read_text()

    def test_file_url_with_path(self, work_tree, source_repo):
        assert cmd_init(source=source_repo["url"], path="presets/small.toml") == 0
        text = norms_file(work_tree).read_text()
        assert "(presets/small.toml @" in text.splitlines()[0]
        assert 'stale = ["wontfix"]' in text

    def test_file_url_with_path_and_ref(self, work_tree, source_repo):
        assert cmd_init(source=source_repo["url"], path="presets/small.toml", ref="v1") == 0
        assert f"@ {source_repo['first'][:7]}" in norms_file(work_tree).read_text()

    def test_github_source_copies_default_branch_file(self, work_tree, monkeypatch):
        api = FakeGitHub(V1)
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        real = norms_source.fetch_source
        monkeypatch.setattr(
            "src.norms.cli.commands.norms_source.fetch_source",
            lambda s, r: real(s, r, client=api.client()),
        )
        assert cmd_init(source="github:octo/hello", today=TODAY) == 0
        text = norms_file(work_tree).read_text()
        assert text.splitlines()[0] == (
            f"# copied from github:octo/hello (.agents/tickster.toml @ {'c' * 7}) on 2026-11-05"
        )
        assert text.endswith(V1)

    @pytest.mark.parametrize(
        ("status", "expected"),
        [(422, "ref 'NOSUCHREF' not found in the source"), (404, "GitHub returned HTTP 404")],
    )
    def test_github_http_errors_are_one_line(
        self, work_tree, monkeypatch, capsys, status, expected
    ):
        client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(status)))
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        real = norms_source.fetch_source
        monkeypatch.setattr(
            "src.norms.cli.commands.norms_source.fetch_source",
            lambda s, r: real(s, r, client=client),
        )
        assert cmd_init(source="github:octo/hello", ref="NOSUCHREF") == 1
        err = capsys.readouterr().err
        assert expected in err
        assert "mozilla" not in err and "developer." not in err
        assert len(err.strip().splitlines()) == 1
        assert not norms_file(work_tree).exists()

    @pytest.mark.parametrize("source", ["ext::sh -c id", "ftp://h/r.git", "http://h/r.git"])
    def test_rejected_transports_write_nothing(self, work_tree, source, capsys):
        assert cmd_init(source=source) == 1
        assert "not allowed" in capsys.readouterr().err
        assert not norms_file(work_tree).exists()

    def test_source_starting_with_dash_is_rejected(self, work_tree, capsys):
        assert main(["norms", "init", "--from=-oProxyCommand=evil"]) == 1
        assert "cannot start with '-'" in capsys.readouterr().err
        assert not norms_file(work_tree).exists()

    def test_newer_schema_source_is_refused(self, work_tree, tmp_path, capsys):
        src = tmp_path / "new.toml"
        src.write_text("schema = 2\n")
        assert cmd_init(source=str(src)) == 1
        assert "unknown (config schema 2; this tkt understands 1)" in capsys.readouterr().err
        assert not norms_file(work_tree).exists()

    def test_invalid_source_is_refused(self, work_tree, tmp_path, capsys):
        src = tmp_path / "bad.toml"
        src.write_text("[labels]\n")
        assert cmd_init(source=str(src)) == 1
        assert "schema" in capsys.readouterr().err
        assert not norms_file(work_tree).exists()

    def test_git_failure_is_reported(self, work_tree, tmp_path, capsys):  # noqa: ARG002
        assert cmd_init(source=f"file://{tmp_path}/missing.git") == 1
        assert "git fetch failed" in capsys.readouterr().err

    def test_error_output_hides_credentials(self, work_tree, tmp_path, capsys):  # noqa: ARG002
        assert cmd_init(source=f"file://user:s3cret@{tmp_path}/missing.git") == 1
        assert "s3cret" not in capsys.readouterr().err

    def test_warns_when_globs_match_nothing_in_target(self, work_tree, tmp_path, capsys):
        (work_tree / "src").mkdir()
        (work_tree / "src" / "app.py").write_text("x = 1\n")
        src = tmp_path / "p.toml"
        src.write_text(
            'schema = 1\n[commits]\nignore_paths = ["docs/**", "src/**"]\n'
            "[reports.manual_test]\nmarker = 'm'\nonly_paths = ['lib/**']\n"
        )
        assert cmd_init(source=str(src)) == 0
        err = capsys.readouterr().err
        assert "commits.ignore_paths: glob 'docs/**' matches no file" in err
        assert "reports.manual_test.only_paths: glob 'lib/**' matches no file" in err
        assert "src/**" not in err

    def test_unknown_key_warning_is_shown(self, work_tree, tmp_path, capsys):  # noqa: ARG002
        src = tmp_path / "p.toml"
        src.write_text("schema = 1\nfuture = 1\n")
        assert cmd_init(source=str(src)) == 0
        assert "future" in capsys.readouterr().err


def test_unmatched_globs_considers_untracked_files_but_not_ignored_ones(work_tree):
    (work_tree / ".gitignore").write_text("build/\n")
    (work_tree / "build").mkdir()
    (work_tree / "build" / "out.js").write_text("x")
    (work_tree / "keep.md").write_text("x")
    norms = parse_norms('schema = 1\n[commits]\nignore_paths = ["build/**", "**/*.md"]\n').norms
    assert norms is not None
    assert unmatched_globs(norms, work_tree) == [("commits.ignore_paths", "build/**")]


class TestCheck:
    def write(self, tmp_path, text):
        f = tmp_path / "t.toml"
        f.write_text(text)
        return str(f)

    def test_ok(self, tmp_path, capsys):
        assert cmd_check(self.write(tmp_path, ISSUE_EXAMPLE), strict=True) == 0
        assert "ok (schema 1)" in capsys.readouterr().out

    def test_directory_argument(self, tmp_path):
        (tmp_path / ".agents").mkdir()
        (tmp_path / ".agents" / "tickster.toml").write_text("schema = 1\n")
        assert cmd_check(str(tmp_path)) == 0

    def test_default_path_is_cwd_agents_file(self, work_tree, capsys):  # noqa: ARG002
        assert cmd_check() == 1
        assert "cannot read" in capsys.readouterr().err
        cmd_init()
        assert cmd_check() == 0

    @pytest.mark.parametrize(
        ("text", "needle"),
        [
            ("[labels]\n", "schema: missing required key"),
            ('schema = "1"\n', "schema: expected a positive integer"),
            ("schema = 7\n", "schema: unknown (config schema 7; this tkt understands 1)"),
            (
                "schema = 1\n[ci]\nignore_checks = 3\n",
                "ci.ignore_checks: expected a list of strings",
            ),
            ("schema = 1\n[reports.x]\nmarker = '('\n", "reports.x.marker: invalid regex"),
        ],
    )
    def test_errors_name_file_and_key(self, tmp_path, capsys, text, needle):
        path = self.write(tmp_path, text)
        assert cmd_check(path) == 1
        assert f"error: {path}: {needle}" in capsys.readouterr().err

    def test_unknown_key_is_a_warning_then_an_error_with_strict(self, tmp_path, capsys):
        path = self.write(tmp_path, "schema = 1\nfuture = 1\n")
        assert cmd_check(path) == 0
        assert f"warning: {path}: future: unknown key" in capsys.readouterr().err
        assert cmd_check(path, strict=True) == 1
        assert f"error: {path}: future: unknown key" in capsys.readouterr().err

    def test_repo_mode_reads_the_default_branch(self, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        api = FakeGitHub(ISSUE_EXAMPLE)
        assert cmd_check(repo="octo/hello", strict=True, client=api.client()) == 0
        assert "octo/hello:.agents/tickster.toml: ok" in capsys.readouterr().out

    def test_repo_mode_strict_flags_unknown_keys(self, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        api = FakeGitHub("schema = 1\nfuture = 1\n")
        assert cmd_check(repo="octo/hello", strict=True, client=api.client()) == 1
        assert "future" in capsys.readouterr().err

    def test_repo_mode_without_a_file(self, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        assert cmd_check(repo="octo/hello", client=FakeGitHub(None).client()) == 1
        assert "has no .agents/tickster.toml" in capsys.readouterr().err

    def test_repo_mode_missing_repo(self, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        client = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(404)))
        assert cmd_check(repo="octo/nope", client=client) == 1
        assert capsys.readouterr().err == (
            "error: repo not found, or not visible to this token: octo/nope\n"
        )

    def test_repo_mode_api_failure(self, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        client = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(500)))
        assert cmd_check(repo="octo/hello", client=client) == 1
        assert "cannot read" in capsys.readouterr().err


class TestShow:
    def test_prints_settings_and_blob_sha(self, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        api = FakeGitHub(ISSUE_EXAMPLE, sha="abc123")
        assert cmd_show("octo/hello", client=api.client()) == 0
        out = capsys.readouterr().out
        assert "blob abc123" in out
        assert '"all-hands-bot"' in out
        assert "[reports.manual_test.impact_line]" in out
        assert "codecov/*" in out

    def test_prints_the_label_rank(self, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        text = 'schema = 1\n[labels]\nrank = ["priority:high", "priority:low"]\n'
        assert cmd_show("octo/hello", client=FakeGitHub(text).client()) == 0
        assert 'rank = [\n    "priority:high",\n    "priority:low",\n]' in capsys.readouterr().out

    def test_no_file(self, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        assert cmd_show("octo/hello", client=FakeGitHub(None).client()) == 0
        assert "not configured" in capsys.readouterr().out

    def test_newer_schema_is_not_in_effect(self, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        assert cmd_show("octo/hello", client=FakeGitHub("schema = 5\n").client()) == 1
        captured = capsys.readouterr()
        assert "not in effect" in captured.out
        assert "config schema 5" in captured.err

    def test_api_failure(self, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        client = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(403)))
        assert cmd_show("octo/hello", client=client) == 1
        assert "cannot read" in capsys.readouterr().err

    def test_missing_repo_is_an_error_not_a_missing_file(self, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        client = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(404)))
        assert cmd_show("octo/nope", client=client) == 1
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err == "error: repo not found, or not visible to this token: octo/nope\n"

    def test_empty_repo_has_no_file(self, monkeypatch, capsys):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(409 if "/commits/" in request.url.path else 404)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        assert cmd_show("octo/empty", client=client) == 0
        assert "not configured" in capsys.readouterr().out

    def test_repo_with_the_file_makes_no_extra_request(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        api = FakeGitHub(ISSUE_EXAMPLE)
        assert cmd_show("octo/hello", client=api.client()) == 0
        assert [r.url.path for r in api.requests] == [
            "/repos/octo/hello/contents/.agents/tickster.toml"
        ]

    def test_repo_without_the_file_asks_whether_the_repo_exists(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        api = FakeGitHub(None)
        assert cmd_show("octo/hello", client=api.client()) == 0
        assert [r.url.path for r in api.requests] == [
            "/repos/octo/hello/contents/.agents/tickster.toml",
            "/repos/octo/hello/commits/HEAD",
        ]


class TestUpgrade:
    def test_current_schema_is_a_no_op(self, tmp_path, capsys):
        f = tmp_path / "t.toml"
        f.write_text("schema = 1\n")
        assert cmd_upgrade(str(f)) == 0
        assert "already at schema 1" in capsys.readouterr().err
        assert f.read_text() == "schema = 1\n"

    def test_newer_schema_is_refused(self, tmp_path, capsys):
        f = tmp_path / "t.toml"
        f.write_text("schema = 3\n")
        assert cmd_upgrade(str(f)) == 1
        assert "config schema 3" in capsys.readouterr().err

    def test_invalid_file(self, tmp_path, capsys):
        f = tmp_path / "t.toml"
        f.write_text("nope = 1\n")
        assert cmd_upgrade(str(f)) == 1
        assert "schema" in capsys.readouterr().err

    def test_missing_file(self, tmp_path, capsys):
        assert cmd_upgrade(str(tmp_path / "missing.toml")) == 1
        assert "cannot read" in capsys.readouterr().err

    @pytest.fixture
    def fake_v2(self, monkeypatch):
        def step(d):
            d = dict(d)
            d["ci"] = {"ignore_checks": d.pop("ignore_ci", [])}
            return d

        monkeypatch.setattr("src.norms.cli.commands.CURRENT_SCHEMA", 2)
        monkeypatch.setitem(MIGRATIONS, 1, step)

    def test_prints_migrated_file_without_writing(self, tmp_path, capsys, fake_v2):  # noqa: ARG002
        f = tmp_path / "t.toml"
        f.write_text('schema = 1\nignore_ci = ["a"]\n')
        assert cmd_upgrade(str(f)) == 0
        out = capsys.readouterr().out
        assert "schema = 2" in out and "[ci]" in out
        assert f.read_text() == 'schema = 1\nignore_ci = ["a"]\n'

    def test_write_flag_rewrites_the_file(self, tmp_path, capsys, fake_v2):  # noqa: ARG002
        f = tmp_path / "t.toml"
        f.write_text('schema = 1\nignore_ci = ["a"]\n')
        assert cmd_upgrade(str(f), write=True) == 0
        assert "schema = 2" in f.read_text()
        assert "Commit it" in capsys.readouterr().out

    def test_missing_step_is_an_error(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr("src.norms.cli.commands.CURRENT_SCHEMA", 2)
        f = tmp_path / "t.toml"
        f.write_text("schema = 1\n")
        assert cmd_upgrade(str(f)) == 1
        assert "no migration from schema 1 to 2" in capsys.readouterr().err
