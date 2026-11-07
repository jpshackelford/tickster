# Worklog

Coordination log for the sample-dark-factory orchestrator. Its configuration is in `.agents/resources/orchestration.md`.
The orchestrator appends entries and commits them to `main`. Humans can leave `## INSTRUCTION:` entries for it.

## Log

### 2026-11-07 14:45 UTC - Orchestrator

🛠 **Launched: Conflict-Fix Worker**

- [PR #69](https://github.com/jpshackelford/tickster/pull/69) (`tkt pr show`): now `CONFLICTING` after #68 merged. Docs done, manual test 16/16 on `31eefb7`, bot-approved on `2568fd6`. Worker rebases and re-pushes: [`ccbb528`](https://app.beta.staging.all-hands-testing.dev/conversations/ccbb528aa9884d8aa97de1b5c019768f). Re-test and re-review are decided next tick from the new head.
- Slots: PR 1 busy, 1 free (no other WIP PR or in-scope ready issue; #54 `hold`); expansion 0 busy, 2 free.

**Active Workers:**

| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `ccbb528` | conflict-fix | PR #69 | **NEW** |

**Current State:**

- [PR #69](https://github.com/jpshackelford/tickster/pull/69): `oAFn conflict ready`, head `31eefb7`
- [PR #44](https://github.com/jpshackelford/tickster/pull/44) release-please, `hold`, untouched
- Ready issues: none unstarted (#54 `hold`). Needs expansion: none in scope

---
### 2026-11-07 15:10 UTC - Orchestrator

⏳ **Waiting for Review**

- [PR #69](https://github.com/jpshackelford/tickster/pull/69) (`tkt pr show`): conflict-fix rebase done (head `f892e26`, docs-only conflict edits). CI green, docs done, manual test 16/16 still valid (no source change). Bot approval is on old head `2568fd6`, so I added `review-this`; review run started.
- Next tick: if the new review is Good/Acceptable on `f892e26`, spawn the merge worker.
- Slots: PR 0 busy, 2 free (no other WIP PR or in-scope ready issue; #54 `hold`); expansion 0 busy, 2 free.

**Active Workers:**

_None._

**Current State:**

- [PR #69](https://github.com/jpshackelford/tickster/pull/69): `oAFn green ready`, head `f892e26`, re-review in flight
- [PR #44](https://github.com/jpshackelford/tickster/pull/44) release-please, `hold`, untouched
- Ready issues: none unstarted (#40 is PR #69, #54 `hold`). Needs expansion: none in scope

---
### 2026-11-07 21:15 UTC - Orchestrator

🛠 **Launched: Implementation Worker**

- [Issue #54](https://github.com/jpshackelford/tickster/issues/54) (`tkt pr steps` Phase B, `priority:low`): `ready`, no `hold`, dependencies #53/#50/#52/#40/#26 merged. Conversation: [`388fd4d`](https://app.beta.staging.all-hands-testing.dev/conversations/388fd4d8051145a799281b06f6277e5a).
- Slots: PR 1 busy, 1 free (no other WIP PR or in-scope ready issue); expansion 0 busy, 2 free.

**Active Workers:**

| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `388fd4d` | implementation | Issue #54 | **NEW** |

**Current State:**

- No in-scope open PR yet
- [PR #44](https://github.com/jpshackelford/tickster/pull/44) release-please, `hold`, untouched
- Ready issues: #54 (`priority:low`, in flight). Needs expansion: none in scope

---
### 2026-11-07 21:20 UTC - Orchestrator

⏳ **PR slot busy**

- Implementation worker [`388fd4d`](https://app.beta.staging.all-hands-testing.dev/conversations/388fd4d8051145a799281b06f6277e5a) for [issue #54](https://github.com/jpshackelford/tickster/issues/54) is still running; no PR opened yet.
- Slots: PR 1 busy, 1 free (no other WIP PR or in-scope ready issue); expansion 0 busy, 2 free.

**Active Workers:**

| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `388fd4d` | implementation | Issue #54 | running |

**Current State:**

- No in-scope open PR yet
- [PR #44](https://github.com/jpshackelford/tickster/pull/44) release-please, `hold`, untouched
- Ready issues: #54 (`priority:low`, in flight). Needs expansion: none in scope

---
### 2026-11-07 21:27 UTC - Orchestrator

🔍 **Launched: 2 Expansion Workers**

- [Issue #70](https://github.com/jpshackelford/tickster/issues/70) (Upgrading to 1.0 docs): [`fc509a1`](https://app.beta.staging.all-hands-testing.dev/conversations/fc509a1)
- [Issue #71](https://github.com/jpshackelford/tickster/issues/71) (README refresh): [`aa51064`](https://app.beta.staging.all-hands-testing.dev/conversations/aa51064)
- Implementation worker `388fd4d` (issue #54) still running; no PR yet.
- Slots: PR 1 busy, 1 free (no WIP PR or other ready issue); expansion 2 busy, 0 free.

**Active Workers:**

| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `388fd4d` | implementation | Issue #54 | running |
| `fc509a1` | expansion | Issue #70 | **NEW** |
| `aa51064` | expansion | Issue #71 | **NEW** |

**Current State:**

- No in-scope open PR yet
- [PR #44](https://github.com/jpshackelford/tickster/pull/44) release-please, `hold`, untouched
- Ready issues: #54 (`priority:low`, in flight). Needs expansion: #72, #73 (queued)

---
### 2026-11-07 21:29 UTC - Worker (#54)

✅ **PR ready for review:** [PR #83](https://github.com/jpshackelford/tickster/pull/83) `tkt pr steps`, Phase B. Fixes [#54](https://github.com/jpshackelford/tickster/issues/54).

- CI is green. All acceptance criteria are covered by tests on recorded public timelines, and `doc/usage.md` is updated.
- Validation over the private PR-shepherd fixtures: counts are in the PR body (52 of 58 mappable expectations agree; no private data in this repo). A human should confirm the mapping.
- Left for a separate conversation: the manual test against live PRs, and review handling.

---
### 2026-11-07 21:37 UTC - Expansion Worker (#73)

✅ **Expanded Issue #73**

- Issue: [docs: add an automation how-to](https://github.com/jpshackelford/tickster/issues/73)
- Type: Enhancement (docs)
- Status: Ready for implementation
- Approach: new `doc/automation.md` plus a README link; norms table, streams and exit codes checked against the code. Must start after [PR #83](https://github.com/jpshackelford/tickster/pull/83) (#54) merges, because it changes the output and the norms reads. Add `hold` if you want that enforced.

---
### 2026-11-07 21:40 UTC - Orchestrator

🚀 **Launched: 4 workers in parallel**

- Testing [PR #83](https://github.com/jpshackelford/tickster/pull/83) (CI green, docs updated, no manual test yet): [`5e3f3da`](https://app.beta.staging.all-hands-testing.dev/conversations/5e3f3da38f38484aad69ce81c2d103b7)
- Implementation [#70](https://github.com/jpshackelford/tickster/issues/70) (assessed `priority:medium`, docs-only): [`4f9636b`](https://app.beta.staging.all-hands-testing.dev/conversations/4f9636b183384e0f94524559f1ed67d7)
- Expansion [#72](https://github.com/jpshackelford/tickster/issues/72): [`18cabaa`](https://app.beta.staging.all-hands-testing.dev/conversations/18cabaaeefbb4d99a6e5d3b5cc98d16c); [#73](https://github.com/jpshackelford/tickster/issues/73): [`f9ae086`](https://app.beta.staging.all-hands-testing.dev/conversations/f9ae086a471947279cac568a4d6ad9ab)
- Slots: PR 2 busy, 0 free; expansion 2 busy, 0 free.

**Active Workers:**

| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `5e3f3da` | testing | PR #83 | **NEW** |
| `4f9636b` | implementation | Issue #70 | **NEW** |
| `18cabaa` | expansion | Issue #72 | **NEW** |
| `f9ae086` | expansion | Issue #73 | **NEW** |

**Current State:**

- [PR #83](https://github.com/jpshackelford/tickster/pull/83): head `2a17c03`, CI green, ready, automated review COMMENTED — testing in flight
- [PR #44](https://github.com/jpshackelford/tickster/pull/44) release-please, `hold`, untouched
- Ready issues: #70 (in flight). Needs split: #71. Needs expansion (queued): #74-#82

---
### 2026-11-07 21:40 UTC - Expansion Worker (`18cabaa`)

✅ **Expanded Issue #72**

- Issue: [docs: bot detection text says every bot ends in [bot], but github-actions is classed as human](https://github.com/jpshackelford/tickster/issues/72)
- Type: Enhancement (docs + norms)
- Status: Ready for implementation
- Root cause: GraphQL returns bot logins without `[bot]` (`github-actions`, `__typename: Bot`); tickster classifies by suffix or list only.
- Approach: fix the "Bot detection" text and `pr show` example in `doc/usage.md`; add `github-actions` to `[actors] agent_logins` (not `bots`, so its AI reviews still count in `tkt pr steps`). Classifying by account type is out of scope and needs a separate code issue.

---
### 2026-11-07 21:50 UTC - Worker (#70)

- PR [#84](https://github.com/jpshackelford/tickster/pull/84) ready for [#70](https://github.com/jpshackelford/tickster/issues/70): new `## Upgrading to 1.0` section in `doc/usage.md`, linked from the README and the `doc/board.md` "No default" row.
- Docs only; CI green; commands verified on a scratch tree. `CHANGELOG.md` and release PR #44 untouched. Testing and review are separate.

---
### 2026-11-07 21:55 UTC - Expansion Worker

✅ **Expanded Issue #74**

- Issue: [tkt --help shows `tkt review list`, but the CLI rejects `list`](https://github.com/jpshackelford/tickster/issues/74)
- Type: Bug
- Status: Ready for implementation
- Root cause: epilog example at `src/__main__.py:101` says `tkt review list`; `review` has no subcommands. The other epilog examples parse.
- Approach: change the line to `tkt review`; add `tests/test_help_examples.py` that parses every epilog example with the real parser.

---
### 2026-11-07 22:00 UTC - Orchestrator

🚀 **Launched: 4 workers in parallel**

- Merge [PR #83](https://github.com/jpshackelford/tickster/pull/83) (CI green, tested, review excellent, head `2a17c03`): [`fa5b6e4`](https://app.beta.staging.all-hands-testing.dev/conversations/fa5b6e4fd277436fb01487993b41cae3). Its body asks a human to confirm the PR-shepherd fixture mapping.
- Testing [PR #84](https://github.com/jpshackelford/tickster/pull/84) (approved, CI green, no manual test yet): [`7d9a398`](https://app.beta.staging.all-hands-testing.dev/conversations/7d9a398bd0704b93b4d1692a6a8d5881)
- Expansion [#74](https://github.com/jpshackelford/tickster/issues/74): [`a50184e`](https://app.beta.staging.all-hands-testing.dev/conversations/a50184efbbce4407b28beeefad5b3f71); [#75](https://github.com/jpshackelford/tickster/issues/75): [`6f6e14c`](https://app.beta.staging.all-hands-testing.dev/conversations/6f6e14c9890e42668a7da6bd9fce928c)
- Slots: PR 2 busy, 0 free; expansion 2 busy, 0 free.

**Active Workers:**

| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `fa5b6e4` | merge | PR #83 | **NEW** |
| `7d9a398` | testing | PR #84 | **NEW** |
| `a50184e` | expansion | Issue #74 | **NEW** |
| `6f6e14c` | expansion | Issue #75 | **NEW** |

**Current State:**

- [PR #83](https://github.com/jpshackelford/tickster/pull/83): head `2a17c03`, `oCn green ready` — merge worker running
- [PR #84](https://github.com/jpshackelford/tickster/pull/84): head `6b27077`, `oA green ready`, approved — testing in flight
- [PR #44](https://github.com/jpshackelford/tickster/pull/44) release-please, `hold`, untouched
- Ready issues, no worker yet: #72, #73 (starts after #83 merges). Needs split: #71. Needs expansion (queued): #76-#82

---
### 2026-11-07 22:05 UTC - Expansion Worker

✅ **Expanded Issue #75**

- Issue: [Some error paths print a traceback or raw HTTP text instead of a one-line message](https://github.com/jpshackelford/tickster/issues/75)
- Type: Bug
- Status: Ready for implementation
- Root cause: four paths with no command-boundary handler. All reproduced except that the `board init` HTTP failure needed a mocked 502. `config set` with no board hits `save_board_config`'s `ValueError`; `board init` lets `HTTPStatusError`/`RuntimeError` escape; `norms init --ref` prints httpx's text for GitHub's 422; `norms check` adds `missing required key` for a key `_validate` already dropped as invalid.
- Approach: guard in `_handle_set`; catch HTTP/GraphQL errors in `board init` with a shared one-line formatter; map 422 to `ref 'X' not found in the source`; skip the required-key check for keys that already failed. One test per case.

---
### 2026-11-07 21:58 UTC - Orchestrator

🚀 **Launched: 4 workers in parallel**

- Merge [PR #84](https://github.com/jpshackelford/tickster/pull/84) (CI green, tested, approved, head `6b27077`): [`66405ea`](https://app.beta.staging.all-hands-testing.dev/conversations/66405eab2d7a496aad0acf3facbceaab)
- Implementation [#74](https://github.com/jpshackelford/tickster/issues/74): [`8f55179`](https://app.beta.staging.all-hands-testing.dev/conversations/8f55179132014c1a9c030241e098eff1)
- Expansion [#76](https://github.com/jpshackelford/tickster/issues/76): [`146b358`](https://app.beta.staging.all-hands-testing.dev/conversations/146b3583f4cc47abb52c601cda3d614e); [#77](https://github.com/jpshackelford/tickster/issues/77): [`777283c`](https://app.beta.staging.all-hands-testing.dev/conversations/777283c6676e4cedb74de02d7ce75363)
- Priorities set: #74, #75 `medium`; #72, #73 `low`. PR #83 merged earlier. Slots: PR 2 busy, 0 free; expansion 2 busy, 0 free.

**Active Workers:**

| Conv ID | Type | Working On | Status |
|---------|------|------------|--------|
| `66405ea` | merge | PR #84 | **NEW** |
| `8f55179` | implementation | Issue #74 | **NEW** |
| `146b358` | expansion | Issue #76 | **NEW** |
| `777283c` | expansion | Issue #77 | **NEW** |

**Current State:**

- [PR #84](https://github.com/jpshackelford/tickster/pull/84): head `6b27077`, `oA green ready`, tested — merge in flight
- [PR #44](https://github.com/jpshackelford/tickster/pull/44) release-please, `hold`, untouched
- Ready, next up: #75 (`medium`), #72, #73 (`low`). Needs split: #71. Needs expansion (queued): #78-#82

---
### 2026-11-07 21:59 UTC - Worker (#70)

✅ **PR merged:** [PR #84](https://github.com/jpshackelford/tickster/pull/84) `docs: add Upgrading to 1.0 section`, squash `08b93f7`. [#70](https://github.com/jpshackelford/tickster/issues/70) closed.

- Docs only: new `## Upgrading to 1.0` in `doc/usage.md`, linked from `README.md` and `doc/board.md`. Head `6b27077`, CI green, manual test posted, review approved.
- Manual test note, not a blocker: `tkt board config set agent-username-pattern` raises a traceback when no board exists. This matches the error-path issue already expanded above.
- Release PR #44 untouched.

---

### 2026-11-07 22:05 UTC - Expansion Worker (#76)

✅ **Expanded Issue #76:** [pr changes --since: a mistyped SHA or a branch name reads as "history rewritten"](https://github.com/jpshackelford/tickster/issues/76)

- Type: bug. Reproduced both cases on `main`; `--since` is never validated, so GitHub's 404/422 and `diverged` all map to `history rewritten`.
- Fix: validate `--since` as 7-40 hex in `src/pr/changes.py`, CLI exits 2; branches and tags are rejected, and `doc/usage.md` says so.
- Labelled `ready`. Complexity low. Priority label left for the orchestrator.

---

### 2026-11-07 22:10 UTC - Expansion Worker

✅ **Expanded Issue #77**

- Issue: [pr changes: read `[commits]` from the repo's norms file instead of only flags](https://github.com/jpshackelford/tickster/issues/77)
- Type: Enhancement
- Status: Ready for implementation
- Approach: `cmd_changes` calls `get_repo_norms` and merges `[commits]` per setting (flag > file > default), via a small helper that `pr steps` can share. Adds `--explain` and a JSON `settings` key to show the source; default text output is unchanged.

---

### 2026-11-07 22:30 UTC - Implementation Worker

✅ **Implemented Issue #74**

- Issue: [tkt --help shows `tkt review list`, but the CLI rejects `list`](https://github.com/jpshackelford/tickster/issues/74)
- PR: https://github.com/jpshackelford/tickster/pull/85 (CI green, ready for review)
- Change: epilog example is now `tkt review`; new `tests/test_help_examples.py` parses every epilog example with the real parser.

---
