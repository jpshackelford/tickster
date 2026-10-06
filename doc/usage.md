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
- [`tkt snapshot`](#tkt-snapshot)
- [Snapshots & diffs](#snapshots--diffs)
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

`tkt` talks to the GitHub API and reads credentials from the environment. A
local `.env` file in the working directory is loaded automatically.

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
by you.

```bash
tkt issue list [OWNER/REPO#NUM ...]
```

| Option | Description |
| --- | --- |
| `--author, -a USER` | Filter by issue author (default: current user) |
| `--repo OWNER/REPO` | Filter by repo (repeatable) |
| `--board, -b NAME` | Use repos from the named board |
| `--label, -l LABEL` | Filter by label. Repeat for AND (`-l bug -l urgent`), comma for OR (`-l bug,stale`) |
| `--open, -O` | Show open issues (default) |
| `--closed, -C` | Show closed issues |
| `--all, -A` | Show all states (open + closed) |
| `--limit, -n N` | Max issues to show (default: 100) |
| `--title, -t` | Show issue titles |
| `--activity, -s` | Sort by recent activity instead of creation date |

```bash
tkt issue list                              # your open issues
tkt issue list --repo octocat/hello-world   # one repo
tkt issue list --all --title -l bug         # all states, titles, bug label
tkt issue list octocat/hello-world#42       # a specific issue
```

Also accepts `--snapshot`, `--diff`, `--watch` for change-since-last-run
output — see [Snapshots & diffs](#snapshots--diffs).

## `tkt pr`

List pull requests with a compact history visualization. Accepts PR refs as
arguments or piped on stdin.

```bash
tkt pr list [OWNER/REPO#NUM ...]
```

| Option | Description |
| --- | --- |
| `--author, -a USER` | Filter by author (`me` = current user) |
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

```bash
tkt pr list --author me                     # your open PRs
tkt pr list --merged --graph                # merge cadence graph
tkt pr list octocat/hello-world#7           # a specific PR
```

Also accepts `--snapshot`, `--diff`, `--watch` for change-since-last-run
output — see [Snapshots & diffs](#snapshots--diffs).

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

```bash
tkt review                                  # your actionable review queue
tkt review --all --title                    # full queue with titles
tkt review -X "dependabot[bot]"             # hide dependabot PRs
```

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

## `tkt snapshot`

Manage saved query snapshots stored under `~/.tkt/snapshots/`. Snapshots
are the raw input to the diff view documented in
[Snapshots & diffs](#snapshots--diffs) below.

```bash
tkt snapshot list [--kind {pr,issue,review}]
tkt snapshot show KIND/NAME [--format {table,json}]
tkt snapshot rm   KIND/NAME [KIND/NAME ...]
tkt snapshot diff PREV CURR  [--all] [--format {table,json}]
```

- `KIND/NAME` refs use `/` as the separator, e.g. `pr/hourly`,
  `issue/last-week`, `review/nightly`. Kind must be one of `pr`, `issue`,
  `review` — the three list commands that produce snapshots.
- Named snapshots overwrite in place; auto-timestamped snapshots (from
  bare `--snapshot`) are named `ts-YYYYMMDDTHHMMSSZ` so they coexist.

```bash
tkt snapshot list                               # all stored snapshots
tkt snapshot show pr/hourly                     # dump a snapshot as a table
tkt snapshot diff pr/hourly pr/last-week        # compare two snapshots
tkt snapshot diff pr/hourly pr/later --format json  # machine-readable
tkt snapshot rm pr/hourly issue/hourly
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

A one-line summary header shows how long ago each snapshot was captured,
the counts, and whether the two snapshots were produced by the same scope
(same board, author, repos, refs, states, labels, limit). Exact capture
times are in `tkt snapshot show` and `--diff-format json`.

```
diff pr/hourly: 1h ago → 4s ago  (+2 new, *5 changed, -1 gone, 29 unchanged)

Δ Repo                  PR     History      CI      State   💬   Last     Note
+ OpenHands/docs        #42    [oCL]        --      open    --   5m ago
* OpenHands/OpenHands   #1234  oRfA[fR]     red!    open    2    1m ago
- OpenHands/infra       #87    oCax         --      open    --   1d ago   closed?

Δ: + new row, * changed, - gone (Note: likely why), (blank) unchanged.  History: [bracketed] = new since last snapshot.  Field!: value changed; prior value via `tkt snapshot diff`.
```

### Why a row is gone

The Note on a `-` row is a hint, not a fact: the snapshot only knows the
row is no longer in the result.

| Note | JSON `disappearance_reason` | Meaning |
| --- | --- | --- |
| `closed?` | `closed-or-gone` | `pr list` / `issue list`: it was open and no longer matches, most likely closed or merged (or deleted / transferred). |
| `done?` | `left-queue` | `tkt review`: it left your queue, usually because you approved it or it went on hold. |
| `scope` | `scope` | The two snapshots used different scopes (only seen with `--diff-force`). |
| `?` | `unknown` | It wasn't open in the previous snapshot. |

Other things can also drop a row: it fell past `--limit`, a filter
attribute changed (label removed, review request withdrawn), or GitHub's
search index briefly lagged.

### Shared flags on list commands

All three list commands accept the same snapshot flags:

| Flag | Meaning |
| --- | --- |
| `--snapshot [NAME]` | Save the result. With NAME, overwrites that snapshot. Without NAME, auto-timestamps. |
| `--diff NAME` | Diff the current query result against snapshot NAME. |
| `--watch NAME` | Shortcut for `--diff NAME --snapshot NAME` — the hourly-cron idiom. |
| `--diff-format {table,json}` | Format for `--diff`/`--watch` output (default `table`). |
| `--diff-include-unchanged` | Include unchanged rows in the diff view (default: only changes shown). |
| `--diff-force` | Proceed with the diff even if the snapshot scope doesn't match the current query. |

`--watch NAME` is the common agent idiom: it diffs against the previous
`NAME` and then overwrites `NAME` with the fresh result, so the next hour
diffs against *this* hour. An empty result is still a snapshot: when the
last item in scope closes, `--watch` reports it as a `-` row and saves an
empty baseline.

### Scope matching

The query filter set (board, author, reviewer, repos, explicit
`owner/repo#N` refs, states, labels, `--all`, limit) is persisted with
every snapshot. `repos` is the list actually queried (`--repo`, else the
board's repos at run time), so adding or removing a repo on the board
counts as a scope change. Repos and refs are compared as sets, so their
order doesn't matter. If the current query's scope doesn't match the
snapshot's scope, the diff refuses to render in either table or JSON mode
and exits 2 without touching the baseline, so you can rerun with
`--diff-force` to proceed (the summary is tagged `[scope-changed]` so you
can see what happened).

### Storage

Snapshots live as JSON files under `~/.tkt/snapshots/<kind>-<name>.json`.
Each file is small, inspectable with a text editor, and trivial to gist
if you want to share. Overwriting an existing name is atomic.

```bash
# hourly agent loop
tkt pr list    --board oh --watch hourly
tkt issue list --board oh --watch hourly
tkt review                 --watch hourly
```

---

## History strings

The most token-dense feature of `tkt`: instead of a verbose timeline, every
issue and PR row carries a compact **history string** that encodes its whole
lifecycle as one character per event. An entire review-and-merge cycle fits in a
handful of characters (e.g. a PR history of `oRfAM`).

Two conventions apply to every history string:

- **Case = who acted.** Lowercase = the reference user (you, or whoever
  `--reviewer`/`--author` selects); UPPERCASE = someone else.
- **Consecutive duplicates collapse.** Ten review comments in a row render as a
  single `C`, so the string stays short and skimmable.

### PR history characters

Used by `tkt pr list` and `tkt review`.

| Char | Meaning |
| --- | --- |
| `o` | Opened |
| `h` | Review requested |
| `r` | Changes requested (a review) |
| `a` | Approved |
| `c` | Comment |
| `f` | Fix — commits pushed after a review (commits before the first review are ignored) |
| `m` | Merged |
| `k` | Killed — closed without merging (not shown if merged) |

Example: `oRfAM` = *you* opened the PR, someone requested changes (`R`), *you*
pushed fixes (`f`), someone approved (`A`), someone merged (`M`).

### Issue history characters

Used by `tkt issue list`.

| Char | Meaning |
| --- | --- |
| `o` | Opened |
| `c` / `C` | Comment (lowercase = you, uppercase = other human) |
| `B` | Bot comment (always uppercase) |
| `l` / `L` | Label added (lowercase = you, uppercase = other human or bot) |
| `a` | Assigned |
| `x` | Closed |
| `r` | Reopened |
| `p` | Linked to an implementing PR |

Examples:

- `oCLx` — opened, another user commented, labelled, then closed.
- `oclBLx` — opened, you commented and labelled, a bot commented (`B`) and
  labelled (`L`), then closed.
- `oCpx` — opened, got a comment, linked to a PR, closed.

### Bot detection

Bot **comments** get the distinct `B` marker (bot labels use `L`, like other
humans). A username is treated as a bot when it ends in `[bot]` or appears in the
configurable list under `[issue]` in `~/.tkt/config.toml`. Default recognised
bots include `github-actions[bot]`, `stale[bot]`, `dependabot[bot]`,
`renovate[bot]`, `allcontributors[bot]`, `codecov[bot]`, and `sonarcloud[bot]`.

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
| `TKT_LOG_API` | Set to `1`/`true` to log raw GitHub API calls (debugging) |
| `TKT_LOG_API_DIR` | Directory for API logs when `TKT_LOG_API` is enabled |
