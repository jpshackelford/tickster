"""Text and JSON output for ``show``."""

from __future__ import annotations

import json

from src.history_legend import AI_CASE_RULE, case_rule, chars_text
from src.issue.dependencies import deps_line
from src.issue.models import Milestone
from src.pr.detail import short_sha
from src.pr.reviewers import ReviewerState, reviewer_mark
from src.show.models import Entry, ReportStatus, Show, Thread

_HISTORY_INTRO = (
    "Legend: the letter is the event's history character ("
    f"{case_rule()}; {AI_CASE_RULE}; - = not in the history string). "
)
PR_LEGEND = (
    f"{_HISTORY_INTRO}{chars_text('pr')}. Class: me human bot agent me_agent. "
    "↳ marks a review thread: path:line, resolved or unresolved."
)
ISSUE_LEGEND = (
    f"{_HISTORY_INTRO}{chars_text('issue')}. "
    "blocked by: open blockers (? = one you cannot read), blocks: open issues this one blocks. "
    "Class: me human bot agent me_agent."
)

_REVIEW_LABELS = {
    "APPROVED": "approved",
    "CHANGES_REQUESTED": "changes requested",
    "COMMENTED": "commented",
    "DISMISSED": "dismissed",
}


def render_json(show: Show) -> str:
    return json.dumps(show.to_dict(), indent=2, ensure_ascii=False)


def render_text(show: Show) -> list[str]:
    lines = _pr_header(show) if show.kind == "pr" else _issue_header(show)
    lines.append(PR_LEGEND if show.kind == "pr" else ISSUE_LEGEND)
    if show.truncated:
        lines.append("(timeline truncated: events past the fetch cap are missing)")
    if show.since is not None:
        if not show.entries:
            lines.append(f"no new events since {show.since}")
            return lines
        lines.append(f"timeline since {show.since}: {len(show.entries)} events, oldest first")
    else:
        lines.append(f"timeline: {len(show.entries)} events, oldest first")
    for entry in show.entries:
        lines.extend(_entry_lines(entry))
    return lines


def _flat(text: str | None) -> str:
    return " ".join((text or "").split())


def _entry_lines(entry: Entry) -> list[str]:
    line = f"{entry.at} {entry.char} {entry.actor}({entry.actor_class.value}) {entry.text}"
    if entry.body:
        line += f": {_flat(entry.body)}"
    lines = [line]
    for thread in entry.threads:
        lines.extend(_thread_lines(thread))
    return lines


def _thread_lines(thread: Thread) -> list[str]:
    state = "resolved" if thread.resolved else "unresolved"
    if thread.outdated:
        state += ", outdated"
    lines = [f"  ↳ {thread.place} [{state}]"]
    for c in thread.comments:
        line = f"    {c.at} {c.actor}({c.actor_class.value})"
        lines.append(f"{line}: {_flat(c.body)}" if c.body else line)
    return lines


def _item_row(show: Show) -> str:
    h = show.header
    parts = [show.ref, show.kind, h["state"]]
    if show.kind == "pr":
        parts.append("draft" if h["draft"] else "ready")
        parts.append(f"ci:{h['ci']}")
        parts.append(f"💬{h['unresolved_threads']}")
    return " ".join(parts) + f' "{show.title}"'


def _pr_header(show: Show) -> list[str]:
    h = show.header
    lines = [
        _item_row(show),
        f"history: {h['history'] or '--'}",
        f"author: {h['author']}  created: {h['created_at']}  last activity: {h['last_activity']}",
        f"head: {short_sha(h['head'])}  mergeable: {_lower(h['mergeable'])}  "
        f"merge: {_lower(h['merge_state'])}  review: {_lower(h['review_decision'])}",
        f"reviewers: {_reviewers(show)}",
        f"linked issues: {', '.join(h['linked_issues']) or '--'}",
    ]
    if show.reports:
        lines.append("reports: " + "; ".join(_report(r) for r in show.reports))
    return lines


def _issue_header(show: Show) -> list[str]:
    h = show.header
    linked = ", ".join(f"{p['ref']} ({p['state']})" for p in h["linked_prs"]) or "--"
    lines = [
        _item_row(show),
        f"history: {h['history'] or '--'}",
        f"author: {h['author']}  created: {h['created_at']}  last activity: {h['last_activity']}",
        f"labels: {', '.join(h['labels']) or '--'}  assignees: {', '.join(h['assignees']) or '--'}",
        f"linked PRs: {linked}",
    ]
    milestone = Milestone.from_dict(h["milestone"]) if h["milestone"] else None
    deps = deps_line(h["open_blockers"], h["blocking"], h["parent"], milestone, show.repo)
    if deps:
        lines.append(deps)
    return lines


def _lower(value: str | None) -> str:
    return value.lower() if value else "--"


def _reviewers(show: Show) -> str:
    if not show.reviewers:
        return "--"
    text = " | ".join(_reviewer(ReviewerState.from_dict(r)) for r in show.reviewers)
    return text + " …" if show.header.get("reviewers_truncated") else text


def _reviewer(r: ReviewerState) -> str:
    who = f"{r.login}({r.actor_class})" if r.actor_class else r.login
    parts = [f"{who} {reviewer_mark(r)}"]
    if r.latest_state:
        label = _REVIEW_LABELS.get(r.latest_state, r.latest_state.lower())
        where = "on head" if r.on_head else f"on {short_sha(r.reviewed_commit)}, not head"
        parts.append(f"{label} {where}")
    if r.rereview_requested:
        parts.append("re-review requested")
    elif r.waiting:
        parts.append("review requested")
    if r.rereview_needed:
        parts.append("re-review needed")
    return " ".join(parts)


def _report(report: ReportStatus) -> str:
    if not report.found:
        return f"{report.name} none"
    where = {True: "on head", False: "not on head", None: "head unknown"}[report.on_head]
    verdict = "FAIL" if report.failed else "no fail match"
    return (
        f"{report.name} {report.at} by {report.actor} at {short_sha(report.head)} "
        f"({where}) {verdict}"
    )
