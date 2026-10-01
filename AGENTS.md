# Agent instructions

This repo uses the agent-skills convention. Repo-local skills live in
[`.openhands/skills/<name>/SKILL.md`](.openhands/skills/) and should be
discovered and followed on demand.

## Build / test / lint

```bash
uv sync --extra dev                   # install
uv run pytest -q                      # tests
uv run ruff check src tests           # lint
uv run ruff format --check src tests  # format
uv run basedpyright src               # type check
```

CI (`.github/workflows/ci.yml`) runs all four on every PR; all must be clean.

## Required workflows

- **Before code review on any PR:** follow
  [`.openhands/skills/manual-test/SKILL.md`](.openhands/skills/manual-test/SKILL.md)
  and post the resulting report as a PR comment. Re-run after any
  review-driven behavior change.

## Conventions

- Attribution: any comment, issue, or PR body an agent posts must include
  _"created by an AI agent (OpenHands) on behalf of @jpshackelford"_.
- Never push directly to `main`. Open a PR.
- Keep this file short. Add new procedures as skills under
  `.openhands/skills/`, not as prose here.
