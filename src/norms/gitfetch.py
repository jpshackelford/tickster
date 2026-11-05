"""Read one file from a git remote with the user's own ``git`` (no new auth code)."""

from __future__ import annotations

import re
import subprocess
import tempfile
from urllib.parse import urlsplit, urlunsplit

ALLOWED_SCHEMES = ("https", "ssh", "git", "file")
GIT_TIMEOUT = 120

_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://")
_SCP_RE = re.compile(r"^[\w.-]+@[\w.-]+:[^\s]+$")

# Only the allowed transports may run; this blocks ext:: and friends even when a
# remote helper or a redirect tries to use them.
_SAFE_GIT = [
    "-c",
    "protocol.allow=never",
    *[arg for s in ALLOWED_SCHEMES for arg in ("-c", f"protocol.{s}.allow=always")],
]


class GitFetchError(RuntimeError):
    pass


def is_git_url(source: str) -> bool:
    match = _SCHEME_RE.match(source)
    if match:
        return match.group(1).lower() in ALLOWED_SCHEMES
    return _SCP_RE.match(source) is not None


def disallowed_transport(source: str) -> str | None:
    """The offending transport name when ``source`` uses one we refuse."""
    match = _SCHEME_RE.match(source)
    if match and match.group(1).lower() not in ALLOWED_SCHEMES:
        return match.group(1).lower()
    helper = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*)::", source)
    return helper.group(1).lower() if helper else None


def strip_credentials(url: str) -> str:
    """Drop secrets from ``url``: all userinfo for http(s)/git, only the password for ssh."""
    if not _SCHEME_RE.match(url):
        return url
    parts = urlsplit(url)
    if "@" not in parts.netloc:
        return url
    userinfo, _, host = parts.netloc.rpartition("@")
    if parts.scheme.lower() in ("ssh",) and ":" not in userinfo:
        return url
    keep = userinfo.split(":", 1)[0] if parts.scheme.lower() == "ssh" else ""
    return urlunsplit(parts._replace(netloc=f"{keep}@{host}" if keep else host))


def _git(workdir: str, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *_SAFE_GIT, "-C", workdir, *args],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
        )
    except FileNotFoundError as e:
        raise GitFetchError("git is not installed") from e
    except subprocess.TimeoutExpired as e:
        raise GitFetchError(f"git {args[0]} timed out") from e
    if proc.returncode != 0:
        raise GitFetchError(f"git {args[0]} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def _resolve(workdir: str, ref: str | None) -> str:
    target = ref or "HEAD"
    try:
        _git(workdir, "fetch", "--depth", "1", "--filter=blob:none", "--no-tags", "origin", target)
        return _git(workdir, "rev-parse", "FETCH_HEAD").strip()
    except GitFetchError:
        if ref is None:
            raise
    # A bare commit SHA can only be fetched shallowly when the server allows it;
    # otherwise take the branches and tags and look the ref up locally.
    _git(
        workdir,
        "fetch",
        "--filter=blob:none",
        "--no-tags",
        "origin",
        "+refs/heads/*:refs/remotes/origin/*",
        "+refs/tags/*:refs/tags/*",
    )
    for candidate in (ref, f"origin/{ref}"):
        try:
            return _git(
                workdir, "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}"
            ).strip()
        except GitFetchError:
            continue
    raise GitFetchError(f"ref {ref!r} not found in the source")


def fetch_file(url: str, path: str, ref: str | None) -> tuple[str, str]:
    """Return (text, commit SHA) for ``path`` at ``ref`` of the remote at ``url``."""
    with tempfile.TemporaryDirectory(prefix="tkt-norms-") as workdir:
        _git(workdir, "init", "-q")
        _git(workdir, "remote", "add", "origin", "--", url)
        try:
            commit = _resolve(workdir, ref)
        except GitFetchError as e:
            raise GitFetchError(str(e).replace(url, strip_credentials(url))) from e
        try:
            text = _git(workdir, "show", f"{commit}:{path}")
        except GitFetchError as e:
            raise GitFetchError(f"{path} not found in the source at {commit[:7]}") from e
    return text, commit
