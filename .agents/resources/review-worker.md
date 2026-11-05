# Review Worker Hints

Review for correctness of the facts tickster reports, and for stable output that scripts can rely on.

- Does the change report only what GitHub's data shows? Guesses must be labelled as guesses.
- Is the default output unchanged unless the issue asked for a change? Is JSON stdout still pure JSON?
- Do the tests use recorded fixtures from public repositories and cover each acceptance criterion?
- Is the issue's scope respected? No multi-provider refactor work slipped in.
- Are `doc/usage.md` and the legend updated for user-visible changes?
