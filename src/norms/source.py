"""Resolve ``tkt norms init --from SOURCE`` and render the copy that gets written."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

from src.board.github_api import describe_http_error, get_github_token
from src.norms import gitfetch, github
from src.norms.model import CURRENT_SCHEMA, NORMS_PATH
from src.norms.schema import (
    Issue,
    Migration,
    dump_raw,
    migrate_raw,
    parse_norms,
    read_raw,
    unsupported_message,
)

COPIED_RE = re.compile(r"^# copied from .*$")
_GITHUB_PREFIX = "github:"


class SourceError(ValueError):
    pass


@dataclass(frozen=True)
class Source:
    kind: str  # github | git | local
    label: str  # the source as given, credentials removed
    path: str
    repo: str | None = None
    url: str | None = None
    local: Path | None = None


@dataclass(frozen=True)
class Fetched:
    text: str
    label: str
    path: str
    commit: str | None


def _check_path(path: str) -> str:
    if path.startswith(("/", "-")) or ".." in Path(path).parts:
        raise SourceError(f"invalid --path {path!r}: use a relative path inside the source")
    return path


def parse_source(source: str, *, path: str | None = None, ref: str | None = None) -> Source:
    if source.startswith("-"):
        raise SourceError(f"invalid source {source!r}: a source cannot start with '-'")
    if ref is not None and ref.startswith("-"):
        raise SourceError(f"invalid --ref {ref!r}: a ref cannot start with '-'")

    if source.startswith(_GITHUB_PREFIX):
        parts = [p for p in source[len(_GITHUB_PREFIX) :].split("/") if p]
        if len(parts) < 2:
            raise SourceError(f"invalid source {source!r}: expected github:owner/repo[/path]")
        inline = "/".join(parts[2:])
        if inline and path:
            raise SourceError("give the file either in the github: source or with --path, not both")
        return Source(
            kind="github",
            label=source,
            path=_check_path(inline or path or NORMS_PATH),
            repo=f"{parts[0]}/{parts[1]}",
        )

    transport = gitfetch.disallowed_transport(source)
    if transport:
        raise SourceError(
            f"transport {transport!r} is not allowed; use "
            f"{', '.join(gitfetch.ALLOWED_SCHEMES)} or a local path"
        )
    if gitfetch.is_git_url(source):
        return Source(
            kind="git",
            label=gitfetch.strip_credentials(source),
            path=_check_path(path or NORMS_PATH),
            url=source,
        )

    local = Path(source).expanduser()
    if not local.exists():
        raise SourceError(
            f"source {source!r} is not a github: source, a git URL or an existing path"
        )
    if ref or path:
        raise SourceError("--ref and --path do not apply to a local path")
    target = local / NORMS_PATH if local.is_dir() else local
    return Source(kind="local", label=source, path=str(target), local=target)


def _local_commit(file: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(file.parent), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def fetch_source(source: Source, ref: str | None, *, client: httpx.Client | None = None) -> Fetched:
    if source.kind == "github":
        assert source.repo is not None
        token = get_github_token()
        try:
            commit = github.resolve_commit(source.repo, ref, token, client=client)
        except httpx.HTTPStatusError as e:
            if ref and e.response.status_code == 422:
                raise SourceError(f"ref {ref!r} not found in the source") from e
            raise SourceError(describe_http_error(e)) from e
        text = github.fetch_file_at(source.repo, source.path, commit, token, client=client)
        if text is None:
            raise SourceError(f"{source.path} not found in {source.repo} at {commit[:7]}")
        return Fetched(text, source.label, source.path, commit)
    if source.kind == "git":
        assert source.url is not None
        text, commit = gitfetch.fetch_file(source.url, source.path, ref)
        return Fetched(text, source.label, source.path, commit)
    assert source.local is not None
    if not source.local.is_file():
        raise SourceError(f"{source.local} does not exist")
    return Fetched(
        source.local.read_text(encoding="utf-8"),
        source.label,
        str(source.local),
        _local_commit(source.local),
    )


def header_line(fetched: Fetched, today: date) -> str:
    at = f" @ {fetched.commit[:7]}" if fetched.commit else ""
    return f"# copied from {fetched.label} ({fetched.path}{at}) on {today.isoformat()}"


def render_copy(
    fetched: Fetched,
    today: date,
    *,
    current_schema: int = CURRENT_SCHEMA,
    migrations: Mapping[int, Migration] | None = None,
) -> tuple[str, list[Issue]]:
    """The file text to write: the source at the current schema, plus a provenance header.

    Raises SourceError for a source that is invalid or newer than this tkt understands.
    """
    data, schema, errors = read_raw(fetched.text)
    if data is None or schema is None:
        raise SourceError("; ".join(i.format(fetched.path) for i in errors))
    if schema > current_schema:
        raise SourceError(
            f"{fetched.path}: {unsupported_message(schema, current_schema)}; upgrade tkt to copy it"
        )
    body = fetched.text
    notes: list[Issue] = []
    if schema < current_schema:
        try:
            body = dump_raw(migrate_raw(data, schema, current_schema, migrations))
        except ValueError as e:
            raise SourceError(f"{fetched.path}: {e}") from e
        notes.append(
            Issue("warning", "schema", f"migrated from schema {schema} to {current_schema}")
        )
    lines = body.splitlines()
    while lines and COPIED_RE.match(lines[0]):
        lines.pop(0)
    text = header_line(fetched, today) + "\n" + "\n".join(lines).rstrip("\n") + "\n"
    result = parse_norms(text, current_schema=current_schema, migrations=migrations)
    if result.errors:
        raise SourceError("; ".join(i.format(fetched.path) for i in result.errors))
    return text, notes + result.warnings
