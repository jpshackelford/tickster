"""tickster (tkt) command-line entry point.

Token-efficient tools for agents to view and manage GitHub issues, pull
requests, and project boards.
"""

from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv
from rich.console import Console

# Load environment variables (e.g. GITHUB_TOKEN/GIST_TOKEN from a local .env)
load_dotenv()

console = Console()


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the CLI.

    Args:
        argv: Command line arguments (defaults to sys.argv[1:])

    Returns:
        Exit code
    """
    from src._version import get_full_version_string

    # Handle --version before argparse (argparse requires subcommand otherwise)
    args_to_check = argv if argv is not None else sys.argv[1:]
    if "--version" in args_to_check or "-V" in args_to_check:
        print(get_full_version_string())
        return 0

    parser = argparse.ArgumentParser(
        prog="tkt",
        description=(
            "tickster (tkt) - token-efficient tools for viewing and managing "
            "GitHub issues, pull requests, and project boards"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  tkt issue list                        List open issues
  tkt pr list                           List open pull requests
  tkt review list                       List PRs awaiting review
  tkt board status                      Show project board status
  tkt repo add owner/name               Track a repo on a board
""",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    board_parser = subparsers.add_parser(
        "board",
        help="Manage GitHub Project board for tracking development workflow",
    )
    board_subparsers = board_parser.add_subparsers(dest="board_command", required=True)

    # board list
    board_subparsers.add_parser(
        "list",
        help="List all configured boards",
    )

    # board init
    board_init_parser = board_subparsers.add_parser(
        "init",
        help="Initialize or configure a GitHub Project board",
    )
    board_init_group = board_init_parser.add_mutually_exclusive_group()
    board_init_group.add_argument(
        "--create",
        metavar="NAME",
        help="Create a new project with this name",
    )
    board_init_group.add_argument(
        "--project-id",
        help="Configure existing project by GraphQL ID (PVT_xxx)",
    )
    board_init_group.add_argument(
        "--project-number",
        type=int,
        help="Configure existing user project by number",
    )
    board_init_parser.add_argument(
        "--board",
        metavar="NAME",
        help="Name for this board in config (default: slugified project name)",
    )
    board_init_parser.add_argument(
        "--scope",
        choices=["user", "project"],
        help="Board scope: 'user' (default) or 'project' for project-scoped boards",
    )
    board_init_parser.add_argument(
        "--overview",
        metavar="URL",
        help="URL of overview item (required for project-scoped boards)",
    )
    board_init_parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be done without making changes",
    )

    # board scan
    board_scan_parser = board_subparsers.add_parser(
        "scan",
        help="Scan repos for issues/PRs and add to board",
    )
    board_scan_parser.add_argument(
        "--repos",
        help="Comma-separated list of repos to scan (default: watched repos)",
    )
    board_scan_parser.add_argument(
        "--user",
        metavar="USERNAME",
        help="Scan all repos owned by this user (auto-discovers repos with activity)",
    )
    board_scan_parser.add_argument(
        "--org",
        metavar="ORGNAME",
        help="Scan all repos in this organization (auto-discovers repos with activity)",
    )
    board_scan_parser.add_argument(
        "--since",
        type=int,
        metavar="DAYS",
        help="Only include items updated in last N days",
    )
    board_scan_parser.add_argument(
        "--board",
        metavar="NAME",
        help="Board to use (default: default board)",
    )
    board_scan_parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be done without making changes",
    )
    board_scan_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )

    # board sync
    board_sync_parser = board_subparsers.add_parser(
        "sync",
        help="Sync board with GitHub state (incremental update)",
    )
    board_sync_parser.add_argument(
        "--full",
        action="store_true",
        help="Force full reconciliation of all items",
    )
    board_sync_parser.add_argument(
        "--board",
        metavar="NAME",
        help="Board to use (default: default board)",
    )
    board_sync_parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be done without making changes",
    )
    board_sync_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed output",
    )

    # board status
    board_status_parser = board_subparsers.add_parser(
        "status",
        help="Show current board status",
    )
    board_status_parser.add_argument(
        "--board",
        metavar="NAME",
        help="Board to use (default: default board)",
    )
    board_status_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show items in each column",
    )
    board_status_parser.add_argument(
        "--attention",
        "-a",
        action="store_true",
        help="Only show items needing attention",
    )
    board_status_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    # board config
    board_config_parser = board_subparsers.add_parser(
        "config",
        help="View and manage board configuration",
    )
    board_config_parser.add_argument(
        "action",
        nargs="?",
        choices=["repos", "set", "default"],
        help="Action: repos (add/remove), set (key value), default (set default board)",
    )
    board_config_parser.add_argument(
        "key",
        nargs="?",
        help="For repos: add/remove; for set: config key; for default: board name",
    )
    board_config_parser.add_argument(
        "value",
        nargs="?",
        help="For repos: owner/repo; for set: value",
    )
    board_config_parser.add_argument(
        "--board",
        metavar="NAME",
        help="Board to configure (default: default board)",
    )
    board_config_parser.add_argument(
        "--show-defaults",
        action="store_true",
        help="Show configuration with defaults",
    )

    # board apply
    board_apply_parser = board_subparsers.add_parser(
        "apply",
        help="Apply a YAML board configuration",
    )
    board_apply_parser.add_argument(
        "--config",
        "-c",
        dest="config_file",
        help="Path to YAML config file (default: ~/.tkt/boards/agent-workflow.yaml)",
    )
    board_apply_parser.add_argument(
        "--template",
        "-t",
        help="Use built-in template instead of file",
    )
    board_apply_parser.add_argument(
        "--board",
        metavar="NAME",
        help="Board to apply to (default: default board)",
    )
    board_apply_parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be done without making changes",
    )
    board_apply_parser.add_argument(
        "--prune",
        action="store_true",
        help="Remove columns not in config",
    )

    # board templates
    board_subparsers.add_parser(
        "templates",
        help="List available built-in templates",
    )

    # board macros
    board_subparsers.add_parser(
        "macros",
        help="List available macros for rule conditions",
    )

    # board add-item
    board_add_item_parser = board_subparsers.add_parser(
        "add-item",
        help="Manually add issues/PRs to the board",
    )
    board_add_item_parser.add_argument(
        "item_refs",
        nargs="+",
        metavar="ITEM",
        help="Item reference(s): URL, owner/repo#123, repo#123, or #123",
    )
    board_add_item_parser.add_argument(
        "--column",
        metavar="NAME",
        help="Target column (default: determined by rules)",
    )
    board_add_item_parser.add_argument(
        "--board",
        metavar="NAME",
        help="Board to use (default: default board)",
    )
    board_add_item_parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be done without making changes",
    )

    # board sync-config (separate from board sync which syncs items)
    board_sync_config_parser = board_subparsers.add_parser(
        "sync-config",
        help="Sync board configuration with GitHub Gist",
    )
    board_sync_config_parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be done without making changes",
    )

    # board rename
    board_rename_parser = board_subparsers.add_parser(
        "rename",
        help="Rename a board",
    )
    board_rename_parser.add_argument(
        "old_name",
        metavar="OLD_NAME",
        help="Current board name",
    )
    board_rename_parser.add_argument(
        "new_name",
        metavar="NEW_NAME",
        help="New board name",
    )

    # board rm/delete
    board_delete_parser = board_subparsers.add_parser(
        "rm",
        aliases=["delete"],
        help="Delete a board",
    )
    board_delete_parser.add_argument(
        "name",
        metavar="NAME",
        help="Board name to delete",
    )

    # pr command
    pr_parser = subparsers.add_parser(
        "pr",
        help="PR history visualization and repo management",
    )
    pr_subparsers = pr_parser.add_subparsers(dest="pr_command", required=True)

    # pr list
    pr_list_parser = pr_subparsers.add_parser(
        "list",
        help="List PRs with history visualization",
        description="List PRs with history visualization. "
        "Accepts PR references as arguments or piped via stdin (one per line). "
        "Both owner/repo#number and GitHub PR URLs are supported.",
    )
    pr_list_parser.add_argument(
        "pr_refs",
        nargs="*",
        metavar="OWNER/REPO#NUM",
        help="Specific PR references (owner/repo#number or GitHub PR URL). "
        "Can also be piped via stdin, one per line.",
    )
    pr_list_parser.add_argument(
        "--author",
        "-a",
        metavar="USER",
        help="Filter by PR author (use 'me' for current user)",
    )
    pr_list_parser.add_argument(
        "--reviewer",
        "-r",
        metavar="USER",
        help="Filter by requested reviewer (use 'me' for current user)",
    )
    pr_list_parser.add_argument(
        "--repo",
        dest="repos",
        action="append",
        metavar="OWNER/REPO",
        help="Filter by repo (can be specified multiple times)",
    )
    pr_list_parser.add_argument(
        "--all",
        "-A",
        dest="all_states",
        action="store_true",
        help="Show all states (open, merged, closed)",
    )
    pr_list_parser.add_argument(
        "--open",
        "-O",
        dest="include_open",
        action="store_true",
        help="Show open PRs (default if no state flags given)",
    )
    pr_list_parser.add_argument(
        "--merged",
        "-M",
        dest="include_merged",
        action="store_true",
        help="Show merged PRs",
    )
    pr_list_parser.add_argument(
        "--closed",
        "-C",
        dest="include_closed",
        action="store_true",
        help="Show closed (unmerged) PRs",
    )
    pr_list_parser.add_argument(
        "--board",
        "-b",
        dest="board_name",
        metavar="NAME",
        help="Use repos from specified board (implies using board repos)",
    )
    pr_list_parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=100,
        help="Maximum number of PRs to show (default: 100)",
    )
    pr_list_parser.add_argument(
        "--title",
        "-t",
        dest="show_title",
        action="store_true",
        help="Show PR titles",
    )
    pr_list_parser.add_argument(
        "--graph",
        "-g",
        dest="show_graph",
        action="store_true",
        help="Show weekly merge/age graph (only works with --merged)",
    )

    # review command - reviewer's view of PR queue
    review_parser = subparsers.add_parser(
        "review",
        help="Show PRs needing your review attention",
        description="Show PRs from a reviewer's perspective. "
        "Default shows only PRs that need your review action.",
    )
    review_parser.add_argument(
        "--all",
        "-A",
        dest="all_reviews",
        action="store_true",
        help="Include approved and hold PRs (default: only actionable)",
    )
    review_parser.add_argument(
        "--reviewer",
        "-r",
        metavar="USER",
        help="Show review queue for specified user (default: current user)",
    )
    review_parser.add_argument(
        "--author",
        metavar="USER",
        help="Filter by PR author",
    )
    review_parser.add_argument(
        "--exclude-author",
        "-X",
        dest="exclude_authors",
        metavar="USERS",
        help="Comma-separated list of authors to exclude (e.g., dependabot[bot],renovate[bot])",
    )
    review_parser.add_argument(
        "--repo",
        dest="repos",
        action="append",
        metavar="OWNER/REPO",
        help="Filter by repo (can be specified multiple times)",
    )
    review_parser.add_argument(
        "--board",
        "-b",
        dest="board_name",
        metavar="NAME",
        help="Use repos from specified board",
    )
    review_parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=100,
        help="Maximum number of PRs to show (default: 100)",
    )
    review_parser.add_argument(
        "--title",
        "-t",
        dest="show_title",
        action="store_true",
        help="Show PR titles",
    )
    review_parser.add_argument(
        "--merged",
        "-M",
        dest="include_merged",
        action="store_true",
        help="Show merged PRs you've reviewed",
    )
    review_parser.add_argument(
        "--closed",
        "-C",
        dest="include_closed",
        action="store_true",
        help="Show closed (unmerged) PRs you've reviewed",
    )

    # issue command - issue history visualization
    issue_parser = subparsers.add_parser(
        "issue",
        help="Issue history visualization",
    )
    issue_subparsers = issue_parser.add_subparsers(dest="issue_command", required=True)

    # issue list
    issue_list_parser = issue_subparsers.add_parser(
        "list",
        help="List issues with history visualization",
        description="List issues with history visualization. "
        "Default shows issues created by you. "
        "Accepts issue references as arguments (owner/repo#number).",
    )
    issue_list_parser.add_argument(
        "issue_refs",
        nargs="*",
        metavar="OWNER/REPO#NUM",
        help="Specific issue references (owner/repo#number)",
    )
    issue_list_parser.add_argument(
        "--author",
        "-a",
        metavar="USER",
        help="Filter by issue author (default: current user)",
    )
    issue_list_parser.add_argument(
        "--repo",
        dest="repos",
        action="append",
        metavar="OWNER/REPO",
        help="Filter by repo (can be specified multiple times)",
    )
    issue_list_parser.add_argument(
        "--board",
        "-b",
        dest="board_name",
        metavar="NAME",
        help="Use repos from specified board",
    )
    issue_list_parser.add_argument(
        "--label",
        "-l",
        dest="labels",
        action="append",
        metavar="LABEL",
        help="Filter by label. Repeat for AND, use comma for OR: "
        "-l bug -l urgent (AND), -l bug,stale (OR)",
    )
    issue_list_parser.add_argument(
        "--open",
        "-O",
        dest="include_open",
        action="store_true",
        help="Show open issues (default if no state flags given)",
    )
    issue_list_parser.add_argument(
        "--closed",
        "-C",
        dest="include_closed",
        action="store_true",
        help="Show closed issues",
    )
    issue_list_parser.add_argument(
        "--all",
        "-A",
        dest="all_states",
        action="store_true",
        help="Show all states (open, closed)",
    )
    issue_list_parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=100,
        help="Maximum number of issues to show (default: 100)",
    )
    issue_list_parser.add_argument(
        "--title",
        "-t",
        dest="show_title",
        action="store_true",
        help="Show issue titles",
    )
    issue_list_parser.add_argument(
        "--activity",
        "-s",
        dest="sort_by_activity",
        action="store_true",
        help="Sort by recent activity instead of creation date",
    )

    # repo command
    repo_parser = subparsers.add_parser(
        "repo",
        help="Manage watched repositories",
    )
    repo_subparsers = repo_parser.add_subparsers(dest="repo_command", required=True)

    # repo add
    repo_add_parser = repo_subparsers.add_parser(
        "add",
        help="Add repos to a board",
    )
    repo_add_parser.add_argument(
        "repos",
        nargs="+",
        metavar="OWNER/REPO",
        help="Repos to add",
    )
    repo_add_parser.add_argument(
        "--board",
        "-b",
        dest="board_name",
        metavar="NAME",
        help="Board to add repos to (creates if doesn't exist)",
    )
    repo_add_parser.add_argument(
        "--set-default",
        "-d",
        action="store_true",
        help="Set this board as the default",
    )

    # repo remove
    repo_remove_parser = repo_subparsers.add_parser(
        "remove",
        help="Remove repos from a board",
    )
    repo_remove_parser.add_argument(
        "repos",
        nargs="+",
        metavar="OWNER/REPO",
        help="Repos to remove",
    )
    repo_remove_parser.add_argument(
        "--board",
        "-b",
        dest="board_name",
        metavar="NAME",
        help="Board to remove repos from (default: default board)",
    )

    # repo list
    repo_list_parser = repo_subparsers.add_parser(
        "list",
        help="List repos in a board",
    )
    repo_list_parser.add_argument(
        "--board",
        "-b",
        dest="board_name",
        metavar="NAME",
        help="Board to list repos from (default: default board)",
    )
    repo_list_parser.add_argument(
        "--all",
        "-a",
        dest="all_boards",
        action="store_true",
        help="Show repos from all boards",
    )

    args = parser.parse_args(argv)

    # Handle board command
    if args.command == "board":
        from src.board.cli import (
            cmd_add_item,
            cmd_apply,
            cmd_config,
            cmd_delete,
            cmd_init,
            cmd_list,
            cmd_macros,
            cmd_rename,
            cmd_scan,
            cmd_status,
            cmd_sync,
            cmd_sync_config,
            cmd_templates,
        )

        if args.board_command == "list":
            return cmd_list()

        if args.board_command == "init":
            return cmd_init(
                create_name=args.create,
                project_id=args.project_id,
                project_number=args.project_number,
                board_name=args.board,
                scope=args.scope,
                overview=args.overview,
                dry_run=args.dry_run,
            )

        if args.board_command == "scan":
            repos = args.repos.split(",") if args.repos else None
            return cmd_scan(
                repos=repos,
                scan_user=args.user,
                scan_org=args.org,
                since_days=args.since,
                board_name=args.board,
                dry_run=args.dry_run,
                verbose=args.verbose,
            )

        if args.board_command == "sync":
            return cmd_sync(
                full=args.full,
                board_name=args.board,
                dry_run=args.dry_run,
                verbose=args.verbose,
            )

        if args.board_command == "sync-config":
            return cmd_sync_config(
                dry_run=args.dry_run,
            )

        if args.board_command == "status":
            return cmd_status(
                board_name=args.board,
                verbose=args.verbose,
                attention=args.attention,
                json_output=args.json,
            )

        if args.board_command == "config":
            return cmd_config(
                action=args.action,
                key=args.key,
                value=args.value,
                board_name=args.board,
                show_defaults=args.show_defaults,
            )

        if args.board_command == "apply":
            return cmd_apply(
                config_file=args.config_file,
                template=args.template,
                board_name=args.board,
                dry_run=args.dry_run,
                prune=args.prune,
            )

        if args.board_command == "templates":
            return cmd_templates()

        if args.board_command == "macros":
            return cmd_macros()

        if args.board_command == "add-item":
            return cmd_add_item(
                item_refs=args.item_refs,
                column=args.column,
                board_name=args.board,
                dry_run=args.dry_run,
            )

        if args.board_command == "rename":
            return cmd_rename(args.old_name, args.new_name)

        if args.board_command in ("rm", "delete"):
            return cmd_delete(args.name)

    # Handle pr command
    if args.command == "pr":
        from src.pr.cli import cmd_list as pr_cmd_list

        if args.pr_command == "list":
            # Build states list based on flags
            # --all trumps everything, otherwise explicit flags determine states
            # If no state flags given, default to open only
            if args.all_states:
                states = ["open", "merged", "closed"]
            else:
                states = []
                if args.include_open:
                    states.append("open")
                if args.include_merged:
                    states.append("merged")
                if args.include_closed:
                    states.append("closed")
                # Default to open if no state flags specified
                if not states:
                    states = ["open"]

            # Collect PR refs from command line args
            pr_refs = list(args.pr_refs) if args.pr_refs else []

            # Read PR URLs from stdin if piped
            if not sys.stdin.isatty():
                pr_refs.extend(_read_pr_refs_from_stdin())

            return pr_cmd_list(
                author=args.author,
                reviewer=args.reviewer,
                repos=args.repos,
                pr_refs=pr_refs if pr_refs else None,
                states=states,
                board_name=args.board_name,
                limit=args.limit,
                show_title=args.show_title,
                show_graph=args.show_graph,
            )

    # Handle review command
    if args.command == "review":
        from src.review.cli import cmd_list as review_cmd_list

        # Build states list based on flags
        # If --merged or --closed specified, use those; otherwise default to open
        review_states: list[str] = []
        if args.include_merged:
            review_states.append("merged")
        if args.include_closed:
            review_states.append("closed")
        # If no historical flags, default to open
        if not review_states:
            review_states.append("open")

        # Parse exclude_authors from comma-separated string
        exclude_authors: list[str] | None = None
        if args.exclude_authors:
            exclude_authors = [a.strip() for a in args.exclude_authors.split(",") if a.strip()]

        return review_cmd_list(
            all_reviews=args.all_reviews,
            reviewer=args.reviewer,
            author=args.author,
            exclude_authors=exclude_authors,
            repos=args.repos,
            board_name=args.board_name,
            limit=args.limit,
            show_title=args.show_title,
            states=review_states,
        )

    # Handle issue command
    if args.command == "issue":
        from src.issue.cli import cmd_list as issue_cmd_list

        if args.issue_command == "list":
            # Build states list based on flags
            issue_states: list[str] | None = None
            if args.all_states:
                issue_states = ["open", "closed"]
            elif args.include_open or args.include_closed:
                issue_states = []
                if args.include_open:
                    issue_states.append("open")
                if args.include_closed:
                    issue_states.append("closed")
            # Default: open only (handled by None -> defaults in cmd_list)

            # Read from stdin if no refs provided and stdin has data
            issue_refs = args.issue_refs
            if not issue_refs and not sys.stdin.isatty():
                issue_refs = _read_issue_refs_from_stdin()

            return issue_cmd_list(
                author=args.author,
                repos=args.repos,
                issue_refs=issue_refs if issue_refs else None,
                states=issue_states,
                labels=args.labels,
                board_name=args.board_name,
                limit=args.limit,
                show_title=args.show_title,
                sort_by_activity=args.sort_by_activity,
            )

    # Handle repo command
    if args.command == "repo":
        from src.repo.cli import cmd_add, cmd_remove
        from src.repo.cli import cmd_list as repo_cmd_list

        if args.repo_command == "add":
            return cmd_add(
                args.repos,
                board_name=args.board_name,
                set_default=args.set_default,
            )

        if args.repo_command == "remove":
            return cmd_remove(
                args.repos,
                board_name=args.board_name,
            )

        if args.repo_command == "list":
            return repo_cmd_list(
                board_name=args.board_name,
                all_boards=args.all_boards,
            )

    return 0


