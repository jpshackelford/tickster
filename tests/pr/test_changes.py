"""Tests for `tkt pr changes`: compare paging, significance rules and CLI output."""

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from src.__main__ import main
from src.board.github_api import GitHubClient
from src.pr.changes import (
    REASON_REWRITTEN,
    REASON_TOO_LARGE,
    REASON_UNCHANGED,
    ChangedCommit,
    ChangedFile,
    ChangesClient,
    Compare,
    assess,
    pr_changes,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "compare_tickster_2b09310_f41cd83.json").read_text()
)
SINCE = "2b09310abcdef"
HEAD = "f41cd838ab430067f143e547283090565f2c4b89"


def _commit(sha: str, *, merge: bool = False) -> ChangedCommit:
    return ChangedCommit(sha, f"commit {sha}", "alice", "2026-11-05T10:00:00Z", merge)


def _file(path: str, add: int = 1, delete: int = 0) -> ChangedFile:
    return ChangedFile(path, "modified", add, delete)


def _api_commit(sha: str, parents: int = 1) -> dict:
    return {
        "sha": sha,
        "parents": [{"sha": f"p{i}"} for i in range(parents)],
        "author": None,
        "commit": {"message": f"msg {sha}\n\nbody", "author": {"name": "Bob", "date": "d"}},
    }


def _api_file(path: str, add: int = 1, delete: int = 0) -> dict:
    return {"filename": path, "status": "modified", "additions": add, "deletions": delete}


class FakeGitHub:
    """Serves the PR and compare REST endpoints through a real httpx client."""

    def __init__(self, compare_pages: list[dict] | None = None, compare_status: int = 200):
        self.compare_pages = compare_pages if compare_pages is not None else [FIXTURE]
        self.compare_status = compare_status
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/pulls/7"):
            return httpx.Response(200, json={"head": {"sha": HEAD}})
        if path.endswith("/pulls/404"):
            return httpx.Response(404, json={"message": "Not Found"})
        if "/compare/" in path:
            if self.compare_status != 200:
                return httpx.Response(self.compare_status, json={"message": "nope"})
            page = int(request.url.params["page"])
            return httpx.Response(
                200, json=self.compare_pages[min(page, len(self.compare_pages)) - 1]
            )
        return httpx.Response(500)

    @property
    def compare_calls(self) -> list[httpx.Request]:
        return [r for r in self.requests if "/compare/" in r.url.path]

    def client(self) -> ChangesClient:
        gh = GitHubClient.__new__(GitHubClient)
        gh._client = httpx.Client(transport=httpx.MockTransport(self.handle))
        client = ChangesClient.__new__(ChangesClient)
        client._client = gh
        return client


def _page(commits: list[dict], files: list[dict], status: str = "ahead") -> dict:
    return {"status": status, "commits": commits, "files": files}


