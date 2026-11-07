# Changelog

## [1.0.0](https://github.com/jpshackelford/tickster/compare/v0.3.0...v1.0.0) (2026-11-07)


### ⚠ BREAKING CHANGES

* **norms:** the agent username pattern no longer defaults to "openhands". Boards that relied on the default lose agent detection until they run `tkt norms init --from github:jpshackelford/tickster` in the repo or set agent_username_pattern on the board.

### Features

* **cli:** add --all-authors to issue list and pr list ([#46](https://github.com/jpshackelford/tickster/issues/46)) ([300bcc9](https://github.com/jpshackelford/tickster/commit/300bcc9d67edd4b1edeca1ce09757b4262328e90)), closes [#45](https://github.com/jpshackelford/tickster/issues/45)
* **cli:** tkt pr show / tkt issue show: item timeline with comment and review text ([#69](https://github.com/jpshackelford/tickster/issues/69)) ([fa2def1](https://github.com/jpshackelford/tickster/commit/fa2def132bc1ca4b2a91be3e06e1e1b226942baa))
* **history:** recognise AI actors in history strings and JSON ([#66](https://github.com/jpshackelford/tickster/issues/66)) ([cc3fe53](https://github.com/jpshackelford/tickster/commit/cc3fe53b12b88d4024d303943da5159b98f21c6a))
* **norms:** per-repo .agents/tickster.toml with a versioned schema, plus tkt norms ([#61](https://github.com/jpshackelford/tickster/issues/61)) ([df89f14](https://github.com/jpshackelford/tickster/commit/df89f14d2afc1c412700b6889b28929f0952a160)), closes [#50](https://github.com/jpshackelford/tickster/issues/50)
* **pr:** add tkt pr changes --since SHA with a significance verdict ([#62](https://github.com/jpshackelford/tickster/issues/62)) ([b04e0f1](https://github.com/jpshackelford/tickster/commit/b04e0f11435ca3cfec7b4787d4b6c139c9caa68d)), closes [#52](https://github.com/jpshackelford/tickster/issues/52)
* **pr:** per-reviewer state: requested, latest review and commit, re-review needed ([#67](https://github.com/jpshackelford/tickster/issues/67)) ([334489b](https://github.com/jpshackelford/tickster/commit/334489be98f831cb57c95287434d2eafc2b2281e)), closes [#51](https://github.com/jpshackelford/tickster/issues/51)
* **pr:** tkt pr steps, Phase A: review, CI, findings and re-review status ([#68](https://github.com/jpshackelford/tickster/issues/68)) ([281a8cd](https://github.com/jpshackelford/tickster/commit/281a8cd4cc884610361740c43e6d5389c8e26d67))
* **snapshot:** record PR head SHA, review decision and merge state ([#63](https://github.com/jpshackelford/tickster/issues/63)) ([9264498](https://github.com/jpshackelford/tickster/commit/9264498984fcdd0ee9174f94b1c93dccf0cf03e3)), closes [#42](https://github.com/jpshackelford/tickster/issues/42)
* **snapshot:** say why a diff row is gone and ignore mergeability warm-up ([73ab0c9](https://github.com/jpshackelford/tickster/commit/73ab0c9426b287033d927b7256c8d788faea2522)), closes [#16](https://github.com/jpshackelford/tickster/issues/16) [#65](https://github.com/jpshackelford/tickster/issues/65)


### Bug Fixes

* **issue:** default `issue list` to open issues ([#60](https://github.com/jpshackelford/tickster/issues/60)) ([f41cd83](https://github.com/jpshackelford/tickster/commit/f41cd838ab430067f143e547283090565f2c4b89)), closes [#49](https://github.com/jpshackelford/tickster/issues/49)
* keep stdout valid JSON with --diff-format json ([#59](https://github.com/jpshackelford/tickster/issues/59)) ([2b09310](https://github.com/jpshackelford/tickster/commit/2b093107ad13ea90d39059daaf354788c1c76cba))
* **pagination:** follow GraphQL pagination for timeline events, review threads and labels ([#64](https://github.com/jpshackelford/tickster/issues/64)) ([dba8f1a](https://github.com/jpshackelford/tickster/commit/dba8f1a6c54a9bd627c480981127ca0303534664)), closes [#26](https://github.com/jpshackelford/tickster/issues/26)
* **pr:** tolerate null author/actor in PR timeline events ([#57](https://github.com/jpshackelford/tickster/issues/57)) ([7a6f658](https://github.com/jpshackelford/tickster/commit/7a6f658e5536176dd15793bf25f19f11d20a4e0c)), closes [#25](https://github.com/jpshackelford/tickster/issues/25)
* **search:** fetch smaller search pages and retry GitHub 502/504 ([#58](https://github.com/jpshackelford/tickster/issues/58)) ([a9cccb9](https://github.com/jpshackelford/tickster/commit/a9cccb9e3a75fcc3f8769bd2578993d4458301ae)), closes [#47](https://github.com/jpshackelford/tickster/issues/47)
* **snapshot:** report last_activity changes in diffs ([#43](https://github.com/jpshackelford/tickster/issues/43)) ([5ff5fbb](https://github.com/jpshackelford/tickster/commit/5ff5fbb219a67784651bdb384d24caafa7bd1f5c)), closes [#27](https://github.com/jpshackelford/tickster/issues/27)

## [0.3.0](https://github.com/jpshackelford/tickster/compare/v0.2.0...v0.3.0) (2026-10-10)


### Features

* **cli:** add date-window filter (--since / --after / --before) to pr/issue/review listings ([#5](https://github.com/jpshackelford/tickster/issues/5)) ([dac0d76](https://github.com/jpshackelford/tickster/commit/dac0d762a727f396b11ee5cc7c1fdfcb5cece814))
* **config:** honor TKT_HOME to relocate the ~/.tkt state directory ([#19](https://github.com/jpshackelford/tickster/issues/19)) ([ab07d1f](https://github.com/jpshackelford/tickster/commit/ab07d1f68003843405ff7e5b143b7ff47df18a4e)), closes [#18](https://github.com/jpshackelford/tickster/issues/18)
* **pr:** add tkt pr checks to explain failing CI ([#17](https://github.com/jpshackelford/tickster/issues/17)) ([fa4e802](https://github.com/jpshackelford/tickster/commit/fa4e8028f5d78b4b0562815a4622f685146714b6))


### Bug Fixes

* **api-logging:** write response logs instead of warning on every call ([#22](https://github.com/jpshackelford/tickster/issues/22)) ([d9e6ff8](https://github.com/jpshackelford/tickster/commit/d9e6ff8ac36f73ffb6d28df129c1935c00a27d44)), closes [#20](https://github.com/jpshackelford/tickster/issues/20)
* **cli:** load .env from the working directory, as documented ([#23](https://github.com/jpshackelford/tickster/issues/23)) ([8eabf60](https://github.com/jpshackelford/tickster/commit/8eabf607566c8788f9bdc765a2f7c93674a8984d)), closes [#21](https://github.com/jpshackelford/tickster/issues/21)
* **github:** raise the GraphQL error when it nulls a field the caller needs ([#3](https://github.com/jpshackelford/tickster/issues/3)) ([90ff030](https://github.com/jpshackelford/tickster/commit/90ff030a02361dc49a62158ae50d89be2dd6b61f))
* **github:** return data on partial GraphQL errors instead of raising ([#13](https://github.com/jpshackelford/tickster/issues/13)) ([c8c3d36](https://github.com/jpshackelford/tickster/commit/c8c3d3616013d1971d4b96e8ab034637a7a1fc18)), closes [#11](https://github.com/jpshackelford/tickster/issues/11)

## [0.2.0](https://github.com/jpshackelford/tickster/compare/v0.1.0...v0.2.0) (2026-10-03)


### Features

* **snapshot:** add snapshot/diff to show what changed between runs ([#7](https://github.com/jpshackelford/tickster/issues/7)) ([4fb6c98](https://github.com/jpshackelford/tickster/commit/4fb6c9819f328b0fe8fde773207225a7c015c74a))
* **snapshot:** add snapshot/diff to show what changed between runs ([#7](https://github.com/jpshackelford/tickster/issues/7)) ([4fb6c98](https://github.com/jpshackelford/tickster/commit/4fb6c9819f328b0fe8fde773207225a7c015c74a)), closes [#6](https://github.com/jpshackelford/tickster/issues/6)


### Bug Fixes

* **pr:** drop requestedReviewer field that needs team-read access ([#9](https://github.com/jpshackelford/tickster/issues/9)) ([75fce85](https://github.com/jpshackelford/tickster/commit/75fce85c23b9c8ac1d887fc452c7cb728b9e3b9d))
* **pr:** drop requestedReviewer field that needs team-read access ([#9](https://github.com/jpshackelford/tickster/issues/9)) ([75fce85](https://github.com/jpshackelford/tickster/commit/75fce85c23b9c8ac1d887fc452c7cb728b9e3b9d)), closes [#11](https://github.com/jpshackelford/tickster/issues/11)


### Documentation

* **agents:** add AGENTS.md and manual-test skill ([#8](https://github.com/jpshackelford/tickster/issues/8)) ([ad38cee](https://github.com/jpshackelford/tickster/commit/ad38cee105a5cfddf67fa91da18e8b7b68ce372c))

## [0.1.0](https://github.com/jpshackelford/tickster/compare/v0.1.0...v0.1.0) (2026-06-30)


### Documentation

* token-efficiency rationale, corrected history-string reference, board guide ([07ba038](https://github.com/jpshackelford/tickster/commit/07ba0381bd42036faeb77ca226d5b9a513968ad8))
* write install instructions for uv ([e5945ac](https://github.com/jpshackelford/tickster/commit/e5945ac4c3db801cc5e4c2479bc41b7103eed81b))


### Miscellaneous Chores

* release 0.1.0 ([10fad53](https://github.com/jpshackelford/tickster/commit/10fad53e3debab920aa05b920fcd848af527c7e0))
