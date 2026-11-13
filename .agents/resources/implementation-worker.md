# Implementation Worker Hints

## Product context

tickster (`tkt`) is a CLI that turns GitHub PRs and issues into compact, token-dense rows and history strings for people and agents.
Current work is GitHub-only. Read the whole issue, including any **Scope** note at its top, before you write code.

## Implementation rules

- Build on the current code. Don't implement the multi-provider refactor (#32, #33 and the rest of #38) as a step toward another issue.
- Keep the default output of `tkt pr list`, `tkt issue list` and `tkt review` unchanged unless the issue says to change it. Put new columns behind a flag.
- With `--format json` or `--format json`, stdout must be valid JSON and nothing else. Send notices to stderr.
- Recorded GraphQL fixtures come from public repositories only. Never copy code or data from private repositories into this repo.
- Update `doc/usage.md` and the legend for every user-visible change.
- The PR title is a conventional commit (`feat(pr): …`, `fix(snapshot): …`). release-please builds the changelog from it.

## Definition of done

- Tests cover the issue's acceptance criteria, using recorded fixtures where the issue asks for them.
- These all pass:
  - `uv run pytest -q`
  - `uv run ruff check src tests`
  - `uv run ruff format --check src tests`
  - `uv run basedpyright src`
- The PR is a draft until local checks pass. The PR body links the issue with `Closes #N`.

## Release PRs

The release PR (title `chore(main): release …`, branch `release-please--branches--main--components--tickster`, opened by `github-actions`) is managed by release-please and released by a human.
Don't merge, approve, review, push to, rebase, edit, relabel or comment on it. If your task seems to need any of that, stop and say so in your final message.
