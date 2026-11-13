# Automating with `tkt`: poll, read what changed, decide what a PR needs

This page is for the author of a scheduled job, or an agent, that shepherds pull
requests. It shows one loop that gets every answer from `tkt` and none from raw
GitHub calls. [doc/usage.md](usage.md) stays the reference for each command; this
page gives the order and the settings, and links back instead of repeating.

The loop has four steps. **Poll** the PRs and learn which ones moved. **Read** only
the new text on those PRs. **Ask** which steps are pending. **Act**: that part is
yours.

## How the examples were made

- Every command here was run against real PRs in `jpshackelford/tickster`, with
  `tkt 0.3.0 (fdb1588)` and the repo's `.agents/tickster.toml` (blob `8a425f6`; see
  [Norms](#norms-what-each-command-reads)).
- Output is trimmed only by removing whole lines or whole JSON fields. A trimmed
  block says so.
- The examples use merged PRs, [#60](https://github.com/jpshackelford/tickster/pull/60)
  and [#62](https://github.com/jpshackelford/tickster/pull/62), whose heads cannot
  change, so you can rerun them. Anything that depends on the time you run it, such
  as ages, is said so. A merged PR has no pending steps and never changes,
  so the examples with a changed row and pending steps come from an open PR, this
  one, and are marked as live. They do not reproduce.
- Snapshot names start with `doc-`. Remove them afterwards with
  `tkt snapshot rm pr/doc-first pr/doc-live`.
- `tkt` reads your GitHub token from `GITHUB_TOKEN`
  ([Authentication](usage.md#authentication)).

## The loop

```bash
REFS="jpshackelford/tickster#60 jpshackelford/tickster#62"   # or --repo / --board
NAME=doc-first                                               # one snapshot per loop

# 1. Poll. Save the result: --watch has already moved the baseline.
tkt pr list $REFS --watch "$NAME" --format json > poll.json

# 2-3. For each row that is new or changed: read what is new, then ask what is pending.
jq -r '.deltas[] | select(.kind == "added" or .kind == "changed")
       | [.key, (.prev.last_activity // "")] | @tsv' poll.json |
while IFS=$'\t' read -r ref since; do
  if [ -n "$since" ]; then tkt pr show "$ref" --since-time "$since" --format json
  else                     tkt pr show "$ref" --format json
  fi
  tkt pr steps "$ref" --format json
  # 4. Act on what you read.
done
```

### 1. Poll: what moved since the last run?

`--watch NAME` diffs the current result against snapshot `pr/NAME`, prints the diff,
and then overwrites `pr/NAME` with the current result. With `--format json`
stdout is one JSON document ([`--watch` and `--format`](usage.md#snapshots--diffs)).
The snapshot always records each PR's step statuses, so a step that moved shows up in the diff without `--steps`.

The first poll has no baseline. Every row is `added`, and the notice
`No snapshot pr/doc-first found; treating all current rows as new.` goes to stderr.

A baseline saved by tickster 0.3.0 gives a different first poll. Every row an AI actor took
part in is `changed`, with `history-rewritten` in `changed_fields` and the whole history in
`new_history_tail`, but nothing is new: the same events are spelled differently. Skip those
deltas on that run, or replace the baseline once before the first scheduled run
([Upgrading to 1.0](usage.md#upgrading-to-10)). The next poll is clean.

```json
{
  "counts": {
    "added": 2,
    "removed": 0,
    "changed": 0,
    "unchanged": 0
  },
  "deltas": [
    {
      "key": "jpshackelford/tickster#60",
      "kind": "added",
      "new_history_tail": "sVnm",
      "changed_fields": [],
      "curr": {
        "key": "jpshackelford/tickster#60",
        "history": "sVnm",
        "state": "merged",
        "last_activity": "2026-11-05T10:45:37Z",
        "head_sha": "742dbea83bb141a3f06c1a82e87e32a862cc85be"
      }
    }
  ]
}
```

_Trimmed: the top-level `schema`, `prev`, `curr` and `scope_matches`; the second delta;
in the delta, `disappearance_reason` and `prev` (both `null`); and in `curr` every
field but the five shown (it also has the title, CI, reviewers, events and `steps`)._

Run the same command again and nothing has changed. The `unchanged` rows stay in
`deltas` (JSON always lists them), but with `prev` and `curr` set to `null`:

```json
{
  "counts": {
    "added": 0,
    "removed": 0,
    "changed": 0,
    "unchanged": 2
  },
  "deltas": [
    {
      "key": "jpshackelford/tickster#60",
      "kind": "unchanged",
      "new_history_tail": "",
      "changed_fields": [],
      "prev": null,
      "curr": null
    }
  ]
}
```

_Trimmed: the same top-level fields, the second delta (also `unchanged`), and
`disappearance_reason` (`null`)._

What a script can rely on in each delta:

| Field | Meaning |
| --- | --- |
| `kind` | `added`, `changed`, `removed` or `unchanged`. Act on `added` and `changed` |
| `changed_fields` | For `changed`: which fields moved, such as `head_sha`, `review_decision`, `activity`, `ci_status` ([why](usage.md#head-review-and-merge-changes)). `history-rewritten` means the new history does not start with the old one, so no event is new |
| `new_history_tail` | The characters appended to the [history string](usage.md#history-strings) since the baseline. With `history-rewritten`, the whole string |
| `prev`, `curr` | The row before and after. `prev` is `null` for `added`, `curr` is `null` for `removed`, and both are `null` for `unchanged` |
| `step_changes`, `reviewer_changes` | Present only when a step or a reviewer moved |

### 1b. A changed row (live)

A merged PR never changes, so this one comes from an open PR: this PR
([#95](https://github.com/jpshackelford/tickster/pull/95)), polled with the same
command as the loop's first line, `--watch doc-live`, once when it was opened (head `6eb294a`)
and again after a second commit was pushed. It will not reproduce, because the PR
moves on; the values here are from 2026-11-08 00:51 UTC.

```json
{
  "key": "jpshackelford/tickster#95",
  "kind": "changed",
  "new_history_tail": "",
  "changed_fields": [
    "ci_status",
    "head_sha",
    "merge_state",
    "activity",
    "steps"
  ],
  "prev": {
    "history": "s",
    "state": "open",
    "last_activity": "2026-11-08T00:51:09Z",
    "ci_status": "pending",
    "head_sha": "6eb294aa0dd948e23266ebf1b48e2c0babe08074"
  },
  "curr": {
    "history": "s",
    "state": "open",
    "last_activity": "2026-11-08T00:51:24Z",
    "ci_status": "--",
    "head_sha": "a77e1355f68fe22c18639c19c520bab54a067136"
  },
  "step_changes": [
    "fix CI: waiting → n/a"
  ]
}
```

_Trimmed: `disappearance_reason` (`null`), and in `prev` and `curr` every field but
the five shown (title, `key`, reviewers, events, `steps` and more)._

A push left the history string alone (`new_history_tail` is empty, because commits
before a review are not events), yet the row is `changed`: `head_sha` moved. The
loop's `prev.last_activity` is `2026-11-08T00:51:09Z`.

### 2. Read: only the new text

`tkt pr show REF --since-time TIME` prints the PR header and the events strictly after
`TIME`. For a `changed` row, `TIME` is `prev.last_activity`. For an `added` row there
is nothing to compare with, so read the whole timeline.
The output is the same as the removed `--since TIME` printed.

```text
$ tkt pr show jpshackelford/tickster#62 --since-time 2026-11-05T11:31:49Z --max-body 40
jpshackelford/tickster#62 pr merged ready ci:green 💬0 "feat(pr): tkt pr changes --since SHA: what changed since a commit, and does it matter"
history: sVnFnFnVm
author: jpshackelford  created: 2026-11-05T10:58:46Z  last activity: 2026-11-05T11:56:18Z
head: 7ada92a  mergeable: unknown  merge: unknown  review: approved
reviewers: github-actions(agent) ✓ approved on head
linked issues: jpshackelford/tickster#52
reports: manual_test 2026-11-05T11:39:10Z by jpshackelford at 7ada92a (on head) no fail match
timeline since 2026-11-05T11:31:49Z: 4 events, oldest first
2026-11-05T11:39:10Z n jpshackelford(me_agent) commented: ## Manual Test Results for PR #62 _This…(14076 more chars)
2026-11-05T11:49:39Z V github-actions(agent) approved on head: **Excellent implementation** — clean des…(2478 more chars)
2026-11-05T11:56:17Z m jpshackelford(me) merged
2026-11-05T11:56:18Z k jpshackelford(me) closed
```

_Trimmed: the `Legend:` line. `--max-body 40` shortens each body; the default is 600.
`TIME` here is the time of an earlier comment, standing in for a `prev.last_activity`._

For the live row above, `TIME` is its `prev.last_activity`:

```text
$ tkt pr show jpshackelford/tickster#95 --since-time 2026-11-08T00:51:09Z --max-body 40
jpshackelford/tickster#95 pr open draft ci:pending 💬0 "docs: add an automation how-to (poll, read what changed, decide what a PR needs)"
history: s
author: jpshackelford  created: 2026-11-08T00:51:09Z  last activity: 2026-11-08T00:51:24Z
head: a77e135  mergeable: mergeable  merge: unstable  review: --
reviewers: --
linked issues: jpshackelford/tickster#73
reports: manual_test none
timeline since 2026-11-08T00:51:09Z: 1 events, oldest first
2026-11-08T00:51:24Z - openhands-agent(agent) pushed 2 commits, last a77e135 "docs: link the automation how-to from the README"
```

_Trimmed: the `Legend:` line. Live, so it will not reproduce. The push is the one
new event._

Use `--format json` in a script ([fields](usage.md#tkt-pr-show)).

**Do not use `--since-snapshot` after `--watch`.** `--watch` has just overwritten the
baseline, so `--since-snapshot pr/NAME` points at now and finds nothing:

```text
$ tkt pr show jpshackelford/tickster#60 --since-snapshot pr/doc-first --max-body 40
…
no new events since 2026-11-05T10:45:37Z
```

_Trimmed: the header lines, ending at the one line that matters. Run after the second
poll above._

Two ways to read new text work. Use the first.

1. **`--watch`, then `show --since-time prev.last_activity`** (the loop above). One query
   decides what moved, and the baseline you act on is the one you saved.
2. **`--diff NAME`, then `show --since-snapshot pr/NAME`, then `--snapshot NAME`.**
   `--diff` reads without saving. The baseline advances only at the last command,
   so a crash in between loses nothing, but an event that lands between the diff
   and the snapshot is saved without ever being read.

`show --since-snapshot` fails with `snapshot pr/NAME has no row for REF` when the
snapshot does not hold the PR, which is the case on the first poll. Read the diff
first and call `show` only for `added` or `changed` rows.

Save `poll.json` before you process it. If the script dies after `--watch`, the
baseline has moved and the next run will not report those rows again.

### 3. Ask: what is pending?

```text
$ tkt pr steps jpshackelford/tickster#62 --explain
jpshackelford/tickster#62
  review the PR: n/a — PR is merged
    why: PR is merged
  fix CI: n/a — PR is merged
    why: PR is merged
  address review findings: n/a — PR is merged
    why: PR is merged
  request re-review: n/a — PR is merged
    why: PR is merged
  manually test: n/a — PR is merged
    why: PR is merged
  address test findings: n/a — PR is merged
    why: PR is merged
  retest after a fix: n/a — PR is merged
    why: PR is merged
```

On a merged or closed PR every step is `n/a`, so this is the whole answer for the
examples that can be rerun. `--format json` gives, per PR, `{"pr": …, "steps": […]}`
with `step`, `status` and `evidence` for each step ([statuses](usage.md#tkt-pr-steps)):

```json
[
  {
    "pr": "jpshackelford/tickster#62",
    "steps": [
      {
        "step": "review the PR",
        "status": "n/a",
        "evidence": [
          {
            "kind": "pr",
            "text": "PR is merged"
          }
        ]
      },
      …
    ]
  }
]
```

_Trimmed: the other six steps._

For a PR that still has work, the same command gives the pending steps. This is the
live PR at head `a77e135`, a draft with CI still running (it will not reproduce):

```text
$ tkt pr steps jpshackelford/tickster#95
jpshackelford/tickster#95
  review the PR: n/a — draft PR
  fix CI: waiting — Lint pending on head a77e135, Type Check pending on head a77e135, Test (Python 3.12) pending on head a77e135
  address review findings: n/a — no reviews
  request re-review: n/a — no reviews
  manually test: needed — no report
  address test findings: n/a — no report
  retest after a fix: n/a — no report
```

`manually test: needed` comes from `[reports.manual_test]` with `required = true` in
the norms file; `tkt` does not say whether to wait for CI first or write the report
now. That order is yours.

### 3b. Did the code change since a report or a review?

`tkt pr steps` already judges whether a report is stale, with the same rules.
When you need that answer for another commit, ask `tkt pr changes` directly. It reads
`[commits]` from the norms file unless you pass flags:

```text
$ tkt pr changes jpshackelford/tickster#60 --since-sha 75d1faa --explain
jpshackelford/tickster#60 75d1faa..742dbea 1 commits 4 files +104 -4
significant: yes (4 files, 108 changed lines)
  why: ignore_paths = [doc/**, **/*.md] (.agents/tickster.toml)
  why: min_changed_lines = 0 (.agents/tickster.toml)
commit	742dbea	--	openhands-agent	fix(issue): default 'issue list' to open issues
file	modified	+0	-1	--	src/__main__.py
file	modified	+2	-1	--	src/issue/cli/list_cmd.py
file	modified	+7	-2	--	src/snapshot/models.py
file	added	+95	-0	--	tests/snapshot/test_issue_default_state.py
```

`75d1faa` is the `main` commit the PR branched from. The `why:` lines say where each
setting came from: here the repo's norms file. `--format json` adds `significant`,
`reasons`, `settings`, `commits` and `files` ([details](usage.md#tkt-pr-changes)).

### 4. Act

`tkt` does not act. It reads. Whatever the loop does next, such as asking for a
review, fixing CI or posting a comment, is your code's job.

## What `tkt` decides, and what it does not

| `tkt` decides | You decide |
| --- | --- |
| Which rows are `added`, `changed`, `removed` | How often to poll, and which PRs are in scope |
| Which steps are `needed`, `waiting`, `done`, `n/a`, `not configured` or `unknown`, and the evidence | **Which step comes first.** `tkt pr steps` says what is pending, never what to do first. Order is policy and belongs to the consumer |
| Whether a change since a commit is significant, by the rules in `[commits]` | What to do with a significant change |
| Whether a comment is a report, and whether it failed, by the patterns in the norms | How to word a report, and when a repo requires one (the norms say so; `tkt` has no default) |

Exit code 0 never means "nothing to do". Read the JSON.

## Norms: what each command reads

The repo's conventions are in `.agents/tickster.toml`
([`tkt norms`](usage.md#tkt-norms)). `tkt` reads it from the repo's **default
branch** through the contents API, never from a PR's head. A change to the file has
no effect until it is merged. `tkt norms show --repo OWNER/NAME` prints the settings
in effect, with the blob SHA of the file read; with no file, steps that depend on it
are `not configured`.

| Command | Keys it reads |
| --- | --- |
| `tkt pr list` (with `--watch`, `--diff`, `--format json`) | `[actors]` `agent_logins`, `bots` and `agent_disclosure`: the [actor class](usage.md#ai-actors) of every event and reviewer in a row. Also everything `tkt pr steps` reads, because the step statuses are always recorded |
| `tkt pr show` | `[actors]`, as above. `[reports.NAME]` `marker` and `fail`: the `reports:` line and the JSON `reports` |
| `tkt pr steps` | `[actors]`, so that classes decide who is a reviewer. `[review]` `count_reviews_from`, `rerequest_labels`. `[ci]` `ignore_checks`. `[commits]` `ignore_paths`, `min_changed_lines`. Every `[reports.NAME]`: `marker`, `required`, `only_paths`, `fail` and `[reports.NAME.impact_line]` `pattern`, `from`, `unassessed` |
| `tkt pr changes` | `[commits]` `ignore_paths`, `min_changed_lines`, and only for a setting you did not give as `--ignore-path` or `--min-changed-lines`. The file is not fetched when you give both |

`[labels] stale` is not read by any of these. It is for [`tkt board`](board.md).

To set the file up, start from `tkt norms init --from github:jpshackelford/tickster`,
then check it with `tkt norms check --strict`.

## Exit codes and streams

Each claim below was checked by running the command.

| Command | stdout | stderr | Exit code |
| --- | --- | --- | --- |
| `tkt pr list … --watch NAME --format json` | One JSON document | Notices, such as `No snapshot pr/NAME found; …`, and errors | 0, whether or not rows changed. A scope mismatch exits 2 with `Error: scope mismatch between snapshots (use --diff-force to proceed anyway)` on stderr, empty stdout, and leaves the baseline untouched. Pass `--diff-force` to proceed. Any other failure, such as a bad token or no network, exits 1 with the `Error:` line on stderr and empty stdout. If only the save fails, stdout still holds the document and the exit code is 1 |
| `tkt pr show REF --format json` | One JSON document | Errors | 0. A bad ref, a bad time, an unknown snapshot or a snapshot with no row for the PR exits 1. `--since-time` with `--since-snapshot` exits 2 |
| `tkt pr steps REF… --format json` | One JSON document | Notices and errors | 0 whatever the statuses. A PR that is not found exits 1, with empty stdout |
| `tkt pr changes REF --since-sha SHA --format json` | One JSON document | Errors | 0 whether or not the change is significant. A PR that is not found exits 1. A `--since-sha` that is not a 7 to 40 character hex SHA, so also a branch or a tag, exits 2, with no GitHub call |

- Parse stdout only. Do not merge stderr into it.
- A command whose stdout closes early, such as `tkt … | head -1`, exits 141 and prints nothing.
- `--watch` and `--diff` exit 0 on an empty diff, and exit 0 when there is a lot to do.
  Decide from `counts` and `kind`.
- A scope is the set of refs, repos, authors, states and so on in the query. If the
  query changes between runs, the loop stops with exit 2 until you pass `--diff-force`
  once, or use a new snapshot name.

## Known limits

These are the limits that matter to a polling loop. The first two are also in
[`tkt pr steps`](usage.md#tkt-pr-steps), the rest under the sections linked.

- **Findings outside threads are not detected.** `address review findings` looks at
  unresolved review threads and at a counted reviewer's latest `CHANGES_REQUESTED`
  review. A finding left in a review summary or a plain comment instead of a thread is
  not seen.
- **Only the first 200 characters of a comment are matched** by `marker`, `fail` and
  `impact_line` patterns. Put a report's verdict near the top.
- **A long timeline is cut.** Past the fetch cap `tkt pr show` prints `(timeline
  truncated: …)` and JSON has `"timeline_truncated": true`; the report
  steps of `tkt pr steps` can be `unknown`.
- **A request made and removed between two polls is not reported.** Removal and
  dismissal of reviews come from comparing snapshots ([Reviewer state](usage.md#reviewer-state)).
- **`UNKNOWN` mergeability is not a change.** While GitHub computes it after a push,
  a move to or from `UNKNOWN` is not flagged ([Head, review and merge
  changes](usage.md#head-review-and-merge-changes)).
- **Table output is for people.** On a terminal the table is fitted to the width: Repo,
  Title and History give up width, and a cut History ends in `>`
  ([`--steps`](usage.md#tkt-pr)). The fit is for terminals only: piped or redirected
  table output is never cropped, and its legends and notes are not wrapped. JSON is not cut.

## See also

- [`tkt pr show`](usage.md#tkt-pr-show), [`tkt pr steps`](usage.md#tkt-pr-steps),
  [`tkt pr changes`](usage.md#tkt-pr-changes)
- [Snapshots & diffs](usage.md#snapshots--diffs), [`tkt snapshot`](usage.md#tkt-snapshot)
- [`tkt norms`](usage.md#tkt-norms)
