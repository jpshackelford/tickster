"""Which of a PR's follow-up steps still need to happen, and the evidence for each.

Phase A covers the four steps GitHub's own data can settle: review, CI, review
findings and re-review. Each rule is a pure function of a :class:`PRInfo`, the repo's
norms (``[review]``, ``[ci]``) and, when ``[ci] ignore_checks`` is in play, the
head commit's individual checks. Phase B (see :mod:`src.pr.reports`) adds three steps
per ``[reports.<name>]`` the repo's norms define. A step says whether it is pending,
not when it should happen: order is policy, and it belongs to the consumer.

Not detected: findings left in a review summary or a plain comment rather than
in a thread.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import assert_never

from src.actors import ACTOR_GROUP, ActorClass
from src.norms.model import CI, Norms, Review, any_glob_match
from src.pr.checks import OUTCOME_FAILED, OUTCOME_PENDING, CheckContext
from src.pr.models import PRInfo, PRState
from src.pr.reports import (
    MANUAL_TEST_STEPS,
    ReportFacts,
    all_step_names,
    closed_steps,
    evaluate_report_steps,
)
from src.pr.reviewers import (
    CHANGES_REQUESTED,
    DISMISSED,
    ReviewerState,
)
from src.pr.step_types import Evidence, StepResult, StepStatus, result, short, unknown

STEP_REVIEW = "review the PR"
STEP_CI = "fix CI"
STEP_FINDINGS = "address review findings"
STEP_REREVIEW = "request re-review"
PHASE_A_STEPS = (STEP_REVIEW, STEP_CI, STEP_FINDINGS, STEP_REREVIEW)
STEP_NAMES = (*PHASE_A_STEPS, *MANUAL_TEST_STEPS)

# One character per step in `pr list --steps`, in STEP_NAMES order. A report other than
# manual_test has steps in `pr steps` and snapshots but no column.
STEP_LETTERS = "rcfamtx"

MARK_DONE = "✓"
MARK_NA = "·"

STEPS_LEGEND = (
    "Steps: r review, c fix CI, f review findings, a re-review, "
    "m manual test, t test findings, x retest. "
    f"UPPER needed, lower waiting, {MARK_DONE} done, {MARK_NA} n/a, ? unknown, - not configured. "
    f"Only {MARK_DONE} and {MARK_NA} ({MARK_DONE * len(STEP_LETTERS)}) = every step done or n/a: "
    "nothing pending."
)

_ROLLUP_PENDING = frozenset({"PENDING", "EXPECTED"})
_ROLLUP_FAILED = frozenset({"FAILURE", "ERROR"})
_ROLLUP_PASSED = frozenset({"SUCCESS"})
_MERGEABLE_UNKNOWN = "UNKNOWN"


def needs_check_details(pr: PRInfo, norms: Norms | None) -> bool:
    """Whether judging CI needs the individual checks: the rollup is unfinished or failing
    and some checks may be ignored."""
    ignore = norms.ci.ignore_checks if norms else ()
    return bool(ignore) and pr.checks_state in (_ROLLUP_FAILED | _ROLLUP_PENDING)


def evaluate_steps(
    pr: PRInfo,
    norms: Norms | None,
    checks: Sequence[CheckContext] | None = None,
    report_facts: ReportFacts | None = None,
) -> tuple[StepResult, ...]:
    """Every step for ``pr``: the four Phase A steps, then the three of each report.

    The order is :data:`STEP_NAMES` (Phase A and ``manual_test``), then the other
    ``[reports.<name>]`` in file order; :func:`step_names_for` lists them.

    ``checks`` are the head commit's individual checks; they are only read when
    ``[ci] ignore_checks`` names something and the rollup is not green.
    ``report_facts`` are what the report steps need beyond the PR: the changes since
    each tested commit and, for ``only_paths``, the PR's files.
    """
    if pr.state is not PRState.OPEN:
        return closed_steps(norms, f"PR is {pr.state.value}", PHASE_A_STEPS)
    review = norms.review if norms else Review()
    ci = norms.ci if norms else CI()
    return (
        _review_step(pr, review, norms),
        _ci_step(pr, ci, checks, norms),
        _findings_step(pr, review, norms),
        _rereview_step(pr, review, norms),
        *evaluate_report_steps(pr, norms, report_facts),
    )


def step_names_for(norms: Norms | None) -> tuple[str, ...]:
    """The names of the steps :func:`evaluate_steps` returns for a repo with ``norms``."""
    return (*PHASE_A_STEPS, *all_step_names(norms))


def _settings_line(norms: Norms | None, setting: str, value: Sequence[str]) -> str:
    source = "default (no norms file)" if norms is None else "from .agents/tickster.toml"
    return f"{setting} = [{', '.join(value) or ''}] ({source})"


def _counted(pr: PRInfo, review: Review) -> list[ReviewerState]:
    """Reviewers whose class is in ``count_reviews_from``; a team counts as humans."""
    wanted = set(review.count_reviews_from)
    return [
        r
        for r in pr.reviewers or ()
        if (ACTOR_GROUP[ActorClass(r.actor_class)] if r.actor_class else "humans") in wanted
    ]


def _reviewed(reviewers: Sequence[ReviewerState]) -> list[ReviewerState]:
    """Reviewers with a standing review; a dismissed review no longer counts."""
    return [r for r in reviewers if r.reviewed and r.latest_state != DISMISSED]


def _review_text(r: ReviewerState) -> str:
    return f"{r.login} {r.latest_state} on {short(r.reviewed_commit)}"


def _review_evidence(r: ReviewerState) -> Evidence:
    return Evidence("review", _review_text(r), r.reviewed_commit)


def _request_evidence(r: ReviewerState) -> Evidence:
    by = f" by {r.requested_by}" if r.requested_by else ""
    when = f" at {r.requested_at}" if r.requested_at else ""
    return Evidence("request", f"{r.login} requested{by}{when}", r.login)


def _review_step(pr: PRInfo, review: Review, norms: Norms | None) -> StepResult:
    if pr.is_draft:
        return result(
            STEP_REVIEW,
            StepStatus.NOT_APPLICABLE,
            [Evidence("pr", "draft PR")],
            ["PR is a draft, so there is nothing to review yet"],
        )
    if pr.reviewers is None:
        return unknown(STEP_REVIEW, "reviewer data was not fetched")

    counted = _counted(pr, review)
    explain = [
        _settings_line(norms, "[review] count_reviews_from", review.count_reviews_from),
        f"counted reviewers: {', '.join(r.login for r in counted) or 'none'} "
        f"of {len(pr.reviewers)} on the PR",
    ]
    reviewed = _reviewed(counted)
    if reviewed:
        explain.append("a counted reviewer has reviewed (any state): done")
        return result(
            STEP_REVIEW, StepStatus.DONE, [_review_evidence(r) for r in reviewed], explain
        )
    waiting = [r for r in counted if r.waiting]
    if waiting:
        explain.append("no counted reviewer has reviewed, and one is requested: waiting")
        return result(
            STEP_REVIEW, StepStatus.WAITING, [_request_evidence(r) for r in waiting], explain
        )
    explain.append("no counted reviewer has reviewed and none is requested: needed")
    return result(
        STEP_REVIEW,
        StepStatus.NEEDED,
        [
            Evidence("review", "no counted reviewer has reviewed"),
            Evidence("request", "none requested"),
        ],
        explain,
    )


def _ci_step(
    pr: PRInfo, ci: CI, checks: Sequence[CheckContext] | None, norms: Norms | None
) -> StepResult:
    explain = [_settings_line(norms, "[ci] ignore_checks", ci.ignore_checks)]
    state = pr.checks_state
    head = f"head {short(pr.head_sha)}"

    if state is None:
        if pr.mergeable == _MERGEABLE_UNKNOWN:
            explain.append("no check rollup yet and mergeability is still UNKNOWN")
            return result(
                STEP_CI,
                StepStatus.UNKNOWN,
                [Evidence("check", f"no checks reported on {head}, mergeability UNKNOWN")],
                explain,
            )
        explain.append("the head commit has no check rollup")
        return result(
            STEP_CI,
            StepStatus.NOT_APPLICABLE,
            [Evidence("check", f"no checks on {head}")],
            explain,
        )

    explain.append(f"check rollup of {head} is {state}")
    if ci.ignore_checks and checks is not None and state not in _ROLLUP_PASSED:
        return _ci_from_checks(ci, checks, head, explain)

    if state in _ROLLUP_PASSED:
        return result(
            STEP_CI, StepStatus.DONE, [Evidence("check", f"checks passed on {head}")], explain
        )
    if state in _ROLLUP_PENDING:
        return result(
            STEP_CI, StepStatus.WAITING, [Evidence("check", f"checks pending on {head}")], explain
        )
    if state in _ROLLUP_FAILED:
        return result(
            STEP_CI,
            StepStatus.NEEDED,
            [Evidence("check", f"check rollup {state} on {head}")],
            explain,
        )
    return unknown(STEP_CI, f"unrecognised check rollup state {state}")


def _ci_from_checks(
    ci: CI, checks: Sequence[CheckContext], head: str, explain: list[str]
) -> StepResult:
    kept = [c for c in checks if not any_glob_match(ci.ignore_checks, c.name)]
    ignored = [c.name for c in checks if c not in kept]
    if ignored:
        explain.append(f"ignored checks: {', '.join(ignored)}")
    failed = [c for c in kept if c.outcome == OUTCOME_FAILED]
    pending = [c for c in kept if c.outcome == OUTCOME_PENDING]
    explain.append(
        f"{len(kept)} checks counted: {len(failed)} failed, {len(pending)} pending, "
        f"{len(kept) - len(failed) - len(pending)} passed"
    )
    if failed:
        return result(
            STEP_CI,
            StepStatus.NEEDED,
            [Evidence("check", f"{c.name} failed on {head}", c.name) for c in failed],
            explain,
        )
    if pending:
        return result(
            STEP_CI,
            StepStatus.WAITING,
            [Evidence("check", f"{c.name} pending on {head}", c.name) for c in pending],
            explain,
        )
    if not kept:
        return result(
            STEP_CI,
            StepStatus.NOT_APPLICABLE,
            [Evidence("check", f"no checks left on {head} after ignoring {', '.join(ignored)}")],
            explain,
        )
    return result(
        STEP_CI,
        StepStatus.DONE,
        [Evidence("check", f"checks passed on {head} (ignored: {', '.join(ignored)})")],
        explain,
    )


def _findings_step(pr: PRInfo, review: Review, norms: Norms | None) -> StepResult:
    if pr.reviewers is None:
        return unknown(STEP_FINDINGS, "reviewer data was not fetched")

    counted = _counted(pr, review)
    changes = [r for r in counted if r.latest_state == CHANGES_REQUESTED]
    threads = pr.unresolved_thread_count
    explain = [
        _settings_line(norms, "[review] count_reviews_from", review.count_reviews_from),
        f"unresolved review threads: {threads}",
        f"counted reviewers whose latest review is {CHANGES_REQUESTED}: "
        f"{', '.join(r.login for r in changes) or 'none'}",
    ]
    if threads or changes:
        evidence = []
        if threads:
            evidence.append(
                Evidence("thread", f"{threads} unresolved review thread{'s' * (threads != 1)}")
            )
        evidence += [_review_evidence(r) for r in changes]
        explain.append("an unresolved thread or a standing changes-request: needed")
        return result(STEP_FINDINGS, StepStatus.NEEDED, evidence, explain)

    if not _reviewed(list(pr.reviewers)):
        explain.append("nobody has reviewed: n/a")
        return result(
            STEP_FINDINGS,
            StepStatus.NOT_APPLICABLE,
            [Evidence("review", "no reviews")],
            explain,
        )
    explain.append("no unresolved threads and no changes-request: done")
    return result(
        STEP_FINDINGS,
        StepStatus.DONE,
        [Evidence("thread", "no unresolved threads, no changes requested")],
        explain,
    )


def _rereview_step(pr: PRInfo, review: Review, norms: Norms | None) -> StepResult:
    if pr.reviewers is None:
        return unknown(STEP_REREVIEW, "reviewer data was not fetched")
    if pr.head_sha is None:
        return unknown(STEP_REREVIEW, "head commit is unknown")

    counted = _reviewed(_counted(pr, review))
    labels = [label for label in pr.labels if label in review.rerequest_labels]
    explain = [
        _settings_line(norms, "[review] count_reviews_from", review.count_reviews_from),
        _settings_line(norms, "[review] rerequest_labels", review.rerequest_labels),
        f"head is {short(pr.head_sha)}; PR labels matching rerequest_labels: "
        f"{', '.join(labels) or 'none'}",
    ]
    if not counted:
        explain.append("no counted reviewer has reviewed: n/a")
        return result(
            STEP_REREVIEW, StepStatus.NOT_APPLICABLE, [Evidence("review", "no reviews")], explain
        )

    stale = [r for r in counted if not r.on_head]
    unrequested = [r for r in stale if r.rereview_needed]
    asked = [r for r in counted if r.rereview_requested or (r.requested and not r.on_head)]
    head_evidence = Evidence("commit", f"head is {short(pr.head_sha)}", pr.head_sha)
    for r in counted:
        explain.append(
            f"{r.login}: reviewed {short(r.reviewed_commit)}, "
            f"{'on head' if r.on_head else 'not on head'}, "
            f"{'request pending' if r.requested else 'no request pending'}"
        )

    if unrequested and not labels:
        explain.append("a counted reviewer's latest review is on an older head with no request")
        evidence = [_review_evidence(r) for r in unrequested]
        evidence += [head_evidence, Evidence("request", "no pending request")]
        return result(STEP_REREVIEW, StepStatus.NEEDED, evidence, explain)

    if asked or (unrequested and labels):
        explain.append("a re-review is requested (pending request or label): waiting")
        evidence = [_request_evidence(r) for r in asked]
        evidence += [Evidence("label", f"label {label}", label) for label in labels]
        evidence.append(head_evidence)
        return result(STEP_REREVIEW, StepStatus.WAITING, evidence, explain)

    explain.append("every counted reviewer's latest review is on the head: done")
    evidence = [_review_evidence(r) for r in counted] + [head_evidence]
    return result(STEP_REREVIEW, StepStatus.DONE, evidence, explain)


def steps_mark(results: Sequence[StepResult]) -> str:
    """One character per step: UPPER needed, lower waiting, ``✓`` done, ``·`` n/a, ``?``
    unknown, ``-`` not configured."""
    return "".join(
        _mark(letter, r.status) for letter, r in zip(STEP_LETTERS, results, strict=False)
    )


def _mark(letter: str, status: StepStatus) -> str:
    if status is StepStatus.NEEDED:
        return letter.upper()
    if status is StepStatus.WAITING:
        return letter
    if status is StepStatus.UNKNOWN:
        return "?"
    if status is StepStatus.NOT_CONFIGURED:
        return "-"
    if status is StepStatus.DONE:
        return MARK_DONE
    if status is StepStatus.NOT_APPLICABLE:
        return MARK_NA
    assert_never(status)


def step_statuses(results: Sequence[StepResult]) -> dict[str, str]:
    return {r.step: r.status.value for r in results}


def step_changes(prev: dict[str, str], curr: dict[str, str]) -> tuple[str, ...]:
    """``step: old → new`` for each step whose status moved: the fixed steps in
    :data:`STEP_NAMES` order, then any other report's steps."""
    ordered = [n for n in STEP_NAMES if n in curr] + [n for n in curr if n not in STEP_NAMES]
    return tuple(
        f"{name}: {prev[name]} → {curr[name]}"
        for name in ordered
        if name in prev and prev[name] != curr[name]
    )
