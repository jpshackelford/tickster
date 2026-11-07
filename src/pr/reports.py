"""Phase B steps: the three a repo's ``[reports.<name>]`` norms define.

A report is a PR comment whose first 200 characters match the report's ``marker``.
The latest one is "the report"; the head when it was posted is "the tested commit".
Each named report gives three steps: write the report, address what it found, and
redo it after a significant change. Nothing here assumes a report's name or format:
the repo's norms say how a report is recognised, when it is required and what counts
as a change, and without norms every step is ``not configured``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from src.actors import ACTOR_GROUP
from src.norms.model import Norms, Report, any_glob_match, pattern_matches
from src.pr.changes import ChangedFile, PRChanges
from src.pr.models import PRComment, PRInfo, PRState
from src.pr.step_types import Evidence, StepResult, StepStatus, result, short, unknown

MANUAL_TEST = "manual_test"
MANUAL_TEST_STEPS = ("manually test", "address test findings", "retest after a fix")

MAX_EXPLAINED_FILES = 10
_NONE = re.compile(r"\bnone\b", re.IGNORECASE)


@dataclass(frozen=True)
class ReportFacts:
    """What the reports' rules need beyond the PR itself, fetched by the caller.

    ``changes`` is keyed by tested commit (full SHA). ``pr_files`` are the files the
    whole PR changes; None when they were not fetched.
    """

    changes: Mapping[str, PRChanges] = field(default_factory=dict)
    pr_files: Sequence[ChangedFile] | None = None


def step_names(report_name: str) -> tuple[str, str, str]:
    """The three step names of a report; ``manual_test`` has its own wording."""
    if report_name == MANUAL_TEST:
        return MANUAL_TEST_STEPS
    label = report_name.replace("_", " ").replace("-", " ")
    return label, f"address {label} findings", f"redo {label} after a fix"


def report_names(norms: Norms | None) -> tuple[str, ...]:
    """``manual_test`` first, configured or not, then the other reports in file order."""
    others = [n for n in (norms.reports if norms else {}) if n != MANUAL_TEST]
    return (MANUAL_TEST, *others)


def all_step_names(norms: Norms | None) -> tuple[str, ...]:
    return tuple(name for report in report_names(norms) for name in step_names(report))


def _matching(pr: PRInfo, report: Report) -> list[PRComment]:
    return [c for c in pr.comments or () if pattern_matches(report.marker, c.text)]


def tested_commits(pr: PRInfo, norms: Norms | None) -> list[str]:
    """The commits whose later changes decide a retest: each report's tested commit
    that is not already the head."""
    if norms is None or pr.state is not PRState.OPEN or pr.timeline_truncated:
        return []
    found: list[str] = []
    for report in norms.reports.values():
        matches = _matching(pr, report)
        head = matches[-1].head if matches else None
        if head and head != pr.head_sha and head not in found:
            found.append(head)
    return found


def needs_pr_files(pr: PRInfo, norms: Norms | None) -> bool:
    """Whether a required report that is missing limits itself with ``only_paths``, which
    needs the PR's files to say whether it is wanted."""
    if norms is None or pr.state is not PRState.OPEN or pr.comments is None:
        return False
    return any(r.required and r.only_paths and not _matching(pr, r) for r in norms.reports.values())


def evaluate_report_steps(
    pr: PRInfo, norms: Norms | None, facts: ReportFacts | None = None
) -> tuple[StepResult, ...]:
    """Every report's three steps, in :func:`all_step_names` order."""
    facts = facts or ReportFacts()
    out: list[StepResult] = []
    for name in report_names(norms):
        report = norms.reports.get(name) if norms else None
        if report is None:
            out += _not_configured(name, norms)
        else:
            out += _report_steps(pr, name, report, facts)
    return tuple(out)


def closed_steps(
    norms: Norms | None, why: str, leading: Sequence[str] = ()
) -> tuple[StepResult, ...]:
    """Every step ``n/a``: the PR is merged or closed. ``leading`` names steps that come first."""
    return tuple(
        StepResult(step, StepStatus.NOT_APPLICABLE, (Evidence("pr", why),), (why,))
        for step in (*leading, *all_step_names(norms))
    )


def _not_configured(name: str, norms: Norms | None) -> list[StepResult]:
    why = (
        "no .agents/tickster.toml on the default branch"
        if norms is None
        else f"no [reports.{name}] in .agents/tickster.toml"
    )
    return [
        StepResult(step, StepStatus.NOT_CONFIGURED, (Evidence("norms", why),), (why,))
        for step in step_names(name)
    ]


