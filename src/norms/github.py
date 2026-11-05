"""Read a repo's norms file through the GitHub contents API, cached by blob SHA."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path

import httpx

from src.board import config as board_config
from src.norms.model import NORMS_PATH

API_URL = "https://api.github.com"
TIMEOUT = 20.0


@dataclass(frozen=True)
class RepoFile:
    text: str
    blob_sha: str


def _headers(token: str, accept: str = "application/vnd.github+json") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
    }


def cache_path(repo: str) -> Path:
    return board_config.TKT_HOME / "norms" / f"{repo.replace('/', '__')}.json"


def _read_cache(repo: str) -> dict | None:
    try:
        return json.loads(cache_path(repo).read_text())
    except (OSError, ValueError):
        return None


def _write_cache(repo: str, entry: dict) -> None:
    path = cache_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry))


def _decode(payload: dict, where: str) -> str:
    if payload.get("encoding") != "base64":
        raise httpx.HTTPError(f"{where} is not returned inline by the contents API")
    return base64.b64decode(payload["content"]).decode("utf-8")


def fetch_default_branch_file(
    repo: str, token: str, *, client: httpx.Client | None = None
) -> RepoFile | None:
    """Read ``.agents/tickster.toml`` from ``repo``'s default branch.

    No ``ref`` is sent, so GitHub answers from the default branch and a PR can never
    change the rules that judge it. The cached copy is reused until the blob SHA changes;
    an ETag makes the unchanged case a free 304.
    """
    cached = _read_cache(repo)
    headers = _headers(token)
    if cached:
        headers["If-None-Match"] = cached["etag"]
    owns_client = client is None
    http = client or httpx.Client(timeout=TIMEOUT)
    try:
        resp = http.get(f"{API_URL}/repos/{repo}/contents/{NORMS_PATH}", headers=headers)
    finally:
        if owns_client:
            http.close()
    if resp.status_code == 404:
        cache_path(repo).unlink(missing_ok=True)
        return None
    if resp.status_code == 304 and cached:
        return RepoFile(text=cached["text"], blob_sha=cached["sha"])
    resp.raise_for_status()
    payload = resp.json()
    sha = payload["sha"]
    text = cached["text"] if cached and cached["sha"] == sha else _decode(payload, NORMS_PATH)
    etag = resp.headers.get("etag")
    if etag:
        _write_cache(repo, {"sha": sha, "etag": etag, "text": text})
    return RepoFile(text=text, blob_sha=sha)


def resolve_commit(
    repo: str, ref: str | None, token: str, *, client: httpx.Client | None = None
) -> str:
    """Full commit SHA for ``ref`` (the default branch when ``ref`` is None)."""
    owns_client = client is None
    http = client or httpx.Client(timeout=TIMEOUT)
    try:
        resp = http.get(
            f"{API_URL}/repos/{repo}/commits/{ref or 'HEAD'}",
            headers=_headers(token, "application/vnd.github.sha"),
        )
    finally:
        if owns_client:
            http.close()
    resp.raise_for_status()
    return resp.text.strip()


def fetch_file_at(
    repo: str, path: str, ref: str, token: str, *, client: httpx.Client | None = None
) -> str | None:
    owns_client = client is None
    http = client or httpx.Client(timeout=TIMEOUT)
    try:
        resp = http.get(
            f"{API_URL}/repos/{repo}/contents/{path}",
            params={"ref": ref},
            headers=_headers(token),
        )
    finally:
        if owns_client:
            http.close()
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return _decode(resp.json(), path)
