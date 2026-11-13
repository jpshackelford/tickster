"""Narrow-terminal rendering of the list tables (#80)."""

import io
from datetime import UTC, datetime, timedelta

import pytest
from rich import box
from rich.cells import cell_len
from rich.console import Console
from rich.table import Table
from rich.text import Text

from src.__main__ import main
from src.connection_paging import TRUNCATION_MARKER
from src.history_legend import chars_text, history_legend
from src.issue.cli import list_cmd as issue_cmd
from src.issue.models import IssueInfo, IssueState
from src.list_table import (
    CROP_LEGEND,
    HISTORY_CROP_MARK,
    HISTORY_MIN_WIDTH,
    add_shrinkable_column,
    crop_history,
    print_fitted_table,
    print_note,
)
from src.pr.cli import list_cmd as pr_cmd
from src.pr.models import CIStatus, PRInfo, PRState
from src.pr.reviewers import REVIEWER_LEGEND
from src.pr.step_types import StepResult, StepStatus
from src.pr.steps import MARK_DONE, MARK_NA, STEP_LETTERS, STEPS_LEGEND, steps_mark
from src.review.cli import list_cmd as review_cmd
from src.review.models import ReviewInfo, ReviewStatus
from src.show.render import ISSUE_LEGEND, PR_LEGEND

NOW = datetime.now(UTC) - timedelta(hours=23, minutes=30)
SHORT = "oCc"
LONG = "o" + "cC" * 20
CAPPED = "o" + "cC" * 24 + TRUNCATION_MARKER

STEP_STATUSES = (
    StepStatus.NEEDED,
    StepStatus.WAITING,
    StepStatus.DONE,
    StepStatus.DONE,
    StepStatus.NEEDED,
    StepStatus.DONE,
    StepStatus.DONE,
)
STEP_RESULTS = tuple(
    StepResult(step=s, status=st) for s, st in zip(STEP_LETTERS, STEP_STATUSES, strict=True)
)
FULL_STEPS = steps_mark(STEP_RESULTS)

HISTORIES = {"short": SHORT, "long": LONG, "capped": CAPPED}


def make_console(width: int) -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, width=width, force_terminal=True, color_system=None), buf


def make_pipe_console(width: int) -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, width=width, color_system=None), buf


def lines_for(out: str, number: int) -> str:
    (line,) = [ln for ln in out.splitlines() if f"#{number}" in ln]
    return line


def history_cell(line: str) -> str:
    return next(t for t in line.split() if t.startswith("oc"))


def make_pr(number: int, history: str) -> PRInfo:
    return PRInfo(
        repo="OpenHands/OpenHands",
        number=number,
        title="fix: a title long enough to need shrinking",
        state=PRState.OPEN,
        ci_status=CIStatus.GREEN,
        history=history,
        created_at=NOW,
        closed_at=None,
        last_activity=NOW,
        author="octocat",
    )


def print_pr(console: Console, *, steps: bool = True, title: bool = True) -> None:
    prs = [
        make_pr(number, history)
        for number, history in zip((1, 2, 3), HISTORIES.values(), strict=True)
    ]
    pr_cmd.console = console
    pr_cmd._print_pr_table(
        prs,
        show_title=title,
        steps={f"{p.repo}#{p.number}": STEP_RESULTS for p in prs} if steps else None,
    )


def print_issue(console: Console, *, title: bool = True) -> None:
    issues = [
        IssueInfo(
            repo="OpenHands/OpenHands",
            number=number,
            title="a title long enough to need shrinking",
            state=IssueState.OPEN,
            history=history,
            linked_pr=None,
            labels=["bug", "priority:medium", "enhancement"],
            created_at=NOW,
            closed_at=None,
            last_activity=NOW,
            author="octocat",
        )
        for number, history in zip((1, 2, 3), HISTORIES.values(), strict=True)
    ]
    issue_cmd.console = console
    issue_cmd._print_issue_table(issues, show_title=title)


def print_review(console: Console, *, title: bool = True) -> None:
    reviews = [
        ReviewInfo(
            repo="OpenHands/OpenHands",
            number=number,
            title="fix: a title long enough to need shrinking",
            history=history,
            status=ReviewStatus.REVIEW,
            wait_seconds=60.0,
            ci_status=CIStatus.GREEN,
            unresolved_thread_count=0,
            author="octocat",
            last_activity=NOW,
        )
        for number, history in zip((1, 2, 3), HISTORIES.values(), strict=True)
    ]
    review_cmd.console = console
    review_cmd._print_review_table(reviews, reviewer="me", show_title=title)


