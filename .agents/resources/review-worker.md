# Review Worker Hints

Review for correctness of the facts tickster reports, and for stable output that scripts can rely on.

- Does the change report only what GitHub's data shows? Guesses must be labelled as guesses.
- Is the default output unchanged unless the issue asked for a change? Is JSON stdout still pure JSON?
- Do the tests use recorded fixtures from public repositories and cover each acceptance criterion?
- Is the issue's scope respected? No multi-provider refactor work slipped in.
- Are `doc/usage.md` and the legend updated for user-visible changes?

## Release PRs

The release PR (title `chore(main): release …`, branch `release-please--branches--main--components--tickster`, opened by `github-actions`) is managed by release-please and released by a human.
Don't merge, approve, review, push to, rebase, edit, relabel or comment on it. If your task seems to need any of that, stop and say so in your final message.
