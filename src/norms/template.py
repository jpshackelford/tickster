"""The neutral starter file written by ``tkt norms init``."""

TEMPLATE = """\
# .agents/tickster.toml - this repo's conventions for tickster.
# tickster reads this file from the default branch only. Validate with `tkt norms check`.
schema = 1

[actors]
# Logins that are AI actors; wins over the [bot] suffix. Globs allowed, e.g. "my-agent*".
agent_logins = []
# Regex; a body that matches marks an agent posting through a human's token.
# agent_disclosure = 'created by an AI agent'
# Non-AI automation. A login ending in [bot] needs no entry; accounts without the suffix must be listed.
bots = []

[labels]
# Labels that mean a bot closed an issue as stale. [] disables the check.
stale = ["stale"]
# Label order for `tkt issue list --sort rank`, best first, e.g. ["priority:high", "priority:low"].
# rank = []

[review]
# Whose review settles "review the PR": humans | agents | bots
count_reviews_from = ["humans", "agents"]
# Labels that count as a re-review request, alongside GitHub review requests.
rerequest_labels = []

[ci]
# Check names (globs) whose failures do not mean "fix CI".
ignore_checks = []

[commits]
# What counts as a code change for "retest".
ignore_paths = []
min_changed_lines = 0

# Named reports: a comment whose first 200 characters match `marker` (a case-insensitive
# regex) is a report of that kind. Add one table per kind.
#
# [reports.manual_test]
# required = true
# only_paths = []                            # empty = any code change
# marker = '^#+ *Manual Test Results'
# fail = '❌ *FAIL'                           # any match = findings to address
#
# [reports.manual_test.impact_line]
# pattern = 'manual[- ]test impact:\\s*(none|re-?run)'
# from = ["agents", "author"]                # who may waive a retest
# unassessed = "rerun"                       # or "ignore"
"""
