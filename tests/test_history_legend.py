"""The History legend: one source for list legends and `show`."""

import pytest

from src.history_legend import (
    AI_CASE_RULE,
    ISSUE_CHARS,
    PR_CHARS,
    case_rule,
    chars_text,
    history_legend,
)
from src.issue.history import AI_CHARS as ISSUE_AI_CHARS
from src.issue.models import IssueActionType
from src.pr.history import AI_CHARS as PR_AI_CHARS
from src.pr.models import ActionType


def named(legend: str) -> list[str]:
    """The characters a legend lists, in order."""
    _, entries = legend.split(". ", 1)
    return [entry.split(" ", 1)[0] for entry in entries.split(", ")]


class TestHistoryLegend:
    def test_names_only_the_characters_present(self):
        assert named(history_legend("pr", ["sVn"]) or "") == ["s", "v", "n"]

    def test_a_pr_history(self):
        assert named(history_legend("pr", ["oRfAM"]) or "") == ["o", "r", "a", "f", "m"]

    def test_upper_and_lower_case_give_the_same_entries(self):
        assert history_legend("pr", ["sVn"]) == history_legend("pr", ["svn"])
        assert history_legend("pr", ["V"]) == history_legend("pr", ["v"])

    def test_entries_are_in_table_order_not_history_order(self):
        assert named(history_legend("pr", ["mkc"]) or "") == ["c", "m", "k"]

    def test_characters_over_many_histories_are_pooled(self):
        assert named(history_legend("pr", ["o", "", "m", "o"]) or "") == ["o", "m"]

    def test_an_issue_history(self):
        legend = history_legend("issue", ["oCLBx"])
        assert legend is not None
        assert named(legend) == ["o", "c", "B", "l", "x"]
        assert "B bot comment" in legend

    def test_the_issue_bot_letter_is_matched_as_written(self):
        assert history_legend("issue", ["b"]) is None

    @pytest.mark.parametrize("histories", [[], [""], ["…"], ["> []"], ["…", ""]])
    def test_no_known_character_gives_no_legend(self, histories):
        assert history_legend("pr", histories) is None
        assert history_legend("issue", histories) is None

    def test_a_truncation_marker_is_ignored(self):
        assert named(history_legend("pr", ["oc…"]) or "") == ["o", "c"]

    def test_the_case_rule_is_in_the_text(self):
        legend = history_legend("pr", ["oC"])
        assert legend == f"History: {case_rule()}. o opened, c comment"

    def test_the_case_rule_names_the_reviewer(self):
        legend = history_legend("pr", ["oC"], you="octocat")
        assert legend is not None
        assert legend.startswith("History: lowercase = octocat, UPPERCASE = others. ")

    def test_the_ai_rule_appears_only_with_an_ai_character(self):
        assert AI_CASE_RULE in (history_legend("pr", ["sc"]) or "")
        assert AI_CASE_RULE not in (history_legend("pr", ["oc"]) or "")

    def test_the_line_is_one_line(self):
        every = "".join(c for c, _ in PR_CHARS)
        assert "\n" not in (history_legend("pr", [every]) or "\n")


class TestCharsText:
    @pytest.mark.parametrize("kind,table", [("pr", PR_CHARS), ("issue", ISSUE_CHARS)])
    def test_names_every_character_in_table_order(self, kind, table):
        text = chars_text(kind)
        assert text == ", ".join(f"{c} {m}" for c, m in table)

    def test_no_character_is_listed_twice(self):
        for table in (PR_CHARS, ISSUE_CHARS):
            chars = [c for c, _ in table]
            assert len(chars) == len(set(chars))


class TestEveryHistoryCharacterHasAnEntry:
    def test_every_pr_action_letter(self):
        letters = {a.value for a in ActionType} | set(PR_AI_CHARS.values())
        assert letters <= {c for c, _ in PR_CHARS}

    def test_every_issue_action_letter(self):
        letters = {a.value for a in IssueActionType} | set(ISSUE_AI_CHARS.values())
        assert letters <= {c for c, _ in ISSUE_CHARS}

    def test_every_pr_character_produces_a_legend_entry(self):
        for char, meaning in PR_CHARS:
            assert f"{char} {meaning}" in (history_legend("pr", [char.upper()]) or "")
