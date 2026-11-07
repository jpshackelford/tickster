"""Tests for issue history processing."""

from datetime import UTC, datetime

import pytest

from src.issue.history import (
    _build_history_string,
    _deduplicate_consecutive,
    _find_last_activity,
    _format_action,
    _parse_datetime,
    _select_linked_pr,
    process_issue_data,
)
from src.issue.models import IssueActionType, IssueState, TimelineEvent


class TestParseDatetime:
    """Tests for _parse_datetime function."""

    def test_parse_iso_with_z(self):
        """Test parsing ISO datetime with Z suffix."""
        dt = _parse_datetime("2024-01-15T10:30:00Z")
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15
        assert dt.hour == 10
        assert dt.minute == 30

    def test_parse_iso_with_offset(self):
        """Test parsing ISO datetime with timezone offset."""
        dt = _parse_datetime("2024-01-15T10:30:00+00:00")
        assert dt.year == 2024
        assert dt.tzinfo is not None


class TestFormatAction:
    """Tests for _format_action function."""

    def test_lowercase_for_reference_user(self):
        """Test that reference user actions are lowercase."""
        char = _format_action(IssueActionType.COMMENT, "testuser", "testuser")
        assert char == "c"

    def test_uppercase_for_other_user(self):
        """Test that other user actions are uppercase."""
        char = _format_action(IssueActionType.COMMENT, "otheruser", "testuser")
        assert char == "C"

    def test_case_insensitive_user_comparison(self):
        """Test that user comparison is case-insensitive."""
        char = _format_action(IssueActionType.COMMENT, "TestUser", "testuser")
        assert char == "c"

    def test_bot_comment_always_uppercase(self):
        """Test that BOT_COMMENT is always B (uppercase)."""
        # Even if actor matches reference user, BOT_COMMENT stays uppercase
        char = _format_action(IssueActionType.BOT_COMMENT, "testuser", "testuser")
        assert char == "B"


class TestDeduplicateConsecutive:
    """Tests for _deduplicate_consecutive function."""

    def test_empty_list(self):
        """Test with empty list."""
        result = _deduplicate_consecutive([])
        assert result == []

    def test_no_duplicates(self):
        """Test with no consecutive duplicates."""
        now = datetime.now(UTC)
        events = [
            TimelineEvent(IssueActionType.OPENED, "user1", now),
            TimelineEvent(IssueActionType.COMMENT, "user1", now),
            TimelineEvent(IssueActionType.LABELED, "user1", now),
        ]
        result = _deduplicate_consecutive(events)
        assert len(result) == 3

    def test_removes_consecutive_duplicates(self):
        """Test that consecutive duplicates are removed."""
        now = datetime.now(UTC)
        events = [
            TimelineEvent(IssueActionType.OPENED, "user1", now),
            TimelineEvent(IssueActionType.COMMENT, "user1", now),
            TimelineEvent(IssueActionType.COMMENT, "user2", now),  # Same action type
            TimelineEvent(IssueActionType.LABELED, "user1", now),
        ]
        result = _deduplicate_consecutive(events)
        assert len(result) == 3
        assert result[0].action == IssueActionType.OPENED
        assert result[1].action == IssueActionType.COMMENT
        assert result[2].action == IssueActionType.LABELED


class TestSelectLinkedPr:
    """Tests for _select_linked_pr function."""

    def test_empty_list(self):
        """Test with no PRs."""
        result = _select_linked_pr([])
        assert result is None

    def test_prefers_open_pr(self):
        """Test that open PRs are preferred over closed."""
        prs = [
            ("owner/repo#1", "CLOSED"),
            ("owner/repo#2", "OPEN"),
            ("owner/repo#3", "CLOSED"),
        ]
        result = _select_linked_pr(prs)
        assert result == "owner/repo#2"

    def test_prefers_merged_over_closed(self):
        """Test that merged PRs are preferred over closed."""
        prs = [
            ("owner/repo#1", "CLOSED"),
            ("owner/repo#2", "MERGED"),
        ]
        result = _select_linked_pr(prs)
        assert result == "owner/repo#2"

    def test_prefers_merged_over_open(self):
        prs = [("owner/repo#1", "OPEN"), ("owner/repo#2", "MERGED")]
        assert _select_linked_pr(prs) == "owner/repo#2"

    def test_merged_beats_an_earlier_closed_pr(self):
        prs = [("owner/repo#1", "CLOSED"), ("owner/repo#2", "MERGED"), ("owner/repo#3", "MERGED")]
        assert _select_linked_pr(prs) == "owner/repo#2"

    def test_falls_back_to_first_if_all_closed(self):
        """Test fallback to first PR if all are closed."""
        prs = [
            ("owner/repo#1", "CLOSED"),
            ("owner/repo#2", "CLOSED"),
        ]
        result = _select_linked_pr(prs)
        assert result == "owner/repo#1"


