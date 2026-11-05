# Testing Worker Hints

Follow `.openhands/skills/manual-test/SKILL.md`. It posts one PR comment that starts with `## Manual Test Results for PR #N`.

- Test the installed CLI (`uv run tkt …`) against public repositories. Never print tokens.
- Exercise the default table output and `--format json` when the change touches both. Check that JSON output parses (for example, pipe it to `python -m json.tool`).
- For snapshot or `--watch` changes, run two ticks against a temporary `TKT_HOME` and show the diff.
- Re-test after any review-driven behavior change.

## Release PRs

The release PR (title `chore(main): release …`, branch `release-please--branches--main--components--tickster`, opened by `github-actions`) is managed by release-please and released by a human.
Don't merge, approve, review, push to, rebase, edit, relabel or comment on it. If your task seems to need any of that, stop and say so in your final message.