class TestAssess:
    def test_no_norms_every_non_merge_change_is_significant(self):
        compare = Compare("ahead", [_commit("a")], [_file("README.md")])

        significant, reasons, ignored = assess(compare)

        assert significant
        assert reasons == ["1 files, 1 changed lines"]
        assert ignored == frozenset()

    def test_docs_only_change_not_significant_when_ignore_paths_cover_it(self):
        compare = Compare("ahead", [_commit("a")], [_file("doc/usage.md"), _file("README.md")])

        significant, reasons, ignored = assess(compare, ignore_paths=["doc/**", "**/*.md"])

        assert not significant
        assert reasons == ["all 2 changed files match ignore_paths"]
        assert ignored == {"doc/usage.md", "README.md"}

    def test_partially_ignored_change_counts_only_remaining_files(self):
        compare = Compare("ahead", [_commit("a")], [_file("doc/x.md", 50), _file("src/a.py", 2, 1)])

        significant, reasons, ignored = assess(compare, ignore_paths=["doc/**"])

        assert significant
        assert reasons == ["1 files, 3 changed lines"]
        assert ignored == {"doc/x.md"}

    def test_merge_commit_alone_is_not_significant(self):
        compare = Compare("ahead", [_commit("m", merge=True)], [_file("src/from_base.py", 400)])

        significant, reasons, _ = assess(compare)

        assert not significant
        assert reasons == ["only merge commits"]

    def test_merge_plus_real_commit_is_significant(self):
        compare = Compare("ahead", [_commit("m", merge=True), _commit("a")], [_file("src/a.py")])

        assert assess(compare)[0]

    def test_min_changed_lines_applies_after_ignore_paths(self):
        compare = Compare(
            "ahead", [_commit("a")], [_file("doc/big.md", 500), _file("src/a.py", 2, 1)]
        )

        # 503 lines in total, but only 3 remain once docs are dropped.
        significant, reasons, _ = assess(compare, ignore_paths=["doc/**"], min_changed_lines=10)

        assert not significant
        assert reasons == ["3 changed lines is below min_changed_lines 10"]

    def test_min_changed_lines_met_is_significant(self):
        compare = Compare("ahead", [_commit("a")], [_file("src/a.py", 8, 2)])

        assert assess(compare, min_changed_lines=10)[0]
        assert not assess(compare, min_changed_lines=11)[0]

    @pytest.mark.parametrize("status", ["diverged", "behind"])
    def test_diverged_or_behind_means_history_rewritten(self, status):
        significant, reasons, _ = assess(
            Compare(status, [_commit("a")], [_file("doc/a.md")]), ignore_paths=["**"]
        )

        assert significant
        assert reasons == [REASON_REWRITTEN]

    def test_truncated_compare_is_too_large_to_inspect(self):
        significant, reasons, _ = assess(Compare("ahead", [_commit("a")], truncated=True))

        assert significant
        assert reasons == [REASON_TOO_LARGE]

    def test_identical_range_is_unchanged(self):
        significant, reasons, _ = assess(Compare("identical"))

        assert not significant
        assert reasons == [REASON_UNCHANGED]

    def test_non_merge_commit_without_files_is_not_significant(self):
        significant, reasons, _ = assess(Compare("ahead", [_commit("a")], []))

        assert not significant
        assert reasons == ["no files changed"]

    @pytest.mark.parametrize(
        ("glob", "path", "expected"),
        [
            ("**/*.md", "README.md", True),
            ("**/*.md", "a/b/c.md", True),
            ("*.md", "a/c.md", False),
            ("doc/**", "doc/a/b.txt", True),
            ("doc/**", "docs/a.txt", False),
            ("src/?.py", "src/a.py", True),
            ("src/?.py", "src/ab.py", False),
            ("a.b", "axb", False),
        ],
    )
    def test_glob_semantics(self, glob, path, expected):
        compare = Compare("ahead", [_commit("a")], [_file(path)])

        assert (not assess(compare, ignore_paths=[glob])[0]) is expected


class TestPrChanges:
    def test_lists_commits_and_files_from_recorded_compare(self):
        fake = FakeGitHub()

        result = pr_changes(fake.client(), "o/r", 7, SINCE)

        assert result.head == HEAD
        assert [c.sha[:7] for c in result.commits] == [
            "75d1faa",
            "845a2c3",
            "39ecd9e",
            "5c5e587",
            "f41cd83",
        ]
        assert not any(c.merge for c in result.commits)
        assert result.commits[0].author == "openhands-agent"
        assert (
            result.commits[-1].headline == "fix(issue): default `issue list` to open issues (#60)"
        )
        assert {f.path: (f.additions, f.deletions) for f in result.files}[
            "src/snapshot/models.py"
        ] == (7, 2)
        assert result.significant

    def test_exactly_one_compare_call_for_a_small_range(self):
        fake = FakeGitHub()

        pr_changes(fake.client(), "o/r", 7, SINCE)

        (call,) = fake.compare_calls
        assert call.url.path == f"/repos/o/r/compare/{SINCE}...{HEAD}"

    def test_since_equal_to_head_makes_no_compare_call(self):
        fake = FakeGitHub()

        result = pr_changes(fake.client(), "o/r", 7, HEAD[:10])

        assert not result.significant
        assert result.reasons == [REASON_UNCHANGED]
        assert fake.compare_calls == []

    def test_unknown_since_commit_is_history_rewritten(self):
        fake = FakeGitHub(compare_status=404)

        result = pr_changes(fake.client(), "o/r", 7, SINCE)

        assert result.significant
        assert result.reasons == [REASON_REWRITTEN]
        assert result.commits == []

    def test_diverged_range_is_history_rewritten(self):
        fake = FakeGitHub([_page([_api_commit("a")], [_api_file("a.py")], status="diverged")])

        result = pr_changes(fake.client(), "o/r", 7, SINCE)

        assert result.significant
        assert result.reasons == [REASON_REWRITTEN]

    def test_unknown_pr_raises(self):
        with pytest.raises(ValueError, match="PR not found"):
            pr_changes(FakeGitHub().client(), "o/r", 404, SINCE)

    def test_server_error_propagates(self):
        with pytest.raises(httpx.HTTPStatusError):
            pr_changes(FakeGitHub(compare_status=500).client(), "o/r", 7, SINCE)

    def test_pages_through_commits_and_files(self):
        first = _page(
            [_api_commit(f"c{i}") for i in range(100)], [_api_file(f"f{i}.py") for i in range(100)]
        )
        second = _page(
            [_api_commit("c100", parents=2)], [_api_file("f100.py"), _api_file("f99.py")]
        )
        fake = FakeGitHub([first, second])

        result = pr_changes(fake.client(), "o/r", 7, SINCE)

        assert len(result.commits) == 101
        assert len(result.files) == 101
        assert result.commits[-1].merge
        assert [r.url.params["page"] for r in fake.compare_calls] == ["1", "2"]

    def test_endless_pages_report_too_large(self):
        counter = iter(range(10_000))
        full = lambda: _page(  # noqa: E731
            [_api_commit(f"c{next(counter)}") for _ in range(100)],
            [_api_file(f"f{next(counter)}.py") for _ in range(100)],
        )
        fake = FakeGitHub([full() for _ in range(20)])

        result = pr_changes(fake.client(), "o/r", 7, SINCE)

        assert result.significant
        assert result.reasons == [REASON_TOO_LARGE]
        assert len(fake.compare_calls) == 10

    def test_repeated_page_stops_paging(self):
        full = _page(
            [_api_commit(f"c{i}") for i in range(100)], [_api_file(f"f{i}.py") for i in range(100)]
        )
        fake = FakeGitHub([full, full])

        result = pr_changes(fake.client(), "o/r", 7, SINCE)

        assert len(result.commits) == 100
        assert len(fake.compare_calls) == 2


