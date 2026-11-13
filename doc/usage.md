# tickster (`tkt`) usage guide

`tkt` is a token-efficient command-line tool for viewing and managing GitHub
issues, pull requests, review queues, and GitHub Project boards. Output is
compact and structured so it is cheap to feed to an LLM agent.

- [Install](#install)
- [Authentication](#authentication)
- [Configuration](#configuration)
- [Global options](#global-options)
- [`tkt issue`](#tkt-issue)
- [`tkt pr`](#tkt-pr)
- [`tkt review`](#tkt-review)
- [`tkt board`](#tkt-board)
- [`tkt repo`](#tkt-repo)
- [`tkt norms`](#tkt-norms)
- [Upgrading to 1.0](#upgrading-to-10)
- [Upgrading to 2.0](#upgrading-to-20)
- [`tkt snapshot`](#tkt-snapshot)
- [Snapshots & diffs](#snapshots--diffs)
- [Date-window filtering](#date-window-filtering)
- [Recipes](#recipes)
- [History strings](#history-strings)
- [Piping refs from stdin](#piping-refs-from-stdin)
- [Environment variables](#environment-variables)

## Install

Tickster is managed with [uv](https://docs.astral.sh/uv/). Python 3.12+ is
required (uv fetches a suitable interpreter automatically).

Install the `tkt` command globally as a uv tool:

```bash
uv tool install git+https://github.com/jpshackelford/tickster
# or, from a local checkout:
uv tool install .
```

For development, sync the project environment and run through uv:

```bash
uv sync --extra dev
uv run tkt --help
```

## Authentication

`tkt` talks to the GitHub API and reads credentials from the environment. The
nearest `.env` file, searching from the working directory up through its
parents, is loaded automatically. Variables already exported in your shell take
precedence over `.env` values.

```bash
export GITHUB_TOKEN=ghp_xxx        # required
export GIST_TOKEN=ghp_xxx          # optional: scoped token for board gist sync
```

If `GITHUB_TOKEN` is not set and the `gh` CLI is authenticated, the board
commands fall back to the `gh` token where possible. A token with `repo` (and
`project` for board write operations) scope is recommended.

## Configuration

Persistent configuration (watched repos, board definitions, defaults) is stored
in:

```
~/.tkt/config.toml          # board, issue, and pr settings
~/.tkt/board-cache.db       # local board cache
```

You normally do not edit these by hand — `tkt repo`, `tkt board config`, and
`tkt board init` manage them for you.

All tickster state (config, cache, `boards/`, `snapshots/`, `api_logs/`) lives
under `~/.tkt` by default. Set `TKT_HOME` to relocate it, e.g. for CI, a
sandbox, or an isolated profile:

```bash
TKT_HOME=/tmp/tkt-ci tkt board status
```

## Global options

```bash
tkt --version               # print version
tkt --help                  # top-level help
tkt <command> --help        # per-command help (authoritative reference)
```

Available commands: `issue`, `pr`, `review`, `board`, `repo`.

---

## `tkt issue`

List issues with a compact history visualization. Default shows issues created
by you; `--all-authors` shows everyone's issues in the scoped repos.

```bash
tkt issue list [OWNER/REPO#NUM ...]
```

| Option | Description |
| --- | --- |
| `--author, -a USER` | Filter by issue author (default: current user) |
| `--all-authors` | Every author's issues in the repos from `--repo` or the board (see [Listing every author](#listing-every-author)) |
| `--repo OWNER/REPO` | Filter by repo (repeatable) |
| `--board, -b NAME` | Use repos from the named board |
| `--label, -l LABEL` | Filter by label. Repeat for AND (`-l bug -l urgent`), comma for OR (`-l bug,stale`) |
| `--not-label LABEL` | Leave out issues that have this label (case-insensitive). Repeat to leave out issues with any of several labels; commas are not special. Combines with `-l`; a label in both returns nothing. Not with explicit refs |
| `--no-pr` | Only issues with no linked PR (the `PR` column shows `--`), by the definition in [Linked PRs](#linked-prs). Closed issues are included only with `--closed` or `--all`. Not with `--has-pr` or explicit refs |
| `--has-pr` | Only issues with at least one linked PR, in any state (open, merged or closed). Not with `--no-pr` or explicit refs |
| `--unblocked` | Only issues with no open blocker. A closed blocker does not count. See [Issue dependencies](#issue-dependencies). Not with `--blocked` or explicit refs |
| `--blocked` | Only issues with at least one open blocker. A blocker you cannot read counts as open (`?`). Not with `--unblocked` or explicit refs |
| `--open, -O` | Show open issues (default) |
| `--closed, -C` | Show closed issues |
| `--all, -A` | Include closed issues as well as open ones. Without `--all`, `--open` or `--closed`, only open issues are listed |
| `--limit, -n N` | Max issues to show (default: 100) |
| `--title, -t` | Show issue titles |
| `--deps` | Add `Blocked by` (open blockers, `--` for none) and `Blocks` (open issues this one blocks) columns. See [Issue dependencies](#issue-dependencies) |
| `--activity, -s` | Sort by recent activity instead of creation date. Not with `--sort` |
| `--sort KEY[,KEY...]` | Order the list by `number`, `created`, `updated`, `blocking` or `rank`, then apply `--limit`. See [Sorting](#sorting-issues). Not with `--activity` |
| `--created-since DAYS` | Only issues created since the start of the UTC day N days ago (`0` = today) |
| `--created-after YYYY-MM-DD`, `--created-before YYYY-MM-DD` | Only issues created on/after, on/before this UTC date (inclusive) |
| `--updated-since DAYS`, `--updated-after YYYY-MM-DD`, `--updated-before YYYY-MM-DD` | The same, on the last-updated date |
| `--closed-since DAYS`, `--closed-after YYYY-MM-DD`, `--closed-before YYYY-MM-DD` | The same, on the close date. Needs `--closed` or `--all` |

```bash
tkt issue list                              # your open issues
tkt issue list --repo octocat/hello-world   # one repo
tkt issue list --all --title -l bug         # all states, titles, bug label
tkt issue list --deps                       # which of my open issues are blocked
tkt issue list --repo octocat/hello-world --all-authors -l ready --not-label hold   # ready, not on hold
tkt issue list --all --no-pr --title        # issues nobody has opened a PR for
tkt issue list --has-pr                     # my open issues that already have a PR
tkt issue list --repo octocat/hello-world --all-authors -l ready --unblocked   # ready and startable now
tkt issue list --blocked --deps             # my open issues that are waiting, and on what
tkt issue list octocat/hello-world#42       # a specific issue
tkt issue list --all --created-since 14      # issues filed in the last 2 weeks
tkt issue list --all --updated-since 14      # issues touched in the last 2 weeks
tkt issue list --all --closed-after 2026-11-01 --closed-before 2026-11-07   # closed that week
tkt issue list --repo octocat/hello-world --all-authors --open   # everyone's open issues
tkt issue list --repo octocat/hello-world --all-authors -l ready --unblocked --sort -blocking,number -n 2   # the two best issues to start
```

`--no-pr`, `--has-pr`, `--blocked` and `--unblocked` filter after the search, so
`--limit` counts matching issues, not issues fetched. When more matching issues exist, the footer says
`Showing N matching issues (more available; raise --limit)`; it gives no total,
since GitHub's count includes issues the filter drops. When the search ran out
of issues, there is no footer. Under `--no-pr`, an issue leaves a `--diff` or
`--watch` when a PR links to it, and the Note says so (see
[Why a row is gone](#why-a-row-is-gone)). Under `--blocked`, an issue leaves
when its last open blocker closes; `--diff-resolve` then reports it as
`still open`.

Also accepts `--snapshot`, `--diff`, `--watch` for change-since-last-run
output — see [Snapshots & diffs](#snapshots--diffs).

`--format json` prints the current result as one JSON document instead of the
table, the same document `tkt snapshot show KIND/NAME --format json` prints,
with `snapshot` present only for a named snapshot. See
[`--format json` on list commands](#--format-json-on-list-commands).

See [Date-window filtering](#date-window-filtering) for the semantics of the
`--created-*` / `--updated-*` / `--closed-*` flags.

### Sorting issues

`--sort KEY[,KEY...]` orders the list. A `-` before a key reverses it.

| Key | Order |
| --- | --- |
| `number` | Ascending |
| `created` | Oldest first |
| `updated` | Least recently updated first (the time in the `Last` column) |
| `blocking` | Most open issues blocked first (the `Blocks` count) |
| `rank` | Best label first, in the order of the repo's [`[labels] rank`](#tkt-norms) list; issues with none of those labels last |

Later keys break ties. A final tie is broken by `number`, then by repo.
`--sort -created` puts the newest first; `--sort -blocking` puts the issues that
block the fewest first. Write a reversed first key as `--sort -created` or
`--sort=-created`; both work.

With `--sort`, tickster fetches every issue that matches the filters, sorts them,
and only then applies `--limit`. So `--sort blocking --limit 1` returns the issue
that blocks the most open issues, even when GitHub would not list it on the first
page. A query that matches more than 500 issues exits 1 with
`more than 500 issues match; narrow the query`, and prints no rows: tickster never
sorts part of the set.

`rank` reads the label order from each repo's norms file, so tickster has no
built-in label names. An issue ranks by the first label of the list that it has
(the best position when it has several); the match ignores case. `--sort rank,blocking,number`
puts the most important issues first, then the ones that block the most, then the
oldest. `--sort -rank` reverses the order, so unranked issues come first. If any repo
in the query has no `[labels] rank`, the command exits 1 with
`no [labels] rank in the norms of OWNER/REPO` and prints no rows. Other keys still work
in that repo.

An unknown key exits 2 and lists the valid keys. Without `--sort`, the order and
the `--limit` behavior are as before. `--sort` works with the table, `--format json`
and explicit refs. It is part of a snapshot's scope: a `--diff` against a snapshot
saved with a different `--sort` reports `scope mismatch` and names the change.

### Which issues can I start now?

A caller that picks the next issues to work on needs one command, not a script.
Run this in the repos you work from (`--repo OWNER/REPO` or `--board NAME`, as
with any list):

```bash
tkt issue list --all-authors -l ready --not-label hold --unblocked --no-pr \
  --sort rank,blocking,number --limit 2 --format json
```

- `--all-authors -l ready` keeps everyone's open issues that carry the label `ready`.
  The label name is yours: tickster has no built-in meaning for it.
- `--not-label hold` drops the issues that carry `hold`. Again the name is yours.
- `--unblocked` keeps issues with no open blocker. A closed blocker does not count.
- `--no-pr` keeps issues with no linked PR, so work that has started is not picked twice.
- `--sort rank,blocking,number` puts the best label first, in the order of the repo's
  [`[labels] rank`](#tkt-norms) list, then the issues that block the most open issues,
  then the oldest. See [Sorting](#sorting-issues).
- `--limit 2` keeps the first two after the sort. You get fewer when fewer match.
- `--format json` prints one document; the issues are in its `items` array.

For the waiting list, the issues that are `ready` but cannot start yet:

```bash
tkt issue list --all-authors -l ready --blocked --format json
```

The `open_blockers` field of each item names what it waits on, as
`owner/repo#number` refs (`?` for a blocker the token cannot read).
See [Issue dependencies](#issue-dependencies).

Close a blocker and run the first command again: the issue it blocked now
qualifies. GitHub's search index can lag a few seconds behind a close or a label
change, so an issue you just closed or labeled may still show for a moment.

tickster does not decide which label means ready, how many issues to start, or
what to do with an issue on hold. Those are your policy: you pass them as flags.
`[labels] rank` has no default, and `--sort rank` exits 1 in a repo that has none.

### Effective filters line

A plain `tkt issue list` prints one `Filters:` line under the table and its
`History:` legend, naming every filter in effect, defaults included. An empty result prints
`No issues found.` and then the same line, so you can see what was searched.

```
Filters: author=octocat (you) · state=open · repos=all GitHub · label=any · limit=100
```

| Field | Value |
| --- | --- |
| `author` | The login, with `(you)` when it is the current user (the default or `me`); `all authors` with `--all-authors` |
| `state` | `open`, `closed` or `open+closed` |
| `repos` | `--repo` values, the board's repos (comma-joined), or `all GitHub` |
| `label` | `any`, or the `-l` values: repeated flags joined with ` & ` (AND), commas shown as `\|` (OR). `-l bug,stale -l urgent` prints `label=bug\|stale & urgent` |
| `not-label` | Only with `--not-label`: the labels, comma-joined |
| `blocked` | Only with `--blocked` (`yes`) or `--unblocked` (`no`) |
| `sort` | Only with `--sort`: the keys, comma-joined, as typed |
| `limit` | `--limit` (default 100) |

With explicit refs the line is `Filters: refs=N`, since refs ignore the other
filters. The line does not repeat the date window; that stays on the `Window:`
line. `--diff`, `--watch`, `--snapshot` and `--format json` do not print it.
When stdout is not a terminal the line is never wrapped.

### `tkt issue show`

Read one issue: a header and its timeline, oldest first, with the text of the
opening post and each comment. Use it after `tkt issue list` shows an issue you
need to read.

```bash
tkt issue show OWNER/REPO#NUM [--since-time TS]
    [--max-body N] [--format text|json]
```

The ref may be `owner/repo#number` or a GitHub issue URL. See
[`tkt pr show`](#tkt-pr-show) for the options; they work the same way here.

```text
$ tkt issue show jpshackelford/tickster#49 --max-body 40
jpshackelford/tickster#49 issue closed "issue list: no state flag returns closed issues too, although --open is documented as the default"
history: slx
author: jpshackelford  created: 2026-10-27T20:37:49Z  last activity: 2026-11-05T10:45:40Z
labels: bug, priority:high, ready  assignees: --
linked PRs: --
Legend: the letter is the event's history character (lowercase = you, UPPERCASE = others; AI letters: lowercase = your login, UPPERCASE = its own login; - = not in the history string). o opened, s AI opened, c comment, n AI comment, B bot comment, l labeled, a assigned, x closed, r reopened, p PR linked. blocked by: open blockers (? = one you cannot read), blocks: open issues this one blocks. Class: me human bot agent me_agent.
timeline: 5 events, oldest first
2026-10-27T20:37:49Z s jpshackelford(me_agent) opened: ## Summary `tkt issue list` with no sta…(1944 more chars)
2026-10-27T20:37:50Z l jpshackelford(me) labeled bug
2026-11-05T05:43:19Z l jpshackelford(me) labeled ready
2026-11-05T05:43:19Z l jpshackelford(me) labeled priority:high
2026-11-05T10:45:40Z x jpshackelford(me) closed
```

The header has the state, the [history string](#history-strings), author, dates,
labels, assignees, and linked PRs. When GitHub knows any
[dependency facts](#issue-dependencies) for the issue, one more line follows:
`blocked by: #121, #123  blocks: 1  parent: #120  milestone: v2`. It leaves out
the parts that are empty and is missing when all four are. Each timeline line is
`time char actor(class) text`; the `char` is the event's character in the
history string (`-` when the history string leaves that event out) and `class`
is the [actor class](#bot-detection) (`me`, `human`, `bot`, `agent`,
`me_agent`).

With `--format json` the output is one object with these top-level keys, in this
order. It has no `draft`, `ci`, `unresolved_threads`, `head`, `mergeable`,
`merge_state`, `review_decision`, `linked_issues`, `reviewers_truncated`,
`reviewers` or `reports`; those are PR-only. The `events` have the
[same keys as for a PR](#tkt-pr-show).

| Key | Meaning |
| --- | --- |
| `kind` | `"issue"` |
| `ref` | `owner/repo#number` |
| `title` | The issue title |
| `repo` | `owner/repo` |
| `number` | The issue number |
| `url` | The issue's web URL |
| `state` | `open` or `closed` |
| `author` | Login of the issue author |
| `created_at` | When the issue was opened (UTC, ISO-8601) |
| `closed_at` | When the issue was closed (UTC, ISO-8601); `null` while it is open |
| `last_activity` | Time of the latest event (UTC, ISO-8601) |
| `history` | The [history string](#history-strings) |
| `labels` | Label names |
| `assignees` | Assignee logins |
| `linked_pr` | One linked PR as `owner/repo#number`, or `null` if there is none. The same PR the [history string](#linked-prs) uses: the first merged one, else the first open one, else the first |
| `linked_prs` | Every linked PR as `{"ref", "state"}`, with a lowercase `state` (`open`, `merged`, `closed`) |
| `open_blockers` | Open issues that block this one, as sorted `owner/repo#number` refs; `[]` when none. One `?` for each blocker the token cannot read. See [Issue dependencies](#issue-dependencies) |
| `blocking` | Number of open issues that this issue blocks |
| `parent` | The parent issue as `owner/repo#number`, or `null` |
| `milestone` | `{"title", "due_on"}` (`due_on` is UTC ISO-8601 or `null`), or `null` without a milestone |
| `since` | The cutoff in UTC that `--since-time` set, `null` without one. The key keeps this name; it did not change with the flag |
| `timeline_truncated` | `true` when the item has more events than the fetch cap |
| `events` | The timeline, oldest first |

## `tkt pr`

List pull requests with a compact history visualization. Accepts PR refs as
arguments or piped on stdin.

```bash
tkt pr list [OWNER/REPO#NUM ...]
```

| Option | Description |
| --- | --- |
| `--author, -a USER` | Filter by author (`me` = current user; default: current user) |
| `--all-authors` | Every author's PRs in the repos from `--repo` or the board (see [Listing every author](#listing-every-author)) |
| `--reviewer, -r USER` | Filter by requested reviewer (`me` = current user) |
| `--repo OWNER/REPO` | Filter by repo (repeatable) |
| `--all, -A` | Show all states (open, merged, closed) |
| `--open, -O` | Show open PRs (default) |
| `--merged, -M` | Show merged PRs |
| `--closed, -C` | Show closed (unmerged) PRs |
| `--board, -b NAME` | Use repos from the named board |
| `--limit, -n N` | Max PRs to show (default: 100) |
| `--title, -t` | Show PR titles |
| `--graph, -g` | Weekly merge/age graph (use with `--merged`) |
| `--detail` | Add **Head**, **Review** and **Merge** columns: the 7-character head commit, GitHub's review decision (`approved`, `changes`, `required`, `--`) and merge state (`clean`, `behind`, `dirty`, `blocked`, `unstable`, …). Off by default so the table stays narrow. With `--diff` / `--watch` the columns are in the diff table too (see [Head, review and merge changes](#head-review-and-merge-changes)) |
| `--reviewers` | Add a **Reviewers** column with one count per [reviewer state](#reviewer-state), e.g. `✓2 ✗1 •1`, and a legend under the table. Off by default so the table stays narrow |
| `--reviewer-names` | Like `--reviewers`, but names each reviewer: `all-hands-bot✓ bob↻` |
| `--steps` | Add a **Steps** column, one character per [step](#tkt-pr-steps) (review, CI, findings, re-review, manual test, test findings, retest), and a legend under the table. A done step is `✓` and an n/a step is `·`; the legend says that only those two (`✓✓✓✓✓✓✓`) means every step is done or n/a, so nothing is pending. Off by default so the table stays narrow. The cell is always the full 7 characters; on a narrow terminal Repo and History give up width instead. The column is all `--steps` does: snapshots (`--snapshot`, `--watch`) and `--format json` always record the statuses, so `--diff` / `--watch` with `--format json` report a step that moved without it. The default diff table marks the row and adds a Note for a step transition only with `--steps`. A plain table without `--steps` makes no step-related requests |
| `--events {brief,full,none}` | With `--diff` / `--watch` and `--format json`: how much of each added or changed PR's new timeline events the delta carries (default `brief`). See [Events and steps in a PR diff](#events-and-steps-in-a-pr-diff) |
| `--max-body N` | With `--events brief`: cut each event body at `N` characters instead of 160 |
| `--created-since DAYS` | Only PRs created since the start of the UTC day N days ago (`0` = today) |
| `--created-after YYYY-MM-DD`, `--created-before YYYY-MM-DD` | Only PRs created on/after, on/before this UTC date (inclusive) |
| `--updated-since DAYS`, `--updated-after YYYY-MM-DD`, `--updated-before YYYY-MM-DD` | The same, on the last-updated date |
| `--closed-since DAYS`, `--closed-after YYYY-MM-DD`, `--closed-before YYYY-MM-DD` | The same, on the close date. Needs `--closed`, `--merged` or `--all` |
| `--merged-since DAYS`, `--merged-after YYYY-MM-DD`, `--merged-before YYYY-MM-DD` | The same, on the merge date. Needs `--merged` or `--all` |


```bash
tkt pr list --author me                     # your open PRs
tkt pr list --merged --graph                # merge cadence graph
tkt pr list octocat/hello-world#7           # a specific PR
tkt pr list --author ak684 --merged --merged-since 14   # merged in the last 2 weeks
tkt pr list --created-since 7                    # opened this week
tkt pr list --board oh --all-authors --watch factory   # everyone's open PRs, diffed
```

Also accepts `--snapshot`, `--diff`, `--watch` for change-since-last-run
output — see [Snapshots & diffs](#snapshots--diffs).

`--format json` prints the current result as one JSON document instead of the
table, the same document `tkt snapshot show KIND/NAME --format json` prints,
with `snapshot` present only for a named snapshot. See
[`--format json` on list commands](#--format-json-on-list-commands).

See [Date-window filtering](#date-window-filtering) for the semantics of the
`--created-*` / `--updated-*` / `--closed-*` / `--merged-*` flags.

### Effective filters line (`tkt pr list`)

A plain `tkt pr list` prints a `History:` [legend](#history-strings) under the table
(then the `Reviewers:` and `Steps:` legends when those columns are on), and one
`Filters:` line after them, before the `Showing N of M` footer and the `Window:` line, naming every filter in effect,
defaults included. An empty result prints `No PRs found.` and then the same line.

```
Filters: author=octocat (you) · state=open · repos=all GitHub · limit=100
```

| Field | Value |
| --- | --- |
| `author` | The login, with `(you)` when it is the current user (the default or `me`); `all authors` with `--all-authors` |
| `reviewer` | With `--reviewer`, in place of `author`: the login, with `(you)` for `me` |
| `state` | The states joined with `+`, in the order `open`, `merged`, `closed`: `open`, `merged`, `open+merged+closed`, … |
| `repos` | `--repo` values, the board's repos (comma-joined), or `all GitHub` |
| `limit` | `--limit` (default 100) |

`--reviewer` runs a different search: open PRs with a review requested from that
user. It ignores `--author`, `--merged` and `--closed`, so its
line always shows `reviewer=… · state=open`. With explicit refs the line is
`Filters: refs=N`. The line does not repeat the date window; that stays on the
`Window:` line. `--diff`, `--watch`, `--snapshot` and `--format json` do not
print it. When stdout is not a terminal the line is never wrapped.

### `tkt pr checks`

Explain a `red` CI column: list the failing checks on one PR's head commit,
the step that failed, and either a link to the log or the log itself. Exactly
one of `--short` or `--full` is required.

```bash
tkt pr checks OWNER/REPO#NUM --short
tkt pr checks OWNER/REPO#NUM --full [--tail N]
```

| Option | Description |
| --- | --- |
| `--short` | One tab-separated line per failing check: `check<TAB>failing step<TAB>log URL` |
| `--full` | Per failing check: name, failing step, and that step's log |
| `--tail N` | With `--full`, keep only the last N log lines per check (default: 100, `0` = all); must be `>= 0` and is not allowed with `--short` |

The ref may be `owner/repo#number` or a GitHub PR URL. Output starts with a
header line (`owner/repo#7 red 2 failing`, or `... green no failing checks`).

```
$ tkt pr checks OpenHands/OpenHands-Cloud#1340 --short
OpenHands/OpenHands-Cloud#1340 red 1 failing
helm-unittest	Run chart unit tests	https://github.com/OpenHands/OpenHands-Cloud/actions/runs/37048045617/job/110974244953
```

```text
$ tkt pr checks OpenHands/OpenHands-Cloud#1340 --full --tail 5
OpenHands/OpenHands-Cloud#1340 red 1 failing

== helm-unittest :: Run chart unit tests
... 147 earlier lines omitted (--tail 0 for all)
Snapshot:    0 passed, 0 total
Time:        3.601522531s

Error: plugin "unittest" exited with error
##[error]Process completed with exit code 1.
```

Notes:

- Unlike `tkt pr list`, this command takes exactly one PR ref and does not read
  refs from stdin.
- Only the newest run of each check (per workflow) is considered, so failures
  superseded by a re-run are not reported.
- A check counts as failing when it concluded `FAILURE`, `TIMED_OUT`,
  `STARTUP_FAILURE` or `CANCELLED`, or an external commit status is
  `FAILURE`/`ERROR`.
- The failing step and `--full` logs exist only for GitHub Actions checks.
  External checks (CircleCI, Jenkins, ...) show `--` for the step and their
  own details URL; `--full` prints a "no log available" line for them.
- Step logs are cut out of the job log by the step's start/end time (second
  resolution), so the first lines may belong to the previous step. The log is
  trimmed after the step's last `##[error]` line, and timestamps and ANSI colour
  codes are stripped.
- Downloading logs needs access to Actions logs (`actions: read`); if GitHub
  refuses or the log has expired, the check is still listed with
  `(log unavailable: HTTP <status>)`.
- The check list is fetched in a single GraphQL request. If the token cannot
  read some check fields on the repo (typically a GitHub App token without
  checks access, reported as `Resource not accessible by integration`), the
  command exits 1 with that error rather than showing a partial list.

### `tkt pr changes`

Answer "has the code changed in a way that matters since commit X?", for example
to decide whether a manual test report posted against X still holds.

```bash
tkt pr changes OWNER/REPO#NUM --since-sha SHA [--format text|json]
    [--ignore-path GLOB ...] [--min-changed-lines N] [--explain]
```

| Option | Description |
| --- | --- |
| `--since-sha SHA` | Required. The commit to compare from: a commit SHA of 7 to 40 hex characters, in either case. A branch name or tag is rejected, because a branch tip moves and the verdict could not be repeated; resolve it to a SHA first |
| `--format` | `text` (default) or `json`; with `json`, stdout is only the JSON document |
| `--ignore-path GLOB` | Drop changed files matching `GLOB` (repeatable; `*` stays in one path segment, `**` crosses segments). Replaces the norms file's `ignore_paths` |
| `--min-changed-lines N` | After ignoring paths, changes below `N` added+deleted lines are not significant. `0` counts as given and replaces the norms file's value |
| `--explain` | After the verdict, print one `why:` line per setting with its value and source |

The 1.x spelling of `--since-sha` was removed in 2.0; see [Upgrading to 2.0](#upgrading-to-20).

Where the settings come from: per setting, a flag beats `[commits]`
(`ignore_paths`, `min_changed_lines`) in the repo's `.agents/tickster.toml`, which
beats the default (no ignored paths, `0`). `--ignore-path` replaces the file's list;
it does not add to it. A flag for one setting leaves the other coming from the file.
The file is read from the default branch, and only when a setting was not given as a
flag. With no norms file, or one tickster cannot read, the defaults apply. `tkt pr
steps` reads the same `[commits]` values, so both commands give the same verdict.

It makes one REST compare call (`SHA...head`, plus further pages for very large
ranges). When that range holds a merge commit it makes one more (`base...head`, the
commits the PR itself carries) to tell which commits a merge brought in from the
base branch. It prints a summary line, a verdict, the `why:` lines with `--explain`,
then one tab-separated line per
commit (`commit<TAB>sha<TAB>merge|base|--<TAB>author<TAB>headline`; `merge` is a
merge commit, `base` a commit reachable from the base branch that a merge brought
in) and per file
(`file<TAB>status<TAB>+added<TAB>-deleted<TAB>ignored|--<TAB>path`). With
`--format json` the document has a `settings` object: `ignore_paths`,
`min_changed_lines` and `sources` (the source of each: `--ignore-path`,
`--min-changed-lines`, `.agents/tickster.toml` or `default (no norms file)`).

```text
$ tkt pr changes OWNER/REPO#NUM --since-sha SHA --explain
...
significant: no (all 1 changed files match ignore_paths)
  why: ignore_paths = [doc/**] (.agents/tickster.toml)
  why: min_changed_lines = 0 (.agents/tickster.toml)
```

```text
$ tkt pr changes jpshackelford/tickster#60 --since-sha 75d1faa --ignore-path 'doc/**' --ignore-path '**/*.md'
jpshackelford/tickster#60 75d1faa..742dbea 1 commits 4 files +104 -4
significant: yes (4 files, 108 changed lines)
commit  742dbea --      openhands-agent fix(issue): default 'issue list' to open issues
file    modified        +0      -1      --      src/__main__.py
file    modified        +2      -1      --      src/issue/cli/list_cmd.py
file    modified        +7      -2      --      src/snapshot/models.py
file    added   +95     -0      --      tests/snapshot/test_issue_default_state.py
```

The example uses a merged PR, whose head is fixed, and `75d1faa`, the `main`
commit it branched from, so it reproduces. No file matched `--ignore-path` here.

Verdict rules, in order:

- `significant: yes (history rewritten)`: a well-formed `SHA` that GitHub does
  not know (it is gone from the history after a force-push) or the range is
  diverged or behind.
- `significant: yes (too large to inspect)`: the range needs more than 10 pages.
- `significant: no`: nothing changed, or every commit is a merge commit (two or
  more parents) or a `base` commit, or no files remain after `--ignore-path`, or
  the remaining lines are below `--min-changed-lines`. A merge-from-base commit
  alone is `no`, however much the base brought in.
- Otherwise `significant: yes`. Without `--ignore-path`, `--min-changed-lines` and
  `[commits]` norms every change the PR itself authored is significant.

Notes:

- The file list is the net diff of the range. When a range holds a merge-from-base
  commit and a real commit, files the merge brought in are counted too, so the
  verdict can only over-report. Use `--ignore-path` or `--min-changed-lines` to
  discount them.
- The `base` marker comes from the PR's current base branch. If the base branch
  was rewound, a commit it no longer holds counts as the PR's own.
- If `base...head` is too large to read (more than 10 pages), the verdict is
  `yes (too large to inspect)`.
- A pipe closed by the reader (`tkt pr changes ... | head -1`) ends quietly with
  exit code 141, without a traceback.
- The exit code is 0 whether or not the change is significant; errors exit 1.
  A malformed `--since-sha` (not 7 to 40 hex characters, so also any branch or tag)
  exits 2 with `Error: --since-sha needs a commit SHA` on stderr, empty stdout, and
  no GitHub call.
- The command is also a library function, `src.pr.changes.pr_changes`.

### `tkt pr steps`

For each PR, say which follow-up steps still need to happen, and why. It states
what is pending, not which step comes first: order is policy, and it belongs to
the consumer. Four steps (review, CI, findings, re-review) come from GitHub's own
data. Three more per `[reports.<name>]` come from the repo's [norms](#tkt-norms):
write the report, address what it found, and redo it after a significant change.

```bash
tkt pr steps REF... [--format text|json] [--explain]
```

| Option | Description |
| --- | --- |
| `REF...` | PR refs, `owner/repo#number` or a PR URL |
| `--format text\|json` | Text (default) or JSON. JSON is the only thing on stdout; notices and errors go to stderr |
| `--explain` | Add why each rule fired: the settings used and the facts compared |

Text gives the PR, then one line per step: the status, then the evidence in a few words.

```
OpenHands/software-agent-sdk#6338
  review the PR: done — enyst COMMENTED on 0945b15
  fix CI: done — checks passed on head e66822d
  address review findings: done — no unresolved threads, no changes requested
  request re-review: needed — enyst COMMENTED on 0945b15, head is e66822d, no pending request
  manually test: not configured — no .agents/tickster.toml on the default branch
  address test findings: not configured — no .agents/tickster.toml on the default branch
  retest after a fix: not configured — no .agents/tickster.toml on the default branch
```

JSON is a list with one object per PR: `{"pr": "owner/repo#N", "steps": [...]}`. Each
step is `{"step", "status", "evidence"}`; `evidence` is a list of `{"kind", "text"}` with
a `ref` (the login, commit or check it is about) when there is one. `--explain` adds an
`explain` list to each step.

| Status | Meaning |
| --- | --- |
| `needed` | The author's side has to act |
| `waiting` | Someone else has to act: a requested reviewer, or running CI |
| `done` | The step is satisfied |
| `n/a` | The step does not apply. Every step is `n/a` on a merged or closed PR |
| `not configured` | The step depends on a [norms](#tkt-norms) setting the repo does not have: no norms file, or no `[reports.manual_test]`. The four GitHub-only steps never use it |
| `unknown` | Facts are missing or uncertain, for example no checks yet while mergeability is still `UNKNOWN` |

| Step | `needed` | `waiting` | `done` | `n/a` |
| --- | --- | --- | --- | --- |
| `review the PR` | No counted reviewer has reviewed, and none is requested | A counted reviewer is requested and has not reviewed since | A counted reviewer has reviewed (any state except dismissed) | Draft PR |
| `fix CI` | The check rollup failed, after dropping `[ci] ignore_checks` | Checks pending | Checks passed | No checks |
| `address review findings` | An unresolved review thread, or a counted reviewer's latest review is `CHANGES_REQUESTED` | | Neither | No reviews |
| `request re-review` | A counted reviewer's latest review is on an older head and no request is pending | A re-request is pending, or a `[review] rerequest_labels` label is on the PR | Every counted reviewer's latest review is on the head | No reviews |

#### Report steps

A report is a comment whose first 200 characters match `[reports.<name>].marker`.
The latest one is "the report"; the head when it was posted is "the tested commit".
`manual_test` always gets its three steps; any other `[reports.<name>]` adds three
more after them, in file order. `tkt` never hard-codes a report's wording or when it
is required: the norms say so, and without them the `manual_test` steps are `not
configured`.

| Step | `needed` | `done` | `n/a` |
| --- | --- | --- | --- |
| `manually test` | `required = true`, no report, and `only_paths` is empty or matches a file the PR changes | A report exists | No report and `required = false`, or no report and `only_paths` matches nothing the PR changes |
| `address test findings` | The latest report matches `fail` | The latest report does not match `fail` (a report with no `fail` pattern never fails) | No report |
| `retest after a fix` | The report is older than the head, a [significant change](#tkt-pr-changes) happened since the tested commit, and nothing waives it | The report is on the head, or no significant change since the tested commit, or it is waived | No report |

A significant change is judged as in `tkt pr changes --since-sha <tested commit>`, with the
repo's `[commits] ignore_paths` and `min_changed_lines`. So a docs-only push leaves
`retest after a fix` at `done`, and a push that touches code makes it `needed`.

**Waiver.** An `impact_line` comment waives the change when all of these hold:

- it matches `[reports.<name>.impact_line].pattern`, and what the pattern captures (its
  first group, or the whole match when it has none) says `none`;
- it was posted after the change: its head is the PR's current head, or a commit at or
  after the last commit of the PR's own in the range;
- its author is in `from`: `agents`, `humans`, `bots` (by [actor class](#ai-actors)) or
  `author` (the PR's author).

The latest such comment decides. One that says `rerun` keeps the step `needed`. A line
from someone not in `from`, or posted before the change, is ignored. When no line covers
the change, `unassessed` decides: `rerun` makes the step `needed`, `ignore` makes it
`done`. With no `impact_line` configured nothing waives a change.

Three situations give `unknown` instead of a guess: the timeline is longer than the fetch
cap (a newer report may be missing), the commit a report was posted on can't be found in
the timeline, and facts that could not be read.

The report steps cost extra requests only when they must: one `compare` for each
distinct tested commit that is older than the head (plus a second when that range holds a
merge commit), and the PR's file list only when a required report with `only_paths` has
not been written yet.

#### Notes

- A reviewer is counted when their [actor class](#ai-actors) is in `[review]
  count_reviews_from` (`humans`, `agents`, `bots`; a team counts as `humans`). Without
  a norms file that is `humans` and `agents`, and no agents are known, so only humans count.
  `agents` come from `[actors] agent_logins`.
- `[ci] ignore_checks` globs are matched against each check's name. Only when a repo
  sets them, and the rollup is failing or pending, does `tkt` read the PR's individual
  checks (one extra request per such PR).
- Not detected: findings left in a review summary or a plain comment instead of a thread.
- `fail` and `impact_line` patterns, like `marker`, read only the first 200 characters of a
  comment ([`tkt norms`](#tkt-norms)). Put a report's verdict near the top.
- `tkt pr list` records the statuses in every snapshot (`--snapshot`, `--watch`) and in
  `--format json`, with or without `--steps`; `--steps` only adds the table column. With
  `--diff` / `--watch` and `--format json`, a step that moved is in `step_changes` and
  `changed_fields` (`step_status`): `request re-review: done → needed`. In the diff table the
  move marks the row `*` and adds that Note only with `--steps`. Every step is recorded,
  including other reports' steps. A step missing from the baseline is skipped.
- `tkt pr list --steps` shows one character per step, in this order: `r` review, `c` CI,
  `f` findings, `a` re-review, `m` manual test, `t` test findings, `x` retest. Uppercase is
  `needed`, lowercase `waiting`, `✓` done, `·` `n/a`, `?` unknown, `-` not configured.
  `R·F····` = review needed and findings to address, the other five steps are `n/a` (for
  example no re-review or report yet); `✓✓✓✓M--` = the first four steps are done and the
  manual test report is missing. A report other than `manual_test` has no column; see it with `tkt pr steps`.
- The exit code is 0 whatever the statuses are; errors (a PR that is not found) exit 1.
- `--explain` adds, for each report step, the marker and how many comments it matched, the
  latest match (author, time, tested commit), `fail` and `impact_line` settings and what
  each impact line did, and the commits and files that made the change significant (first
  10 files; `and N more`) or the ignored ones.
- On a merged or closed PR every step, report steps included, is `n/a`.
- The command is also a library function, `src.pr.steps.evaluate_steps`.

### `tkt pr show`

Read one PR: a header and its timeline, oldest first, with the text of comments,
reviews and review threads. Use it after `tkt pr list` or `tkt review` shows a PR
you need to read, or from a polling loop to read only what is new.

```bash
tkt pr show OWNER/REPO#NUM [--since-time TS]
    [--max-body N] [--format text|json]
```

| Option | Description |
| --- | --- |
| `--since-time TS` | Only events after this ISO-8601 time, e.g. `2026-11-05T10:00:00Z`. A date or a time with no zone is UTC |
| `--max-body N` | Trim each comment, review or thread-comment body to its first `N` characters (default: 600, `0` = no trimming). `N` counts the body only; a trimmed body ends with an extra `…(K more chars)` suffix |
| `--format` | `text` (default) or `json`; with `json`, stdout is only the JSON document |

The ref may be `owner/repo#number` or a GitHub PR URL.

The 1.x spelling of `--since-time` was removed in 2.0; see
[Upgrading to 2.0](#upgrading-to-20).

```text
$ tkt pr show jpshackelford/tickster#60 --max-body 40
jpshackelford/tickster#60 pr merged ready ci:green 💬0 "fix(issue): default `issue list` to open issues"
history: sVnm
author: jpshackelford  created: 2026-11-05T10:28:10Z  last activity: 2026-11-05T10:45:37Z
head: 742dbea  mergeable: unknown  merge: unknown  review: approved
reviewers: github-actions(agent) ✓ approved on head
linked issues: jpshackelford/tickster#49
reports: manual_test 2026-11-05T10:37:08Z by jpshackelford at 742dbea (on head) no fail match
Legend: the letter is the event's history character (lowercase = you, UPPERCASE = others; AI letters: lowercase = your login, UPPERCASE = its own login; - = not in the history string). o opened, s AI opened, h review requested, r changes or inline review, e AI review, a approved, v AI approval, c comment, n AI comment, f push after a review, m merged, k closed. Class: me human bot agent me_agent. ↳ marks a review thread: path:line, resolved or unresolved.
timeline: 5 events, oldest first
2026-11-05T10:27:37Z - openhands-agent(agent) pushed 1 commit, last 742dbea "fix(issue): default 'issue list' to open issues"
2026-11-05T10:28:10Z s jpshackelford(me_agent) opened: Fixes #49 ## Why `tkt issue list` with…(2537 more chars)
2026-11-05T10:33:56Z V github-actions(agent) approved on head: **Correctness verified.** The fix proper…(1269 more chars)
2026-11-05T10:37:08Z n jpshackelford(me_agent) commented: ## Manual Test Results for PR #60 _This…(7375 more chars)
2026-11-05T10:45:37Z m jpshackelford(me) merged
```

The example uses a merged PR, so it reproduces; the `more chars` counts and
`last activity` change if someone adds to the PR. `github-actions` shows as `agent`
because this repo lists it in `[actors] agent_logins`: GitHub's GraphQL API gives that
account without a `[bot]` suffix, and its reviews are AI reviews. Without the entry it
would show as `human`.

Header lines: state, draft or ready, CI (`ci:green|red|pending|--`), unresolved
review threads (`💬N`); the [history string](#history-strings); author and dates;
head commit, mergeability, merge state and review decision; each reviewer with
their [reviewer state](#reviewer-state); linked issues; and one `reports:` entry
per `[reports]` marker in the [norms file](#tkt-norms) (when the repo has one),
saying whether the latest matching comment was posted on the current head.

Timeline lines are `time char actor(class) text`, as in
[`tkt issue show`](#tkt-issue-show). Review threads print under their review as
`↳ path:line [resolved|unresolved]`, one indented line per comment.
Each body is flattened to one line, so a long comment cannot break the
line-per-event layout.

`--since-time` keeps events strictly after the cutoff, and keeps
an older review if one of its thread comments is newer. With nothing new, the
output is the header and `no new events since <time>`. The cutoff is printed in
UTC. To read only what changed since the last poll, use the `prev.last_activity`
of the changed row in the [diff](#snapshots--diffs) JSON as the cutoff:

```bash
tkt pr show jpshackelford/tickster#60 --since-time 2026-11-05T10:35:00Z
```

JSON output (`--format json`) is one object with these top-level keys, in this
order:

| Key | Meaning |
| --- | --- |
| `kind` | `"pr"` |
| `ref` | `owner/repo#number` |
| `title` | The PR title |
| `repo` | `owner/repo` |
| `number` | The PR number |
| `url` | The PR's web URL |
| `state` | `open`, `merged` or `closed` |
| `draft` | `true` while the PR is a draft |
| `author` | Login of the PR author |
| `labels` | Label names |
| `created_at` | When the PR was opened (UTC, ISO-8601) |
| `last_activity` | Time of the latest event (UTC, ISO-8601) |
| `history` | The [history string](#history-strings) |
| `ci` | `green`, `red`, `pending`, `conflict` or `--` (none) |
| `unresolved_threads` | Number of unresolved review threads |
| `head` | SHA of the head commit |
| `mergeable` | GitHub's value, as is: `MERGEABLE`, `CONFLICTING` or `UNKNOWN` |
| `merge_state` | GitHub's merge state status, as is, e.g. `CLEAN` or `BLOCKED` |
| `review_decision` | GitHub's review decision, as is: `APPROVED`, `CHANGES_REQUESTED` or `REVIEW_REQUIRED`; `null` when the repo does not require reviews |
| `reviewers_truncated` | `true` when the reviewer list hit the fetch cap, so some reviewers are missing. The text output marks this with a trailing `…` on the `reviewers:` line |
| `linked_issues` | Issues the PR closes, as `owner/repo#number` strings |
| `reviewers` | One object per reviewer, with the fields of the [reviewer state](#reviewer-state) (`login`, `actor_class`, `requested`, `latest_state`, `on_head`, `waiting`, `rereview_needed` and more) |
| `reports` | One object per `[reports]` marker: `name`, `found`, `at`, `actor`, `head`, `on_head`, `failed` |
| `since` | The cutoff in UTC that `--since-time` set, `null` without one. The key keeps this name; it did not change with the flag |
| `timeline_truncated` | `true` when the item has more events than the fetch cap |
| `events` | The timeline, oldest first |

Each object in `events` has these keys:

| Key | Meaning |
| --- | --- |
| `at` | When the event happened (UTC, ISO-8601) |
| `kind` | What happened, e.g. `opened`, `comment`, `review`, `merged` |
| `char` | The event's [history](#history-strings) character, `-` if the history string leaves it out |
| `actor` | Login of the person or bot that did it |
| `actor_class` | `me`, `human`, `bot`, `agent` or `me_agent` |
| `text` | The one-line description shown in the text output |
| `body` | The comment, review or opening post, trimmed by `--max-body`; `null` if there is none |
| `more_chars` | Characters cut by `--max-body` (`0` if none) |

Some events add keys of their own, e.g. `reviewer` for a review request, `head`
for a force push, `state`, `commit` and `on_head` for a review. A review with threads also
has `threads`: a list of `path`, `line`, `resolved`, `outdated` and `comments`
(each with `at`, `actor`, `actor_class`, `body` and `more_chars`).

```bash
tkt pr show jpshackelford/tickster#60 --format json | jq '.events[] | select(.kind == "merged") | .at'
```

Notes:

- Unlike `tkt pr list`, this command takes exactly one ref and does not read
  refs from stdin.
- Errors (bad ref, bad time, unknown snapshot, no such item) print
  `Error: ...` on stderr and exit 1. An invalid option combination exits 2.
- If the item has more events than the fetch cap, the text output says
  `(timeline truncated: ...)` and JSON has `"timeline_truncated": true`.

## `tkt review`

Show PRs from a reviewer's perspective. By default shows only PRs that need
your review action.

```bash
tkt review [options]
```

| Option | Description |
| --- | --- |
| `--all, -A` | Include approved and on-hold PRs (default: only actionable) |
| `--reviewer, -r USER` | Review queue for a specific user (default: current user) |
| `--author USER` | Filter by PR author |
| `--exclude-author, -X USERS` | Comma-separated authors to exclude (e.g. `dependabot[bot],renovate[bot]`) |
| `--repo OWNER/REPO` | Filter by repo (repeatable) |
| `--board, -b NAME` | Use repos from the named board |
| `--limit, -n N` | Max PRs to show (default: 100) |
| `--title, -t` | Show PR titles |
| `--merged, -M` | Show merged PRs you've reviewed |
| `--closed, -C` | Show closed (unmerged) PRs you've reviewed |
| `--created-since DAYS` | Only PRs created since the start of the UTC day N days ago (`0` = today) |
| `--created-after YYYY-MM-DD`, `--created-before YYYY-MM-DD` | Only PRs created on/after, on/before this UTC date (inclusive) |
| `--updated-since DAYS`, `--updated-after YYYY-MM-DD`, `--updated-before YYYY-MM-DD` | The same, on the last-updated date |
| `--closed-since DAYS`, `--closed-after YYYY-MM-DD`, `--closed-before YYYY-MM-DD` | The same, on the close date. Needs `--closed` or `--merged` (merged PRs are closed) |
| `--merged-since DAYS`, `--merged-after YYYY-MM-DD`, `--merged-before YYYY-MM-DD` | The same, on the merge date. Needs `--merged` |

`--all` / `-A` (include approved and on-hold PRs) is not a state flag: it does not satisfy the `--merged-*` or `--closed-*` checks.

```bash
tkt review                                  # your actionable review queue
tkt review --all --title                    # full queue with titles
tkt review -X "dependabot[bot]"             # hide dependabot PRs
tkt review --merged --merged-since 7        # PRs you reviewed that merged this week
tkt review --created-since 14               # review requests on PRs opened in the last 2 weeks
tkt review --closed --closed-since 7        # closed (unmerged) PRs you reviewed, closed this week
```

See [Date-window filtering](#date-window-filtering) for the semantics of the
`--created-*` / `--updated-*` / `--closed-*` / `--merged-*` flags.

The output computes, for each PR, **what action you owe it** rather than dumping
raw review state:

- **Status**
  - `review` — initial review requested, you have not reviewed yet
  - `re-review` — new commits were pushed after your last review
  - `hold` — you requested changes, waiting on the author (no new commits)
  - `approved` — you approved, no action needed
- **Wait** — how long the PR has been waiting for action, colour-coded: red
  above 48h, yellow above 24h, default below 24h.
- **CI** — `green` / `red` / `pending` / `conflict`.
- **💬** — count of unresolved review threads.

By default only actionable PRs (`review`, `re-review`) are shown; `--all`
includes `hold` and `approved`.

Also accepts `--snapshot`, `--diff`, `--watch` for change-since-last-run
output — see [Snapshots & diffs](#snapshots--diffs).

`--format json` prints the current result as one JSON document instead of the
table, the same document `tkt snapshot show KIND/NAME --format json` prints,
with `snapshot` present only for a named snapshot. See
[`--format json` on list commands](#--format-json-on-list-commands).

### Effective filters line (`tkt review`)

A plain `tkt review` prints a `History:` [legend](#history-strings) naming the
reviewer, and one `Filters:` line under the table and that legend,
before the `Showing N PRs …` footer and the `Window:` line. An empty result
prints its message (`No PRs needing your review.`) and then the same line, so
you can tell an empty queue from a mis-scoped one.

```
Filters: reviewer=octocat (you) · show=actionable · state=open · repos=all GitHub · limit=100
```

| Field | Value |
| --- | --- |
| `reviewer` | The queue's owner: the login with `(you)` by default, plain with `--reviewer USER`. `--reviewer me` prints `me` |
| `author` | Only with `--author` |
| `exclude` | Only with `--exclude-author`: the logins, comma-joined |
| `show` | `actionable` by default; `all` with `--all` (approved and on-hold PRs included) |
| `state` | `open` by default; `merged`, `closed` or `merged+closed` with `--merged` / `--closed` (no `open` then) |
| `repos` | `--repo` values, the board's repos (comma-joined), or `all GitHub` |
| `limit` | `--limit` (default 100) |

The line does not repeat the date window; that stays on the `Window:` line.
`--diff`, `--watch`, `--snapshot` and `--format json` do not print it. When
stdout is not a terminal the line is never wrapped.

## `tkt board`

Manage a GitHub Project board used to track development workflow.

```bash
tkt board <subcommand> [options]
```

| Subcommand | Description |
| --- | --- |
| `list` | List all configured boards |
| `init` | Initialize or configure a GitHub Project board |
| `scan` | Scan repos for issues/PRs and add them to the board |
| `sync` | Sync the board with GitHub state (incremental) |
| `status` | Show current board status |
| `config` | View and manage board configuration |
| `apply` | Apply a YAML board configuration |
| `templates` | List available built-in templates |
| `macros` | List available macros for rule conditions |
| `add-item` | Manually add issues/PRs to the board |
| `sync-config` | Sync board configuration with a GitHub Gist |
| `rename` | Rename a board |
| `rm` / `delete` | Delete a board |

Common flags on the data subcommands: `--board NAME` (target board, default:
default board), `--dry-run, -n` (preview), `--verbose, -v`.

```bash
tkt board init --create "Team Workflow"     # create a new project board
tkt board scan --user octocat --updated-since 30    # discover recent activity
tkt board sync                              # incremental sync
tkt board status --attention                # only items needing attention
tkt board status --json                     # machine-readable status
tkt board add-item octocat/hello-world#42   # add an item
```

Boards auto-organise items into workflow columns based on their state
(Icebox → Backlog → Agent Coding → Human Review → Agent Refinement →
Final Review → Approved → Done / Closed). For the full board reference —
scopes, column assignment rules, YAML configuration, macros, gist sync, and
config/cache locations — see **[doc/board.md](board.md)**.

## `tkt repo`

Manage the repositories tracked by a board.

```bash
tkt repo add OWNER/REPO [OWNER/REPO ...] [--board NAME] [--set-default]
tkt repo remove OWNER/REPO [OWNER/REPO ...] [--board NAME]
tkt repo list [--board NAME] [--all]
```

```bash
tkt repo add octocat/hello-world -b team    # track a repo on board "team"
tkt repo add octocat/spoon-knife -d         # add and set board as default
tkt repo list --all                         # repos across all boards
```

## `tkt norms`

A repo's conventions live in `.agents/tickster.toml`, committed to the repo. tickster
keeps only GitHub's own meanings in code; who counts as an agent or a bot, how a test
report is recognised, and which checks to ignore are data the repo owns.

```bash
tkt norms init [--from SOURCE [--ref REF] [--path PATH]] [--force]
tkt norms check [PATH | --repo OWNER/NAME] [--strict]
tkt norms show --repo OWNER/NAME
tkt norms upgrade [PATH] [--write]
```

- `init` writes `.agents/tickster.toml` at the root of the current git work tree. With
  no `--from` it writes a neutral, self-documenting template. It refuses to overwrite a
  file unless you pass `--force`, exits non-zero outside a git work tree, and never
  commits or pushes. Commit it and merge it to the default branch; it takes effect
  from there.
- `init --from SOURCE` copies another file (never a live reference). `SOURCE` is:
  - `github:owner/repo[/path]`: read through the GitHub API with your token, so private
    repos work. Without `/path` it reads `.agents/tickster.toml`.
  - a git URL (`https://`, `ssh://`, `git://`, `file://` or scp-style
    `git@host:org/repo.git`): fetched with your own `git`, so SSH keys, credential
    helpers and proxies apply. Other transports are refused. Use `--path` for a file
    other than `.agents/tickster.toml`.
  - a local file, or a directory holding `.agents/tickster.toml`.
  - `--ref` picks a branch, tag or commit for `github:` and git URLs.
  The copy starts with a header naming the source (credentials removed), the path and
  the commit read. A source with an older schema is migrated; a source with a newer
  schema is refused. Afterwards `init` warns about `ignore_paths` / `only_paths` globs
  that match nothing in your tree.
- `check` validates the file: schema, types, unknown keys and every regex. Problems name
  the file and the key. `--strict` turns the unknown-key warning into an error.
- `show` prints the settings in effect for a repo and the blob SHA of the file read.
- `upgrade` prints the file migrated to the current schema; `--write` rewrites it
  (comments are not preserved).

### The file

```toml
schema = 1                                # required integer

[actors]
agent_logins = ["all-hands-bot"]          # AI actors; globs; win over the [bot] suffix
agent_disclosure = 'created by an AI agent \(OpenHands\)'
bots = []                                 # non-AI automation without a [bot] suffix

[labels]
stale = ["stale"]                         # closed_by_bot; this is the fallback; [] disables
rank = ["priority:critical", "priority:high", "priority:low"]  # issue list --sort rank; best first

[review]
count_reviews_from = ["humans", "agents"] # humans | agents | bots
rerequest_labels = ["review-this"]

[ci]
ignore_checks = ["codecov/*"]

[commits]
ignore_paths = ["docs/**", "**/*.md"]
min_changed_lines = 0

[reports.manual_test]                     # any [reports.<name>] table works
required = true
only_paths = []
marker = '^#+ *Manual Test Results'
fail = '❌ *FAIL'

[reports.manual_test.impact_line]
pattern = 'manual[- ]test impact:\s*(none|re-?run)'
from = ["agents", "author"]
unassessed = "rerun"                      # or "ignore"
```

- Patterns are Python regexes, matched case-insensitively against the first 200
  characters of a comment. Use single-quoted strings so backslashes stay literal.
- Globs (`ignore_paths`, `only_paths`, `agent_logins`, `bots`, `ignore_checks`) use `*`
  (within one path segment) and `**` (across segments).
- tickster reads the file from the repo's **default branch** through the contents API,
  never from a PR's head, so a PR cannot change the rules that judge it. The file is
  cached under `$TKT_HOME/norms/` and re-fetched when its blob SHA changes.
- With no file, convention-based steps report "not configured"; tickster never guesses.

### Schema version

`schema` is an integer covering the whole file. It is bumped only for breaking changes
(a key renamed or removed, a key whose meaning changes, a default that changes answers);
new optional keys do not bump it.

| Situation | What happens |
|-----------|--------------|
| file older than this tkt | migrated in memory, with a warning; no commit is ever required |
| file newer than this tkt | not an error: steps that need it report `unknown (config schema N; this tkt understands M)`; GitHub-only data still answers, and `tkt pr list` / `tkt issue list` keep working |
| unknown key | warning naming the key; error with `check --strict` |
| missing or non-integer `schema`, bad TOML, wrong type, invalid regex | the file is rejected with a message naming the file and key; GitHub data alone is used |

### What uses it today

- `$has_agent_assigned` is true when an assignee matches the repo's `[actors]
  agent_logins`, which win over a board's `agent_username_pattern`. With neither, it is
  false, and a rule that needs it prints a one-time warning pointing to
  `tkt norms init --from github:jpshackelford/tickster`.
- `$closed_by_bot` also matches the `[labels] stale` labels.
- `tkt issue list --sort rank` orders issues by `[labels] rank`: a list of label names, best
  first, with no repeats (case ignored). It defaults to empty, and `--sort rank` needs it.
- `tkt pr steps` reads `[review] count_reviews_from`, `[review] rerequest_labels`,
  `[ci] ignore_checks`, `[commits]` and every `[reports.<name>]`; with no file it counts
  humans and agents, and the report steps are `not configured`.
- Bot detection for issue history is the union of the `[bot]` suffix, `[issue]
  bot_usernames` and the repo's `[actors] bots`. An account that arrives without the
  suffix must be listed (see [Bot detection](#bot-detection)).

## Upgrading to 1.0

**What changed.** The agent username pattern no longer defaults to `"openhands"`. Boards
that relied on the default lose agent detection until you set an agent setting. This is the
only breaking change in 1.0.

**Are you affected?** Yes, if you used `$has_agent_assigned` in a board rule and never set
`agent_username_pattern`. The rule stops matching, and stderr shows once per run:

```text
tkt: $has_agent_assigned is always false for OWNER/NAME: no agent setting applies. ...
```

**Fix, per repo (preferred).**

```bash
tkt norms init --from github:jpshackelford/tickster   # or plain `tkt norms init`
# edit [actors] agent_logins to your agent accounts, then commit and merge to the
# default branch: tkt reads the file from there, not from your work tree
tkt norms check
```

`init` never commits or pushes, so the fix does not take effect until the file is merged to
the default branch. The `--from` source file lists tickster's own agents (`all-hands-bot`,
`openhands-agent`); replace them with yours. Plain `tkt norms init` writes a neutral
template to fill in. See [`tkt norms`](#tkt-norms) for the file format.

**Fix, per board.**

```bash
tkt board config set agent-username-pattern openhands
```

You can also set `agent_username_pattern` in the board TOML. The repo's `agent_logins` win
over the board pattern when both are set.

**Verify.** `tkt norms check` validates the file; `tkt norms show --repo OWNER/NAME`
prints the settings in effect.

**Saved snapshots.** Recognising AI actors also changes the history string of every item
one took part in: `oAcm` from 0.3.0 reads `sVnm` now (see [AI actors](#ai-actors)). The
first `--watch` or `--diff` run against a snapshot saved by 0.3.0 reports each such row as
changed, with `history-rewritten` in `changed_fields`, and `new_history_tail` is the whole
string, not new events. Rows with no AI actor are not affected, and neither is any repo
without a norms file. A `--watch` run replaces the baseline, so the second run is clean. To
skip the report, replace the baseline once, before the first scheduled run, with the same
query and name and `--snapshot`:

```bash
tkt pr list --repo OWNER/NAME --all --snapshot NAME
```

A job that polls can also skip the deltas that have `history-rewritten` on that first run
([`doc/automation.md`](automation.md#the-recipe-poll-act-ack)).

## Upgrading to 2.0

**What changed.** The date flags used to filter on a field that tickster guessed, and two
commands used `--since` for unrelated things. In 2.0 the flag name says what it means. Each
old flag still exists as a stub that only prints an error. `--snapshot`,
`--diff` and `--watch` are unchanged.

- `issue list`, `pr list` and `review`: the date field moves into the flag name.
- `issue show` and `pr show`: `--since TS` is `--since-time TS`.
- `pr changes`: `--since SHA` is `--since-sha SHA`.
- `board scan`: `--since DAYS` is `--updated-since DAYS`.

| Command | Old (1.x) | New (2.0) | Error the old flag prints (after `tkt <cmd>: error: `) |
| --- | --- | --- | --- |
| `issue list` | `--since N` | `--created-since N`, `--updated-since N` or `--closed-since N` | `--since was removed: use --created-since N, --updated-since N or --closed-since N` |
| `issue list` | `--after D` | `--created-after D`, `--updated-after D` or `--closed-after D` | `--after was removed: use --created-after D, --updated-after D or --closed-after D` |
| `issue list` | `--before D` | `--created-before D`, `--updated-before D` or `--closed-before D` | `--before was removed: use --created-before D, --updated-before D or --closed-before D` |
| `issue list` | `--date-field F` | the field goes in the flag name | `--date-field was removed: put the field in the flag name, for example --created-since N` |
| `pr list`, `review` | `--since N` | `--created-since N`, `--updated-since N`, `--closed-since N` or `--merged-since N` | `--since was removed: use --created-since N, --updated-since N or --closed-since N (--merged-since N on pr list and review)` |
| `pr list`, `review` | `--after D` | `--created-after D`, `--updated-after D`, `--closed-after D` or `--merged-after D` | `--after was removed: use --created-after D, --updated-after D or --closed-after D (--merged-after D on pr list and review)` |
| `pr list`, `review` | `--before D` | `--created-before D`, `--updated-before D`, `--closed-before D` or `--merged-before D` | `--before was removed: use --created-before D, --updated-before D or --closed-before D (--merged-before D on pr list and review)` |
| `pr list`, `review` | `--date-field F` | the field goes in the flag name | `--date-field was removed: put the field in the flag name, for example --created-since N` (the field you typed replaces `created` when it is valid for the command) |
| `pr show`, `issue show` | `--since TS` | `--since-time TS` | `--since was removed on show: use --since-time TS` |
| `pr changes` | `--since SHA` | `--since-sha SHA` | `--since was removed on pr changes: use --since-sha SHA` |
| `board scan` | `--since DAYS` | `--updated-since DAYS` | `--since was removed: use --updated-since DAYS` |

**Are you affected?** Yes, if a script, cron job, agent prompt or board automation passes any
of the old flags. The old flags fail at parse time: exit 2, empty stdout, and no GitHub call.
A job fails loudly on its first run and never returns data from a field you did not choose.
There is no silent fallback to a default field. The stubs stay for at least one minor release
after 2.0.0. After that they are removed, and argparse reports an unrecognized argument.

**Find the callers.**

```bash
grep -rnE -- '--(since|after|before|date-field)\b' path/to/your/scripts
```

`--since-time` and `--since-sha` also match this pattern; they are the
new spellings and need no change. For the rest: a flag that took days goes to
`--<field>-since`, and a flag that took a date goes to `--<field>-after` or
`--<field>-before`. Before 2.0 the field was `--date-field`, or when you gave none, `merged`
for a `--merged`-only listing, `closed` for a `--closed`-only listing and `updated` for
everything else. A bare `--since 14` was therefore `--updated-since 14` on an open listing.

**List JSON.** `--format json` on `issue list`, `pr list` and `review`, and `tkt snapshot show
--format json`, print one compact document: `schema`, `filters`, `total_count`, `has_more`,
`items`, plus `snapshot` for a named snapshot ([`--format json` on list
commands](#--format-json-on-list-commands)). The old top-level `kind`, `name`, `captured_at`,
`scope` and `scope_hash` are gone: `scope` is `filters` (unset keys left out, and `author`
and `reviewer` are the login that was queried), and the name and capture time are under
`snapshot`. A script that reads `.scope`, `.kind` or `.name` has to change. A schema 2 file in
the old layout is not readable: it is deleted with a notice, as below.

**Saved snapshots.** The snapshot file has a new schema (2), and tkt does not read schema 1.
A snapshot or pending baseline that tkt cannot read is deleted, and tkt prints one notice on
stderr, for example `tkt: discarded snapshot issue/hourly: schema 1, this tkt writes
schema 2`. The run then goes on as a first run with no baseline: the first `--diff` or
`--watch` after upgrading reports every row as new (`baseline` is `missing` in JSON), and
`--watch` saves a schema 2 baseline. Nothing needs to be migrated or removed by hand.

**Row keys.** A row is the object for one issue, PR or review: the items of the list JSON,
of the snapshot file and the `prev` / `curr` of a diff delta. It now uses the names of
`show`, and only the keys of its kind ([Row fields](#row-fields)):

- `key` is `ref`.
- The CI key is `ci`, the draft flag is `draft`, the head commit is `head`, and the count of
  unresolved threads is `unresolved_threads`.
- In a row, `steps` is `step_status`: a map of step name to status. `pr steps` and the delta
  keep `steps` for the list with evidence.
- `events` is gone from a row. `history` has the same facts as letters, and `pr show` and
  `issue show` have the timeline.
- New: `kind`, `url`, `created_at`, and `closed_at` on an issue row and on `issue show`.
  `review` rows now carry the PR fields, so `review --diff` reports a push, a draft change
  or a reviewer move that it never saw before.

`changed_fields` in a diff uses the same names, so a scripted filter on the old head, CI or
steps name has to change to `head`, `ci` and `step_status`. The 1.x entry `activity` is now
`last_activity`.

**Diff JSON.** `--diff` and `--watch` with `--format json`, and `tkt snapshot diff --format
json`, print a document with the names of the list document ([Diff
JSON](#diff-json)). In each delta:

- `key` is `ref`.
- The old `kind` (`added`, `changed`, `removed` or `unchanged`) is now `change`.
- `kind` is new and is the kind of the row: `issue`, `pr` or `review`, as in a list row. It is
  there for all four changes.
- The top-level `prev` and `curr` have `name`, `captured_at` and `scope_hash`, and no `kind`.

A script that reads `.deltas[].key` or `.deltas[].kind` has to change: `jq 'select(.kind ==
"changed")'` is `select(.change == "changed")`, and `.key` is `.ref`. A script that is not
changed keeps running, but `.kind == "changed"` never matches.

The `since` key in `tkt pr show --format json`, `tkt issue show --format json` and
`tkt pr changes --format json` did not change.

## `tkt snapshot`

Manage saved query snapshots stored under `~/.tkt/snapshots/`. Snapshots
are the raw input to the diff view documented in
[Snapshots & diffs](#snapshots--diffs) below.

```bash
tkt snapshot list [--kind {pr,issue,review}]
tkt snapshot show KIND/NAME [--format {table,json}]
tkt snapshot rm   KIND/NAME [KIND/NAME ...]
tkt snapshot ack  KIND/NAME
tkt snapshot diff PREV CURR  [--all] [--format {table,json}] [--detail]
```

- `KIND/NAME` refs use `/` as the separator, e.g. `pr/hourly`,
  `issue/last-week`, `review/nightly`. Kind must be one of `pr`, `issue`,
  `review` — the three list commands that produce snapshots.
- Named snapshots overwrite in place; auto-timestamped snapshots (from
  bare `--snapshot`) are named `ts-YYYYMMDDTHHMMSSZ` so they coexist.
- `snapshot show` and `snapshot list` follow the same width rule as the list
  commands. Piped or redirected, the table prints at its natural width: full
  Repo, `#` and History, no `…` or `>`, no crop legend, whatever `$COLUMNS` says.
  On a terminal, `snapshot show` fits to the width (`#` and State kept whole,
  Repo gives up width first, History cropped with `>` and a one-line legend), and
  `snapshot list` prints as before. `--format json` is unchanged.
- `snapshot ack KIND/NAME` makes the result staged by the last `--diff NAME` the
  new baseline and deletes the staged file. With nothing staged it changes nothing
  and exits 1: `nothing to ack: pr/NAME has no pending baseline (run a --diff NAME first)`.
  See [Staging a baseline with `--diff`](#staging-a-baseline-with---diff).
- `snapshot list` marks a snapshot that has a staged baseline with `(pending ack)`,
  so a forgotten ack is visible. `snapshot rm` deletes the staged baseline too.

```bash
tkt snapshot list                               # all stored snapshots
tkt snapshot show pr/hourly                     # dump a snapshot as a table
tkt snapshot diff pr/hourly pr/last-week        # compare two snapshots
tkt snapshot diff pr/hourly pr/later --format json  # machine-readable
tkt snapshot rm pr/hourly issue/hourly
tkt snapshot ack pr/hourly                      # commit the baseline a --diff staged
```

---

## Snapshots & diffs

`tkt pr list`, `tkt issue list`, and `tkt review` can save their result
as a snapshot and later diff a fresh run against that snapshot. The diff
is the same dense table you already read, with two added visual channels:

- A leading **Δ** column: `+` new row, `*` changed row, `-` row that is
  gone from the current result, blank for unchanged.
- Characters appended to the history string since the previous snapshot
  are `[bracketed]` (and bold magenta in color output).
- A `!` after a value marks a field that changed. A `!` on **Last**
  (e.g. `5m ago!`) with no bracketed history means new events arrived
  but collapsed into the existing string (consecutive duplicates
  collapse), e.g. replies after your comment. In `--format json`
  this is `"last_activity"` in `changed_fields`.

A one-line summary header shows how long ago each snapshot was captured,
the counts, and whether the two snapshots were produced by the same scope
(same board, author or `--all-authors`, repos, refs, states, labels, `--not-label`, `--no-pr` / `--has-pr`, `--blocked` / `--unblocked`, `--sort`, limit). Exact capture
times are in `tkt snapshot show` and `--format json`.

```
diff pr/hourly: 1h ago → 4s ago  (+2 new, *5 changed, -1 gone, 29 unchanged)

Δ Repo                  PR     History      CI      State   💬   Last     Note
+ OpenHands/docs        #42    [oCL]        --      open    --   5m ago
* OpenHands/OpenHands   #1234  oRfA[fR]     red!    open    2    1m ago!
- OpenHands/infra       #87    oCax         --      open    --   1d ago   closed?

Δ: + new row, * changed, - gone (Note: why, `?` = a guess), (blank) unchanged.  History: [bracketed] = new since last snapshot.  Field!: value changed; prior value via `tkt snapshot diff`.  head!/review!/merge!: PR head commit, review decision or merge state changed.
```

A Note with several parts (history rewritten, `head!` tags, reviewer changes, step changes) joins them with `; `.

### Row fields

A row is the object for one issue, PR or review. It is one item in the list JSON
(`items`), in the saved snapshot file and in the `prev` and `curr` of a diff delta.
A row has the fields of its kind and no others. Every field is always present: `null`
means none and `[]` means empty. `tkt issue show` and `tkt pr show` use the same name and
value for the same fact, in `--format json`.

| Kind | Fields |
| --- | --- |
| all | `ref` (`owner/repo#N`), `kind` (`issue`, `pr` or `review`), `repo`, `number`, `url`, `title`, `state`, `author`, `labels`, `history`, `created_at`, `last_activity` (UTC, ISO-8601) |
| issue | `linked_pr`, `closed_at` (`null` while open), `open_blockers`, `blocking`, `parent`, `milestone` ([Issue dependencies](#issue-dependencies)) |
| pr | `draft`, `ci`, `unresolved_threads`, `head` (full SHA), `review_decision`, `merge_state`, `mergeable`, `reviewers` ([Reviewer state](#reviewer-state), `[]` when none), `step_status` (step name to status, or `null` when the steps were not evaluated) |
| review | the PR fields, plus `review_status` and `wait_seconds` (`step_status` is always `null`) |

`url` is `https://github.com/OWNER/REPO/issues/N` for an issue and
`https://github.com/OWNER/REPO/pull/N` for a PR or a review. `changed_fields` in a diff names
row fields, such as `last_activity`, plus the marker `history-rewritten`
([Diff JSON](#diff-json)).

### Step changes

`tkt pr list` always records each PR's [step](#tkt-pr-steps) statuses in a snapshot
(`--snapshot`, `--watch`) and prints them in `--format json`; `--steps` only adds the table
column. In `--format json` a diff lists a step that moved in `step_changes` and `step_status` in
`changed_fields`. The diff table reports the move (the `*` mark and a Note such as
`request re-review: done → needed`) only with `--steps`. Evaluating steps costs no extra
request for a repo without a [norms](#tkt-norms) file; a plain table without `--steps`,
snapshot, diff or JSON evaluates nothing.

### Head, review and merge changes

PR rows (`tkt pr list`) record four fields from GitHub: `head`
(the full head commit), `review_decision` (`APPROVED`, `CHANGES_REQUESTED`,
`REVIEW_REQUIRED`, or null), `merge_state` (`mergeStateStatus`: `BEHIND`,
`DIRTY`, `BLOCKED`, `CLEAN`, `UNSTABLE`, …) and `mergeable` (`MERGEABLE`,
`CONFLICTING`, `UNKNOWN`). A change in any of them marks the row `*`, so a push
that leaves CI, history and 💬 unchanged still shows up. The Note names what
changed:

| Note | JSON `changed_fields` | Meaning |
| --- | --- | --- |
| `head!` | `head` | New head commit (a push or force-push). |
| `review!` | `review_decision` | GitHub's review decision changed, e.g. an approval was withdrawn. |
| `merge!` | `merge_state`, `mergeable` | Merge state changed, e.g. the branch fell behind base or into conflict. |

The review decision is whatever GitHub reports for the PR, so an approval made
before a new push keeps showing `approved` next to `head!` unless the repo
dismisses stale approvals, so read the two together.

With `--detail` (on `tkt pr list`, or `tkt snapshot diff`) the Head, Review and
Merge columns are shown and a changed value gets the `!` itself (`3f9a1c2!`)
instead of a Note.

- GitHub reports `UNKNOWN` mergeability while it computes it after a push or a
  base change. A move to or from `UNKNOWN` is not a change, so `UNKNOWN` →
  `CLEAN` on the next run is silent. The same goes for the CI column: while
  either run has `UNKNOWN` mergeability, CI falls back to the check rollup
  (for example `green`) and then shows `conflict` once GitHub answers, so a CI
  move to or from `conflict` is not flagged. A real rollup change
  (`green` → `red`) is still flagged, and a push shows as `head!`.
- `tkt issue list` rows do not have these fields. `tkt review` rows have them like `tkt pr list`
  rows do.

### Issue dependencies

GitHub issues can be linked as "blocked by" and "blocking", can have a parent
issue and can have a milestone. `tkt issue list`, `tkt issue show` and issue
snapshots read all four from the query they already run, so a caller can tell
whether an issue can be started without one request per issue. The only extra
requests are for pages past the first 50 blockers or blocked issues (up to 500).

| Field | Meaning |
| --- | --- |
| `open_blockers` | Issues that block this one and are not closed, as `owner/repo#number` refs sorted by repo, then number. A blocker in another repo has a state too. A blocker the token cannot read has none, so it counts as open and shows as `?`, one for each. An issue with only closed blockers has `[]` |
| `blocking` | Number of open issues that this issue blocks |
| `parent` | The parent issue as `owner/repo#number`, or `null` |
| `milestone` | `{"title", "due_on"}` (`due_on` is UTC ISO-8601 or `null`), or `null` |

They are in `tkt issue show --format json` and in every row of
`tkt issue list --format json` (and of `tkt snapshot show issue/NAME --format
json`). Every issue row has them.

`tkt issue list --deps` adds the `Blocked by` and `Blocks` columns to the table.
Open blockers in the issue's own repo print as `#N`, others as `owner/repo#N`.
The default table is unchanged.

`tkt issue list --unblocked` keeps the issues whose `open_blockers` is empty, and
`--blocked` the rest, so the two together list every issue once. Use `--unblocked`
to find issues you can start now. A blocker you cannot read counts as open, so
the issue is listed by `--blocked`. A dependency cycle leaves every issue in it
blocked. Neither flag works with explicit refs.

With `--diff` / `--watch`, a change in `open_blockers` marks the row `*`, puts
`open_blockers` in `changed_fields` and adds a Note (`blocker_note` in the
JSON):

| Note | Meaning |
| --- | --- |
| `unblocked` | The issue had open blockers and has none now |
| `blocked` | The issue had no open blockers and has some now |
| `blockers changed` | The set of open blockers changed and is not empty on either side |

A change in `blocking`, `parent` or `milestone` alone does not mark the row.

### Reviewer state

PR and review rows also have one record per reviewer, built from GitHub's pending
review requests, each reviewer's latest review and the commit it covered. They
are in the JSON outputs (`tkt snapshot show --format json`, `--format json`)
as `reviewers`:

| Field | Meaning |
| --- | --- |
| `login` | The reviewer, or `team:SLUG` for a team. A team the token can't read is `team:unknown` (and logged), not a failed query |
| `actor_class` | `me`, `human`, `bot` or `agent`; null for a team. `agent` comes from the repo's `[actors] agent_logins`, never from GitHub's account type |
| `requested`, `requested_by`, `requested_at`, `as_code_owner` | A review request is pending now, who made it and when |
| `latest_state`, `reviewed_commit`, `submitted_at` | The latest review (`APPROVED`, `CHANGES_REQUESTED`, `COMMENTED`, `DISMISSED`) and the commit it was on |
| `on_head` | That review is on the PR's current head |
| `waiting` | Requested, and no review has answered the request yet |
| `rereview_requested` | Requested again after an earlier review |
| `rereview_needed` | The latest review is on an older head and nothing asks for another: the sidebar's re-request case |

`--reviewers` shows one mark per reviewer, counted per mark: `✓` approved on
head, `✗` changes requested on head, `~` commented on head, `⊘` dismissed, `•`
waiting, `↻` re-review requested, `!` review on an old head with no request.

With `--diff` / `--watch`, a reviewer transition marks the row `*` and the Note
(and `reviewer_changes` in the JSON) says what happened: `alice requested`, `all-hands-bot
approved on head`, `bob ↻ re-requested`, `bob review now on old head` (a push
after the review), `bob request removed`, `alice review dismissed`.

- Up to 200 reviewers are read per PR; beyond that the `--reviewers` cell ends in `…`.
- Removal and dismissal come from comparing snapshots, not from the PR timeline,
  so a request made and removed between two runs is not reported.

### Why a row is gone

By default the Note on a `-` row is a hint, not a fact: the snapshot only
knows the row is no longer in the result.

| Note | JSON `disappearance_reason` | Meaning |
| --- | --- | --- |
| `closed?` | `closed-or-gone` | `pr list` / `issue list`: it was open and no longer matches, most likely closed or merged (or deleted / transferred). |
| `PR linked?` | `pr-linked?` | `issue list --no-pr`: an open issue is gone, most likely because a PR now links to it (it may instead have been closed, if the list was open-only). |
| `done?` | `left-queue` | `tkt review`: it left your queue, usually because you approved it or it went on hold. |
| `limit?` | `limit` | The current result was cut off by `--limit` and the row was among the last ones of the previous result, as many rows as were added. It probably still matches; it just no longer fits. |
| `scope` | `scope` | The two snapshots used different scopes (only seen with `--diff-force`). |
| `?` | `unknown` | It wasn't open in the previous snapshot. |

Snapshots record whether the query matched more rows than `--limit` kept
(`has_more` in `tkt snapshot show --format json`). The `limit?` note uses the
current result's flag only.

Other things can also drop a row: a filter attribute changed (label removed,
review request withdrawn), or GitHub's search index briefly lagged.

#### `--diff-resolve`: look the rows up

`--diff-resolve` replaces the guess with a fact. Each `-` row is fetched by
ref (one batched GitHub query per 20 gone rows; no query when no row is gone)
and the Note says what GitHub reports now:

| Note | JSON `disappearance_reason` | Meaning |
| --- | --- | --- |
| `merged` | `merged` | The PR was merged. |
| `closed` | `closed` | The PR or issue was closed. |
| `PR linked` | `pr-linked` | `issue list --no-pr`: it is open and now has a linked PR. |
| `still open` | `still-open` | It is open but no longer matches the query: a filter attribute changed, it fell past `--limit`, or the search index lagged. |
| `not found` | `not-found` | GitHub no longer returns it (deleted, transferred or no access). |

Without the flag the diff makes no extra network calls. `tkt review` rows are
looked up as PRs. A failed lookup is an error and the baseline is not
overwritten.

```bash
tkt pr list --watch hourly --diff-resolve
```

### Shared flags on list commands

All three list commands accept the same snapshot flags:

| Flag | Meaning |
| --- | --- |
| `--snapshot [NAME]` | Save the result. With NAME, overwrites that snapshot. Without NAME, auto-timestamps. |
| `--diff NAME` | Diff the current query result against snapshot NAME. Alone (without `--snapshot` or `--watch`), it leaves NAME as it is and stages the result; `tkt snapshot ack` makes it the new baseline. See [Staging a baseline with `--diff`](#staging-a-baseline-with---diff). |
| `--watch NAME` | Shortcut for `--diff NAME --snapshot NAME` — the hourly-cron idiom. |
| `--format {table,json}` | `json` prints one JSON document instead of the table: the diff with `--diff`/`--watch`, else the current result as a snapshot. Default `table`. |
| `--diff-include-unchanged` | Include unchanged rows in the diff view (default: only changes shown). |
| `--diff-force` | Proceed with the diff even if the snapshot scope doesn't match the current query. |
| `--diff-resolve` | Look up each gone (`-`) row and say why (`closed`, `merged`, `still open`, `not found`) instead of guessing. See [Why a row is gone](#why-a-row-is-gone). |

`--watch NAME` is the common agent idiom: it diffs against the previous
`NAME` and then overwrites `NAME` with the fresh result, so the next hour
diffs against *this* hour. An empty result is still a snapshot: when the
last item in scope closes, `--watch` reports it as a `-` row and saves an
empty baseline.

### Exit codes and `--exit-code`

`--diff` and `--watch` exit 0 whether or not any row changed, so a script cannot tell a quiet
tick from a busy one without reading the output. `--exit-code` on `tkt pr list`,
`tkt issue list` and `tkt review` makes that a status, the way
[`git diff --exit-code`](https://git-scm.com/docs/git-diff#Documentation/git-diff.txt---exit-code)
does for a work tree:

| Exit code | Meaning |
| --- | --- |
| 0 | Success. With `--exit-code`: no row was added, changed or removed, or there are no rows |
| 1 | Error, such as a bad token, no network, a bad baseline file or a failed save |
| 2 | Usage error, such as `--exit-code` without `--diff` or `--watch`, or a scope mismatch |
| 10 | With `--exit-code` only: at least one row was added (`+`), changed (`*`) or removed (`-`) |

- `--exit-code` is a usage error (exit 2, empty stdout, no GitHub call) without `--diff` or `--watch`.
- Exit 10 follows the same rules as exit 0: the diff is printed, then the baseline is saved
  (`--watch`) or staged for `tkt snapshot ack` (`--diff`). stdout is the same with and without the flag.
- Exit 1 and exit 2 win over 10. A scope mismatch still exits 2, and writes nothing.
- A first run with no baseline and at least one row exits 10: every row is new.
- Unchanged rows never count, even with `--diff-include-unchanged`.
- Without `--exit-code` the exit codes are as before; most shells run `set -e` scripts
  as if exit 10 were a failure, which is why the flag is opt-in.

| | `git diff --exit-code` | `tkt … --diff NAME --exit-code` |
| --- | --- | --- |
| No changes | 0 | 0 |
| Changes | 1 | 10 |
| Error | 128, or another code above 1 | 1 |
| Usage error | 129 | 2 |

`tkt` uses 10 because 1 already means error and 2 already means usage error here. A caller can
tell "something changed" from "something broke":

```bash
tkt pr list --board oh --watch hourly --exit-code --format json > tick.json
case $? in
  0)  ;;                    # quiet tick: do nothing
  10) handle tick.json ;;   # something moved
  *)  echo "tkt failed" >&2; exit 1 ;;
esac
```

### Staging a baseline with `--diff`

A person at a terminal uses `--watch NAME`. A job uses `--diff NAME`, handles the
rows, then runs `tkt snapshot ack`:

```bash
tkt pr list --diff poll --format json > poll.json   # diff against baseline "poll"
handle poll.json                                         # your code; may fail
tkt snapshot ack pr/poll                                 # only now: "poll" becomes this result
```

A bare `--diff NAME` (no `--snapshot`, no `--watch`) never writes the baseline
`NAME`. After a successful diff it writes the current result to
`snapshots/pending/<kind>-<name>.json` instead. That directory is separate, so a
pending file never collides with a snapshot name, and `snapshot list` does not
read it as a snapshot.

- If the job fails before the ack, run `--diff NAME` again. It diffs against the
  same, older baseline, so the rows are reported again, and it replaces the
  pending file with the newest result.
- `tkt snapshot ack KIND/NAME` replaces the baseline with the pending result and
  deletes the pending file. With no pending file it exits 1 and changes nothing.
- A scope mismatch (exit 2) writes no pending file and leaves an existing one as
  it was.
- `--snapshot NAME`, `--watch NAME` and `tkt snapshot rm KIND/NAME` delete the
  pending file for NAME.
- The first `--diff NAME` with no baseline reports every row as `+` and still
  stages the result, so the first `ack` creates the baseline.
- Rule of use: one consumer per name, one tick at a time.

With `--format json`, the document has a top-level `"baseline"`: `"found"`
or `"missing"`. When it is `"missing"`, the rows are all `added`, and the notice
`No snapshot … found` goes to stderr. A job can treat a first run differently
without parsing stderr. Test `baseline`, not `prev.captured_at`: with no baseline,
`prev.captured_at` is the time of the run.

### Diff JSON

With `--diff` or `--watch` and `--format json`, stdout is one document. Its top level is
`schema` (2), `prev` and `curr` (each with `name`, `captured_at` and `scope_hash`),
`baseline`, `scope_matches`, `counts` and `deltas`. A delta names a row as a list row does:

| Field | Meaning |
| --- | --- |
| `ref` | `owner/repo#N`, as `ref` in `items` |
| `kind` | The row kind: `issue`, `pr` or `review`. Set for every change, `unchanged` included |
| `change` | `added`, `changed`, `removed` or `unchanged` |
| `new_history_tail` | The characters appended to the [history string](#history-strings) |
| `changed_fields` | Row field names, such as `ci`, `draft`, `head`, `step_status` and `last_activity`, plus `history-rewritten`. That one is a marker, not a row field: the new history does not start with the old one |
| `disappearance_reason` | For `removed` ([Why a row is gone](#why-a-row-is-gone)), else `null` |
| `prev`, `curr` | The row before and after, with the fields of a row of that `kind` ([Row fields](#row-fields)). `prev` is `null` for `added`, `curr` is `null` for `removed`, and both are `null` for `unchanged` |

The optional fields (`reviewer_changes`, `step_changes`, `blocker_note`, `events_since`,
`events_truncated`, `steps`) are present as before. The diff table, its notes and the `Δ`
column are the same as before.

```bash
tkt pr list jpshackelford/tickster#60 --diff demo --format json | jq -r '.deltas[] | [.ref, .kind, .change] | @tsv'
```

```text
jpshackelford/tickster#60pradded
```

With no baseline `demo`, the notice `No snapshot pr/demo found; treating all current rows as new.`
goes to stderr.


### `--format json` on list commands

`--format {table,json}` (default `table`) is on `tkt pr list`, `tkt issue list`
and `tkt review`. It replaces the old diff-only flag, which is now an argparse error.
With `json`, stdout holds one JSON document and nothing else. Notices and
errors go to stderr.

- With `--diff` or `--watch`, the document is the diff.
- Without them, it is the current result: one compact document, and only that on stdout.
  The legend, the `Filters:` line and the footer are not printed.
- `--snapshot NAME --format json` saves the snapshot and prints the document instead of the
  table. The saved file is that same document, byte for byte, and
  `tkt snapshot show KIND/NAME --format json` prints it again.

```json
{
  "schema": 2,
  "filters": {"repos": ["jpshackelford/tickster"], "author": "jpshackelford",
              "states": ["open"], "pr_filter": "no-pr",
              "window": {"field": "created", "since_days": 14}, "limit": 100},
  "total_count": 31,
  "has_more": false,
  "items": [{"ref": "jpshackelford/tickster#142", "kind": "issue", "...": "see Row fields"}]
}
```

| Key | Meaning |
| --- | --- |
| `schema` | The format version, `2` |
| `snapshot` | Only with `--snapshot NAME` (and in a stored file): `{"name", "captured_at"}`, placed after `schema`. `captured_at` is UTC ISO-8601 |
| `filters` | The query that ran, as the machine form of the `Filters:` line. Unset keys (`null`, `false`, empty list) are left out, and `limit` is always there. `author` and `reviewer` hold the login that was queried: never `null` and never `me`. With explicit refs there is `refs` and no `author`. `window` has only the keys that are set: `field` with `since_days`, or with `after` and / or `before` |
| `total_count` | How many rows matched `filters`. It is larger than the number of `items` when `has_more` is `true`. It is never the count of the unfiltered search. It is `null` when it cannot be known without reading every page: a client-side filter (`--no-pr`, `--has-pr`, `--blocked`, `--unblocked`, OR labels, `pr list` with two states such as `open,merged`) or a `review` search that stopped at `--limit` with more pages left. With explicit refs it is the number of refs resolved |
| `has_more` | Always present, `true` or `false`: more rows match than `items` holds |
| `items` | The rows ([Row fields](#row-fields)). Each has `kind`. `[]` for an empty result, with exit 0 |

There is no top-level `kind`, `name`, `captured_at` or `scope_hash`. The scope hash that
`tkt snapshot list` shows is computed from `filters`. `review` reports `total_count` as the
number of matching PRs before `--limit`. A closed pipe (`| head -1`) ends the command with exit
141 and no traceback.

```bash
tkt pr list octocat/hello-world#7 --format json | python -m json.tool
tkt issue list --all-authors --repo o/r --created-since 14 --no-pr --format json | jq '.items | length'
tkt review --format json | jq '{total_count, has_more, n: (.items | length)}'
tkt pr list --author me --snapshot mine --format json   # save and print
```

### Events and steps in a PR diff

With `--diff` or `--watch` and `--format json`, `tkt pr list` adds two fields to every
`added` or `changed` delta, so a poll loop needs no `tkt pr show` or `tkt pr steps` call:

| Field | Meaning |
| --- | --- |
| `events_since` | The PR's timeline events after the cutoff, oldest first. The cutoff is `prev.last_activity` for a `changed` row; an `added` row has no earlier state, so it gets the whole timeline. Each event has the fields of an event in [`tkt pr show --format json`](#tkt-pr-show) (`at`, `kind`, `char`, `actor`, `actor_class`, `text`, `body`, `more_chars`, and `threads` for a review) |
| `events_truncated` | `true`, and only then present, when the timeline fetch cap was hit and events past the cap are missing (`timeline_truncated` in `pr show`) |
| `steps` | What `tkt pr steps --format json` prints for the PR: a list of `step`, `status` and `evidence`. Snapshots keep only the statuses, so evidence is in the diff output only |

`removed` and `unchanged` deltas have none of these fields and cost no GitHub call. The other
delta fields (`ref`, `kind`, `change`, `new_history_tail`, `changed_fields`, `prev`, `curr`,
`step_changes`, `reviewer_changes`) are described in [Diff JSON](#diff-json). `issue list` and `review` are unchanged.

`--events` and `--max-body` set the size:

| Option | Effect |
| --- | --- |
| `--events brief` (default) | Each event body is cut to 160 characters and ends `…(N more chars)`, as in `pr show` |
| `--events full` | Whole bodies |
| `--events none` | No `events_since` and no timeline fetch at all. The cheapest mode: read `new_history_tail` and call `tkt pr show --since-time` for the rows you care about |
| `--max-body N` | With `brief`, cut bodies at `N` characters instead of 160. With `full` or `none` it is a usage error (exit 2) |

Both options are usage errors (exit 2) without `--diff` / `--watch` or without `--format json`.
Each row costs one `pr show` query, so a tick with many moved PRs costs that many more requests;
use `--events none` to avoid them.

```bash
tkt pr list --watch hourly --format json --max-body 400   # bodies cut at 400
tkt pr list --diff poll --format json --events none       # steps only, no timeline requests
```

### Scope matching

The query filter set (board, author or `--all-authors`, reviewer, repos, explicit
`owner/repo#N` refs, states, labels, `--not-label`, `--no-pr` / `--has-pr`, `--blocked` / `--unblocked`, `--sort`, `--all`, limit, and the
[date window](#date-window-filtering)) is persisted with
every snapshot. `repos` is the list actually queried (`--repo`, else the
board's repos at run time), so adding or removing a repo on the board
counts as a scope change. Repos, refs and `--not-label` labels are compared as
sets, so their order doesn't matter. The window is recorded as typed, so `--created-since 14`
matches `--created-since 14` on any later day, while `--created-since 14` against
`--created-since 3`, `--updated-since 14` or no window at all is a scope change; the error
(or the `window:` line under the summary) names both windows. A changed PR filter is named the
same way, on a `pr filter: none → no-pr` line, and a changed blocked filter on a
`blocked filter: none → blocked` line. If the
current query's scope doesn't match the
snapshot's scope, the diff refuses to render in either table or JSON mode
and exits 2 without touching the baseline, so you can rerun with
`--diff-force` to proceed (the summary is tagged `[scope-changed]` so you
can see what happened).

### Storage

Snapshots live as JSON files under `~/.tkt/snapshots/<kind>-<name>.json`.
Each file is small, inspectable with a text editor, and trivial to gist
if you want to share. Overwriting an existing name is atomic.

A name may use letters, digits, `.`, `_` and `-`. Any other run of characters,
such as `/` or a space, is stored as one `-`, so `a/b` and `a-b` are the same
snapshot. When `--snapshot` or `--watch` saves under a name it had to change,
`tkt` prints `tkt: snapshot name 'a/b' is stored as 'a-b'` on stderr.

A snapshot or pending-baseline file that tkt cannot read (another schema, invalid
JSON, a missing or unexpected field, a value of the wrong type) is deleted, and tkt
prints one notice on stderr: `tkt: discarded snapshot issue/NAME: schema 1, this tkt
writes schema 2`. The file then counts as missing, as on a first run. No `tkt snapshot rm`
is needed. `tkt snapshot list` discards such a file in the same way. A `*.json` file in the
folder whose name does not start with `pr-`, `issue-` or `review-` is left alone.

```bash
# hourly agent loop
tkt pr list    --board oh --watch hourly
tkt issue list --board oh --watch hourly
tkt review                 --watch hourly
```

---

## Date-window filtering

`tkt issue list`, `tkt pr list`, and `tkt review` accept flags that restrict
results to a time window. Each flag names the date it filters on. They translate
directly into the GitHub search date qualifiers (`created:`, `updated:`,
`merged:`, `closed:`), so you no longer have to run a separate GitHub search and
pipe refs back in.

| Field | Days back (UTC day boundary) | Absolute (UTC date, inclusive) |
| --- | --- | --- |
| created | `--created-since N` | `--created-after DATE`, `--created-before DATE` |
| updated | `--updated-since N` | `--updated-after DATE`, `--updated-before DATE` |
| closed | `--closed-since N` | `--closed-after DATE`, `--closed-before DATE` |
| merged (PRs only) | `--merged-since N` | `--merged-after DATE`, `--merged-before DATE` |

`tkt pr list` and `tkt review` offer all four fields. There is no `--merged-*`
on `tkt issue list`: argparse rejects it as an unrecognized argument (exit 2).
`DATE` is `YYYY-MM-DD`.

Semantics:

- `--F-since N` is shorthand for `--F-after <today minus N days>`, where "today"
  is the current **UTC** date. It reaches back to the start of that UTC day, not
  to N × 24 hours ago, so `--created-since 0` means "today (UTC)".
  `tkt board scan --updated-since DAYS` uses the same rule.
- `--F-after` and `--F-before` may be combined to express a closed interval;
  using both renders as `field:AFTER..BEFORE`.
- `--F-since` cannot be combined with `--F-after`/`--F-before` of the same field.
- **The field is the one in the flag name.** It is never inferred from the state
  being queried. In 1.x a window with no field flag meant a field the state
  picked, mostly "updated"; now `--updated-since 14` says so.
- One date field per query. `--created-since 14 --updated-since 2` is an error
  naming both flags.
- **The window is reported.** (`tkt issue list`, `tkt pr list` and `tkt review` also print a separate
  `Filters:` line ([issue](#effective-filters-line),
  [pr](#effective-filters-line-tkt-pr-list),
  [review](#effective-filters-line-tkt-review)); it does not repeat the window.)
  A listing that used a window ends with a
  `Window: merged ≥ 2026-09-26 (UTC)` line, and an empty result names it too
  (`No PRs found (merged ≥ 2026-09-26, UTC).`), so a window that is narrower
  than you meant is visible rather than silent.
- **Window with `--watch`/`--diff`/`--snapshot`.** The window is part of the
  snapshot's [scope](#scope-matching). It records the field and the number of
  days (or the bounds), so a rolling window compares equal from day to day.

Combinations that cannot do what they say are errors, not silent no-ops:

| Command | Why it is rejected |
| --- | --- |
| Any date flag with explicit refs (`owner/repo#N`, or refs piped on stdin) | Refs list exactly the items named; a window can't narrow them. The error names the flag you typed. Drop one or the other. |
| `--merged-*` without `--merged` or `--all` | Only merged items have a merge date, so nothing can match. |
| `--closed-*` without `--closed` or `--all` (`--merged` also works on `tkt pr list` and `tkt review`; on `tkt review`, `--all` does not count) | Open items have no close date. |
| `--F-since` mixed with `--F-after`/`--F-before` | One spelling per field: use the days-back form or the absolute bounds. |
| Flags for two different fields (`--created-since 14 --updated-since 2`) | One date field per query; the snapshot scope stores one window. |

On `tkt review`, `--all` means "include approved and on-hold PRs", not "all
states": its states come only from `--merged` and `--closed`, so `--merged-*`
needs `--merged`, `--closed-*` needs `--closed` or `--merged`, and the error does
not suggest `--all`. For example:

```text
--closed-since only matches closed items, but the state filter is open: add --closed (or --merged)
```

On `tkt pr list` the same error suggests `--all` as well:

```text
--merged-since only matches merged items, but the state filter is open: add --merged (or --all)
```

```bash
tkt pr list --author ak684 --merged --merged-since 14             # merged in the last 2 weeks
tkt issue list --created-after 2026-08-01 --created-before 2026-08-31   # opened in August
tkt pr list --created-since 30 --all                              # PRs created in the last 30 days, any state
tkt review --merged --merged-since 7                              # reviewed & merged this week
```

The date flags of tickster 1.x were removed in 2.0. See
[Upgrading to 2.0](#upgrading-to-20) for what each one is now.

---

## Recipes

What I filed in the last two weeks, with titles:

```bash
tkt issue list --all --created-since 14 --title
```

`--author` defaults to you, so these are your issues. `--all` includes closed
ones: leave it out and only open issues are listed, so closed ones are missed.
`--created-since` filters on the created date (UTC day boundary).

Which of those have no PR yet:

```bash
tkt issue list --all --created-since 14 --no-pr --title
```

`--no-pr` keeps issues with no linked PR. Linked means a PR closes or mentions
the issue, in any PR state (see [Linked PRs](#linked-prs)). The `PR` column shows
`--` for every row, and the `Window:` line under the table says which dates were
searched. For the opposite, the issues a PR already links to, use `--has-pr`:

```bash
tkt issue list --all --created-since 14 --has-pr --title
```

Every open issue in a repo, whoever opened it, as one JSON document:

```bash
tkt issue list --repo octocat/hello-world --all-authors --format json
```

The document has `schema`, `filters`, `total_count`, `has_more` and `items`;
each item is one issue with the keys `ref`, `title`, `state`, `linked_pr` and
the rest of the [row fields](#row-fields). Read the rows from `.items[]`:

```bash
tkt issue list --repo octocat/hello-world --all-authors --format json | jq -r '.items[] | "\(.ref)  \(.title)"'
```

`tkt issue list --help` shows the same recipes, each with the question it answers.

What merged in the last two weeks:

```bash
tkt pr list --merged --merged-since 14
```

What I touched in the last week, across all states:

```bash
tkt issue list --all --updated-since 7 --title
```

---

## Listing every author

`tkt issue list` and `tkt pr list` search by author: the current user unless
`--author` names someone else. `--all-authors` drops the author filter, for
example to watch every open issue and PR in a repo whoever opened it.

```bash
tkt issue list --repo octocat/hello-world --all-authors --open
tkt pr list    --board oh --all-authors --watch factory
```

- It needs repos, from `--repo` or the board (`--board`, else the default
  board). With no repos it exits 1 rather than search all of GitHub.
- It can't be combined with `--author`, with explicit `owner/repo#N` refs
  (arguments or stdin), or with `pr list --reviewer` (review-requested PRs are
  already every author's). Each of these is an error, not a silently ignored
  flag.
- Labels, states, date windows, `--limit`, `--activity` and the snapshot flags
  work as usual.
- History case stays relative to you: `o` = you opened it, `O` = someone else
  did. The author's login is in the JSON outputs (`--format json`,
  `tkt snapshot show --format json`).
- A snapshot taken with `--all-authors` records it in its scope, so diffing it
  against one taken without the flag is a scope mismatch.

---

## History strings

The most token-dense feature of `tkt`: instead of a verbose timeline, every
issue and PR row carries a compact **history string** that encodes its whole
lifecycle as one character per event. An entire review-and-merge cycle fits in a
handful of characters (e.g. a PR history of `oRfAM`).

Two conventions apply to every history string:

- **Case = who acted.** Lowercase = the reference user (you, or whoever
  `--reviewer`/`--author` selects); UPPERCASE = someone else.
- **An item an AI actor opened starts with `s` / `S`** instead of `o` / `O`; see
  [AI actors](#ai-actors).
- **Consecutive duplicates collapse.** Ten review comments in a row render as a
  single `C`, so the string stays short and skimmable.
- **A trailing `…` means the history is cut off.** `tkt` reads up to 500 timeline
  events per PR or issue (extra GraphQL requests are made only for items with
  more than 100). If an item has more, the oldest 500 are shown and the string
  ends in `…`; later events, including a final `M` or `x`, are not shown. Review
  threads are counted up to 1000 and labels are read up to 100 per issue.
- **A trailing `>` means the history was cropped to fit the terminal.** The width
  fit applies on a terminal only: when stdout is a pipe or a file, tables print at
  their natural width and are never cropped, whatever `$COLUMNS` says. On a
  terminal, when the History cell of `tkt pr list`, `tkt issue list`, `tkt review`
  or a `--diff` / `--watch` table is wider than the room left, `tkt` keeps its head and ends it
  in `>`, and prints one line under the table to say so. Repo, Title and Labels
  give up width first (down to a floor); the PR / issue number and the Steps cell
  are never shortened. A `>` is only about width: widen the terminal to see
  the whole string. `…` stays the 500-event cap and is never added by the crop.
  If the columns cannot fit even then (for example `--detail --steps --title` at
  80 columns), the table prints at the width it needs instead of squeezing every
  column. When stdout is a pipe or a file, the legends and notes around the
  tables are not wrapped either: each prints on one line, whatever `$COLUMNS` says.

### PR history characters

Used by `tkt pr list` and `tkt review`.

| Char | Meaning |
| --- | --- |
| `o` | Opened |
| `s` / `S` | Opened by an AI actor |
| `h` | Review requested |
| `r` | Changes requested (a review) |
| `a` | Approved |
| `c` | Comment |
| `e` / `E` | Changes requested by an AI actor |
| `v` / `V` | Approved by an AI actor |
| `n` / `N` | Comment by an AI actor |
| `f` | Fix — commits pushed after a review (commits before the first review are ignored) |
| `m` | Merged |
| `k` | Killed — closed without merging (not shown if merged) |

Example: `oRfAM` = *you* opened the PR, someone requested changes (`R`), *you*
pushed fixes (`f`), someone approved (`A`), someone merged (`M`).

`s`, `e`, `v` and `n` replace `o`, `r`, `a` and `c` when an [AI actor](#ai-actors) did it: lowercase
when it acted with your own login (an AI disclosure in the text), uppercase when it
acted under its own login. `oEVM` = an agent requested changes, an agent approved, and
someone merged; `SEVM` = the same PR, opened by an agent.

### Issue history characters

Used by `tkt issue list`.

| Char | Meaning |
| --- | --- |
| `o` | Opened |
| `s` / `S` | Opened by an AI actor (lowercase = it acted with your login, uppercase = its own login) |
| `c` / `C` | Comment (lowercase = you, uppercase = other human) |
| `n` / `N` | Comment by an AI actor (lowercase = it acted with your login, uppercase = its own login) |
| `B` | Bot comment (always uppercase) |
| `l` / `L` | Label added (lowercase = you, uppercase = other human or bot) |
| `a` | Assigned |
| `x` | Closed |
| `r` | Reopened |
| `p` | Linked to a PR (see [Linked PRs](#linked-prs)) |

Examples:

- `oCLx` — opened, another user commented, labelled, then closed.
- `oclBLx` — opened, you commented and labelled, a bot commented (`B`) and
  labelled (`L`), then closed.
- `oCpx` — opened, got a comment, linked to a PR, closed.

#### Linked PRs

An issue counts as linked to a PR, in `p`, in `linked PRs` of `tkt issue show`,
and in `linked_pr` of `tkt issue list` and `tkt snapshot`, when either holds:

- the PR has a closing keyword for the issue (`Fixes #N`, `Closes #N`, `Resolves #N`)
  in its body, whether the PR is open, merged or closed; or
- the PR mentions the issue in any other way.

A mention of the issue in another issue does not count. A PR is listed once even
if both rules match; the `p` event is dated when the PR was opened. A closing PR
from another repository shows as `owner/repo#N`. When several PRs are linked,
`linked_pr` is the first merged one, else the first open one, else the first
closed one. A release PR whose changelog says "closes #N" is linked too.

`tkt issue list --no-pr` and `--has-pr` use exactly this definition: `--no-pr`
keeps the rows whose `PR` column is `--`, `--has-pr` the rest.

### AI actors

Every event also carries an **actor class**, shown in JSON (the `events` list of
`tkt pr show` and `tkt issue show`, as `actor_class`):

| Class | Who |
| --- | --- |
| `me` | the reference user |
| `human` | anyone else |
| `bot` | non-AI automation: a `[bot]` login, an `[issue] bot_usernames` entry or an `[actors] bots` entry; some accounts come without the suffix, so list them |
| `agent` | a login in the repo's `[actors] agent_logins`, even if it ends in `[bot]` |
| `me_agent` | the reference user, when their login is in `agent_logins` or their text matches `[actors] agent_disclosure` |

Logins and the disclosure pattern come only from the repo's `.agents/tickster.toml`
([norms file](#tkt-norms)). With no file, no AI actor is recognised and `[bot]`
accounts are still `bot`. The disclosure pattern is matched against the whole body of
a comment, review or opened item (the PR or issue body).

An item an AI actor opened starts with `s` / `S` instead of `o` / `O`. Each later event
of an AI actor changes its letter too: `A` becomes `V` and `c` becomes `n`, so `oAcm` in
0.3.0 is `sVnm` now. See [Upgrading to 1.0](#upgrading-to-10).

### Bot detection

Bot **comments** get the distinct `B` marker (bot labels use `L`, like other
humans). A username is treated as a bot when it ends in `[bot]` or appears in the
list under `[issue] bot_usernames` in `~/.tkt/config.toml`, or in the repo's
`[actors] bots` ([norms file](#tkt-norms)). There is no built-in name list, and the
`[bot]` suffix is a convenience, not a guarantee: some GitHub data sources give an
automation account without it. For example, the GraphQL API that `tkt pr show`,
`tkt pr list` and the reviewer records use returns `github-actions`, where the REST
API returns `github-actions[bot]`. List such accounts in `[actors] bots`, or in
`[actors] agent_logins` if they are AI actors; otherwise they are classed `human`.
A login in `[actors] agent_logins` is an AI actor instead, even if it ends in `[bot]`.

`tkt pr list`, `tkt issue list` and `tkt review` print a one-line `History:` legend
beneath the table, so the encoding is self-documenting at the terminal. It names
only the characters in the rows shown, in a fixed order, after the case rule
(lowercase = you or an AI acting with your login, UPPERCASE = others or an AI under
its own login), for example:

```
History: lowercase = you, UPPERCASE = others (AI letters: lowercase = your login, UPPERCASE = its own login). s AI opened, v AI approval, n AI comment
```

The character is matched in either case, so `V` and `v` both give the `v AI approval`
entry. No legend prints when no row has a known character. `tkt review` names the
reviewer in the case rule (`lowercase = octocat`). Piped, the legend is one line
whatever `$COLUMNS` says; on a terminal it wraps. `--format json` and the `--diff` /
`--watch` diff tables do not print it. A `Filters:` line sits under the table and its
legends ([issue](#effective-filters-line), [pr](#effective-filters-line-tkt-pr-list),
[review](#effective-filters-line-tkt-review)). The wording lives in
`src/history_legend.py`; the `Legend:` block of `show` renders from the same table.

## Piping refs from stdin

`tkt pr list` and `tkt issue list` accept references on stdin (one per line).
Both `owner/repo#number` and full GitHub URLs are supported, so you can compose
with other tools:

```bash
gh search prs --author me --json url -q '.[].url' | tkt pr list
cat my-issues.txt | tkt issue list --title
```

## Environment variables

| Variable | Purpose |
| --- | --- |
| `GITHUB_TOKEN` | GitHub API token (required) |
| `GIST_TOKEN` | Optional scoped token used for `board sync-config` gists; falls back to `GITHUB_TOKEN` |
| `GITHUB_USERNAME` | Override the detected current user |
| `TKT_HOME` | State directory for config, cache, boards, snapshots and API logs (default `~/.tkt`) |
| `TKT_LOG_API` | Set to `1`/`true` to log raw GitHub API calls (debugging) |
| `TKT_LOG_API_DIR` | Directory for API logs when `TKT_LOG_API` is enabled (default `$TKT_HOME/api_logs`) |
