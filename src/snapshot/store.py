"""Filesystem store for snapshots under ~/.tkt/snapshots/.

One JSON file per snapshot: `<kind>-<name>.json`. Named snapshots
(`--snapshot=hourly`) overwrite in place; auto-timestamped snapshots use
`ts-YYYYMMDDTHHMMSSZ` as the name so they coexist.

A `--diff NAME` run stages its result as a pending baseline in
`pending/<kind>-<name>.json`; `tkt snapshot ack` promotes it. The separate
directory keeps a pending file from colliding with any snapshot name.

Pure filesystem, no network. Any snapshot can be inspected or edited with a
text editor; schema is versioned (see `models.SCHEMA_VERSION`). A file this tkt
cannot read (another schema, invalid JSON, a missing or mistyped field) is deleted
with a notice and then counts as missing.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from src.board import config as _board_config
from src.snapshot.models import VALID_KINDS, Snapshot

logger = logging.getLogger(__name__)

_SNAPSHOTS_DIRNAME = "snapshots"
_PENDING_DIRNAME = "pending"
_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def snapshots_dir() -> Path:
    """Return the snapshots directory, creating it if needed.

    Reads `TKT_HOME` from `src.board.config` on each call so tests that
    monkeypatch the attribute take effect without re-importing this module.
    """
    _board_config.ensure_tkt_home()
    d = _board_config.TKT_HOME / _SNAPSHOTS_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def slugify(name: str) -> str:
    """Normalize a snapshot name to a safe filesystem fragment."""
    cleaned = _SLUG_RE.sub("-", name.strip()).strip("-.")
    if not cleaned:
        raise ValueError(f"invalid snapshot name: {name!r}")
    return cleaned


def auto_timestamp_name() -> str:
    """Auto-timestamped snapshot name (`ts-YYYYMMDDTHHMMSSZ`)."""
    return "ts-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _validate_kind(kind: str) -> None:
    if kind not in VALID_KINDS:
        raise ValueError(f"invalid snapshot kind: {kind!r}; expected one of {VALID_KINDS}")


def path_for(kind: str, name: str) -> Path:
    """Return the on-disk path for a snapshot (kind, name)."""
    _validate_kind(kind)
    return snapshots_dir() / f"{kind}-{slugify(name)}.json"


def pending_path_for(kind: str, name: str) -> Path:
    """Return the on-disk path for the pending baseline of (kind, name)."""
    _validate_kind(kind)
    return snapshots_dir() / _PENDING_DIRNAME / f"{kind}-{slugify(name)}.json"


def _write(snapshot: Snapshot, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".json.tmp")
    payload = json.dumps(snapshot.to_dict(), indent=2, sort_keys=False)
    with tmp.open("w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(dst)
    return dst


def save(snapshot: Snapshot) -> Path:
    """Persist a snapshot to disk, atomically. Returns the written path.

    Writes to a sibling `.tmp` and `rename`s into place. The `fsync`
    before `replace` ensures the tmp file's contents actually hit the disk
    before the rename, so a crash can't leave a zero-byte baseline file
    that a watching agent would then trust for weeks.
    """
    _validate_kind(snapshot.kind)
    dst = path_for(snapshot.kind, snapshot.name)
    stored_name = slugify(snapshot.name)
    if stored_name != snapshot.name:
        logger.warning("tkt: snapshot name %r is stored as %r", snapshot.name, stored_name)
    return _write(snapshot, dst)


def save_pending(snapshot: Snapshot) -> Path:
    """Stage `snapshot` as the pending baseline; the saved baseline is untouched."""
    _validate_kind(snapshot.kind)
    return _write(snapshot, pending_path_for(snapshot.kind, snapshot.name))


def load(kind: str, name: str) -> Snapshot:
    """Load a snapshot by (kind, name).

    Raises FileNotFoundError if absent. A file that cannot be read is deleted with a
    notice and raises FileNotFoundError too.
    """
    return _read(path_for(kind, name), kind, name)


def load_pending(kind: str, name: str) -> Snapshot:
    """Load the pending baseline of (kind, name); same errors as `load`."""
    return _read(pending_path_for(kind, name), kind, name, what="pending baseline")


def _read(p: Path, kind: str, name: str, what: str = "snapshot") -> Snapshot:
    missing = FileNotFoundError(f"{what} not found: {kind}/{name} (looked in {p})")
    if not p.exists():
        raise missing
    try:
        return Snapshot.from_dict(json.loads(p.read_text()))
    except json.JSONDecodeError as e:
        reason = f"invalid JSON at line {e.lineno} column {e.colno}"
    except ValueError as e:
        reason = str(e)
    p.unlink(missing_ok=True)
    logger.warning("tkt: discarded %s %s/%s: %s", what, kind, name, reason)
    raise missing


def exists(kind: str, name: str) -> bool:
    return path_for(kind, name).exists()


def has_pending(kind: str, name: str) -> bool:
    return pending_path_for(kind, name).exists()


def delete_pending(kind: str, name: str) -> bool:
    """Delete a pending baseline. Returns True if it existed and was removed."""
    p = pending_path_for(kind, name)
    if not p.exists():
        return False
    p.unlink()
    return True


def delete(kind: str, name: str) -> bool:
    """Delete a snapshot and its pending baseline. True if either existed."""
    p = path_for(kind, name)
    existed = p.exists()
    if existed:
        p.unlink()
    return delete_pending(kind, name) or existed


def ack(kind: str, name: str) -> bool:
    """Promote the pending baseline of (kind, name) to the saved baseline.

    Returns False if nothing is pending. The baseline is written before the
    pending file is removed, so a crash in between leaves a re-ackable state.
    """
    if not has_pending(kind, name):
        return False
    pending = load_pending(kind, name)
    save(replace(pending, name=name))
    delete_pending(kind, name)
    return True


@dataclass(frozen=True)
class SnapshotRecord:
    """Metadata about a stored snapshot, used by `list_()`."""

    kind: str
    name: str
    captured_at: str
    scope_hash: str
    item_count: int
    path: Path
    pending: bool = False


def list_(kind: str | None = None) -> list[SnapshotRecord]:
    """List stored snapshots, optionally filtered by kind.

    Reads each `<kind>-*.json` file like `load` does, so an unreadable one is deleted
    with a notice instead of listed. Other `*.json` files are skipped.
    """
    if kind is not None:
        _validate_kind(kind)
    out: list[SnapshotRecord] = []
    for p in sorted(snapshots_dir().glob("*.json")):
        file_kind = next((k for k in VALID_KINDS if p.name.startswith(f"{k}-")), None)
        if file_kind is None or (kind is not None and file_kind != kind):
            continue
        file_name = p.stem[len(file_kind) + 1 :]
        try:
            snap = _read(p, file_kind, file_name)
        except FileNotFoundError:
            continue
        out.append(
            SnapshotRecord(
                kind=snap.kind,
                name=snap.name,
                captured_at=snap.captured_at,
                scope_hash=snap.scope_hash,
                item_count=len(snap.items),
                path=p,
                pending=pending_path_for(snap.kind, snap.name).exists(),
            )
        )
    return out
