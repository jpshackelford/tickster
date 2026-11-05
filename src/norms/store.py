"""Process-wide access to a watched repo's norms, fetched lazily from GitHub."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from src.board.github_api import get_github_token
from src.norms.github import fetch_default_branch_file
from src.norms.model import NORMS_PATH, Norms
from src.norms.schema import LoadResult, parse_norms

type Loader = Callable[[str], Norms | None]


@dataclass(frozen=True)
class RepoNorms:
    """What GitHub holds for a repo: the parse result and where it came from."""

    result: LoadResult | None
    blob_sha: str | None = None
    text: str | None = None


def load_repo_norms(repo: str, token: str, *, client: httpx.Client | None = None) -> RepoNorms:
    file = fetch_default_branch_file(repo, token, client=client)
    if file is None:
        return RepoNorms(result=None)
    return RepoNorms(result=parse_norms(file.text), blob_sha=file.blob_sha, text=file.text)


def _warn(message: str) -> None:
    print(f"tkt: {message}", file=sys.stderr)


def github_loader(repo: str, client: httpx.Client | None = None) -> Norms | None:
    if "/" not in repo:
        return None
    try:
        found = load_repo_norms(repo, get_github_token(), client=client)
    except (ValueError, httpx.HTTPError) as e:
        _warn(f"could not read {NORMS_PATH} for {repo}: {e}")
        return None
    result = found.result
    if result is None:
        return None
    for issue in result.issues:
        _warn(f"{repo}: {issue.format(NORMS_PATH)}")
    return result.norms


_loader: Loader = github_loader
_memo: dict[str, Norms | None] = {}


def get_repo_norms(repo: str) -> Norms | None:
    """Norms for ``repo``, or None when it has none (or ours can't read them)."""
    key = repo.lower()
    if key not in _memo:
        _memo[key] = _loader(repo)
    return _memo[key]


def set_loader(loader: Loader | None) -> None:
    """Swap the loader (None restores GitHub) and forget every memoised answer."""
    global _loader
    _loader = loader or github_loader
    _memo.clear()