def _read_refs_from_stdin(item_type: str) -> list[str]:
    """Read GitHub refs from stdin, converting URLs to owner/repo#number format.

    Args:
        item_type: 'pull' for PRs or 'issues' for issues (used in URL pattern matching)

    Accepts both formats:
    - GitHub URLs: https://github.com/owner/repo/{item_type}/123
    - Direct refs: owner/repo#123

    Returns:
        List of references in owner/repo#number format
    """
    import re

    refs = []
    pattern = rf"https://github\.com/([^/]+/[^/]+)/{item_type}/(\d+)"

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        # Check if it's a GitHub URL
        if line.startswith("https://github.com/"):
            match = re.match(pattern, line)
            if match:
                repo_slug = match.group(1)
                number = match.group(2)
                refs.append(f"{repo_slug}#{number}")
            else:
                console.print(f"[yellow]Warning: Skipping invalid URL: {line}[/]")
        else:
            # Assume it's already in owner/repo#number format
            refs.append(line)

    return refs


def _read_pr_refs_from_stdin() -> list[str]:
    """Read PR references from stdin.

    Wrapper for _read_refs_from_stdin('pull') for backward compatibility.
    """
    return _read_refs_from_stdin("pull")


def _read_issue_refs_from_stdin() -> list[str]:
    """Read issue references from stdin.

    Wrapper for _read_refs_from_stdin('issues') for backward compatibility.
    """
    return _read_refs_from_stdin("issues")


if __name__ == "__main__":
    sys.exit(main())
