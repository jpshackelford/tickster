"""The row: the object for one issue, PR or review.

A row is the unit of the list JSON, the snapshot file and the diff `prev` / `curr`.
`ROW_FIELDS` is the one table of which keys a row of each kind has, in order.
Every key is always present: `null` means none, `[]` means empty. `decode_row`
reads a row strictly; anything else raises `ValueError`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from src.issue.models import Milestone
from src.pr.reviewers import ReviewerState

KIND_PR = "pr"
KIND_ISSUE = "issue"
KIND_REVIEW = "review"
VALID_KINDS = (KIND_PR, KIND_ISSUE, KIND_REVIEW)

ROW_COMMON = (
    "ref",
    "kind",
    "repo",
    "number",
    "url",
    "title",
    "state",
    "author",
    "labels",
    "history",
    "created_at",
    "last_activity",
)
ISSUE_FIELDS = ("linked_pr", "closed_at", "open_blockers", "blocking", "parent", "milestone")
PR_FIELDS = (
    "draft",
    "ci",
    "unresolved_threads",
    "head",
    "review_decision",
    "merge_state",
    "mergeable",
    "reviewers",
    "step_status",
)
REVIEW_FIELDS = ("review_status", "wait_seconds")

ROW_FIELDS: dict[str, tuple[str, ...]] = {
    KIND_ISSUE: ROW_COMMON + ISSUE_FIELDS,
    KIND_PR: ROW_COMMON + PR_FIELDS,
    KIND_REVIEW: ROW_COMMON + PR_FIELDS + REVIEW_FIELDS,
}


def item_url(repo: str, kind: str, number: int) -> str:
    """The web URL of an issue, PR or review row."""
    path = "issues" if kind == KIND_ISSUE else "pull"
    return f"https://github.com/{repo}/{path}/{number}"


def as_str(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError(value)
    return value


def as_opt_str(value: Any) -> str | None:
    return None if value is None else as_str(value)


def as_bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise TypeError(value)
    return value


def as_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(value)
    return value


def as_opt_int(value: Any) -> int | None:
    return None if value is None else as_int(value)


def as_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(value)
    return value


def as_strs(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TypeError(value)
    return tuple(as_str(v) for v in value)


def as_opt_strs(value: Any) -> tuple[str, ...] | None:
    return None if value is None else as_strs(value)


def _as_milestone(value: Any) -> Milestone | None:
    if value is None:
        return None
    return Milestone(title=as_str(value["title"]), due_on=as_opt_str(value["due_on"]))


def _as_reviewer(value: Any) -> ReviewerState:
    return ReviewerState(
        login=as_str(value["login"]),
        actor_class=as_opt_str(value["actor_class"]),
        requested=as_bool(value["requested"]),
        requested_by=as_opt_str(value["requested_by"]),
        requested_at=as_opt_str(value["requested_at"]),
        as_code_owner=as_bool(value["as_code_owner"]),
        latest_state=as_opt_str(value["latest_state"]),
        reviewed_commit=as_opt_str(value["reviewed_commit"]),
        on_head=as_bool(value["on_head"]),
        submitted_at=as_opt_str(value["submitted_at"]),
    )


def _as_reviewers(value: Any) -> tuple[ReviewerState, ...]:
    if not isinstance(value, list):
        raise TypeError(value)
    return tuple(_as_reviewer(v) for v in value)


def _as_step_status(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise TypeError(value)
    return {as_str(k): as_str(v) for k, v in value.items()}


_DECODERS: dict[str, Callable[[Any], Any]] = {
    "ref": as_str,
    "kind": as_str,
    "repo": as_str,
    "number": as_int,
    "url": as_str,
    "title": as_str,
    "state": as_str,
    "author": as_str,
    "labels": as_strs,
    "history": as_str,
    "created_at": as_str,
    "last_activity": as_str,
    "linked_pr": as_opt_str,
    "closed_at": as_opt_str,
    "open_blockers": as_strs,
    "blocking": as_int,
    "parent": as_opt_str,
    "milestone": _as_milestone,
    "draft": as_bool,
    "ci": as_str,
    "unresolved_threads": as_int,
    "head": as_opt_str,
    "review_decision": as_opt_str,
    "merge_state": as_opt_str,
    "mergeable": as_opt_str,
    "reviewers": _as_reviewers,
    "step_status": _as_step_status,
    "review_status": as_str,
    "wait_seconds": as_number,
}

_ENCODERS: dict[str, Callable[[Any], Any]] = {
    "labels": list,
    "open_blockers": list,
    "milestone": lambda m: m.to_dict() if m else None,
    "reviewers": lambda rs: [r.to_dict() for r in rs],
    "step_status": lambda s: dict(s) if s is not None else None,
}


def encode_field(name: str, value: Any) -> Any:
    encode = _ENCODERS.get(name)
    return encode(value) if encode else value


def read_field(data: Mapping[str, Any], name: str, decode: Callable[[Any], Any]) -> Any:
    """Decode `data[name]`, raising `ValueError` if it is missing or has the wrong type."""
    if name not in data:
        raise ValueError(f"missing field {name!r}")
    try:
        return decode(data[name])
    except (TypeError, ValueError, KeyError, AttributeError):
        raise ValueError(f"field {name!r} has the wrong type") from None


def decode_row(data: Any) -> dict[str, Any]:
    """The attributes of a row read from `data`; `ValueError` if it is not exactly a row."""
    if not isinstance(data, dict):
        raise ValueError("a row is not a JSON object")
    kind = data.get("kind")
    if kind not in VALID_KINDS:
        raise ValueError(f"field 'kind' has the wrong type: {kind!r}")
    fields = ROW_FIELDS[kind]
    for name in data:
        if name not in fields:
            raise ValueError(f"unexpected field {name!r}")
    return {name: read_field(data, name, _DECODERS[name]) for name in fields}
