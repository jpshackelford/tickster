"""Width fitting shared by the `pr list`, `issue list`, `review` and snapshot tables.

Rich can only narrow wrap-able columns. With every column `no_wrap`, an over-wide
table shrinks all columns in proportion, which erases the short ones (PR number,
Steps) and ends the History cell in Rich's own `…` -- the same character that
marks the 500-event cap. Here Repo, Title and Labels give up width first, then
History is cropped by tickster itself and ends in `>`.
"""

from collections.abc import Sequence

from rich.console import Console
from rich.table import Table
from rich.text import Text

HISTORY_CROP_MARK = ">"
HISTORY_MIN_WIDTH = 8
SHRINK_FLOOR = 8

CROP_LEGEND = (
    f"History cropped to fit the terminal; '{HISTORY_CROP_MARK}' marks the cut. "
    "A trailing '…' still means the 500-event cap."
)


def add_shrinkable_column(table: Table, header: str, **kwargs) -> None:
    """Add a column Rich may ellipsize before it shrinks any other column."""
    table.add_column(header, no_wrap=False, overflow="ellipsis", **kwargs)


def crop_history(history: Text, width: int) -> bool:
    """Crop `history` in place to `width`, keeping the head and ending in `>`.

    Returns whether it was cropped.
    """
    if history.cell_len <= width:
        return False
    history.truncate(max(width - 1, 0), overflow="crop")
    history.append(HISTORY_CROP_MARK)
    return True


def print_fitted_table(
    console: Console,
    table: Table,
    rows: Sequence[Sequence[str]],
    *,
    history_col: int,
    floor: int = SHRINK_FLOOR,
) -> bool:
    """Add `rows` to `table`, crop History to the room left, and print it.

    Cells are Rich markup. Columns built with `add_shrinkable_column` never wrap:
    their cells ellipsize on one line. If even the floors do not fit, the table
    prints at the width it needs rather than letting Rich shrink every column.
    `floor` is the narrowest a shrinkable column gets before History is cropped.
    Returns whether a History cell was cropped; the crop legend is printed too.
    """
    shrinkable = {i for i, c in enumerate(table.columns) if c.width is None and not c.no_wrap}
    histories = [Text.from_markup(row[history_col]) for row in rows]
    for row, history in zip(rows, histories, strict=True):
        cells = [_cell(i, cell, shrinkable) for i, cell in enumerate(row)]
        cells[history_col] = history
        table.add_row(*cells)

    needed = _floor_width(console, table, shrinkable, history_col, floor)
    budget = max(console.width - needed + HISTORY_MIN_WIDTH, HISTORY_MIN_WIDTH)
    cropped = [crop_history(h, budget) for h in histories]

    saved = console.width
    console.width = max(saved, needed)
    try:
        console.print(table)
        if any(cropped):
            console.print(f"[dim]{CROP_LEGEND}[/]")
    finally:
        console.width = saved
    return any(cropped)


def _cell(index: int, cell: str, shrinkable: set[int]) -> Text | str:
    if index in shrinkable:
        text = Text.from_markup(cell, overflow="ellipsis")
        text.no_wrap = True
        return text
    return cell


def _floor_width(
    console: Console, table: Table, shrinkable: set[int], history_col: int, floor: int
) -> int:
    """Width the table needs with History at its minimum and shrinkable columns at their floor."""
    columns = table.columns
    saved = [(c.max_width, c.width) for c in columns]
    try:
        for i in shrinkable:
            columns[i].max_width = min(columns[i].max_width or floor, floor)
        columns[history_col].width = HISTORY_MIN_WIDTH
        return console.measure(table, options=console.options.update_width(10_000)).maximum
    finally:
        for column, (max_width, width) in zip(columns, saved, strict=True):
            column.max_width, column.width = max_width, width
