---
name: single-command-eval
description: Check that a fresh agent answers "list the issues I filed in the last two weeks that have no PR" with exactly one `tkt issue list` command and no pipe, using only `tkt --help`. Run it on a release candidate, with two or more phrasings of the question, and save the transcript under doc/evals/.
triggers:
  - /single-command-eval
  - single-command eval
  - one-command eval
---

# Single-command eval (tickster)

Tests the help text, not the code. A fresh agent that only reads `tkt --help` (and the
`--help` of any subcommand it opens) must find the one command that answers the
reference question. The result is evidence for one release: it depends on the model,
so do not treat it as a regression test.

## Setup

1. Install the release candidate: `uv tool install --force git+https://github.com/jpshackelford/tickster@REF`
   (or `uv tool install --force .` from a checkout). Note `tkt --version`.
2. Export `GITHUB_TOKEN` for the agent. Use a token for a user who filed at least a few
   issues in the last 14 days, some with a linked PR and some without.
3. Use a fresh agent with no repo checkout, no tickster docs and no memory of earlier runs.
   Give it a shell. Make `tkt` the only GitHub tool: no `gh`, no `curl` to api.github.com.
4. Write down the model, the date and the tickster version. They go into the transcript.

## The prompt

The agent sees only this. Give the text of `tkt --help` as its first tool result, or in
its system prompt, and tell it today's date.

> You answer questions about GitHub issues from a shell. The only GitHub tool installed
> is `tkt`. Today is YYYY-MM-DD. You can run `tkt <subcommand> --help`. Run what you
> need, then answer in plain text.

Then ask the question. Use at least two phrasings, each in its own fresh run:

1. List the issues I filed in the last two weeks that have no PR.
2. Which issues did I open this fortnight that nobody has picked up?
3. Show my issues from the past 14 days that still have no pull request, with titles.

Tell the agent to look in one public repository (for example `jpshackelford/tickster`)
so the saved rows are public. Put that repository in the question; do not name any flag.

## Record

Save every command the agent runs, in order, with its exit code, and the final answer.
Remove token values and anything private. Use public repositories and public issues only.

## Pass criteria

All of these, for every phrasing:

- The agent runs exactly one `tkt issue list` command, not counting `--help` calls.
- That command has no pipe, no `awk`, `jq`, `grep` or second tool, and no second `tkt` call.
- The command uses `--created-since 14` (or `--created-after DATE`), `--no-pr` and
  `--all`, so closed issues count. The `Window:` line under the table shows the date.
  The `Filters:` line shows the author, the states and the repos.
- The rows equal the baseline below.

## Baseline

With `DATE` = today minus 14 days (the UTC day that `--created-since 14` starts on):

1. `gh search issues --repo OWNER/REPO --author @me --created ">=DATE" --limit 200 --json repository,number`
   lists the issues created since `DATE`.
2. For each, ask GraphQL whether a PR links to it: `closedByPullRequestsReferences`
   with `includeClosedPrs: true`, plus `CrossReferencedEvent` items whose `source` is
   a `PullRequest`. This is the definition in
   [Linked PRs](../../../doc/usage.md#linked-prs): a PR closes or mentions the issue,
   in any state.
3. Keep the issues with no linked PR. Compare them, case-insensitively by
   `owner/repo#number`, with the rows of the agent's command. The same command with
   `--format json | jq -r '.items[] | "\(.repo)#\(.number)"'` gives a list to compare.

The sets must be equal.

## Saved transcript

Save the result as `doc/evals/single-command-VERSION.md`: model, date, version, one
section per phrasing with the commands and the final answer, then the baseline
comparison and the verdict. `doc/evals/single-command-1.0.0-dry-run.md` is the author's
check of the command and the baseline; it is not a fresh-agent run.
