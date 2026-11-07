"""The shape of a step's verdict: its status, the evidence for it and the lines that explain it."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

SHORT_SHA = 7


class StepStatus(StrEnum):
    NEEDED = "needed"  # the author's side has to act
    WAITING = "waiting"  # someone else has to act: a requested reviewer, or running CI
    DONE = "done"
    NOT_APPLICABLE = "n/a"
    NOT_CONFIGURED = "not configured"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Evidence:
    """One fact a status rests on; ``ref`` is the login, commit or check it is about."""

    kind: str
    text: str
    ref: str | None = None

    def to_dict(self) -> dict:
        data = {"kind": self.kind, "text": self.text}
        if self.ref is not None:
            data["ref"] = self.ref
        return data


@dataclass(frozen=True)
class StepResult:
    step: str
    status: StepStatus
    evidence: tuple[Evidence, ...] = ()
    explain: tuple[str, ...] = ()

    def to_dict(self, *, explain: bool = False) -> dict:
        data = {
            "step": self.step,
            "status": self.status.value,
            "evidence": [e.to_dict() for e in self.evidence],
        }
        if explain:
            data["explain"] = list(self.explain)
        return data

    def line(self) -> str:
        text = ", ".join(e.text for e in self.evidence)
        return f"{self.step}: {self.status.value}" + (f" — {text}" if text else "")


def short(sha: str | None) -> str:
    return sha[:SHORT_SHA] if sha else "?"


def result(step: str, status: StepStatus, evidence: list[Evidence], explain: list[str]):
    return StepResult(step, status, tuple(evidence), tuple(explain))


def unknown(step: str, why: str) -> StepResult:
    return StepResult(step, StepStatus.UNKNOWN, (Evidence("pr", why),), (why,))
