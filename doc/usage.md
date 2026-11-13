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
- [`tkt snapshot`](#tkt-snapshot)
- [Snapshots & diffs](#snapshots--diffs)
- [Date-window filtering](#date-window-filtering)
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
| `--open, -O` | Show open issues (default) |
| `--closed, -C` | Show closed issues |
| `--all, -A` | Show all states (open + closed) |
| `--limit, -n N` | Max issues to show (default: 100) |
| `--title, -t` | Show issue titles |
| `--activity, -s` | Sort by recent activity instead of creation date |
| `--since DAYS` | Only issues since the start of the UTC day N days ago |
| `--after YYYY-MM-DD` | Only issues on/after this date (inclusive) |
| `--before YYYY-MM-DD` | Only issues on/before this date (inclusive) |
| `--date-field FIELD` | Date field to filter on: `created`, `updated`, `merged`, `closed` (default: inferred from state) |

```bash
tkt issue list                              # your open issues
tkt issue list --repo octocat/hello-world   # one repo
tkt issue list --all --title -l bug         # all states, titles, bug label
tkt issue list octocat/hello-world#42       # a specific issue
tkt issue list --since 14                    # issues touched in the last 2 weeks
tkt issue list --repo octocat/hello-world --all-authors --open   # everyone's open issues
```

Also accepts `--snapshot`, `--diff`, `--watch` for change-since-last-run
output — see [Snapshots & diffs](#snapshots--diffs).

See [Date-window filtering](#date-window-filtering) for the shared semantics of
`--since` / `--after` / `--before` / `--date-field`.

### `tkt issue show`

Read one issue: a header and its timeline, oldest first, with the text of the
opening post and each comment. Use it after `tkt issue list` shows an issue you
need to read.

```bash
tkt issue show OWNER/REPO#NUM [--since TS | --since-snapshot KIND/NAME]
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
Legend: the letter is the event's history character (lowercase = you, uppercase = others; s n = AI opened, comment, B = bot comment; - = not in the history string). o opened, c comment, l labeled, a assigned, x closed, r reopened, p PR linked. Class: me human bot agent me_agent.
timeline: 5 events, oldest first
2026-10-27T20:37:49Z s jpshackelford(me_agent) opened: ## Summary `tkt issue list` with no sta…(1944 more chars)
2026-10-27T20:37:50Z l jpshackelford(me) labeled bug
2026-11-05T05:43:19Z l jpshackelford(me) labeled ready
2026-11-05T05:43:19Z l jpshackelford(me) labeled priority:high
2026-11-05T10:45:40Z x jpshackelford(me) closed
```

The header has the state, the [history string](#history-strings), author, dates,
labels, assignees, and linked PRs. Each timeline line is
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
| `last_activity` | Time of the latest event (UTC, ISO-8601) |
| `history` | The [history string](#history-strings) |
| `labels` | Label names |
| `assignees` | Assignee logins |
| `linked_pr` | One linked PR as `owner/repo#number`, or `null` if there is none. The same PR the [history string](#linked-prs) uses: the first merged one, else the first open one, else the first |
| `linked_prs` | Every linked PR as `{"ref", "state"}`, with a lowercase `state` (`open`, `merged`, `closed`) |
| `since` | The `--since` cutoff in UTC, `null` without one |
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
| `--steps` | Add a **Steps** column, one character per [step](#tkt-pr-steps) (review, CI, findings, re-review, manual test, test findings, retest), and a legend under the table. Off by default so the table stays narrow. The cell is always the full 7 characters; on a narrow terminal Repo and History give up width instead. Snapshots record the statuses, so `--diff` / `--watch` report transitions |
| `--since DAYS` | Only PRs since the start of the UTC day N days ago |
| `--after YYYY-MM-DD` | Only PRs on/after this date (inclusive) |
| `--before YYYY-MM-DD` | Only PRs on/before this date (inclusive) |
| `--date-field FIELD` | Date field to filter on: `created`, `updated`, `merged`, `closed` (default: inferred from state) |

```bash
tkt pr list --author me                     # your open PRs
tkt pr list --merged --graph                # merge cadence graph
tkt pr list octocat/hello-world#7           # a specific PR
tkt pr list --author ak684 --merged --since 14   # merged in the last 2 weeks
tkt pr list --board oh --all-authors --watch factory   # everyone's open PRs, diffed
```

Also accepts `--snapshot`, `--diff`, `--watch` for change-since-last-run
output — see [Snapshots & diffs](#snapshots--diffs).

See [Date-window filtering](#date-window-filtering) for the shared semantics of
`--since` / `--after` / `--before` / `--date-field`.

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
tkt pr changes OWNER/REPO#NUM --since SHA [--format text|json]
    [--ignore-path GLOB ...] [--min-changed-lines N] [--explain]
```

| Option | Description |
| --- | --- |
| `--since SHA` | Required. The commit to compare from: a commit SHA of 7 to 40 hex characters, in either case. A branch name or tag is rejected, because a branch tip moves and the verdict could not be repeated; resolve it to a SHA first |
| `--format` | `text` (default) or `json`; with `json`, stdout is only the JSON document |
| `--ignore-path GLOB` | Drop changed files matching `GLOB` (repeatable; `*` stays in one path segment, `**` crosses segments). Replaces the norms file's `ignore_paths` |
| `--min-changed-lines N` | After ignoring paths, changes below `N` added+deleted lines are not significant. `0` counts as given and replaces the norms file's value |
| `--explain` | After the verdict, print one `why:` line per setting with its value and source |

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
$ tkt pr changes OWNER/REPO#NUM --since SHA --explain
...
significant: no (all 1 changed files match ignore_paths)
  why: ignore_paths = [doc/**] (.agents/tickster.toml)
  why: min_changed_lines = 0 (.agents/tickster.toml)
```

```text
$ tkt pr changes jpshackelford/tickster#60 --since 75d1faa --ignore-path 'doc/**' --ignore-path '**/*.md'
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
  A malformed `--since` (not 7 to 40 hex characters, so also any branch or tag)
  exits 2 with `Error: --since needs a commit SHA` on stderr, empty stdout, and
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

A significant change is judged as in `tkt pr changes --since <tested commit>`, with the
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
- With `--diff` / `--watch` on `tkt pr list --steps`, a step that moved marks the row `*`
  and the Note (and `step_changes` in the JSON) says how: `request re-review: done →
  needed`. Every step is recorded, including other reports' steps. A baseline saved without
  `--steps` is not compared, and a step missing from the baseline is skipped.
- `tkt pr list --steps` shows one character per step, in this order: `r` review, `c` CI,
  `f` findings, `a` re-review, `m` manual test, `t` test findings, `x` retest. Uppercase is
  `needed`, lowercase `waiting`, `.` done or `n/a`, `?` unknown, `-` not configured.
  `R.F....` = review needed and findings to address; `....M--` = the manual test report is
  missing. A report other than `manual_test` has no column; see it with `tkt pr steps`.
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
tkt pr show OWNER/REPO#NUM [--since TS | --since-snapshot KIND/NAME]
    [--max-body N] [--format text|json]
```

| Option | Description |
| --- | --- |
| `--since TS` | Only events after this ISO-8601 time, e.g. `2026-11-05T10:00:00Z`. A date or a time with no zone is UTC |
| `--since-snapshot KIND/NAME` | Only events after the `last_activity` the named [snapshot](#snapshots--diffs) stored for this item. Use `pr/NAME` or `review/NAME` for a PR (`issue/NAME` for an issue). Errors if the snapshot has no row for the item. Cannot be combined with `--since` |
| `--max-body N` | Trim each comment, review or thread-comment body to its first `N` characters (default: 600, `0` = no trimming). `N` counts the body only; a trimmed body ends with an extra `…(K more chars)` suffix |
| `--format` | `text` (default) or `json`; with `json`, stdout is only the JSON document |

The ref may be `owner/repo#number` or a GitHub PR URL.

```text
$ tkt pr show jpshackelford/tickster#60 --max-body 40
jpshackelford/tickster#60 pr merged ready ci:green 💬0 "fix(issue): default `issue list` to open issues"
history: sVnm
author: jpshackelford  created: 2026-11-05T10:28:10Z  last activity: 2026-11-05T10:45:37Z
head: 742dbea  mergeable: unknown  merge: unknown  review: approved
reviewers: github-actions(agent) ✓ approved on head
linked issues: jpshackelford/tickster#49
reports: manual_test 2026-11-05T10:37:08Z by jpshackelford at 742dbea (on head) no fail match
Legend: the letter is the event's history character (lowercase = you, uppercase = others; s e v n = AI opened, review, approval, comment; - = not in the history string). o opened, h review requested, r changes or inline review, a approved, c comment, f push after a review, m merged, k closed. Class: me human bot agent me_agent. ↳ marks a review thread: path:line, resolved or unresolved.
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

`--since` and `--since-snapshot` keep events strictly after the cutoff, and keep
an older review if one of its thread comments is newer. With nothing new, the
output is the header and `no new events since <time>`. The cutoff is printed in
UTC. Together with a snapshot saved by `--watch` or `--snapshot`, this reads
only what changed since the last poll:

```bash
tkt pr list jpshackelford/tickster#60 --snapshot hourly   # save a snapshot (pr/hourly)
tkt pr show jpshackelford/tickster#60 --since-snapshot pr/hourly
tkt pr show jpshackelford/tickster#60 --since 2026-11-05T10:35:00Z
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
| `since` | The `--since` cutoff in UTC, `null` without one |
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
| `--since DAYS` | Only PRs since the start of the UTC day N days ago |
| `--after YYYY-MM-DD` | Only PRs on/after this date (inclusive) |
| `--before YYYY-MM-DD` | Only PRs on/before this date (inclusive) |
| `--date-field FIELD` | Date field to filter on: `created`, `updated`, `merged`, `closed` (default: inferred from state) |

```bash
tkt review                                  # your actionable review queue
tkt review --all --title                    # full queue with titles
tkt review -X "dependabot[bot]"             # hide dependabot PRs
tkt review --merged --since 7               # PRs you reviewed that merged this week
```

See [Date-window filtering](#date-window-filtering) for the shared semantics of
`--since` / `--after` / `--before` / `--date-field`.

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
tkt board scan --user octocat --since 30    # discover recent activity
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

A job that polls with `--watch` can also skip the deltas that have `history-rewritten` on
that first run ([`doc/automation.md`](automation.md#1-poll-what-moved-since-the-last-run)).

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
  collapse), e.g. replies after your comment. In `--diff-format json`
  this is `"activity"` in `changed_fields`.

A one-line summary header shows how long ago each snapshot was captured,
the counts, and whether the two snapshots were produced by the same scope
(same board, author or `--all-authors`, repos, refs, states, labels, limit). Exact capture
times are in `tkt snapshot show` and `--diff-format json`.

```
diff pr/hourly: 1h ago → 4s ago  (+2 new, *5 changed, -1 gone, 29 unchanged)

Δ Repo                  PR     History      CI      State   💬   Last     Note
+ OpenHands/docs        #42    [oCL]        --      open    --   5m ago
* OpenHands/OpenHands   #1234  oRfA[fR]     red!    open    2    1m ago!
- OpenHands/infra       #87    oCax         --      open    --   1d ago   closed?

Δ: + new row, * changed, - gone (Note: why, `?` = a guess), (blank) unchanged.  History: [bracketed] = new since last snapshot.  Field!: value changed; prior value via `tkt snapshot diff`.  head!/review!/merge!: PR head commit, review decision or merge state changed.
```

A Note with several parts (history rewritten, `head!` tags, reviewer changes, step changes) joins them with `; `.

### Head, review and merge changes

PR snapshots (`tkt pr list`) also record four fields from GitHub: `head_sha`
(the full head commit), `review_decision` (`APPROVED`, `CHANGES_REQUESTED`,
`REVIEW_REQUIRED`, or null), `merge_state` (`mergeStateStatus`: `BEHIND`,
`DIRTY`, `BLOCKED`, `CLEAN`, `UNSTABLE`, …) and `mergeable` (`MERGEABLE`,
`CONFLICTING`, `UNKNOWN`). A change in any of them marks the row `*`, so a push
that leaves CI, history and 💬 unchanged still shows up. The Note names what
changed:

| Note | JSON `changed_fields` | Meaning |
| --- | --- | --- |
| `head!` | `head_sha` | New head commit (a push or force-push). |
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
  move to or from `conflict` is not flagged. A baseline saved before `mergeable`
  was recorded counts the same way. A real rollup change
  (`green` → `red`) is still flagged, and a push shows as `head!`.
- A baseline saved before these fields existed has no head SHA, so these
  fields are not compared until it is replaced; the first run after upgrading
  does not flag every row.
- `tkt issue list` snapshots do not record these fields. `tkt review` snapshots
  record `mergeable` only, for the CI rule above.

### Reviewer state

PR snapshots also record one record per reviewer, built from GitHub's pending
review requests, each reviewer's latest review and the commit it covered. They
are in the JSON outputs (`tkt snapshot show --format json`, `--diff-format json`)
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
after the review), `bob request removed`, `alice review dismissed`. A baseline
saved before reviewer state existed is not compared until it is replaced.

- Up to 200 reviewers are read per PR; beyond that the `--reviewers` cell ends in `…`.
- Removal and dismissal come from comparing snapshots, not from the PR timeline,
  so a request made and removed between two runs is not reported.

### Why a row is gone

By default the Note on a `-` row is a hint, not a fact: the snapshot only
knows the row is no longer in the result.

| Note | JSON `disappearance_reason` | Meaning |
| --- | --- | --- |
| `closed?` | `closed-or-gone` | `pr list` / `issue list`: it was open and no longer matches, most likely closed or merged (or deleted / transferred). |
| `done?` | `left-queue` | `tkt review`: it left your queue, usually because you approved it or it went on hold. |
| `limit?` | `limit` | The current result was cut off by `--limit` and the row was among the last ones of the previous result, as many rows as were added. It probably still matches; it just no longer fits. |
| `scope` | `scope` | The two snapshots used different scopes (only seen with `--diff-force`). |
| `?` | `unknown` | It wasn't open in the previous snapshot. |

Snapshots record whether the query matched more rows than `--limit` kept
(`has_more` in `tkt snapshot show --format json`; absent when it did not). A
baseline saved before this was recorded never says `limit?` for its own run,
since only the current result's flag is used.

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
| `--diff-format {table,json}` | Format for `--diff`/`--watch` output (default `table`). |
| `--diff-include-unchanged` | Include unchanged rows in the diff view (default: only changes shown). |
| `--diff-force` | Proceed with the diff even if the snapshot scope doesn't match the current query. |
| `--diff-resolve` | Look up each gone (`-`) row and say why (`closed`, `merged`, `still open`, `not found`) instead of guessing. See [Why a row is gone](#why-a-row-is-gone). |

`--watch NAME` is the common agent idiom: it diffs against the previous
`NAME` and then overwrites `NAME` with the fresh result, so the next hour
diffs against *this* hour. An empty result is still a snapshot: when the
last item in scope closes, `--watch` reports it as a `-` row and saves an
empty baseline.

### Staging a baseline with `--diff`

A person at a terminal uses `--watch NAME`. A job uses `--diff NAME`, handles the
rows, then runs `tkt snapshot ack`:

```bash
tkt pr list --diff poll --diff-format json > poll.json   # diff against baseline "poll"
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

With `--diff-format json`, the document has a top-level `"baseline"`: `"found"`
or `"missing"`. When it is `"missing"`, the rows are all `added`, and the notice
`No snapshot … found` goes to stderr. A job can treat a first run differently
without parsing stderr.

### Scope matching

The query filter set (board, author or `--all-authors`, reviewer, repos, explicit
`owner/repo#N` refs, states, labels, `--all`, limit, and the
[date window](#date-window-filtering)) is persisted with
every snapshot. `repos` is the list actually queried (`--repo`, else the
board's repos at run time), so adding or removing a repo on the board
counts as a scope change. Repos and refs are compared as sets, so their
order doesn't matter. The window is recorded as typed, so `--since 14`
matches `--since 14` on any later day, while `--since 14` against
`--since 3`, or against no window at all, is a scope change; the error
(or the `window:` line under the summary) names both windows. If the
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

A snapshot file that is not valid, or lacks a required field, is an error that
names the snapshot and the file. `tkt snapshot rm KIND/NAME` deletes it.
`tkt snapshot list` skips such a file and warns on stderr.

```bash
# hourly agent loop
tkt pr list    --board oh --watch hourly
tkt issue list --board oh --watch hourly
tkt review                 --watch hourly
```

---

## Date-window filtering

`tkt issue list`, `tkt pr list`, and `tkt review` accept a shared set of options
to restrict results to a recent time window. They translate directly into the
GitHub search date qualifiers (`created:`, `updated:`, `merged:`, `closed:`), so
you no longer have to run a separate GitHub search and pipe refs back in.

| Option | Description |
| --- | --- |
| `--since DAYS` | Relative window: from the start of the UTC day N days ago |
| `--after YYYY-MM-DD` | Absolute lower bound (inclusive) |
| `--before YYYY-MM-DD` | Absolute upper bound (inclusive) |
| `--date-field FIELD` | Which date to filter on: `created`, `updated`, `merged`, `closed` |

Semantics:

- `--since N` is shorthand for `--after <today minus N days>`, where "today" is
  the current **UTC** date. It reaches back to the start of that UTC day, not
  to N × 24 hours ago, so `--since 0` means "today (UTC)". It mirrors the
  `--since` flag already used by `tkt board scan`.
- `--after` and `--before` may be combined to express a closed interval; using
  both renders as `field:AFTER..BEFORE`.
- `--since` cannot be combined with `--after`/`--before`.
- **Date field selection.** If `--date-field` is not given, the field is
  inferred from the state being queried: a `--merged`-only listing filters on
  `merged:`, a `--closed`-only listing on `closed:`, and everything else on
  `updated:`. Pass `--date-field` to override (for example, filter merged PRs by
  when they were `created`).
- **The window is reported.** A listing that used a window ends with a
  `Window: merged ≥ 2026-09-26 (UTC)` line, and an empty result names it too
  (`No PRs found (merged ≥ 2026-09-26, UTC).`), so a window that is narrower
  than you meant is visible rather than silent.
- **Window with `--watch`/`--diff`/`--snapshot`.** The window is part of the
  snapshot's [scope](#scope-matching).

Combinations that cannot do what they say are errors (exit 1), not silent
no-ops:

| Command | Why it is rejected |
| --- | --- |
| `--date-field` with no `--since`/`--after`/`--before` | There is no window for it to apply to. |
| `--since`/`--after`/`--before` with explicit refs (`owner/repo#N`, or refs piped on stdin) | Refs list exactly the items named; a window can't narrow them. Drop one or the other. |
| `--date-field merged` without `--merged` | Only merged items have a merge date, so nothing can match. |
| `--date-field closed` without `--closed` (or `--merged`) | Open items have no close date. |
| `--date-field merged` on `tkt issue list` | Issues are never merged. |

```bash
tkt pr list --author ak684 --merged --since 14        # merged in the last 2 weeks
tkt issue list --after 2026-08-01 --before 2026-08-31 # opened/updated in August
tkt pr list --merged --date-field created --since 30  # merged, created in last 30d
tkt review --merged --since 7                         # reviewed & merged this week
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
  did. The author's login is in the JSON outputs (`--diff-format json`,
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

### AI actors

Every event also carries an **actor class**, shown in JSON (the `events` list of each
`tkt snapshot` item, one entry per history character, as `actor_class`):

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
a comment, review or opened item (the PR or issue body). Histories with no AI actors
render exactly as before.

An item an AI actor opened starts with `s` / `S` instead of `o` / `O`. Each later event
of an AI actor changes its letter too: `A` becomes `V` and `c` becomes `n`, so `oAcm` in
0.3.0 is `sVnm` now. A snapshot saved before AI actors were recognised holds the old
letters, so the first diff against it reports each row an AI actor took part in as
`history-rewritten`, once. See [Upgrading to 1.0](#upgrading-to-10).

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

`tkt issue list` also prints a one-line legend beneath the table, so the
encoding is self-documenting at the terminal.

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
