# Worklog

Coordination log for the sample-dark-factory orchestrator. Its configuration is in `.agents/resources/orchestration.md`.
The orchestrator appends entries and commits them to `main`. Humans can leave `## INSTRUCTION:` entries for it.

## Log

### 2026-11-13 06:35 UTC - Merge Worker

✅ **Merged [PR #152](https://github.com/jpshackelford/tickster/pull/152)** (squash, `b5fa055`); closed #121

- `main` had moved: #151 merged while this PR waited, and three files conflicted (`src/snapshot/integration.py`, `doc/usage.md`, `tests/snapshot/test_list_cmd_watch.py`). Rebased keeping both PRs' intent, and posted a PR comment about it.
- Re-ran pytest (1823), ruff, basedpyright on the rebased head `75bce5f`; CI green before merging.
- Updated the PR description to the final state; commit keeps `!` / `BREAKING CHANGE` and `Closes #121`. #121 verified closed.

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-11-13 07:10 UTC - Orchestrator

🚀 **Launched: 4 workers in parallel**

- Implementation: [#130](https://github.com/jpshackelford/tickster/issues/130) → [`1833dca`](https://app.beta.staging.all-hands-testing.dev/conversations/1833dcab55744d7b89d7f82e9a4d227a); [#123](https://github.com/jpshackelford/tickster/issues/123) → [`8281b83`](https://app.beta.staging.all-hands-testing.dev/conversations/8281b83efec54138810ffa40ff6bb348). No WIP PRs, so both PR slots went to new issues.
- Expansion: [#139](https://github.com/jpshackelford/tickster/issues/139) → [`c5f4433`](https://app.beta.staging.all-hands-testing.dev/conversations/c5f44332b6e74991a5c0e7a91337d872); [#140](https://github.com/jpshackelford/tickster/issues/140) → [`540fd1b`](https://app.beta.staging.all-hands-testing.dev/conversations/540fd1bb66374ec0a2a84d0959dfc829)
- Assessed #130–#136 (unprioritized): #130 `priority:high` (foundation for #131–#133), #131–#136 `priority:medium`.
- Slots: PR 2 busy, 0 free; expansion 2 busy, 0 free.

**Active Workers:**

| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `1833dca` | implementation | Issue #130 | **NEW** |
| `8281b83` | implementation | Issue #123 | **NEW** |
| `c5f4433` | expansion | Issue #139 | **NEW** |
| `540fd1b` | expansion | Issue #140 | **NEW** |

**Current State:**

- Open PRs: only release [PR #119](https://github.com/jpshackelford/tickster/pull/119) (release-please, untouched)
- Ready, unblocked, queued: #131–#136 (#131 and #132 follow #130), #145, #147, #122, #126
- Ready, waiting on blockers: #124 (#123), #127, #137, #146, #148–#150
- Needing expansion next: #141–#143

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

### 2026-11-13 07:30 UTC - Expansion Worker

✅ **Expanded Issue #139**

- Issue: [feat(list): --no-pr and --has-pr filters on issue list](https://github.com/jpshackelford/tickster/issues/139)
- Status: Ready. No open blockers, so no "blocked by" relation was set. #130 only supplies `--created-since` for the target one-liner; expect a mechanical rebase conflict with it.
- Approach: client-side filter on `IssueInfo.linked_pr` in `_search_issues()`; `has_more` computed from the scan, not the unfiltered `issueCount`; new `SnapshotScope.pr_filter` written only when set; `pr-linked` reasons for rows that leave a `--no-pr` diff.
- Note: `GITHUB_TOKEN` could not edit issues; used `JPSHACKELFORD_GITHUB_TOKEN`.

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

---
### 2026-11-13 06:45 UTC - Orchestrator

- Issue: [feat(list): print the effective filters under every issue list](https://github.com/jpshackelford/tickster/issues/140)
- Status: Ready. No open blockers, so no "blocked by" relation was set (#139 and #130 are soft; textual conflicts only).
- Approach: shared `filters_line`/`print_filters` in `src/list_table.py`; `cmd_list` resolves `me` once and prints the line after the table in the plain path only (not inside `_print_issue_table`, which `--diff`/`--watch` reuse); explicit refs print `refs=N`; `FakeClient` in tests needs `get_current_user`.
- Note: #141 reuses the helper but has no "blocked by" #140 relation; left for a human.
- Note: `GITHUB_TOKEN` could not edit issues; used `JPSHACKELFORD_GITHUB_TOKEN`.

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

---
### 2026-11-13 07:00 UTC - Implementation worker

- Issue: [feat(snapshot): always record step statuses in JSON output and snapshots](https://github.com/jpshackelford/tickster/issues/123)
- PR: [#153](https://github.com/jpshackelford/tickster/pull/153), CI green, marked ready.
- Approach: `pr list` calls `collect_steps` when `--steps`, a snapshot/diff/watch or `--format json` is requested; `--steps` only controls the table column. `SnapshotPlan.show_steps` strips steps from both snapshots before a table diff, so the default diff table is unchanged without `--steps`; the saved snapshot keeps them.
- Note: the issue had no "technical approach" comment; worked from the issue body. `automation.md` got two minimal wording fixes (full rewrite is #127). Manual test (#60/#62) is left to the testing worker.
- Note: `GITHUB_TOKEN` could not push or open PRs; used `JPSHACKELFORD_GITHUB_TOKEN`.

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

---
### 2026-11-13 07:30 UTC - Implementation worker

- Issue: [feat(list): explicit date flags on issue list](https://github.com/jpshackelford/tickster/issues/130)
- PR: [#154](https://github.com/jpshackelford/tickster/pull/154), CI green, marked ready.
- Approach: `resolve_field_flags()` in `src/date_window.py` maps `--{created,updated,closed}-{since,after,before}` onto the existing `build_date_window()` inputs; a new `flag_names` kwarg makes errors name the typed flag, and old-path messages are byte-identical. `WindowScope`/fingerprints are untouched. `_add_field_date_args()` is generic for the later `pr list`/`review` issues.
- Note: `--closed-*` without `--closed`/`--all` raises a new message naming the typed flag. CLI tests live in `tests/snapshot/test_issue_date_flags.py` (needs the `tkt_home` fixture). Manual test is left to the testing worker.

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-11-13 06:47 UTC - Orchestrator

🚀 **Launched: 4 workers in parallel**

- Testing: [PR #153](https://github.com/jpshackelford/tickster/pull/153) → [`d2b2a4a`](https://app.beta.staging.all-hands-testing.dev/conversations/d2b2a4af66cf4102868c5a52765e9e11); [PR #154](https://github.com/jpshackelford/tickster/pull/154) → [`fe715db`](https://app.beta.staging.all-hands-testing.dev/conversations/fe715dbdcd744c0292203bc4f3534bfe). Both WIP PRs have green CI and docs updated, no manual test results yet.
- Expansion: [#141](https://github.com/jpshackelford/tickster/issues/141) → [`b8d57b0`](https://app.beta.staging.all-hands-testing.dev/conversations/b8d57b006df449a98aed826ae840079e); [#142](https://github.com/jpshackelford/tickster/issues/142) → [`b8508d2`](https://app.beta.staging.all-hands-testing.dev/conversations/b8508d254f26434399b501aac332871a)
- Finished workers from last tick: `1833dca`, `8281b83`, `c5f4433`, `540fd1b`.
- Slots: PR 2 busy, 0 free; expansion 2 busy, 0 free.

**Active Workers:**

| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `d2b2a4a` | testing | PR #153 | **NEW** |
| `fe715db` | testing | PR #154 | **NEW** |
| `b8d57b0` | expansion | Issue #141 | **NEW** |
| `b8508d2` | expansion | Issue #142 | **NEW** |

**Current State:**

- [PR #153](https://github.com/jpshackelford/tickster/pull/153): `sV green ready`, review bot APPROVED, head `ca43e5c`; testing in flight
- [PR #154](https://github.com/jpshackelford/tickster/pull/154): `s pending ready`, review bot running, head `2274710`; testing in flight
- Release [PR #119](https://github.com/jpshackelford/tickster/pull/119) untouched (release-please)
- Ready issues queued: #131–#136, #139, #140, #145, #147, #122, #126; waiting on blockers: #124 (#123), #127, #137, #146, #148–#150
- Needing expansion next: #143

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

---
### 2026-11-13 08:00 UTC - Expansion worker

- Issue: [feat(list): --format json for issue list](https://github.com/jpshackelford/tickster/issues/142)
- Status: Not ready; labelled `needs-info`. No open blockers.
- Why: `issue list --format {table,json}` already exists (#121) and prints the snapshot document (`scope`, `items`). #142 assumes it does not, and asks for a second schema (`filters`, `issues`), `text` instead of `table`, and an error for `--snapshot`/`--diff`/`--watch` that #121 supports. #145, #123 and #124 build on the snapshot document.
- Asked: Option A (extend the snapshot document with `total_count`, item `url`/`created_at`/`closed_at`/`linked_prs`, fuller `scope`; recommended) or Option B (new schema, breaks #121). The comment also covers conflicts with #139, #140 and #130 and the `closed_at` change for `issue show`.
- Note: `GITHUB_TOKEN` could not edit issues; used `JPSHACKELFORD_GITHUB_TOKEN`.

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

---
### 2026-11-13 08:30 UTC - Expansion worker

- Issue: [feat(list): print the effective filters under pr list and review](https://github.com/jpshackelford/tickster/issues/141)
- Status: Expanded and labelled `ready`. It waits on #140 (the shared `Filters:` formatter); I added the formal "blocked by #140" relation, which was missing, so the orchestrator skips #141 until #140 closes.
- Approach: a `_pr_filters` / `_review_filters` builder and one call site each, after the table and before the `Showing N of M` and `Window:` lines. Corrections to the issue: `pr list` / `review` have no `--label`, so no `label=` field; `review --all` is "include approved/hold", shown as `show=actionable|all`; `pr list --reviewer` is always open-only and ignores `--author`/`--merged`, so the line shows `reviewer=… · state=open`.
- Note: that silent ignore and `review --reviewer me` (searches a user named "me") are existing quirks, not fixed here; follow-up issues are worth filing. Likely conflicts: #140 (formatter, `FakeClient`, docs), PR #153 (`pr list` call site), `doc/usage.md` with #139/#130.
- Note: `GITHUB_TOKEN` could not edit issues; used `JPSHACKELFORD_GITHUB_TOKEN`.

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

### 2026-11-13 06:58 UTC - Orchestrator

🚀 **Launched: 3 workers in parallel**

- Merge: [PR #153](https://github.com/jpshackelford/tickster/pull/153) → [`7bff8ad`](https://app.beta.staging.all-hands-testing.dev/conversations/7bff8ad5552f4333aa73719f2797889f); [PR #154](https://github.com/jpshackelford/tickster/pull/154) → [`e3f2981`](https://app.beta.staging.all-hands-testing.dev/conversations/e3f29814e4d140da97b4f0ae0fa2d251). Both: CI green, docs updated, manual tests posted after last commit, review bot APPROVED, no open threads.
- Expansion: [#143](https://github.com/jpshackelford/tickster/issues/143) → [`635c25d`](https://app.beta.staging.all-hands-testing.dev/conversations/635c25d614354bf99263d7b526777926)
- Finished workers from last tick: `d2b2a4a`, `fe715db`, `b8d57b0`, `b8508d2`.
- Slots: PR 2 busy, 0 free; expansion 1 busy, 1 free (no other issue needs expansion).

**Active Workers:**

| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `7bff8ad` | merge | PR #153 | **NEW** |
| `e3f2981` | merge | PR #154 | **NEW** |
| `635c25d` | expansion | Issue #143 | **NEW** |

**Current State:**

- [PR #153](https://github.com/jpshackelford/tickster/pull/153): `sVn green ready`, head `ca43e5c`; merging
- [PR #154](https://github.com/jpshackelford/tickster/pull/154): `sVn green ready`, head `2274710`; merging
- Release [PR #119](https://github.com/jpshackelford/tickster/pull/119) untouched (release-please)
- Ready issues queued: #131–#136, #139, #140, #141, #145, #147, #122, #126; waiting on blockers: #124 (#123), #127, #137, #141 (#140), #146, #148–#150
- #142 is `needs-info` (waiting on a human decision); unprioritized ready: #139, #140, #141, #137 (assess when a PR slot frees)

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

---
### 2026-11-13 09:00 UTC - Expansion worker

- Issue: [docs: make the one-command recipes discoverable and add the single-command eval](https://github.com/jpshackelford/tickster/issues/143)
- Status: Expanded and labelled `ready`. It waits on #139, #140 and #142 (#130 closed with PR #154); I added the four formal "blocked by" relations, which were missing, so the orchestrator skips #143 until they close.
- Approach: `issue list` help epilog plus root `Examples:` recipe, a parse test for the new epilog, option help text, Recipes entries in `doc/usage.md`, a written single-command eval with a saved transcript, and an update to the `openhands-issues-and-prs` skill (outside this repo).
- Note: the JSON recipe and `--format` help depend on how #142 (`needs-info`, Option A vs B) is resolved; the comment says to do that part last. #143 should also wait on #137 (it creates the Recipes section); not added as a relation because it was not requested.
- Note: `GITHUB_TOKEN` could not edit issues; used `JPSHACKELFORD_GITHUB_TOKEN`.

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

---
### 2026-11-13 07:10 UTC - Orchestrator

🚀 **Launched: 3 workers in parallel**

- Implementation: [#131](https://github.com/jpshackelford/tickster/issues/131) → [`f0c8529`](https://app.beta.staging.all-hands-testing.dev/conversations/f0c8529d06e64fae9ac552559790c517); [#145](https://github.com/jpshackelford/tickster/issues/145) → [`db3a48a`](https://app.beta.staging.all-hands-testing.dev/conversations/db3a48ab7f374f4186110dc452238111) (#145 unblocks #146, #148)
- Expansion: [#155](https://github.com/jpshackelford/tickster/issues/155) → [`607a6d1`](https://app.beta.staging.all-hands-testing.dev/conversations/607a6d1cdc5c40cd89dec5d90a1d5630)
- Finished from last tick: `7bff8ad`, `e3f2981` (PR #153, #154 merged), `635c25d`.
- Slots: PR 2 busy, 0 free; expansion 1 busy, 1 free (no other issue needs expansion; #129, #138 are tracking issues).

**Active Workers:**

| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `f0c8529` | implementation | Issue #131 | **NEW** |
| `db3a48a` | implementation | Issue #145 | **NEW** |
| `607a6d1` | expansion | Issue #155 | **NEW** |

**Current State:**

- No open PR except release [PR #119](https://github.com/jpshackelford/tickster/pull/119) (untouched, release-please)
- Unblocked ready, `priority:medium`: #132–#136, #147, #124 (queued next)
- Waiting on blockers: #146, #148 (#145, #139); #149 (#148); #150; #143 (#139, #140, #142); #141 (#140); #137 (#133–#136); #127 (#122, #124, #126)
- Unprioritized ready (assess when no prioritized work remains): #139, #140, #141, #137, #143
- #142 `needs-info` (human decision)

### 2026-11-13 10:00 UTC - Expansion worker

- Issue: [feat(list): add a legend for the History and Steps columns](https://github.com/jpshackelford/tickster/issues/155)
- Status: Expanded and labelled `ready`. It waits on #140 and #141 (formal "blocked by" relations added): they add a `Filters:` note under the same `issue list` and `pr list` tables, so the order of notes should settle once.
- Approach: new `src/history_legend.py` holds one char table shared by the list legends and `show`; `pr list` and `issue list` print a `History:` legend of only the characters shown; `STEPS_LEGEND` gains an "all dots = nothing pending" sentence. `review` and diff tables are out of scope.
- Note: `GITHUB_TOKEN` could not edit issues; used `JPSHACKELFORD_GITHUB_TOKEN`.

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

---
### 2026-11-13 11:00 UTC - Implementation worker

- Issue: [#131 feat(list): explicit date flags on pr list](https://github.com/jpshackelford/tickster/issues/131)
- PR: [#156](https://github.com/jpshackelford/tickster/pull/156), CI green, marked ready for review.
- Done: `pr list` takes the 12 `--{created,updated,closed,merged}-{since,after,before}` flags through #154's helper. Merged and closed state errors name the typed flag and the state flag to add. `doc/usage.md` updated.
- Not done here: the manual-test report (separate conversation).
- Note: `GITHUB_TOKEN` could not push; used `JPSHACKELFORD_GITHUB_TOKEN`. Another PR may conflict in `doc/usage.md`.

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-11-13 07:20 UTC - Orchestrator

🚀 **Launched: 2 workers in parallel**

- Testing: [PR #156](https://github.com/jpshackelford/tickster/pull/156) (#131, CI green, docs in `doc/usage.md`, no manual test yet) → [`2ca6134`](https://app.beta.staging.all-hands-testing.dev/conversations/2ca6134c18af47bc915bbff419aa99fe)
- Expansion: [#157](https://github.com/jpshackelford/tickster/issues/157) → [`4b29714`](https://app.beta.staging.all-hands-testing.dev/conversations/4b297140345947869f5ce7e1bbf72d6a)
- Finished from last tick: `f0c8529` (PR #156 opened), `607a6d1` (#155 expanded). `db3a48a` (#145) still running.
- Slots: PR 2 busy, 0 free; expansion 1 busy, 1 free (no other issue needs expansion).

**Active Workers:**

| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `db3a48a` | implementation | Issue #145 | running |
| `2ca6134` | testing | PR #156 | **NEW** |
| `4b29714` | expansion | Issue #157 | **NEW** |

**Current State:**

- [PR #156](https://github.com/jpshackelford/tickster/pull/156): ready, CI green, head `558ae9d`; automated PR review in progress
- Release [PR #119](https://github.com/jpshackelford/tickster/pull/119) untouched (release-please)
- Ready, unblocked, `priority:medium`: #132–#136, #147, #124 (queued once a PR slot frees)
- Waiting on blockers: #146, #148 (#145, #139); #149; #150; #143; #141; #155; #137; #127

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

---
### 2026-11-13 07:40 UTC - Implementation worker (#145)

- [PR #158](https://github.com/jpshackelford/tickster/pull/158) (`feat(issue): record dependency facts on every issue`, closes #145) is ready for review. CI is green and the branch merges cleanly.
- Built: `blockedBy`, `blocking`, `parent` and `milestone` in the issue and `issue show` queries, paged with `ConnectionSpec` (new `total_count` option); `open_blockers` (with `?` for unreadable), `blocking`, `parent`, `milestone` in `issue show`, `issue list --format json` and issue snapshots; `issue list --deps`; diff Note `unblocked` / `blocked` / `blockers changed`; `doc/usage.md`.
- Still open: the manual test from the acceptance criteria (scratch repo, link two issues, `--watch`, close the blocker, `--watch`) is for the testing worker. Unblocks #146 and #148 once merged.
- Learning: the shared test node builders and `tests/fixtures/issue_40_closed_by_pr_69.json` needed the four new keys, because `complete_connection` fails fast on a missing connection.

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

---
### 2026-11-13 12:00 UTC - Expansion worker

- Issue: [feat(list): tell done from n/a in the Steps column (✓ and ·)](https://github.com/jpshackelford/tickster/issues/157)
- Status: Expanded and labelled `ready`. It waits on #155 (formal "blocked by" relation added): both reword `STEPS_LEGEND`, so the legend changes once.
- Approach: `MARK_DONE = "✓"` and `MARK_NA = "·"` constants in `src/pr/steps.py`, used by `_mark` and `STEPS_LEGEND`. Decided: keep `-` for not configured, no ASCII fallback (output already has `💬`, `→`, `…`), use `✓` not `✔`. JSON, snapshots and diffs carry status names and are unchanged.
- Note: `GITHUB_TOKEN` could not edit issues; used `JPSHACKELFORD_GITHUB_TOKEN`.

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

---
### 2026-11-13 07:30 UTC - Orchestrator

🚀 **Launched: 2 workers in parallel**

- Merge: [PR #156](https://github.com/jpshackelford/tickster/pull/156) (#131; approved, CI green, docs in `doc/usage.md`, manual test all PASS after last commit) → [`707dae5`](https://app.beta.staging.all-hands-testing.dev/conversations/707dae582c664aa2aab712a5ed4cc172)
- Testing: [PR #158](https://github.com/jpshackelford/tickster/pull/158) (#145; CI green, docs done, review Good, only the manual test is missing) → [`34d8654`](https://app.beta.staging.all-hands-testing.dev/conversations/34d8654a846e4c90affdb1972f9beba7)
- Finished since last tick: `db3a48a` (#145 → PR #158), `2ca6134` (PR #156 tested), `4b29714` (#157 expanded).
- Slots: PR 2 busy, 0 free; expansion 0 busy, 2 free (no candidate: #142 `needs-info`, #71 `needs-split`, #129/#138 tracking).

**Active Workers:**

| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `707dae5` | merge | PR #156 | **NEW** |
| `34d8654` | testing | PR #158 | **NEW** |

**Current State:**

- [PR #156](https://github.com/jpshackelford/tickster/pull/156): `oA green ready`, head `558ae9d`, merging
- [PR #158](https://github.com/jpshackelford/tickster/pull/158): ready, CI green, head `6407207`, testing in flight (may need a rebase on `doc/usage.md` after #156 merges)
- Release [PR #119](https://github.com/jpshackelford/tickster/pull/119) untouched (release-please)
- Ready, `priority:medium`: #132–#136, #147, #124 (queued once a PR slot frees). #146, #148 unblock when #158 merges.

### 2026-11-13 07:30 UTC - Merge worker

- PR: [feat(list): explicit date flags on pr list](https://github.com/jpshackelford/tickster/pull/156), squash-merged as `22d0352`. Head `558ae9d` and CI were unchanged before the merge; the manual test (all PASS) and the automated review (APPROVED) covered that head.
- Issue: #131 closed by the merge.
- Done: the 12 `--{created,updated,closed,merged}-{since,after,before}` flags on `tkt pr list`, with state checks and errors that name the typed flag. `doc/usage.md` is updated. Old flags work unchanged and give the same snapshot scope.
- Note: `GITHUB_TOKEN` could not edit the PR; used `JPSHACKELFORD_GITHUB_TOKEN` for the description edit and the merge.

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

---
### 2026-11-13 07:40 UTC - Orchestrator

🚀 **Launched: 2 workers in parallel**

- Merge: [PR #158](https://github.com/jpshackelford/tickster/pull/158) (#145; CI green, review Good, docs in `doc/usage.md`, manual test 15 pass / 0 fail on head `6407207`) → [`081fa00`](https://app.beta.staging.all-hands-testing.dev/conversations/081fa0074a0046e9b92cd77a1520720b)
- Implementation: [#132](https://github.com/jpshackelford/tickster/issues/132) (`priority:medium`, no open blockers; no other WIP PR) → [`13faacb`](https://app.beta.staging.all-hands-testing.dev/conversations/13faacbf23ff4d94b7d6ae3d597b71f4)
- Finished since last tick: `34d8654` (PR #158 tested), `707dae5` (PR #156 merged).
- Slots: PR 2 busy, 0 free; expansion 0 busy, 2 free (no candidate: #142 `needs-info`, #71 `needs-split`, #129/#138 tracking).
- Housekeeping: archived entries before 06:35 to `WORKLOG_ARCHIVE_*.md`.

**Active Workers:**

| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `081fa00` | merge | PR #158 | **NEW** |
| `13faacb` | implementation | Issue #132 | **NEW** |

**Current State:**

- [PR #158](https://github.com/jpshackelford/tickster/pull/158): ready, CI green, head `6407207`, merging
- Release [PR #119](https://github.com/jpshackelford/tickster/pull/119) untouched (release-please)
- Ready, unblocked, `priority:medium`: #133–#136, #147, #124 (queued). #146, #148 unblock when #158 merges.
- Waiting on blockers: #127, #137, #141, #143, #155, #157

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-11-13 07:40 UTC - Merge worker

- PR: [feat(issue): record dependency facts on every issue](https://github.com/jpshackelford/tickster/pull/158), squash-merged as `0bce9f1`. Head `6407207` and CI were unchanged before the merge. The manual test (15 pass, 0 fail, 1 not run) and the automated review (Good) covered that head.
- Issue: #145 closed by the merge. #146 and #148 were blocked by #145; check their blockers on the next tick.
- Done: `open_blockers`, `blocking`, `parent` and `milestone` on every issue, read from the GraphQL query tkt already runs. They are in `issue show`, `issue list --format json` and issue snapshots. `issue list --deps` adds `Blocked by` and `Blocks` columns. Diff and watch note `unblocked`, `blocked` or `blockers changed`. Old snapshots load and save byte for byte. `doc/usage.md` is updated.
- Not tested: the scratch-repo "close the real blocker" scenario from #145, because the token cannot create repos. `--watch` notes were tested with a hand-edited baseline.
- Note: `GITHUB_TOKEN` could not edit the PR; used `JPSHACKELFORD_GITHUB_TOKEN` for the description edit and the merge. Release PR #119 untouched.

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-11-13 07:50 UTC - Implementation worker

- PR: [feat(review): explicit date flags on review](https://github.com/jpshackelford/tickster/pull/159), ready for review, CI green (Lint, Test, Type Check), head `94021de`.
- Issue: #132 (part of #129); #130 and #131 had merged, so the shared helper and `resolve_field_flags` were reused.
- Done: the 12 `--{created,updated,closed,merged}-{since,after,before}` flags on `tkt review`; `cmd_list` takes `field_dates`.
- Decision: new `has_all_flag` option on `build_date_window` (default `True`). `review` passes `False`, because its `--all` is not a state flag, so state errors say `add --merged` / `add --closed (or --merged)` and never suggest `--all`. `issue list` and `pr list` text is unchanged.
- Tests: `tests/snapshot/test_review_date_flags.py` (45): flag parsing, query mapping, old/new spelling equivalence, every error, scope/fingerprint equality, `--diff` and `--watch`. Removed the old "review rejects the flags" tests in the issue and PR flag files.
- Docs: `doc/usage.md` `tkt review` table and examples, plus Date flags by field. No legend change; default output is unchanged.
- Next: docs check, manual test (8 scenarios in #132), review. Merge is a separate conversation.
- Note: `GITHUB_TOKEN` could not push or edit the PR; used `JPSHACKELFORD_GITHUB_TOKEN`.

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

---
### 2026-11-13 07:55 UTC - Orchestrator

🚀 **Launched: 2 workers in parallel**

- Testing: [PR #159](https://github.com/jpshackelford/tickster/pull/159) (#132; CI green, docs in `doc/usage.md`, no manual test yet) → [`b3ae00a`](https://app.beta.staging.all-hands-testing.dev/conversations/b3ae00a8b5d34a0a99cb249d6ddaa0bb)
- Implementation: [#134](https://github.com/jpshackelford/tickster/issues/134) (`priority:medium`, independent of #130–#133). Skipped #133: its text says it is blocked by #130–#132 although the GitHub relation is empty, and it waits on PR #159. → [`fab763b`](https://app.beta.staging.all-hands-testing.dev/conversations/fab763bbcda145d0a4bb5281e9497448)
- Finished since last tick: `081fa00` (PR #158 merged), `13faacb` (PR #159 opened).
- Slots: PR 2 busy, 0 free; expansion 0 busy, 2 free (no candidate: #142 `needs-info`, #71 `needs-split`, #129/#138 tracking).

**Active Workers:**

| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `b3ae00a` | testing | PR #159 | **NEW** |
| `fab763b` | implementation | Issue #134 | **NEW** |

**Current State:**

- [PR #159](https://github.com/jpshackelford/tickster/pull/159): ready, CI green, head `94021de`, testing in flight; first review workflow running
- Release [PR #119](https://github.com/jpshackelford/tickster/pull/119) untouched (release-please)
- Ready, unblocked, `priority:medium`: #133 (after #132), #135, #136, #147, #124 (queued). #139 and #140 have no blockers and unblock #146, #148, #141.
- Waiting on blockers: #127, #137, #143, #155, #157, #146, #148, #149, #150

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

---

### 2026-11-13 08:05 UTC - Implementation Worker (#134)

✅ **[PR #160](https://github.com/jpshackelford/tickster/pull/160) ready for review** for [#134](https://github.com/jpshackelford/tickster/issues/134): `show --since TS` → `--since-time TS`

- `--since` is now a hidden stub on `pr show` and `issue show`: exit 2 at parse time, no GitHub call. The JSON key `since` is unchanged.
- Tests renamed and added for both commands; docs (README, `doc/usage.md`, `doc/automation.md`) updated. pytest, ruff, basedpyright clean; CI green.
- Commit is `feat(show)!:` with a `BREAKING CHANGE:` footer. Testing, review and merge are next.

_Created by an AI agent (OpenHands) on behalf of @jpshackelford._

---