@pytest.fixture
def run(capsys):
    def _run(fake: FakeGitHub, *args: str) -> tuple[int, str, str]:
        with patch("src.pr.cli.changes_cmd.ChangesClient", return_value=fake.client()):
            code = main(["pr", "changes", "o/r#7", "--since", SINCE, *args])
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


class TestCli:
    def test_text_output(self, run):
        code, out, _ = run(FakeGitHub())

        lines = out.splitlines()
        assert code == 0
        assert lines[0].startswith("o/r#7 2b09310..f41cd83 5 commits 5 files +")
        assert lines[1] == "significant: yes (5 files, 177 changed lines)"
        assert (
            "commit\t75d1faa\t--\topenhands-agent\tchore(worklog): PR #59 merged, #48 closed"
            in lines
        )
        assert "file\tmodified\t+7\t-2\t--\tsrc/snapshot/models.py" in lines

    def test_json_output_is_valid_and_complete(self, run):
        code, out, err = run(FakeGitHub(), "--format", "json")

        data = json.loads(out)
        assert code == 0
        assert err == ""
        assert data["head"] == HEAD
        assert data["significant"] is True
        assert len(data["commits"]) == 5
        assert data["commits"][0]["merge"] is False
        assert {f["path"] for f in data["files"]} >= {"src/__main__.py", "WORKLOG.md"}

    def test_docs_only_since_commit_with_ignore_path(self, run):
        page = _page([_api_commit("a")], [_api_file("doc/usage.md", 9)])

        _, out, _ = run(FakeGitHub([page]), "--ignore-path", "doc/**", "--format", "json")
        data = json.loads(out)
        assert data["significant"] is False
        assert data["files"][0]["ignored"] is True

        _, out, _ = run(FakeGitHub([page]), "--format", "json")
        assert json.loads(out)["significant"] is True

    def test_merge_from_base_alone_is_not_significant(self, run):
        page = _page([_api_commit("m", parents=2)], [_api_file("src/from_base.py", 99)])

        _, out, _ = run(FakeGitHub([page]))

        assert "significant: no (only merge commits)" in out
        assert "\tmerge\tBob\tmsg m" in out

    def test_force_push_reports_history_rewritten(self, run):
        _, out, _ = run(FakeGitHub(compare_status=404))

        assert "significant: yes (history rewritten)" in out

    def test_min_changed_lines_flag(self, run):
        page = _page([_api_commit("a")], [_api_file("src/a.py", 2, 1)])

        _, out, _ = run(FakeGitHub([page]), "--min-changed-lines", "10")

        assert out.splitlines()[1].startswith("significant: no")

    def test_error_exits_1_and_keeps_stdout_empty(self, capsys):
        with patch("src.pr.cli.changes_cmd.ChangesClient", return_value=FakeGitHub().client()):
            code = main(["pr", "changes", "o/r#404", "--since", SINCE, "--format", "json"])

        captured = capsys.readouterr()
        assert code == 1
        assert captured.out == ""
        assert "PR not found" in captured.err

    def test_invalid_ref_exits_1(self, capsys):
        assert main(["pr", "changes", "nonsense", "--since", SINCE]) == 1
        assert "Invalid PR reference" in capsys.readouterr().err

    def test_since_is_required(self):
        with pytest.raises(SystemExit):
            main(["pr", "changes", "o/r#7"])
