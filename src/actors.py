"""Who acted: the actor classes shared by history strings, snapshots and reviewer state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from src.issue.config import is_bot_user
from src.norms.model import Norms


class ActorClass(StrEnum):
    ME = "me"  # the reference user
    HUMAN = "human"
    BOT = "bot"  # non-AI automation: dependabot, github-actions, stale
    AGENT = "agent"  # an AI actor recognised by login ([actors] agent_logins)
    ME_AGENT = "me_agent"  # the reference user's login, with an AI disclosure in the text

    @property
    def is_ai(self) -> bool:
        return self in (ActorClass.AGENT, ActorClass.ME_AGENT)


# The ``[review] count_reviews_from`` / ``[reports.*.impact_line] from`` group of each class.
ACTOR_GROUP = {
    ActorClass.ME: "humans",
    ActorClass.HUMAN: "humans",
    ActorClass.AGENT: "agents",
    ActorClass.ME_AGENT: "agents",
    ActorClass.BOT: "bots",
}


def classify_actor(
    login: str,
    reference_user: str,
    norms: Norms | None,
    body: str | None = None,
) -> ActorClass:
    """Classify ``login`` from the viewpoint of ``reference_user``.

    Logins and the disclosure pattern come only from ``norms``; with none, no AI
    actor is recognised and ``[bot]`` accounts are still bots.
    """
    if login.lower() == reference_user.lower():
        if norms is not None and (norms.is_agent(login) or _discloses_ai(norms, body)):
            return ActorClass.ME_AGENT
        return ActorClass.ME
    if norms is not None and norms.is_agent(login):
        return ActorClass.AGENT
    if is_bot_user(login, norms):
        return ActorClass.BOT
    return ActorClass.HUMAN


def _discloses_ai(norms: Norms, body: str | None) -> bool:
    pattern = norms.actors.agent_disclosure
    return pattern is not None and body is not None and pattern.search(body) is not None


@dataclass(frozen=True)
class HistoryEvent:
    """One character of a history string, with who acted. ``at`` is ISO-8601 UTC."""

    char: str
    action: str
    actor: str
    actor_class: ActorClass
    at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "char": self.char,
            "action": self.action,
            "actor": self.actor,
            "actor_class": self.actor_class.value,
            "at": self.at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> HistoryEvent:
        return cls(
            char=data["char"],
            action=data["action"],
            actor=data["actor"],
            actor_class=ActorClass(data["actor_class"]),
            at=data["at"],
        )


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