PRINTERS = {"pr": print_pr, "issue": print_issue, "review": print_review}


@pytest.fixture(autouse=True)
def restore_consoles():
    saved = pr_cmd.console, issue_cmd.console, review_cmd.console
    yield
    pr_cmd.console, issue_cmd.console, review_cmd.console = saved


class TestCropHistory:
    def test_shorter_than_width_is_unchanged(self):
        text = Text("oCc")
        assert crop_history(text, 10) is False
        assert text.plain == "oCc"

    def test_exactly_width_is_unchanged(self):
        text = Text("oCcCc")
        assert crop_history(text, 5) is False
        assert text.plain == "oCcCc"

    def test_longer_keeps_head_and_ends_in_mark(self):
        text = Text("oCcCcCcCc")
        assert crop_history(text, 5) is True
        assert text.plain == "oCcC" + HISTORY_CROP_MARK

    def test_empty_is_unchanged(self):
        text = Text("")
        assert crop_history(text, 0) is False
        assert text.plain == ""

    def test_width_one_is_only_the_mark(self):
        text = Text("oCc")
        assert crop_history(text, 1) is True
        assert text.plain == HISTORY_CROP_MARK

    def test_width_zero_is_only_the_mark(self):
        text = Text("oCc")
        assert crop_history(text, 0) is True
        assert text.plain == HISTORY_CROP_MARK

    def test_cap_marker_input_is_cropped_to_the_crop_mark(self):
        text = Text("oCcCc" + TRUNCATION_MARKER)
        crop_history(text, 4)
        assert text.plain == "oCc" + HISTORY_CROP_MARK
        assert TRUNCATION_MARKER not in text.plain

    def test_cap_marker_input_that_fits_keeps_the_cap_marker(self):
        text = Text("oCc" + TRUNCATION_MARKER)
        assert crop_history(text, 4) is False
        assert text.plain.endswith(TRUNCATION_MARKER)

    def test_styled_tail_is_dropped_with_the_crop(self):
        text = Text.from_markup("oC[bold]\\[cC][/]cCcC")
        crop_history(text, 4)
        assert text.plain == "oC[" + HISTORY_CROP_MARK


@pytest.mark.parametrize("kind", PRINTERS)
class TestListTablesAtEightyColumns:
    def render(self, kind: str, width: int) -> tuple[str, Console]:
        console, buf = make_console(width)
        PRINTERS[kind](console)
        return buf.getvalue(), console

    def test_numbers_are_complete_for_every_row(self, kind):
        out, _ = self.render(kind, 80)
        for number in (1, 2, 3):
            assert f"#{number}" in lines_for(out, number)

    def test_short_history_is_unchanged(self, kind):
        out, _ = self.render(kind, 80)
        assert SHORT in lines_for(out, 1).split()

    def test_width_crop_ends_in_crop_mark_and_never_in_cap_marker(self, kind):
        out, _ = self.render(kind, 80)
        for number in (2, 3):
            cell = history_cell(lines_for(out, number))
            assert cell.endswith(HISTORY_CROP_MARK)
            assert TRUNCATION_MARKER not in cell

    def test_legend_is_printed_once_and_fits_the_table_width(self, kind):
        out, _ = self.render(kind, 80)
        assert out.count("History cropped to fit the terminal") == 1
        assert "'>' marks the cut" in out

    def test_table_without_title_fits_the_terminal(self, kind):
        console, buf = make_console(80)
        PRINTERS[kind](console, title=False)
        assert max(len(ln) for ln in buf.getvalue().splitlines() if "#" in ln) <= 80

    def test_console_width_is_restored(self, kind):
        _, console = self.render(kind, 80)
        assert console.width == 80


@pytest.mark.parametrize("kind", PRINTERS)
class TestListTablesAtTwoHundredColumns:
    def render(self, kind: str) -> str:
        console, buf = make_console(200)
        PRINTERS[kind](console)
        return buf.getvalue()

    def test_capped_history_ends_in_cap_marker_without_crop_mark(self, kind):
        line = lines_for(self.render(kind), 3)
        assert CAPPED in line
        assert HISTORY_CROP_MARK not in line

    def test_long_history_is_whole(self, kind):
        assert LONG in lines_for(self.render(kind), 2)

    def test_no_legend(self, kind):
        assert "History cropped" not in self.render(kind)


