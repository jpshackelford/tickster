"""What changed in a PR since a commit, and whether it matters.

The facts come from one REST compare call (``since...head``). When that range holds
a merge commit, a second compare (``base...head``) tells which commits belong to the
PR and which a merge brought in from the base. Whether the change matters is decided
by :func:`assess`, a pure function of those facts plus the ``[commits]`` norms
(``ignore_paths``, ``min_changed_lines``). With no norms every PR-authored
non-merge change counts.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from functools import lru_cache

from src.board.github_api import GitHubClient, get_github_token

PER_PAGE = 100
MAX_PAGES = 10

REASON_REWRITTEN = "history rewritten"
REASON_TOO_LARGE = "too large to inspect"
REASON_UNCHANGED = "no changes since commit"
REASON_ONLY_MERGES = "only merge commits"
REASON_ONLY_MERGES_AND_BASE = "only merge commits and commits brought in from the base"


@dataclass(frozen=True)
class ChangedCommit:
    sha: str
    headline: str
    author: str | None
    date: str | None
    merge: bool
    from_base: bool = False


@dataclass(frozen=True)
class PullRef:
    head: str
    base: str


@dataclass(frozen=True)
class ChangedFile:
    path: str
    status: str
    additions: int
    deletions: int

    @property
    def lines(self) -> int:
        return self.additions + self.deletions


@dataclass
class Compare:
    """Commits and files between two commits, as GitHub reports them."""

    status: str
    commits: list[ChangedCommit] = field(default_factory=list)
    files: list[ChangedFile] = field(default_factory=list)
    truncated: bool = False


@dataclass
class PRChanges:
    repo: str
    number: int
    since: str
    head: str
    significant: bool
    reasons: list[str]
    commits: list[ChangedCommit] = field(default_factory=list)
    files: list[ChangedFile] = field(default_factory=list)
    ignored: frozenset[str] = frozenset()


@lru_cache(maxsize=256)
def _glob_regex(glob: str) -> re.Pattern[str]:
    """``*`` stays within a path segment, ``**`` crosses segments; ``**/`` may match nothing."""
    out: list[str] = []
    i = 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("".join(out))


def _is_ignored(path: str, globs: Sequence[str]) -> bool:
    return any(_glob_regex(g).fullmatch(path) for g in globs)


def assess(
    compare: Compare,
    *,
    ignore_paths: Sequence[str] = (),
    min_changed_lines: int = 0,
) -> tuple[bool, list[str], frozenset[str]]:
    """Decide whether a compare result is a change that matters.

    Returns ``(significant, reasons, ignored_paths)``. Merge commits (two or more
    parents) and commits a merge brought in from the base (``from_base``) are not
    PR changes. ``ignore_paths`` drops files first, then ``min_changed_lines`` is
    applied to what remains.

    The compare file list is the net diff of the whole range, so files a merge
    brought in are counted when the range also holds a PR-authored commit. That can
    only over-report.
    """
    if compare.truncated:
        return True, [REASON_TOO_LARGE], frozenset()
    if compare.status in ("diverged", "behind"):
        return True, [REASON_REWRITTEN], frozenset()
    if not compare.commits:
        return False, [REASON_UNCHANGED], frozenset()
    if all(c.merge or c.from_base for c in compare.commits):
        reason = (
            REASON_ONLY_MERGES_AND_BASE
            if any(c.from_base for c in compare.commits)
            else REASON_ONLY_MERGES
        )
        return False, [reason], frozenset()

    ignored = frozenset(f.path for f in compare.files if _is_ignored(f.path, ignore_paths))
    kept = [f for f in compare.files if f.path not in ignored]
    if not kept:
        if ignored:
            return False, [f"all {len(ignored)} changed files match ignore_paths"], ignored
        return False, ["no files changed"], ignored

    lines = sum(f.lines for f in kept)
    if lines < min_changed_lines:
        return (
            False,
            [f"{lines} changed lines is below min_changed_lines {min_changed_lines}"],
            (ignored),
        )
    return True, [f"{len(kept)} files, {lines} changed lines"], ignored


def _commit(data: dict) -> ChangedCommit:
    commit = data["commit"]
    author = (data.get("author") or {}).get("login") or commit["author"].get("name")
    return ChangedCommit(
        sha=data["sha"],
        headline=commit["message"].split("\n", 1)[0],
        author=author,
        date=commit["author"].get("date"),
        merge=len(data.get("parents") or []) >= 2,
    )


def _file(data: dict) -> ChangedFile:
    return ChangedFile(
        path=data["filename"],
        status=data["status"],
        additions=data["additions"],
        deletions=data["deletions"],
    )


class ChangesClient:
    """Reads the commits and files between a commit and a PR's head."""

    def __init__(self, token: str | None = None):
        self._client = GitHubClient(token or get_github_token())

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ChangesClient":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def get_pull(self, repo: str, number: int) -> PullRef:
        resp = self._client.rest_get(f"{GitHubClient.REST_BASE}/repos/{repo}/pulls/{number}")
        if resp.status_code == 404:
            raise ValueError(f"PR not found: {repo}#{number}")
        resp.raise_for_status()
        data = resp.json()
        return PullRef(head=data["head"]["sha"], base=data["base"]["sha"])

    def compare(self, repo: str, since: str, head: str) -> Compare:
        """One compare call, plus further pages while a page comes back full.

        A ``since`` GitHub can't find (404/422) means the commit is no longer on any
        branch, which is reported as a diverged range.
        """
        return self._compare(repo, since, head) or Compare(status="diverged")

    def pr_commits(self, repo: str, base: str, head: str) -> Compare:
        """The commits the PR itself carries: reachable from ``head``, not from ``base``."""
        result = self._compare(repo, base, head)
        if result is None:
            raise ValueError(f"cannot compare base {base[:7]} with head {head[:7]}")
        return result

    def _compare(self, repo: str, start: str, head: str) -> Compare | None:
        url = f"{GitHubClient.REST_BASE}/repos/{repo}/compare/{start}...{head}"
        result = Compare(status="")
        seen_commits: set[str] = set()
        seen_files: set[str] = set()

        for page in range(1, MAX_PAGES + 1):
            resp = self._client.rest_get(url, params={"per_page": PER_PAGE, "page": page})
            if resp.status_code in (404, 422):
                return None
            resp.raise_for_status()
            data = resp.json()
            result.status = data["status"]

            commits = [_commit(c) for c in data.get("commits", [])]
            files = [_file(f) for f in data.get("files", [])]
            new_commits = [c for c in commits if c.sha not in seen_commits]
            new_files = [f for f in files if f.path not in seen_files]
            seen_commits.update(c.sha for c in new_commits)
            seen_files.update(f.path for f in new_files)
            result.commits.extend(new_commits)
            result.files.extend(new_files)

            full = len(commits) >= PER_PAGE or len(files) >= PER_PAGE
            if not full or not (new_commits or new_files):
                return result
        result.truncated = True
        return result