def _report_steps(pr: PRInfo, name: str, report: Report, facts: ReportFacts) -> list[StepResult]:
    test, findings, retest = step_names(name)
    if pr.comments is None:
        why = "comments were not fetched"
        return [unknown(step, why) for step in (test, findings, retest)]

    matches = _matching(pr, report)
    latest = matches[-1] if matches else None
    base = [
        f"[reports.{name}] marker = '{report.marker.pattern}' matched {len(matches)} of "
        f"{len(pr.comments)} comments",
    ]
    if latest:
        base.append(
            f"the report is the latest match: {latest.actor} at {latest.at}; "
            f"tested commit {short(latest.head)}"
        )
    return [
        _test_step(pr, name, report, test, latest, facts, base),
        _findings_step(pr, name, report, findings, latest, base),
        _retest_step(pr, name, report, retest, latest, facts, base),
    ]


def _report_evidence(c: PRComment) -> Evidence:
    return Evidence("report", f"report by {c.actor} at {c.at} on {short(c.head)}", c.head)


def _test_step(
    pr: PRInfo,
    name: str,
    report: Report,
    step: str,
    latest: PRComment | None,
    facts: ReportFacts,
    base: list[str],
) -> StepResult:
    explain = [
        f"[reports.{name}] required = {str(report.required).lower()}, "
        f"only_paths = [{', '.join(report.only_paths)}]",
        *base,
    ]
    if latest:
        explain.append("a report exists: done")
        return result(step, StepStatus.DONE, [_report_evidence(latest)], explain)
    if not report.required:
        explain.append("no report, and one is not required: n/a")
        return result(step, StepStatus.NOT_APPLICABLE, [Evidence("norms", "not required")], explain)
    if report.only_paths:
        if facts.pr_files is None:
            return unknown(step, "the PR's changed files were not fetched")
        hits = [f.path for f in facts.pr_files if any_glob_match(report.only_paths, f.path)]
        explain.append(
            f"{len(hits)} of {len(facts.pr_files)} changed files match only_paths"
            + (f": {', '.join(hits[:MAX_EXPLAINED_FILES])}" if hits else "")
        )
        if not hits:
            evidence = [Evidence("norms", "no changed file matches only_paths")]
            return result(step, StepStatus.NOT_APPLICABLE, evidence, explain)
    if pr.timeline_truncated:
        return unknown(step, "the timeline is truncated, so a report may be missing")
    explain.append("required and no comment matches the marker: needed")
    return result(step, StepStatus.NEEDED, [Evidence("report", "no report")], explain)


def _findings_step(
    pr: PRInfo,
    name: str,
    report: Report,
    step: str,
    latest: PRComment | None,
    base: list[str],
) -> StepResult:
    if pr.timeline_truncated:
        return unknown(step, "the timeline is truncated, so a newer report may be missing")
    if latest is None:
        explain = [*base, "no report: n/a"]
        return result(step, StepStatus.NOT_APPLICABLE, [Evidence("report", "no report")], explain)
    if report.fail is None:
        explain = [*base, f"[reports.{name}] has no fail pattern, so a report never fails: done"]
        return result(step, StepStatus.DONE, [Evidence("report", "no fail pattern")], explain)
    failed = pattern_matches(report.fail, latest.text)
    explain = [
        *base,
        f"[reports.{name}] fail = '{report.fail.pattern}' "
        f"{'matches' if failed else 'does not match'} the latest report",
    ]
    if failed:
        evidence = [Evidence("report", f"latest report matches fail, by {latest.actor}")]
        return result(step, StepStatus.NEEDED, evidence, explain)
    return result(
        step, StepStatus.DONE, [Evidence("report", "latest report has no fail match")], explain
    )