class TestSteps:
    def test_full_steps_cell_survives_eighty_columns(self):
        console, buf = make_console(80)
        print_pr(console)
        assert len(FULL_STEPS) == len(STEP_LETTERS)
        for number in (1, 2, 3):
            assert FULL_STEPS in lines_for(buf.getvalue(), number).split()

    def test_other_short_columns_survive_with_a_long_history(self):
        console, buf = make_console(80)
        print_pr(console)
        line = lines_for(buf.getvalue(), 2)
        for cell in ("green", "ready", "23h", "ago"):
            assert cell in line

    def test_steps_without_the_flag_adds_no_column(self):
        console, buf = make_console(200)
        print_pr(console, steps=False)
        assert "Steps" not in buf.getvalue()


class TestStepsCellWidth:
    @pytest.mark.parametrize("width", [40, 200])
    @pytest.mark.parametrize("status", [StepStatus.DONE, StepStatus.NOT_APPLICABLE])
    def test_cell_stays_seven_cells_wide(self, width, status):
        results = tuple(StepResult(step=s, status=status) for s in STEP_LETTERS)
        mark = steps_mark(results)
        console, buf = make_pipe_console(width)
        pr_cmd.console = console
        pr_cmd._print_pr_table(
            [make_pr(1, SHORT)], show_title=False, steps={"OpenHands/OpenHands#1": results}
        )
        (row,) = [
            ln for ln in buf.getvalue().splitlines() if mark in ln and not ln.startswith("Steps:")
        ]
        (cell,) = [c for c in row.split() if mark in c]
        assert cell == mark
        assert cell_len(cell) == len(STEP_LETTERS)


class TestPrintFittedTable:
    @staticmethod
    def table() -> Table:
        table = Table(box=box.SIMPLE)
        add_shrinkable_column(table, "Repo")
        table.add_column("History", no_wrap=True)
        table.add_column("PR", no_wrap=True)
        return table

    def test_floors_that_do_not_fit_print_at_the_needed_width(self):
        console, buf = make_console(20)
        rows = [["owner/repository-name", LONG, "#12345"]]
        assert print_fitted_table(console, self.table(), rows, history_col=1) is True
        line = lines_for(buf.getvalue(), 12345)
        assert "#12345" in line
        assert HISTORY_CROP_MARK in line
        assert len(line.split()[1]) == HISTORY_MIN_WIDTH
        assert console.width == 20

    def test_history_that_fits_is_not_cropped_and_prints_no_legend(self):
        console, buf = make_console(80)
        rows = [["owner/repo", SHORT, "#1"]]
        assert print_fitted_table(console, self.table(), rows, history_col=1) is False
        assert SHORT in buf.getvalue()
        assert CROP_LEGEND not in buf.getvalue()

    def test_repo_gives_up_width_before_history_is_cropped(self):
        console, buf = make_console(40)
        history = "o" + "cC" * 8
        rows = [["owner/a-long-repository-name", history, "#1"]]
        assert print_fitted_table(console, self.table(), rows, history_col=1) is False
        line = lines_for(buf.getvalue(), 1)
        assert history in line
        assert "…" in line.split()[0]

    def test_history_markup_is_kept(self):
        console, buf = make_console(80)
        rows = [["owner/repo", "oC\\[c]", "#1"]]
        print_fitted_table(console, self.table(), rows, history_col=1)
        assert "oC[c]" in buf.getvalue()


@pytest.mark.parametrize("kind", PRINTERS)
class TestListTablesWhenPiped:
    def render(self, kind: str, width: int = 80) -> tuple[str, Console]:
        console, buf = make_pipe_console(width)
        assert not console.is_terminal
        PRINTERS[kind](console)
        return buf.getvalue(), console

    def test_history_is_whole_and_never_cropped(self, kind):
        out, _ = self.render(kind)
        assert LONG in lines_for(out, 2)
        assert CAPPED in lines_for(out, 3)
        assert HISTORY_CROP_MARK not in out

    def test_no_legend(self, kind):
        out, _ = self.render(kind)
        assert "History cropped" not in out

    def test_repo_title_and_labels_are_never_ellipsized(self, kind):
        out, _ = self.render(kind)
        assert "…" not in out.replace(CAPPED, "")
        assert "OpenHands/OpenHands" in lines_for(out, 1)
        assert "a title long enough to need shrinking" in " ".join(lines_for(out, 1).split())

    def test_cells_stay_on_one_line_per_row(self, kind):
        out, _ = self.render(kind)
        assert len([ln for ln in out.splitlines() if "#" in ln]) == 3

    def test_columns_variable_does_not_change_the_output(self, kind, monkeypatch):
        monkeypatch.setenv("COLUMNS", "40")
        narrow, _ = self.render(kind, 40)
        wide, _ = self.render(kind, 200)
        assert LONG in lines_for(narrow, 2)
        assert LONG in lines_for(wide, 2)

    def test_console_width_is_restored(self, kind):
        _, console = self.render(kind)
        assert console.width == 80


