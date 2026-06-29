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

## Development

```bash
pip install -e ".[dev]"
pytest                             # run the test suite
ruff check .                       # lint
```
