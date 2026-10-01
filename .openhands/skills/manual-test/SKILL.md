---
name: manual-test
description: Blackbox-test a tickster PR through the `tkt` CLI and post a structured results comment. Required before code review; repeat after behavior-changing review fixes.
triggers:
  - /manual-test
  - /test-pr
  - manual test
  - blackbox test
---

# Manual Test (tickster)

Run manual blackbox tests for a PR against the `tkt` CLI and post a structured results comment to the PR. Required before code review. Repeat after review changes that alter behavior (>50 LOC non-test changes, or any user-visible change).

Not required when only tests, docs, comments, or type hints changed.

## Preconditions

- CI is green on the PR head.
- `GITHUB_TOKEN` is set in the environment (tickster reads it to call the GitHub API). A `.env` is loaded automatically if present.

## 1. Set up the environment

```bash
gh repo clone jpshackelford/tickster /tmp/tickster-test 2>/dev/null || true
cd /tmp/tickster-test
gh pr checkout {pr_number}
uv sync --extra dev
uv run tkt --version
uv run tkt --help
```

## 2. Read the PR

```bash
gh pr view {pr_number}
gh pr diff {pr_number} --name-only
gh pr diff {pr_number}
```

Identify every user-visible surface the PR adds or changes:

- new subcommands (`tkt <group> <cmd>`)
- new or changed flags on existing commands
- new output columns, formats, or exit codes
- new on-disk state (files under `~/.tkt/`, `.env`, config)
- new error paths

Each one is a test case.

## 3. Design test scenarios

For every surface identified in step 2, cover:

- **Happy path** — normal invocation, as a user would type it.
- **Edge cases** — empty input, missing auth, no matching rows, invalid flag combos, scope mismatch, etc.
- **Output formats** — if the command supports `--format json` / `--format table` (or similar), test both; verify JSON parses with `python -c 'import json,sys;json.load(sys.stdin)'`.
- **Integration** — pipe into / out of other `tkt` commands where documented.
- **README/`doc/usage.md` examples verbatim** — copy each example that touches changed code and run it unchanged. If an example fails or output differs materially, that is a test failure; note it.

## 4. Execute tests

Run through the CLI. **Only the CLI.** Record for each test: command, expected result, actual output (verbatim), pass/fail.

```bash
# example
uv run tkt pr list --board oh --diff
# Expected: Δ column present; summary line shows +/*/- counts
# Result: ✅ PASS
```

## 5. Run the dev suite

```bash
uv run pytest -q
uv run ruff check src tests
uv run ruff format --check src tests
uv run basedpyright src
```

All four must be clean. Record the pytest count and any failures.

## 6. Post the test report

Post a single PR comment using the template in the next section:

```bash
gh pr comment {pr_number} --body "$(cat <<'EOF'
<report body — see template below>
EOF
)"
```

Verify the comment appeared (`gh pr view {pr_number} --comments | tail -40`). Done.

## Test report template

```markdown
## Manual Test Results for PR #{N}

_This comment was created by an AI agent (OpenHands) on behalf of @jpshackelford._

### Setup

- Branch: `{branch}` @ `{short_sha}`
- Python: `{python --version}`
- `tkt --version`: `{version}`
- Install: `uv sync --extra dev`
- Auth: `GITHUB_TOKEN` set ✅

### Summary

| # | Command | Status | Notes |
|---|---------|--------|-------|
| 1 | `tkt …` | ✅ PASS | |
| 2 | `tkt …` | ✅ PASS | |
| 3 | `tkt …` | ❌ FAIL | {what broke} |

### Detailed results

#### Test 1 — {name}

**Command**
```bash
uv run tkt …
```

**Expected:** {one line}

**Actual**
```
{verbatim output}
```

**Result:** ✅ PASS

---

#### Test 2 — {name}
…

### Dev suite

| Check | Result |
|---|---|
| `uv run pytest -q` | {N} passed |
| `uv run ruff check src tests` | clean |
| `uv run ruff format --check src tests` | clean |
| `uv run basedpyright src` | 0 errors, 0 warnings |

### Verdict

{All tests pass. / {N} pass, {M} fail — details above.}
```

## Re-test report template

Used after review-driven behavior changes. Shorter: context + diff since last test, delta table, regression check.

```markdown
## Re-Test Results for PR #{N} (Round {K})

_This comment was created by an AI agent (OpenHands) on behalf of @jpshackelford._

### Context

Re-testing after round {K-1}. Changes since last test:
- {change 1}
- {change 2}

### Delta

| Area | Previous | Current | Notes |
|------|----------|---------|-------|
| {area} | ✅ PASS | ✅ PASS | no regression |
| {new area} | — | ✅ PASS | new coverage |

### New / changed tests

#### Test — {name}
**Command:** `uv run tkt …`
**Purpose:** {what review change we're verifying}
**Result:** ✅ PASS

### Regression check

All {N} tests from the previous round still pass ✅.

### Dev suite

| Check | Result |
|---|---|
| `uv run pytest -q` | {N} passed |
| `uv run ruff check src tests` | clean |
| `uv run ruff format --check src tests` | clean |
| `uv run basedpyright src` | 0 errors, 0 warnings |

### Verdict

{All changes verified. No regressions. / …}
```

## Valid vs invalid tests

### ✅ Valid — blackbox CLI

```bash
uv run tkt pr list --board oh --diff
uv run tkt snapshot show my-snap --format json
uv run tkt review --watch hourly
```

### ❌ Invalid — bypasses the CLI

```python
# importing internals is a unit test, not a manual test
from tickster.snapshot.diff import diff_snapshots
diff_snapshots(a, b)
```

```bash
# python -c against internals is a unit test, not a manual test
python -c "from tickster.pr.cli.list_cmd import run; run()"
```

Rule: **if a user cannot type it at a shell prompt, it is not a manual test.** Internal-function coverage belongs in `tests/`, under pytest.

## Rules

- Only CLI calls (`uv run tkt …`) count as manual tests.
- Paste real output. Never paraphrase, never fabricate.
- Test every new flag, subcommand, and output format the PR introduces.
- Run `pytest`, `ruff check`, `ruff format --check`, and `basedpyright src` every round.
- Attribution line is required on every posted comment.
- One comment per round. Do not edit prior rounds; post a new comment.

## Failure handling

- Bug found → document it in the report, post the report with failures noted, exit.
- Setup fails → report the specific error, do not post a partial pass report.
