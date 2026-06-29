# tickster (`tkt`)

Token-efficient tools for agents (and humans) to view and manage developer
tracker data from the command line. The output is compact and structured so it
costs few tokens when handed to an LLM agent.

Today `tickster` covers **GitHub**: issues, pull requests, review queues, and
GitHub Project boards. Support for additional trackers (e.g. Linear, HappyFox)
is planned behind the same compact CLI.

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
tkt review list                    # list PRs awaiting review
tkt board status                   # show project board status
tkt repo add owner/name            # track a repo on a board
tkt --version
```

Run `tkt <command> --help` for the full set of options on each subcommand
(`issue`, `pr`, `review`, `board`, `repo`).

See **[doc/usage.md](doc/usage.md)** for the complete usage guide: every command
and option, configuration, stdin piping, and environment variables.

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
