"""Filesystem store for snapshots under ~/.tkt/snapshots/.

One JSON file per snapshot: `<kind>-<name>.json`. Named snapshots
(`--snapshot=hourly`) overwrite in place; auto-timestamped snapshots use
`ts-YYYYMMDDTHHMMSSZ` as the name so they coexist.

Pure filesystem, no network. Any snapshot can be inspected or edited with a
text editor; schema is versioned (see `models.SCHEMA_VERSION`).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from src.board import config as _board_config
from src.snapshot.models import VALID_KINDS, Snapshot

_SNAPSHOTS_DIRNAME = "snapshots"
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


def save(snapshot: Snapshot) -> Path:
    """Persist a snapshot to disk, atomically. Returns the written path.

    Writes to a sibling `.tmp` and `rename`s into place. The `fsync`
    before `replace` ensures the tmp file's contents actually hit the disk
    before the rename, so a crash can't leave a zero-byte baseline file
    that a watching agent would then trust for weeks.
    """
    _validate_kind(snapshot.kind)
    dst = path_for(snapshot.kind, snapshot.name)
    tmp = dst.with_suffix(".json.tmp")
    payload = json.dumps(snapshot.to_dict(), indent=2, sort_keys=False)
    with tmp.open("w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(dst)
    return dst


def load(kind: str, name: str) -> Snapshot:
    """Load a snapshot by (kind, name). Raises FileNotFoundError if absent."""
    p = path_for(kind, name)
    if not p.exists():
        raise FileNotFoundError(f"snapshot not found: {kind}/{name} (looked in {p})")
    return Snapshot.from_dict(json.loads(p.read_text()))


def exists(kind: str, name: str) -> bool:
    return path_for(kind, name).exists()


def delete(kind: str, name: str) -> bool:
    """Delete a snapshot. Returns True if it existed and was removed."""
    p = path_for(kind, name)
    if not p.exists():
        return False
    p.unlink()
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


def list_(kind: str | None = None) -> list[SnapshotRecord]:
    """List stored snapshots, optionally filtered by kind.

    Reads only metadata (not the item list) for speed on large snapshots —
    we still have to parse the JSON header, but the item array is small
    relative to the typical hundred-item snapshot so this stays cheap.
    """
    if kind is not None:
        _validate_kind(kind)
    out: list[SnapshotRecord] = []
    for p in sorted(snapshots_dir().glob("*.json")):
        try:
            data = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        k = data.get("kind")
        if k not in VALID_KINDS:
            continue
        if kind is not None and k != kind:
            continue
        out.append(
            SnapshotRecord(
                kind=k,
                name=data.get("name", p.stem),
                captured_at=data.get("captured_at", ""),
                scope_hash=data.get("scope_hash", ""),
                item_count=len(data.get("items", [])),
                path=p,
            )
        )
    return out