def _retest_step(
    pr: PRInfo,
    name: str,
    report: Report,
    step: str,
    latest: PRComment | None,
    facts: ReportFacts,
    base: list[str],
) -> StepResult:
    if pr.timeline_truncated:
        return unknown(step, "the timeline is truncated, so a newer report may be missing")
    if latest is None:
        return result(
            step,
            StepStatus.NOT_APPLICABLE,
            [Evidence("report", "no report")],
            [*base, "no report: n/a"],
        )
    tested = latest.head
    if tested is None or pr.head_sha is None:
        return unknown(step, "the head when the report was posted is unknown")
    explain = [*base, f"head is {short(pr.head_sha)}"]
    if tested == pr.head_sha:
        explain.append("the report was posted on the head: done")
        evidence = [Evidence("commit", f"report is on head {short(tested)}", tested)]
        return result(step, StepStatus.DONE, evidence, explain)

    change = facts.changes.get(tested)
    if change is None:
        return unknown(step, f"changes since {short(tested)} were not fetched")
    explain += _change_lines(change)
    since = f"since {short(tested)}"
    if not change.significant:
        explain.append("the change is not significant: done")
        evidence = [Evidence("change", f"no significant change {since}: {change.reasons[0]}")]
        return result(step, StepStatus.DONE, evidence, explain)

    impact_explain, covering, waived = _impact(pr, name, report, change)
    explain += impact_explain
    significant = Evidence("change", f"significant change {since}: {'; '.join(change.reasons)}")
    if covering is not None and waived:
        explain.append("an allowed actor waived the change: done")
        waiver = Evidence("impact", f"{covering.actor} said none at {covering.at}", covering.actor)
        return result(step, StepStatus.DONE, [significant, waiver], explain)
    if covering is None and report.impact_line and report.impact_line.unassessed == "ignore":
        explain.append("no impact line covers the change and unassessed = ignore: done")
        evidence = [significant, Evidence("impact", "unassessed, ignored")]
        return result(step, StepStatus.DONE, evidence, explain)
    explain.append("the change is significant and not waived: needed")
    evidence = [significant, Evidence("report", f"report is on {short(tested)}", tested)]
    if covering:
        evidence.append(Evidence("impact", f"{covering.actor} said rerun at {covering.at}"))
    return result(step, StepStatus.NEEDED, evidence, explain)


def _change_lines(change: PRChanges) -> list[str]:
    own = [c for c in change.commits if not c.merge and not c.from_base]
    lines = [
        f"significant since {short(change.since)}: {'yes' if change.significant else 'no'} "
        f"({'; '.join(change.reasons)})"
    ]
    if change.significant and own:
        lines.append(
            "commits that count: " + ", ".join(f'{short(c.sha)} "{c.headline}"' for c in own)
        )
    counted = [f for f in change.files if f.path not in change.ignored]
    if change.significant and counted:
        shown = [f"{f.path} +{f.additions} -{f.deletions}" for f in counted[:MAX_EXPLAINED_FILES]]
        more = len(counted) - len(shown)
        lines.append(
            "files that count: " + ", ".join(shown) + (f", and {more} more" if more > 0 else "")
        )
    if change.ignored:
        ignored = sorted(change.ignored)[:MAX_EXPLAINED_FILES]
        lines.append(f"files ignored by [commits] ignore_paths: {', '.join(ignored)}")
    return lines


def _impact(
    pr: PRInfo, name: str, report: Report, change: PRChanges
) -> tuple[list[str], PRComment | None, bool]:
    """The latest impact line that covers the change, from an allowed actor.

    Returns ``(explain, comment, waived)``; ``comment`` is None when no line covers it.
    """
    line = report.impact_line
    if line is None:
        return (
            [f"[reports.{name}] has no impact_line, so nothing can waive the change"],
            None,
            False,
        )
    explain = [
        f"[reports.{name}.impact_line] pattern = '{line.pattern.pattern}' "
        f"from = [{', '.join(line.from_)}] unassessed = {line.unassessed}"
    ]

    shas = [c.sha for c in change.commits]
    own = [i for i, c in enumerate(change.commits) if not c.merge and not c.from_base]
    boundary = own[-1] if own else None

    def covers(c: PRComment) -> bool:
        if c.head is None:
            return False
        if c.head == pr.head_sha:
            return True
        return boundary is not None and c.head in shas and shas.index(c.head) >= boundary

    def allowed(c: PRComment) -> bool:
        if "author" in line.from_ and c.actor.lower() == pr.author.lower():
            return True
        return ACTOR_GROUP[c.actor_class] in line.from_

    verdict: tuple[PRComment, re.Match[str]] | None = None
    for c in pr.comments or ():
        found = line.pattern.search(c.text)
        if not found:
            continue
        if not covers(c):
            explain.append(f"impact line by {c.actor} at {c.at} is before the change: ignored")
        elif not allowed(c):
            explain.append(
                f"impact line by {c.actor} ({c.actor_class.value}) at {c.at}: "
                f"not from an allowed actor, ignored"
            )
        else:
            verdict = (c, found)
    if verdict is None:
        explain.append("no impact line from an allowed actor covers the change")
        return explain, None, False
    comment, found = verdict
    says = next((g for g in found.groups() if g), found.group(0))
    waived = _NONE.search(says) is not None
    explain.append(
        f"impact line by {comment.actor} at {comment.at} says '{says}': "
        f"{'waives' if waived else 'does not waive'} the change"
    )
    return explain, comment, waived
