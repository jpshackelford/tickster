"""Tests for `tkt pr changes`: compare paging, significance rules and CLI output."""

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from src.__main__ import main
from src.board.github_api import GitHubClient
from src.norms import store as norms_store
from src.norms.model import Norms
from src.norms.schema import parse_norms
from src.pr.changes import (
    REASON_ONLY_MERGES,
    REASON_ONLY_MERGES_AND_BASE,
    REASON_REWRITTEN,
    REASON_TOO_LARGE,
    REASON_UNCHANGED,
    ChangedCommit,
    ChangedFile,
    ChangesClient,
    Compare,
    InvalidSince,
    assess,
    parse_since,
    pr_changes,
    resolve_commit_settings,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


FIXTURE = _fixture("compare_tickster_2b09310_f41cd83.json")
SINCE = "2b09310abcdef"
HEAD = "f41cd838ab430067f143e547283090565f2c4b89"
BASE = "75d1faacb87d639de2bd81afaa00c4cbfd26a243"

# OpenHands/software-agent-sdk#6471: its head 043e0fd is "Merge branch 'main'", which
# brought in main's f987cb4. The PR's own commits are 4c8680e and the merge.
SDK_HEAD = "043e0fd332d0cc4164b9396832603fc379f05151"
SDK_BASE = "f987cb468997ee05dd763adff4e0cc2277957ac1"
SDK_PREV_TIP = "4c8680ef8ad9e72135dfa3d173311bdfb33612f6"
SDK_MERGE_ALONE = _fixture("compare_sdk_6471_4c8680e_043e0fd.json")
SDK_MERGE_AND_COMMIT = _fixture("compare_sdk_6471_e0f52ea_043e0fd.json")
SDK_OWN_COMMITS = _fixture("compare_sdk_6471_base_f987cb4_043e0fd.json")
SDK_BEFORE_REAL_COMMIT = "e0f52ea"


def _commit(sha: str, *, merge: bool = False, from_base: bool = False) -> ChangedCommit:
    return ChangedCommit(sha, f"commit {sha}", "alice", "2026-11-05T10:00:00Z", merge, from_base)


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
    """Serves the PR and compare REST endpoints through a real httpx client.

    ``compare_pages`` answers ``since...head``; ``base_pages`` answers ``base...head``.
    A test that gives no ``base_pages`` fails if the code asks for them.
    """

    def __init__(
        self,
        compare_pages: list[dict] | None = None,
        compare_status: int = 200,
        *,
        head: str = HEAD,
        base: str = BASE,
        base_pages: list[dict] | None = None,
        base_status: int = 200,
    ):
        self.compare_pages = compare_pages if compare_pages is not None else [FIXTURE]
        self.compare_status = compare_status
        self.head = head
        self.base = base
        self.base_pages = base_pages
        self.base_status = base_status
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/pulls/7"):
            return httpx.Response(
                200, json={"head": {"sha": self.head}, "base": {"sha": self.base}}
            )
        if path.endswith("/pulls/404"):
            return httpx.Response(404, json={"message": "Not Found"})
        if "/compare/" in path:
            is_base = f"/compare/{self.base}..." in path
            pages = self.base_pages if is_base else self.compare_pages
            status = self.base_status if is_base else self.compare_status
            if pages is None:
                return httpx.Response(500, json={"message": f"unexpected call {path}"})
            if status != 200:
                return httpx.Response(status, json={"message": "nope"})
            page = int(request.url.params["page"])
            return httpx.Response(200, json=pages[min(page, len(pages)) - 1])
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


def _sdk_fake(pages: dict) -> FakeGitHub:
    return FakeGitHub([pages], head=SDK_HEAD, base=SDK_BASE, base_pages=[SDK_OWN_COMMITS])


def _page(commits: list[dict], files: list[dict], status: str = "ahead") -> dict:
    return {"status": status, "commits": commits, "files": files}


VALID_SINCE = ["abcdef0", "ABCDEF0", "a" * 40, "aBcDeF0" * 5, "0a1b2c3" * 5 + "d4e5f"]
INVALID_SINCE = [
    "notasha",
    "main",
    "v1.0.0",
    "abcdef",
    "a" * 41,
    "",
    "abc123g",
    f"{'a' * 7}\n",
    " abcdef0",
]


class TestParseSince:
    @pytest.mark.parametrize("since", VALID_SINCE)
    def test_accepts_7_to_40_hex_characters(self, since):
        assert parse_since(since) == since.lower()

    @pytest.mark.parametrize("since", INVALID_SINCE)
    def test_rejects_anything_else(self, since):
        with pytest.raises(InvalidSince, match="--since needs a commit SHA"):
            parse_since(since)

    @pytest.mark.parametrize("since", INVALID_SINCE)
    def test_pr_changes_makes_no_github_call_for_an_invalid_since(self, since):
        fake = FakeGitHub()

        with pytest.raises(InvalidSince):
            pr_changes(fake.client(), "o/r", 7, since)

        assert fake.requests == []

    def test_uppercase_since_is_lowercased_in_the_result(self):
        fake = FakeGitHub()

        result = pr_changes(fake.client(), "o/r", 7, SINCE.upper())

        assert result.since == SINCE
        assert fake.compare_calls[0].url.path == f"/repos/o/r/compare/{SINCE}...{HEAD}"


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
        assert reasons == [REASON_ONLY_MERGES]

    def test_commits_brought_in_from_base_are_not_changes(self):
        compare = Compare(
            "ahead",
            [_commit("b", from_base=True), _commit("m", merge=True)],
            [_file("src/from_base.py", 400)],
        )

        significant, reasons, _ = assess(compare)

        assert not significant
        assert reasons == [REASON_ONLY_MERGES_AND_BASE]

    def test_real_commit_next_to_base_commits_is_significant(self):
        compare = Compare(
            "ahead",
            [_commit("b", from_base=True), _commit("a"), _commit("m", merge=True)],
            [_file("src/a.py")],
        )

        significant, _, _ = assess(compare)

        assert significant

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

    def test_merge_from_base_alone_is_not_significant(self):
        fake = _sdk_fake(SDK_MERGE_ALONE)

        result = pr_changes(fake.client(), "o/r", 7, SDK_PREV_TIP)

        assert [(c.sha[:7], c.merge, c.from_base) for c in result.commits] == [
            ("f987cb4", False, True),
            ("043e0fd", True, False),
        ]
        assert len(result.files) == 2
        assert not result.significant
        assert result.reasons == [REASON_ONLY_MERGES_AND_BASE]

    def test_merge_from_base_plus_real_commit_is_significant(self):
        fake = _sdk_fake(SDK_MERGE_AND_COMMIT)

        result = pr_changes(fake.client(), "o/r", 7, SDK_BEFORE_REAL_COMMIT)

        assert [(c.sha[:7], c.merge, c.from_base) for c in result.commits] == [
            ("f987cb4", False, True),
            ("4c8680e", False, False),
            ("043e0fd", True, False),
        ]
        assert result.significant

    def test_merge_from_base_makes_two_compare_calls(self):
        fake = _sdk_fake(SDK_MERGE_ALONE)

        pr_changes(fake.client(), "o/r", 7, SDK_PREV_TIP)

        since_call, base_call = fake.compare_calls
        assert since_call.url.path == f"/repos/o/r/compare/{SDK_PREV_TIP}...{SDK_HEAD}"
        assert base_call.url.path == f"/repos/o/r/compare/{SDK_BASE}...{SDK_HEAD}"

    def test_range_without_a_merge_does_not_ask_for_the_base_range(self):
        fake = FakeGitHub([_page([_api_commit("a")], [_api_file("a.py")])])

        pr_changes(fake.client(), "o/r", 7, SINCE)

        assert len(fake.compare_calls) == 1

    def test_unreadable_base_range_raises(self):
        fake = FakeGitHub(
            [SDK_MERGE_ALONE], head=SDK_HEAD, base=SDK_BASE, base_pages=[{}], base_status=404
        )

        with pytest.raises(ValueError, match="cannot compare base"):
            pr_changes(fake.client(), "o/r", 7, SDK_PREV_TIP)

    def test_endless_base_range_reports_too_large(self):
        counter = iter(range(10_000))
        full = lambda: _page(  # noqa: E731
            [_api_commit(f"b{next(counter)}") for _ in range(100)],
            [_api_file(f"g{next(counter)}.py") for _ in range(100)],
        )
        fake = FakeGitHub(
            [SDK_MERGE_ALONE],
            head=SDK_HEAD,
            base=SDK_BASE,
            base_pages=[full() for _ in range(20)],
        )

        result = pr_changes(fake.client(), "o/r", 7, SDK_PREV_TIP)

        assert result.significant
        assert result.reasons == [REASON_TOO_LARGE]

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
        own = _page([_api_commit(f"c{i}") for i in range(100, 101)], [])
        fake = FakeGitHub([first, second], base_pages=[own])

        result = pr_changes(fake.client(), "o/r", 7, SINCE)

        assert len(result.commits) == 101
        assert len(result.files) == 101
        assert result.commits[-1].merge
        since_calls = [r for r in fake.compare_calls if f"/compare/{SINCE}..." in r.url.path]
        assert [r.url.params["page"] for r in since_calls] == ["1", "2"]

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
    def _run(fake: FakeGitHub, *args: str, since: str = SINCE) -> tuple[int, str, str]:
        with patch("src.pr.cli.changes_cmd.ChangesClient", return_value=fake.client()):
            code = main(["pr", "changes", "o/r#7", "--since", since, *args])
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

    def test_merge_commit_alone_is_not_significant(self, run):
        page = _page([_api_commit("m", parents=2)], [_api_file("src/from_base.py", 99)])
        fake = FakeGitHub([page], base_pages=[page])

        _, out, _ = run(fake)

        assert "significant: no (only merge commits)" in out
        assert "\tmerge\tBob\tmsg m" in out

    def test_merge_from_base_alone_is_not_significant(self, run):
        fake = FakeGitHub(
            [SDK_MERGE_ALONE], head=SDK_HEAD, base=SDK_BASE, base_pages=[SDK_OWN_COMMITS]
        )

        _, out, _ = run(fake, since=SDK_PREV_TIP)

        lines = out.splitlines()
        assert lines[0].startswith("o/r#7 4c8680e..043e0fd 2 commits 2 files +172 -5")
        assert lines[1] == (
            "significant: no (only merge commits and commits brought in from the base)"
        )
        assert any(
            line.startswith("commit\tf987cb4\tbase\tak684\tfix(workspace)") for line in lines
        )
        assert any(line.startswith("commit\t043e0fd\tmerge\t") for line in lines)

    def test_merge_from_base_plus_real_commit_is_significant(self, run):
        fake = FakeGitHub(
            [SDK_MERGE_AND_COMMIT], head=SDK_HEAD, base=SDK_BASE, base_pages=[SDK_OWN_COMMITS]
        )

        _, out, _ = run(fake, "--format", "json", since=SDK_BEFORE_REAL_COMMIT)

        data = json.loads(out)
        assert data["significant"] is True
        assert [(c["sha"][:7], c["from_base"]) for c in data["commits"]] == [
            ("f987cb4", True),
            ("4c8680e", False),
            ("043e0fd", False),
        ]

    def test_force_push_reports_history_rewritten(self, run):
        _, out, _ = run(FakeGitHub(compare_status=404))

        assert "significant: yes (history rewritten)" in out

    @pytest.mark.parametrize("since", ["notasha", "main"])
    @pytest.mark.parametrize("fmt", ["text", "json"])
    def test_malformed_since_exits_2_with_empty_stdout(self, run, since, fmt):
        fake = FakeGitHub()

        code, out, err = run(fake, "--format", fmt, since=since)

        assert code == 2
        assert out == ""
        assert err.strip() == "Error: --since needs a commit SHA"
        assert fake.requests == []

    def test_well_formed_unknown_sha_still_reports_history_rewritten(self, run):
        fake = FakeGitHub(compare_status=422)

        code, out, _ = run(fake, since="deadbeefdeadbeef")

        assert code == 0
        assert "significant: yes (history rewritten)" in out
        assert len(fake.compare_calls) == 1

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


def _norms(commits_toml: str) -> Norms:
    norms = parse_norms(commits_toml).norms
    assert norms is not None
    return norms


def _install(text: str | None) -> None:
    norms = _norms(text) if text else None
    norms_store.set_loader(lambda _repo: norms)


DOCS_NORMS = 'schema = 1\n[commits]\nignore_paths = ["doc/**"]\n'
MIN10_NORMS = "schema = 1\n[commits]\nmin_changed_lines = 10\n"
BOTH_NORMS = 'schema = 1\n[commits]\nignore_paths = ["doc/**"]\nmin_changed_lines = 10\n'
FILE = ".agents/tickster.toml"
DEFAULT = "default (no norms file)"


class TestResolveCommitSettings:
    def test_no_norms_and_no_flags_is_the_default(self):
        s = resolve_commit_settings(None)
        assert (s.ignore_paths, s.min_changed_lines) == ((), 0)
        assert (s.ignore_paths_source, s.min_changed_lines_source) == (DEFAULT, DEFAULT)

    def test_file_values_fill_unset_flags(self):
        s = resolve_commit_settings(_norms(BOTH_NORMS))
        assert (s.ignore_paths, s.min_changed_lines) == (("doc/**",), 10)
        assert (s.ignore_paths_source, s.min_changed_lines_source) == (FILE, FILE)

    def test_empty_ignore_paths_counts_as_not_given(self):
        s = resolve_commit_settings(_norms(DOCS_NORMS), [], None)
        assert s.ignore_paths == ("doc/**",)

    def test_each_flag_replaces_only_its_own_setting(self):
        norms = _norms(BOTH_NORMS)

        paths = resolve_commit_settings(norms, ["src/**"], None)
        assert (paths.ignore_paths, paths.ignore_paths_source) == (("src/**",), "--ignore-path")
        assert (paths.min_changed_lines, paths.min_changed_lines_source) == (10, FILE)

        lines = resolve_commit_settings(norms, None, 0)
        assert (lines.min_changed_lines, lines.min_changed_lines_source) == (
            0,
            "--min-changed-lines",
        )
        assert (lines.ignore_paths, lines.ignore_paths_source) == (("doc/**",), FILE)

    def test_flags_without_a_norms_file(self):
        s = resolve_commit_settings(None, ["a"], 3)
        assert (s.ignore_paths, s.min_changed_lines) == (("a",), 3)


class TestCliNorms:
    DOCS_PAGE = _page([_api_commit("a")], [_api_file("doc/usage.md", 9)])
    SMALL_PAGE = _page([_api_commit("a")], [_api_file("src/a.py", 2, 1)])
    MIXED_PAGE = _page(
        [_api_commit("a")], [_api_file("doc/usage.md", 9), _api_file("src/a.py", 2, 1)]
    )

    def _json(self, run, page, *args):
        code, out, err = run(FakeGitHub([page]), *args, "--format", "json")
        assert code == 0
        assert err == ""
        return json.loads(out)

    def test_norms_ignore_paths_apply_without_flags(self, run):
        _install(DOCS_NORMS)

        data = self._json(run, self.DOCS_PAGE)

        assert data["significant"] is False
        assert data["files"][0]["ignored"] is True

    def test_norms_min_changed_lines_apply_without_flags(self, run):
        _install(MIN10_NORMS)

        _, out, _ = run(FakeGitHub([self.SMALL_PAGE]))

        assert out.splitlines()[1] == (
            "significant: no (3 changed lines is below min_changed_lines 10)"
        )

    def test_ignore_path_flag_replaces_the_file_list(self, run):
        _install(DOCS_NORMS)

        data = self._json(run, self.DOCS_PAGE, "--ignore-path", "src/**")

        assert data["significant"] is True
        assert data["files"][0]["ignored"] is False
        assert data["settings"]["sources"]["ignore_paths"] == "--ignore-path"

    def test_min_changed_lines_zero_overrides_the_file_value(self, run):
        _install(MIN10_NORMS)

        data = self._json(run, self.SMALL_PAGE, "--min-changed-lines", "0")

        assert data["significant"] is True
        assert data["settings"]["min_changed_lines"] == 0

    def test_the_setting_not_passed_still_comes_from_the_file(self, run):
        _install(BOTH_NORMS)

        data = self._json(run, self.MIXED_PAGE, "--min-changed-lines", "1")
        assert data["settings"]["ignore_paths"] == ["doc/**"]
        assert data["settings"]["sources"] == {
            "ignore_paths": FILE,
            "min_changed_lines": "--min-changed-lines",
        }
        assert [f["ignored"] for f in data["files"]] == [True, False]
        assert data["significant"] is True

        data = self._json(run, self.SMALL_PAGE, "--ignore-path", "x/**")
        assert data["settings"]["min_changed_lines"] == 10
        assert data["significant"] is False

    def test_no_norms_file_behaves_as_before(self, run):
        _install(None)

        data = self._json(run, self.DOCS_PAGE)

        assert data["significant"] is True
        assert data["settings"] == {
            "ignore_paths": [],
            "min_changed_lines": 0,
            "sources": {"ignore_paths": DEFAULT, "min_changed_lines": DEFAULT},
        }

    def test_norms_are_not_fetched_when_both_flags_are_given(self, run):
        def boom(_repo):
            raise AssertionError("norms fetched")

        norms_store.set_loader(boom)

        code, _, _ = run(
            FakeGitHub([self.DOCS_PAGE]), "--ignore-path", "x", "--min-changed-lines", "0"
        )

        assert code == 0

    def test_explain_prints_each_setting_and_its_source(self, run):
        _install(DOCS_NORMS)

        _, out, _ = run(FakeGitHub([self.DOCS_PAGE]), "--min-changed-lines", "4", "--explain")

        lines = out.splitlines()
        assert lines[1].startswith("significant:")
        assert lines[2] == f"  why: ignore_paths = [doc/**] ({FILE})"
        assert lines[3] == "  why: min_changed_lines = 4 (--min-changed-lines)"

    def test_explain_without_a_norms_file(self, run):
        _install(None)

        _, out, _ = run(FakeGitHub([self.DOCS_PAGE]), "--explain")

        assert f"  why: ignore_paths = [] ({DEFAULT})" in out.splitlines()

    def test_default_text_has_no_why_lines(self, run):
        _install(DOCS_NORMS)

        _, out, _ = run(FakeGitHub([self.MIXED_PAGE]))

        assert "why:" not in out

    def test_explain_keeps_json_valid(self, run):
        _install(DOCS_NORMS)

        data = self._json(run, self.DOCS_PAGE, "--explain")

        assert data["settings"]["ignore_paths"] == ["doc/**"]