def _mark_base_commits(client: ChangesClient, repo: str, pull: PullRef, compare: Compare) -> None:
    """Flag range commits that a merge brought in from the base.

    Only a merge can bring them in, so the second compare runs only when the range
    holds one. A commit the PR carries is in ``base...head``; any other commit in
    the range is reachable from the base.
    """
    if compare.truncated or compare.status in ("diverged", "behind"):
        return
    if not any(c.merge for c in compare.commits):
        return
    own = client.pr_commits(repo, pull.base, pull.head)
    if own.truncated:
        compare.truncated = True
        return
    own_shas = {c.sha for c in own.commits}
    compare.commits = [replace(c, from_base=c.sha not in own_shas) for c in compare.commits]


def pr_changes(
    client: ChangesClient,
    repo: str,
    number: int,
    since: str,
    *,
    ignore_paths: Sequence[str] = (),
    min_changed_lines: int = 0,
) -> PRChanges:
    """Library entry point: commits and files since ``since``, and whether they matter."""
    pull = client.get_pull(repo, number)
    head = pull.head
    if len(since) >= 7 and head.startswith(since.lower()):
        return PRChanges(repo, number, since, head, False, [REASON_UNCHANGED])

    compare = client.compare(repo, since, head)
    _mark_base_commits(client, repo, pull, compare)
    significant, reasons, ignored = assess(
        compare, ignore_paths=ignore_paths, min_changed_lines=min_changed_lines
    )
    return PRChanges(
        repo=repo,
        number=number,
        since=since,
        head=head,
        significant=significant,
        reasons=reasons,
        commits=compare.commits,
        files=compare.files,
        ignored=ignored,
    )