class TestPrintFittedTableWhenPiped:
    @staticmethod
    def table() -> Table:
        table = Table(box=box.SIMPLE)
        add_shrinkable_column(table, "Repo")
        add_shrinkable_column(table, "Labels", max_width=10)
        table.add_column("History", no_wrap=True)
        table.add_column("PR", no_wrap=True)
        return table

    ROWS = [["owner/a-long-repository-name", "bug, priority:medium", LONG, "#1"]]

    def test_returns_false_and_prints_whole_cells_without_legend(self):
        console, buf = make_pipe_console(80)
        assert print_fitted_table(console, self.table(), self.ROWS, history_col=2) is False
        out = buf.getvalue()
        assert LONG in out
        assert HISTORY_CROP_MARK not in out
        assert CROP_LEGEND not in out
        assert "…" not in out
        assert "owner/a-long-repository-name" in out
        assert "bug, priority:medium" in out

    def test_a_line_may_be_longer_than_the_console(self):
        console, buf = make_pipe_console(40)
        print_fitted_table(console, self.table(), self.ROWS, history_col=2)
        assert max(len(ln) for ln in buf.getvalue().splitlines()) > 40
        assert console.width == 40

    def test_column_max_width_is_restored(self):
        console, _ = make_pipe_console(80)
        table = self.table()
        print_fitted_table(console, table, self.ROWS, history_col=2)
        assert [c.max_width for c in table.columns] == [None, 10, None, None]

    def test_wide_console_keeps_its_width(self):
        console, buf = make_pipe_console(200)
        print_fitted_table(console, self.table(), self.ROWS, history_col=2)
        assert console.width == 200
        assert "…" not in buf.getvalue()

    def test_history_markup_is_kept(self):
        console, buf = make_pipe_console(80)
        rows = [["owner/repo", "bug", "oC\\[c]", "#1"]]
        print_fitted_table(console, self.table(), rows, history_col=2)
        assert "oC[c]" in buf.getvalue()


NOTE = "a note that is much longer than the forty column console it is printed to " * 2


class TestPrintNote:
    def test_piped_note_is_one_line_at_any_width(self):
        outs = []
        for width in (20, 200):
            console, buf = make_pipe_console(width)
            print_note(console, f"[dim]{NOTE}[/]")
            outs.append(buf.getvalue())
        assert outs[0] == outs[1] == f"{NOTE}\n"

    def test_terminal_note_wraps(self):
        console, buf = make_console(40)
        print_note(console, NOTE)
        assert len(buf.getvalue().splitlines()) > 1
        assert max(len(line) for line in buf.getvalue().splitlines()) <= 40

    def test_markup_still_renders_when_piped(self):
        console, buf = make_pipe_console(20)
        print_note(console, "[bold]one[/] \\[two]")
        assert buf.getvalue() == "one [two]\n"


class TestLegendsWhenPiped:
    @pytest.mark.parametrize("width", [40, 200])
    def test_pr_legends_are_one_line_each(self, width):
        console, buf = make_pipe_console(width)
        pr_cmd.console = console
        pr_cmd._print_pr_table(
            [make_pr(1, SHORT)],
            show_title=False,
            reviewers="counts",
            steps={"OpenHands/OpenHands#1": STEP_RESULTS},
        )
        lines = buf.getvalue().splitlines()
        assert lines.count(REVIEWER_LEGEND) == 1
        assert lines.count(STEPS_LEGEND) == 1

    @pytest.mark.parametrize("kind", PRINTERS)
    def test_output_is_the_same_at_every_width(self, kind):
        outs = []
        for width in (40, 200):
            console, buf = make_pipe_console(width)
            PRINTERS[kind](console)
            outs.append(buf.getvalue())
        assert outs[0] == outs[1]

    @pytest.mark.parametrize("width", [40, 200])
    def test_empty_pr_and_issue_lists_are_one_line(self, width):
        console, buf = make_pipe_console(width)
        pr_cmd.console = issue_cmd.console = console
        pr_cmd._print_pr_table([])
        issue_cmd._print_issue_table([])
        assert buf.getvalue().splitlines() == ["No PRs found.", "No issues found."]

    def test_pr_legends_still_wrap_on_a_terminal(self):
        console, buf = make_console(40)
        pr_cmd.console = console
        pr_cmd._print_pr_table(
            [make_pr(1, SHORT)], show_title=False, steps={"OpenHands/OpenHands#1": STEP_RESULTS}
        )
        assert STEPS_LEGEND not in buf.getvalue().splitlines()
        assert "Steps:" in buf.getvalue()


