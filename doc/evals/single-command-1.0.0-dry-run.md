# Single-command eval: author's dry run

This is **not** a fresh-agent run. The author ran the reference command and the
baseline of the [single-command eval](../../.openhands/skills/single-command-eval/SKILL.md)
by hand, to prove the procedure and that the recipe in `--help` answers the question.
The fresh-agent runs, with two or more phrasings, are still to do.

| | |
| --- | --- |
| Date | 2026-11-13 |
| tickster | `tkt 1.0.0` at the head of the PR for #143 |
| Agent | none (author, by hand) |
| Question | List the issues I filed in the last two weeks that have no PR. |
| Repository | `jpshackelford/tickster` (public) |

## Command

The recipe from `tkt issue list --help`, with `--repo` to keep the rows public:

```console
$ tkt issue list --repo jpshackelford/tickster --all --created-since 14 --no-pr --title
...
Filters: author=jpshackelford (you) · state=open+closed · repos=jpshackelford/tickster · label=any · limit=100
Window: created ≥ 2026-10-30 (UTC)
```

One `tkt issue list` command, no pipe. 11 rows.

## Baseline

`DATE` = 2026-10-30.

| Step | Result |
| --- | --- |
| `gh search issues --repo jpshackelford/tickster --author @me --created ">=2026-10-30"` | 67 issues |
| With a closing PR (`closedByPullRequestsReferences`) or a PR that mentions them (`CrossReferencedEvent`) | 56 issues |
| No linked PR | 11 issues |

The 11 issues: #71, #100, #101, #107, #120, #128, #129, #138, #143, #144, #179.

## Verdict

The 11 rows of the command are the same 11 issues as the baseline (compared
case-insensitively by `owner/repo#number`). The command answers the question in one step.

## Findings

- The `Filters:` line does not name `--no-pr` (or `--has-pr`, or the date window, which
  is on the `Window:` line). A reader of the `Filters:` line alone cannot tell that the
  list was cut to issues with no PR. This is outside the scope of #143 (no behavior
  change); it is raised as a follow-up on the PR.
- A first `gh`-only attempt that used the REST timeline (`cross-referenced` events)
  found no linked PRs at all and gave the wrong baseline: PRs that close an issue show
  up in `closedByPullRequestsReferences`, not always in the REST timeline. The
  baseline in the procedure uses GraphQL for that reason.
