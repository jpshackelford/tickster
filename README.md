# tickster (`tkt`)

Token-efficient tools for agents (and humans) to view and manage developer
tracker data from the command line. The output is compact and structured so it
costs few tokens when handed to an LLM agent.

Today `tickster` covers **GitHub**: issues, pull requests, review queues, and
GitHub Project boards. Support for additional trackers (e.g. Linear, HappyFox)
is planned behind the same compact CLI.

## Why "token efficient"?

GitHub's own API (and the `gh` CLI) returns deeply nested JSON. Dropping a PR
timeline or an issue list straight into an LLM prompt burns thousands of tokens
on punctuation, URLs, and fields the model does not need — and the agent still
has to reason over raw events to figure out what matters. `tkt` does that
reasoning up front and emits a dense, one-row-per-ticket view instead. Four
design choices make it cheap to feed to an agent:

**1. History strings — a whole lifecycle in a few characters.** Every issue and
PR row carries a compact code where each character is one event and case shows
who acted (lowercase = you, UPPERCASE = others). A full open → changes-requested
→ fix → approve → merge cycle is just `oRfAM`. Consecutive duplicates collapse,
so ten review comments are a single `C`.

```
Repo              Issue   History     PR       Labels              State    Age      Last
owner/repo        #123    oCLxr       #456     bug,help wanted     open     15d      2d ago
owner/repo        #124    olc         --       enhancement         open     3d       1h ago
other/repo        #42     oClLCBx     #78      bug,stale           closed   45d      10d ago
```

That `oClLCBx` replaces what would be a page of JSON timeline objects. See the
[history string reference](doc/usage.md#history-strings) for the full legend.

**2. Only signal-bearing columns.** Each row shows just what drives a decision —
history, CI status (`green`/`red`/`pending`/`conflict`), state, age, last
activity, and the count of unresolved review threads — not the dozens of fields
the API hands back.

**3. Computed answers, not raw data.** `tkt review` tells you *what action you
owe each PR* (`review`, `re-review`, `hold`, `approved`) and how long it has been
waiting, instead of making you (or the agent) derive that from raw review events.

**4. Query and filter at the source.** Author, reviewer, label (with AND/OR),
repo, and board filters — plus stdin piping of refs — mean the agent fetches
exactly the slice it needs rather than pulling everything and filtering in the
model.

## Install

```bash
pip install -e ".[dev]"
```

This installs the `tkt` command.

## Authentication

`tickster` reads a GitHub token from the environment (a local `.env` file is
loaded automatically):

```bash
export GITHUB_TOKEN=ghp_...        # required for GitHub access
export GIST_TOKEN=ghp_...          # optional; used for board state gists
```

## Usage

```bash
tkt issue list                     # list open issues
tkt pr list                        # list open pull requests
tkt review                         # list PRs awaiting your review
tkt board status                   # show project board status
tkt repo add owner/name            # track a repo on a board
tkt --version
```

Run `tkt <command> --help` for the full set of options on each subcommand
(`issue`, `pr`, `review`, `board`, `repo`).

Documentation:

- **[doc/usage.md](doc/usage.md)** — complete usage guide: every command and
  option, the [history string reference](doc/usage.md#history-strings),
  configuration, stdin piping, and environment variables.
- **[doc/board.md](doc/board.md)** — full board reference: scopes, workflow
  columns, column assignment rules, YAML configuration, macros, and gist sync.

## Development

```bash
pip install -e ".[dev]"
pytest                             # run the test suite
ruff check src tests               # lint
ruff format --check src tests      # format check
basedpyright src                   # type check
```

CI (`.github/workflows/ci.yml`) runs lint, format check, type check, and tests
on every push and pull request. Releases are automated with
[release-please](https://github.com/googleapis/release-please) via
`.github/workflows/release-please.yml`; the version lives in `src/_version.py`.

An optional automated PR reviewer
(`.github/workflows/pr-review-by-openhands.yml`) runs when a PR is opened,
marked ready for review, or labelled `review-this`. It requires an `LLM_API_KEY`
repository secret.
