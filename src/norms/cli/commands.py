"""``tkt norms`` commands: init, check, show, upgrade."""

from __future__ import annotations

import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

import httpx

from src.board.github_api import describe_http_error, get_github_token
from src.norms import source as norms_source
from src.norms.gitfetch import GitFetchError
from src.norms.github import resolve_commit
from src.norms.model import CURRENT_SCHEMA, NORMS_PATH, Norms, glob_regex
from src.norms.schema import (
    Issue,
    LoadResult,
    dump_raw,
    migrate_raw,
    parse_norms,
    read_raw,
    unsupported_message,
)
from src.norms.store import RepoNorms, load_repo_norms
from src.norms.template import TEMPLATE


def _err(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)


def _warn(message: str) -> None:
    print(f"warning: {message}", file=sys.stderr)


def _repo_exists(repo: str, token: str, client: httpx.Client | None) -> bool:
    """GitHub answers 404 for a missing file and for a missing repo alike, so ask for the repo's head."""
    try:
        resolve_commit(repo, None, token, client=client)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return False
        if e.response.status_code != 409:  # 409: an empty repo, which does exist
            raise
    return True


def _load_repo(repo: str, client: httpx.Client | None) -> RepoNorms | None:
    """Read the norms file of `repo`; print the error and return None when that fails."""
    token = get_github_token()
    try:
        found = load_repo_norms(repo, token, client=client)
        if found.text is None and not _repo_exists(repo, token, client):
            _err(f"repo not found, or not visible to this token: {repo}")
            return None
    except (ValueError, httpx.HTTPError) as e:
        _err(f"cannot read {NORMS_PATH} from {repo}: {describe_http_error(e)}")
        return None
    return found


def _git_output(*args: str, cwd: Path | None = None) -> str | None:
    try:
        proc = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def unmatched_globs(norms: Norms, root: Path) -> list[tuple[str, str]]:
    """(key, glob) pairs for path globs that match no tracked or untracked file under ``root``."""
    listing = _git_output("ls-files", "--cached", "--others", "--exclude-standard", cwd=root)
    files = listing.splitlines() if listing else []
    globs = [("commits.ignore_paths", g) for g in norms.commits.ignore_paths]
    for name, report in norms.reports.items():
        globs += [(f"reports.{name}.only_paths", g) for g in report.only_paths]
    return [(key, g) for key, g in globs if not any(glob_regex(g).fullmatch(f) for f in files)]


def _report(result: LoadResult, filename: str) -> None:
    for issue in result.issues:
        (_err if issue.level == "error" else _warn)(issue.format(filename))


def cmd_init(
    *,
    source: str | None = None,
    ref: str | None = None,
    path: str | None = None,
    force: bool = False,
    today: date | None = None,
) -> int:
    toplevel = _git_output("rev-parse", "--show-toplevel")
    if toplevel is None:
        _err("not inside a git work tree; run `tkt norms init` from a repo checkout")
        return 1
    root = Path(toplevel.strip())
    target = root / NORMS_PATH
    if target.exists() and not force:
        _err(f"{target} already exists; use --force to overwrite")
        return 1

    notes: list[Issue] = []
    if source is None:
        if ref or path:
            _err("--ref and --path need --from")
            return 1
        text = TEMPLATE
    else:
        try:
            parsed = norms_source.parse_source(source, path=path, ref=ref)
            fetched = norms_source.fetch_source(parsed, ref)
            text, notes = norms_source.render_copy(fetched, today or date.today())
        except (norms_source.SourceError, GitFetchError, httpx.HTTPError, ValueError) as e:
            _err(describe_http_error(e))
            return 1

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"Wrote {target}")

    for note in notes:
        _warn(note.format(NORMS_PATH))
    if source is not None:
        result = parse_norms(text)
        if result.norms is not None:
            for key, glob in unmatched_globs(result.norms, root):
                _warn(
                    f"{NORMS_PATH}: {key}: glob {glob!r} matches no file in this repo; "
                    "it may be specific to the source"
                )
    print(
        "\nNext steps:\n"
        f"  1. Review {NORMS_PATH} and edit it for this repo.\n"
        "  2. Run `tkt norms check --strict`.\n"
        "  3. Commit it and merge it to the default branch; tickster reads it from there."
    )
    return 0