class TestFindLastActivity:
    """Tests for _find_last_activity function."""

    def test_empty_events_returns_created_at(self):
        """Test that empty events returns created_at."""
        created = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        result = _find_last_activity([], created)
        assert result == created

    def test_returns_latest_timestamp(self):
        """Test that latest timestamp is returned."""
        t1 = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
        t2 = datetime(2024, 1, 2, 12, 0, 0, tzinfo=UTC)
        t3 = datetime(2024, 1, 3, 12, 0, 0, tzinfo=UTC)
        events = [
            TimelineEvent(IssueActionType.OPENED, "user1", t1),
            TimelineEvent(IssueActionType.COMMENT, "user1", t3),  # Latest
            TimelineEvent(IssueActionType.LABELED, "user1", t2),
        ]
        result = _find_last_activity(events, t1)
        assert result == t3


class TestBuildHistoryString:
    """Tests for _build_history_string function."""

    def test_basic_history(self):
        """Test basic history string generation."""
        now = datetime.now(UTC)
        events = [
            TimelineEvent(IssueActionType.OPENED, "author", now),
            TimelineEvent(IssueActionType.COMMENT, "other", now),
            TimelineEvent(IssueActionType.CLOSED, "author", now),
        ]
        result = _build_history_string(events, "author")
        assert result == "oCx"

    def test_bot_comment_always_uppercase(self):
        """Test that bot comments are always B."""
        now = datetime.now(UTC)
        events = [
            TimelineEvent(IssueActionType.OPENED, "author", now),
            TimelineEvent(IssueActionType.BOT_COMMENT, "stale[bot]", now),
        ]
        result = _build_history_string(events, "author")
        assert result == "oB"


class TestProcessIssueData:
    """Tests for process_issue_data function."""

    @pytest.fixture
    def sample_issue_data(self):
        """Create sample issue data from GraphQL response."""
        return {
            "number": 123,
            "title": "Test issue title",
            "state": "OPEN",
            "createdAt": "2024-01-15T10:00:00Z",
            "closedAt": None,
            "author": {"login": "testauthor"},
            "repository": {"nameWithOwner": "owner/repo"},
            "labels": {
                "nodes": [
                    {"name": "bug"},
                    {"name": "enhancement"},
                ]
            },
            "timelineItems": {
                "nodes": [
                    {
                        "__typename": "IssueComment",
                        "author": {"login": "commenter"},
                        "createdAt": "2024-01-15T11:00:00Z",
                    },
                    {
                        "__typename": "LabeledEvent",
                        "actor": {"login": "labeler"},
                        "label": {"name": "bug"},
                        "createdAt": "2024-01-15T12:00:00Z",
                    },
                ]
            },
        }

    def test_processes_basic_fields(self, sample_issue_data):
        """Test that basic fields are processed correctly."""
        result = process_issue_data(sample_issue_data, "testauthor")
        assert result.repo == "owner/repo"
        assert result.number == 123
        assert result.title == "Test issue title"
        assert result.state == IssueState.OPEN
        assert result.author == "testauthor"

    def test_processes_labels_alphabetically(self, sample_issue_data):
        """Test that labels are sorted alphabetically."""
        result = process_issue_data(sample_issue_data, "testauthor")
        assert result.labels == ["bug", "enhancement"]

    def test_builds_history_string(self, sample_issue_data):
        """Test that history string is built."""
        result = process_issue_data(sample_issue_data, "testauthor")
        # Should have: o (opened), C (comment by other), L (labeled by other)
        assert "o" in result.history
        assert len(result.history) > 0

    def test_handles_closed_state(self, sample_issue_data):
        """Test handling of closed issues."""
        sample_issue_data["state"] = "CLOSED"
        sample_issue_data["closedAt"] = "2024-01-16T10:00:00Z"
        result = process_issue_data(sample_issue_data, "testauthor")
        assert result.state == IssueState.CLOSED
        assert result.closed_at is not None

    def test_handles_missing_author(self, sample_issue_data):
        """Test handling when author is None (deleted user)."""
        sample_issue_data["author"] = None
        result = process_issue_data(sample_issue_data, "testauthor")
        assert result.author == "ghost"


