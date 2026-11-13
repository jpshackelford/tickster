# Automating with `tkt`: poll, act, ack

For the author of a scheduled job, or an agent, that shepherds pull requests. One
loop gets every answer from `tkt`, with no raw GitHub calls. [doc/usage.md](usage.md)
is the reference for each command; this page gives the order and the settings.

Examples use two merged PRs,
[#60](https://github.com/jpshackelford/tickster/pull/60) and
[#62](https://github.com/jpshackelford/tickster/pull/62), and a temporary
`TKT_HOME`, so you can rerun them. Output is trimmed only by removing whole lines or
JSON fields. `tkt` reads your token from `GITHUB_TOKEN`
([Authentication](usage.md#authentication)).

## The recipe: poll, act, ack

`--diff NAME` compares the query with the baseline `NAME`, and stages the new result
without moving the baseline. `--exit-code` exits 10 when something changed. Your code
acts on each row, and `tkt snapshot ack` moves the baseline only after that. Save it as
`tick.sh`; for the examples, first run `export TKT_HOME=$(mktemp -d)` in your shell.

```bash
REFS="jpshackelford/tickster#60 jpshackelford/tickster#62"   # or --board / --repo
tkt pr list $REFS --diff doc-poll --format json --exit-code > poll.json; rc=$?
[ $rc -eq 10 ] || exit $rc            # 0: nothing changed. Other than 10: tkt failed
jq -r '.deltas[] | select(.change == "added" or .change == "changed")
       | [.ref, (.events_since | length), ([.steps[] | select(.status == "needed") | .step] | join(","))]
       | @tsv' poll.json |
while IFS=$'\t' read -r ref events needed; do
  echo "$ref: $events new events, needed: ${needed:-none}"   # act here: .events_since and .steps are in poll.json
done
tkt snapshot ack pr/doc-poll
```

First run: there is no baseline, so every row is `added`. The notice goes to stderr.

```text
No snapshot pr/doc-poll found; treating all current rows as new.
jpshackelford/tickster#60: 5 new events, needed: none
jpshackelford/tickster#62: 12 new events, needed: none
acked pr/doc-poll
```

Second run: nothing changed, `tkt` exits 0, the script exits there and prints nothing.

To see a `changed` row, rewind the baseline as if #62 had not been approved and merged
yet, then run the recipe again:

```bash
jq '(.items[] | select(.ref | endswith("#62"))) |= (.history = "sVnFnFn"
    | .last_activity = "2026-11-05T11:31:49Z")' \
  "$TKT_HOME/snapshots/pr-doc-poll.json" > rewound.json &&
  mv rewound.json "$TKT_HOME/snapshots/pr-doc-poll.json"
```

```text
jpshackelford/tickster#62: 4 new events, needed: none
acked pr/doc-poll
```

The delta in `poll.json` (with `--max-body 40` added to the `tkt` line):

```bash
jq -c '.deltas[] | select(.change == "changed")
       | del(.prev, .curr, .steps, .events_since, .disappearance_reason),
         (.events_since[] | {at, kind, actor, body})' poll.json
```

```json
{"ref":"jpshackelford/tickster#62","kind":"pr","change":"changed","new_history_tail":"Vm","changed_fields":["history","last_activity"]}
{"at":"2026-11-05T11:39:10Z","kind":"comment","actor":"jpshackelford","body":"## Manual Test Results for PR #62\n\n_This…(14076 more chars)"}
{"at":"2026-11-05T11:49:39Z","kind":"review","actor":"github-actions","body":"**Excellent implementation** — clean des…(2478 more chars)"}
{"at":"2026-11-05T11:56:17Z","kind":"merged","actor":"jpshackelford","body":null}
{"at":"2026-11-05T11:56:18Z","kind":"closed","actor":"jpshackelford","body":null}
```

If the job dies before the ack, the next run diffs against the same baseline and reports
the same rows again. A person at a terminal can use `--watch NAME` instead: it diffs and
moves the baseline in one step ([Staging a baseline](usage.md#staging-a-baseline-with---diff)).
Rule of use: one consumer per name, one tick at a time.

## The delta fields a script can rely on

With `--diff` or `--watch` and `--format json`, stdout is one JSON document with
`schema` (2), `prev` and `curr` (the `name`, `captured_at` and `scope_hash` of the two
snapshots), `baseline` (`found` or `missing`), `scope_matches`, `counts` and `deltas`.
With `baseline: "missing"` every row is `added` and `prev.captured_at` is the time of the
run, so use `baseline`, not `prev`, to tell a first run. A delta uses the names of a row in
a list document: `ref` and `kind`. Each delta has:

| Field | Meaning |
| --- | --- |
| `ref` | The row, as `owner/repo#N`. The same value as `ref` in `tkt pr list --format json` |
| `kind` | The kind of the row: `pr`, `issue` or `review`. Present for every change, including `unchanged` and `removed` |
| `change` | `added`, `changed`, `removed` or `unchanged`. Act on `added` and `changed` |
| `changed_fields` | For `changed`: the row fields that moved, such as `head`, `review_decision`, `last_activity`, `ci`, `step_status` ([why](usage.md#head-review-and-merge-changes)). `history-rewritten` is a marker, not a row field: it means the new history does not start with the old one, so no event is new: skip the row |
| `new_history_tail` | The characters appended to the [history string](usage.md#history-strings) since the baseline |
| `disappearance_reason` | For `removed`: a hint why the row left the result, such as `closed-or-gone` or `limit` ([values](usage.md#why-a-row-is-gone)). `null` for the other changes |
| `prev`, `curr` | The row before and after, with the fields of a list row of that `kind`. `prev` is `null` for `added`, `curr` is `null` for `removed`; both are `null` for `unchanged` |
| `events_since` | Timeline events after `prev.last_activity`, oldest first; the whole timeline for `added`. Same fields as an event in [`tkt pr show --format json`](usage.md#tkt-pr-show) |
| `events_truncated` | Present, and `true`, only when the timeline fetch cap hid events |
| `steps` | What [`tkt pr steps`](usage.md#tkt-pr-steps) prints: `step`, `status` and `evidence` for each step |
| `step_changes`, `reviewer_changes` | Present only when a step or a reviewer moved |

`removed` and `unchanged` deltas carry no `events_since` or `steps`. `--events` and
`--max-body` set the size ([details](usage.md#events-and-steps-in-a-pr-diff)):

| Option | Effect |
| --- | --- |
| `--events brief` (default) | Each body is cut to 160 characters and ends `…(N more chars)` |
| `--events full` | Whole bodies |
| `--events none` | No `events_since` and no timeline requests. `steps` stays. Cheapest |
| `--max-body N` | With `brief`, cut at `N` characters. A usage error (exit 2) with `full` or `none` |

Each `added` or `changed` row costs one timeline request, unless `--events none`.

## A second recipe: the sweep

The recipe above is edge-triggered: it sees what moved. A PR that needs something
and then goes quiet never moves again. A level-triggered sweep ignores history and asks
what is pending now. Run it on a slower schedule:

```bash
tkt pr list $REFS --format json | jq -r '.items[] | .ref as $k
  | .step_status | to_entries[] | select(.value == "needed") | "\($k)\t\(.key)"'
```

It prints one `ref<TAB>step` line for each pending step. The two merged PRs have none,
so it prints nothing. `.items[].step_status` holds the statuses only; run
[`tkt pr steps REF`](usage.md#tkt-pr-steps) for the evidence.

## An example: act on three cases only

A job that wants only three things (broken CI, a new review comment, a new test
report) uses the same loop and narrows the delta with `jq`. Every other change, such as a
push or a label, still exits 10 and is acked, and the filter prints nothing for it. Save as
`triage.sh`; the snapshot has its own name, `doc-triage`.

```bash
REFS="jpshackelford/tickster#60 jpshackelford/tickster#62"   # or --board / --repo
tkt pr list $REFS --diff doc-triage --format json --exit-code --max-body 60 > poll.json; rc=$?
[ $rc -eq 10 ] || exit $rc
jq -c '
  def report: (.body // "") | test("test results"; "i");
  .deltas[] | select(.change == "added" or .change == "changed") | . as $d
  | ($d.events_since // []) as $ev
  | {ref: $d.ref,
     broken_ci: (($d.changed_fields // [] | index("ci")) != null and $d.curr.ci == "red"),
     review_comments: [$ev[] | select(.kind == "review" or .kind == "comment")
                       | select(report | not)
                       | select(.actor_class != "me" and .actor_class != "me_agent")
                       | {at, kind, actor}],
     test_results: [$ev[] | select(.kind == "comment" and report) | {at, actor}]}
  | select(.broken_ci or (.review_comments | length > 0) or (.test_results | length > 0))' poll.json
tkt snapshot ack pr/doc-triage
```

| Case | What the filter reads |
| --- | --- |
| Broken CI | `ci` is in `changed_fields` and `curr.ci` is `red` (`green`, `red`, `pending`, `conflict` or `--`) |
| A new review comment | An event in `events_since` of `kind` `review` or `comment`, not from you (`actor_class` is not `me` or `me_agent`), and not a test report |
| A new test report | A `comment` event whose body matches `test results`. Match your own reports' heading. If the repo's norms define `[reports.manual_test]`, read `step_changes` for `manually test` and `address test findings` instead |

The first run has no baseline, so both rows print. The second run changes nothing and
prints nothing. Rewind #62 as in the first recipe, on `pr-doc-triage.json`, then run again:

```json
{"ref":"jpshackelford/tickster#62","broken_ci":false,"review_comments":[{"at":"2026-11-05T11:49:39Z","kind":"review","actor":"github-actions"}],"test_results":[{"at":"2026-11-05T11:39:10Z","actor":"jpshackelford"}]}
```

Neither PR has red CI, so `broken_ci` is `false`. The row printed because of the other two
cases.

- **A change, not a state.** `broken_ci` fires on the tick where `ci` moves. A PR that stays
  red is reported once. To ask what is red now, add the sweep with
  `select(.step_status["fix CI"] == "needed")` on the `.items[]` of `tkt pr list --format json`.
- **Review comments in threads.** `unresolved_threads` and the `address review findings` step
  count threads. This filter reads the events only.
- **Where the baseline lives.** It is a file in `$TKT_HOME/snapshots`. A job whose files do
  not survive a run, such as a cloud sandbox, has to keep that directory somewhere that does.

## What `tkt` decides, and what it does not

| `tkt` decides | You decide |
| --- | --- |
| Which rows are `added`, `changed`, `removed` | How often to poll, and which PRs are in scope |
| Which steps are `needed`, `waiting`, `done`, `n/a`, `not configured` or `unknown`, and the evidence | **Which step comes first.** `tkt pr steps` says what is pending, never what to do first. Order is policy and belongs to the consumer |
| Whether a change since a commit is significant, by the rules in `[commits]` | What to do with a significant change |
| Whether a comment is a report, and whether it failed, by the patterns in the norms | How to word a report, and when a repo requires one (the norms say so; `tkt` has no default) |

`tkt` does not act. It reads. Asking for a review, fixing CI or posting a comment is
your code's job. Exit code 0 never means "nothing to do": read the JSON.

## Norms: what each command reads

The repo's conventions are in `.agents/tickster.toml` ([`tkt norms`](usage.md#tkt-norms)).
`tkt` reads it from the repo's **default branch** through the contents API, never from a
PR's head, so a change has no effect until it is merged. `tkt norms show --repo OWNER/NAME`
prints the settings in effect, with the blob SHA of the file read. With no file, steps that
depend on it are `not configured`.

| Command | Keys it reads |
| --- | --- |
| `tkt pr list` (with `--watch`, `--diff`, `--format json`) | `[actors]` `agent_logins`, `bots` and `agent_disclosure`: the [actor class](usage.md#ai-actors) of every event and reviewer. Also everything `tkt pr steps` reads, because step statuses are always recorded |
| `tkt pr show` | `[actors]`, as above. `[reports.NAME]` `marker` and `fail`: the `reports:` line and the JSON `reports` |
| `tkt pr steps` | `[actors]`. `[review]` `count_reviews_from`, `rerequest_labels`. `[ci]` `ignore_checks`. `[commits]` `ignore_paths`, `min_changed_lines`. Every `[reports.NAME]`: `marker`, `required`, `only_paths`, `fail` and `[reports.NAME.impact_line]` `pattern`, `from`, `unassessed` |
| `tkt pr changes` | `[commits]` `ignore_paths`, `min_changed_lines`, only for a setting you did not give as `--ignore-path` or `--min-changed-lines` |

`[labels] stale` is read by [`tkt board`](board.md) only. To start a norms file, run
`tkt norms init --from github:jpshackelford/tickster`, then `tkt norms check --strict`.

## Exit codes and streams

| Command | stdout | Exit code |
| --- | --- | --- |
| `tkt pr list … --diff NAME --format json` | One JSON document | 0 whether or not rows changed. With `--exit-code`: 0 for no change, **10** for at least one `added`, `changed` or `removed` row. A scope mismatch exits 2 and writes nothing; pass `--diff-force` to proceed. Any other failure exits 1, with empty stdout |
| `tkt pr list … --exit-code` without `--diff` or `--watch` | Empty | 2, with no GitHub call |
| `tkt snapshot ack pr/NAME` | `acked pr/NAME` | 0. With nothing staged, 1 |
| `tkt pr show REF --format json`, `tkt pr steps REF --format json` | One JSON document | 0 whatever the statuses. A PR that is not found exits 1 |

- Parse stdout only. Notices such as `No snapshot … found` go to stderr.
- Exit 1 and 2 win over 10. A first run with rows exits 10: every row is new.
- Unchanged rows never count toward 10.
- `--exit-code` is opt-in because most shells treat exit 10 as a failure under `set -e`
  ([`--exit-code`](usage.md#exit-codes-and---exit-code)).
- A scope is the set of refs, repos, authors, states and so on in the query. If it
  changes between runs, use a new snapshot name or pass `--diff-force` once.

## Known limits

- **Findings outside threads are not detected.** `address review findings` looks at
  unresolved review threads and at a counted reviewer's latest `CHANGES_REQUESTED`
  review. A finding in a review summary or a plain comment is not seen.
- **Only the first 200 characters of a comment are matched** by `marker`, `fail` and
  `impact_line` patterns. Put a report's verdict near the top.
- **A long timeline is cut.** Past the fetch cap `tkt pr show` prints `(timeline
  truncated: …)`, JSON has `"timeline_truncated": true`, and the report steps of
  `tkt pr steps` can be `unknown`. In a diff the flag is `events_truncated`.
- **A request made and removed between two polls is not reported.** Removal and
  dismissal come from comparing snapshots ([Reviewer state](usage.md#reviewer-state)).
- **`UNKNOWN` mergeability is not a change.** A move to or from `UNKNOWN` while GitHub
  computes it is not flagged ([details](usage.md#head-review-and-merge-changes)).
- **Table output is for people.** On a terminal the table is fitted to the width and a
  cut History ends in `>`. Piped output is never cropped, and JSON is not cut.

## See also

[`tkt pr show`](usage.md#tkt-pr-show), [`tkt pr steps`](usage.md#tkt-pr-steps),
[`tkt pr changes`](usage.md#tkt-pr-changes),
[Snapshots & diffs](usage.md#snapshots--diffs), [`tkt snapshot`](usage.md#tkt-snapshot),
[`tkt norms`](usage.md#tkt-norms)