def _read_file(path: str | None) -> tuple[Path, str] | None:
    target = Path(path) if path else Path(NORMS_PATH)
    if target.is_dir():
        target = target / NORMS_PATH
    try:
        return target, target.read_text(encoding="utf-8")
    except OSError as e:
        _err(f"cannot read {target}: {e.strerror or e}")
        return None


def cmd_check(
    path: str | None = None,
    *,
    repo: str | None = None,
    strict: bool = False,
    client: httpx.Client | None = None,
) -> int:
    if repo is not None:
        found = _load_repo(repo, client)
        if found is None:
            return 1
        if found.text is None:
            _err(f"{repo} has no {NORMS_PATH} on its default branch")
            return 1
        filename = f"{repo}:{NORMS_PATH}"
        text = found.text
    else:
        loaded = _read_file(path)
        if loaded is None:
            return 1
        target, text = loaded
        filename = str(target)
    result = parse_norms(text, strict=strict)
    _report(result, filename)
    if result.errors:
        return 1
    print(f"{filename}: ok (schema {result.file_schema})")
    return 0


def _norms_to_dict(norms: Norms) -> dict[str, Any]:
    def pat(p) -> str:
        return p.pattern

    reports: dict[str, Any] = {}
    for name, r in norms.reports.items():
        entry: dict[str, Any] = {
            "marker": pat(r.marker),
            "required": r.required,
            "only_paths": list(r.only_paths),
        }
        if r.fail is not None:
            entry["fail"] = pat(r.fail)
        if r.impact_line is not None:
            entry["impact_line"] = {
                "pattern": pat(r.impact_line.pattern),
                "from": list(r.impact_line.from_),
                "unassessed": r.impact_line.unassessed,
            }
        reports[name] = entry
    actors: dict[str, Any] = {
        "agent_logins": list(norms.actors.agent_logins),
        "bots": list(norms.actors.bots),
    }
    if norms.actors.agent_disclosure is not None:
        actors["agent_disclosure"] = pat(norms.actors.agent_disclosure)
    out: dict[str, Any] = {
        "schema": norms.schema,
        "actors": actors,
        "labels": {"stale": list(norms.labels.stale), "rank": list(norms.labels.rank)},
        "review": {
            "count_reviews_from": list(norms.review.count_reviews_from),
            "rerequest_labels": list(norms.review.rerequest_labels),
        },
        "ci": {"ignore_checks": list(norms.ci.ignore_checks)},
        "commits": {
            "ignore_paths": list(norms.commits.ignore_paths),
            "min_changed_lines": norms.commits.min_changed_lines,
        },
    }
    if reports:
        out["reports"] = reports
    return out


def cmd_show(repo: str, *, client: httpx.Client | None = None) -> int:
    found = _load_repo(repo, client)
    if found is None:
        return 1
    result = found.result
    if result is None:
        print(
            f"{repo}: no {NORMS_PATH} on the default branch; convention-based steps report 'not configured'"
        )
        return 0
    print(f"# {repo}: {NORMS_PATH} on the default branch (blob {found.blob_sha})")
    _report(result, f"{repo}:{NORMS_PATH}")
    if result.norms is None:
        print("# not in effect")
        return 1
    print(dump_raw(_norms_to_dict(result.norms)), end="")
    return 0


def cmd_upgrade(path: str | None = None, *, write: bool = False) -> int:
    loaded = _read_file(path)
    if loaded is None:
        return 1
    target, text = loaded
    data, schema, errors = read_raw(text)
    if data is None or schema is None:
        for issue in errors:
            _err(issue.format(str(target)))
        return 1
    if schema > CURRENT_SCHEMA:
        _err(f"{target}: {unsupported_message(schema, CURRENT_SCHEMA)}")
        return 1
    if schema == CURRENT_SCHEMA:
        print(f"{target}: already at schema {CURRENT_SCHEMA}", file=sys.stderr)
        return 0
    try:
        migrated = dump_raw(migrate_raw(data, schema, CURRENT_SCHEMA))
    except ValueError as e:
        _err(f"{target}: {e}")
        return 1
    if write:
        target.write_text(migrated, encoding="utf-8")
        print(f"Wrote {target} at schema {CURRENT_SCHEMA}; comments are not preserved. Commit it.")
    else:
        print(migrated, end="")
    return 0