def closing_pr(number: int, state: str, at: str, repo: str = "owner/repo", author="dev") -> dict:
    return {
        "number": number,
        "state": state,
        "createdAt": at,
        "author": {"login": author} if author else None,
        "repository": {"nameWithOwner": repo},
    }


def cross_reference(number: int, state: str, at: str) -> dict:
    return {
        "__typename": "CrossReferencedEvent",
        "actor": {"login": "dev"},
        "createdAt": at,
        "source": {
            "__typename": "PullRequest",
            "number": number,
            "state": state,
            "repository": {"nameWithOwner": "owner/repo"},
        },
    }


def issue_with(closing: list[dict] | None, timeline: list[dict] | None = None, **extra) -> dict:
    data = {
        "number": 7,
        "title": "t",
        "state": "OPEN",
        "createdAt": "2024-01-15T10:00:00Z",
        "closedAt": None,
        "author": {"login": "dev"},
        "repository": {"nameWithOwner": "owner/repo"},
        "labels": {"nodes": []},
        "timelineItems": {"nodes": timeline or []},
    }
    if closing is not None:
        data["closedByPullRequestsReferences"] = {"nodes": closing}
    data.update(extra)
    return data


class TestClosingPrReferences:
    """A PR that says ``Fixes #N`` leaves no timeline item, only a closing reference."""

    def test_merged_closing_pr_is_linked(self):
        data = issue_with(
            [closing_pr(69, "MERGED", "2024-01-16T10:00:00Z")],
            [
                {
                    "__typename": "ClosedEvent",
                    "actor": {"login": "dev"},
                    "createdAt": "2024-01-17T10:00:00Z",
                }
            ],
            state="CLOSED",
            closedAt="2024-01-17T10:00:00Z",
        )

        info = process_issue_data(data, "dev")

        assert info.linked_pr == "owner/repo#69"
        assert info.history == "opx"
        pr_event = info.events[1]
        assert (pr_event.action, pr_event.actor, pr_event.at) == (
            "pr_linked",
            "dev",
            "2024-01-16T10:00:00Z",
        )

    def test_open_closing_pr_is_linked_without_an_x(self):
        info = process_issue_data(
            issue_with([closing_pr(85, "OPEN", "2024-01-16T10:00:00Z")]), "dev"
        )

        assert info.linked_pr == "owner/repo#85"
        assert info.history == "op"

    def test_another_users_pr_is_uppercase(self):
        data = issue_with([closing_pr(85, "OPEN", "2024-01-16T10:00:00Z", author="bob")])

        assert process_issue_data(data, "dev").history == "oP"

    def test_deleted_author_is_ghost(self):
        data = issue_with([closing_pr(85, "OPEN", "2024-01-16T10:00:00Z", author=None)])

        info = process_issue_data(data, "dev")

        assert info.events[1].actor == "ghost"

    def test_pr_found_by_cross_reference_and_closing_reference_counts_once(self):
        data = issue_with(
            [closing_pr(5, "OPEN", "2024-01-16T09:00:00Z")],
            [cross_reference(5, "OPEN", "2024-01-16T09:00:01Z")],
        )

        info = process_issue_data(data, "dev")

        assert info.history == "op"
        assert [e.action for e in info.events].count("pr_linked") == 1

    def test_merged_closing_pr_beats_an_earlier_closed_pr(self):
        data = issue_with(
            [closing_pr(9, "MERGED", "2024-01-18T10:00:00Z")],
            [cross_reference(3, "CLOSED", "2024-01-16T10:00:00Z")],
        )

        assert process_issue_data(data, "dev").linked_pr == "owner/repo#9"

    def test_a_closing_pr_from_another_repo_keeps_its_repo(self):
        data = issue_with([closing_pr(2, "MERGED", "2024-01-16T10:00:00Z", repo="other/fork")])

        assert process_issue_data(data, "dev").linked_pr == "other/fork#2"

    def test_no_closing_references_changes_nothing(self):
        for data in (
            issue_with(None),
            issue_with([]),
            issue_with(None, closedByPullRequestsReferences=None),
        ):
            info = process_issue_data(data, "dev")
            assert info.linked_pr is None
            assert info.history == "o"