class TestHistoryLegendInLists:
    @pytest.mark.parametrize("kind", PRINTERS)
    @pytest.mark.parametrize("width", [40, 200])
    def test_piped_legend_is_one_line_naming_the_characters_shown(self, kind, width):
        console, buf = make_pipe_console(width)
        PRINTERS[kind](console)
        lines = [ln for ln in buf.getvalue().splitlines() if ln.startswith("History:")]
        expected = "History: lowercase = {}, UPPERCASE = others. o opened, c comment"
        assert lines == [expected.format("me" if kind == "review" else "you")]

    @pytest.mark.parametrize("kind", PRINTERS)
    def test_legend_wraps_on_a_terminal(self, kind):
        console, buf = make_console(40)
        PRINTERS[kind](console)
        out = buf.getvalue()
        assert "History: lowercase" in out
        assert not any(ln.startswith("History:") and "c comment" in ln for ln in out.splitlines())

    def test_issue_legend_comes_from_the_shared_text(self):
        console, buf = make_pipe_console(200)
        print_issue(console)
        assert history_legend("issue", [SHORT]) in buf.getvalue().splitlines()

    @pytest.mark.parametrize("kind", PRINTERS)
    def test_no_legend_without_a_known_character(self, kind, monkeypatch):
        monkeypatch.setattr(
            "tests.test_list_table.HISTORIES", {"a": "…", "b": ">", "c": ""}, raising=True
        )
        console, buf = make_pipe_console(200)
        PRINTERS[kind](console)
        assert "History:" not in buf.getvalue()

    def test_the_legend_is_a_pr_list_note_above_reviewers_and_steps(self):
        console, buf = make_pipe_console(200)
        pr_cmd.console = console
        prs = [make_pr(1, SHORT)]
        pr_cmd._print_pr_table(
            prs, reviewers="counts", steps={"OpenHands/OpenHands#1": STEP_RESULTS}
        )
        lines = buf.getvalue().splitlines()
        history, reviewers, steps = (
            next(i for i, ln in enumerate(lines) if ln.startswith(prefix))
            for prefix in ("History:", "Reviewers:", "Steps:")
        )
        assert history < reviewers < steps

    def test_a_pr_row_with_an_ai_character_names_it_case_insensitively(self):
        console, buf = make_pipe_console(200)
        pr_cmd.console = console
        pr_cmd._print_pr_table([make_pr(1, "sVn")])
        (line,) = [ln for ln in buf.getvalue().splitlines() if ln.startswith("History:")]
        assert line.endswith("s AI opened, v AI approval, n AI comment")


class TestStepsLegendGlyphs:
    def test_names_both_glyphs(self):
        assert "✓ done, · n/a," in STEPS_LEGEND

    def test_no_longer_uses_a_dot_for_either(self):
        assert ". done or n/a" not in STEPS_LEGEND
        assert "dots" not in STEPS_LEGEND

    def test_says_all_ticks_means_nothing_pending(self):
        assert f"Only ✓ and · ({'✓' * 7}) = every step done or n/a: nothing pending." in (
            STEPS_LEGEND
        )

    def test_tick_count_follows_the_step_letters(self):
        assert "✓" * len(STEP_LETTERS) in STEPS_LEGEND


class TestShowLegendsUseTheTables:
    def test_pr_legend_names_every_character(self):
        assert chars_text("pr") in PR_LEGEND

    def test_issue_legend_names_every_character(self):
        assert chars_text("issue") in ISSUE_LEGEND


class TestStepsHelpGlyphs:
    @staticmethod
    def _steps_help(capsys) -> str:
        with pytest.raises(SystemExit) as exc:
            main(["pr", "list", "--help"])
        assert exc.value.code == 0
        return " ".join(capsys.readouterr().out.split())

    def test_names_the_same_glyphs_as_the_table(self, capsys):
        assert f"{MARK_DONE} done, {MARK_NA} n/a," in self._steps_help(capsys)

    def test_no_longer_uses_a_dot_for_done(self, capsys):
        assert ". done or n/a" not in self._steps_help(capsys)
