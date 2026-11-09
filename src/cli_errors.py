"""Error lines for the list and repo commands.

They go to stderr, so a job that reads JSON from stdout never finds an `Error:` line in it.
"""

from rich.console import Console

err_console = Console(stderr=True)

VERBOSE_HINT = "Run with --verbose for full traceback"


def print_error(message: str, *, hint: str | None = None) -> None:
    """Print `Error: <message>` and an optional dim hint line to stderr, unwrapped."""
    err_console.print(f"[red]Error:[/] {message}", soft_wrap=True)
    if hint:
        err_console.print(f"[dim]{hint}[/]", soft_wrap=True)
