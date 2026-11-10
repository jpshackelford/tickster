# Changelog

## [1.0.0](https://github.com/jpshackelford/tickster/compare/v0.3.0...v1.0.0) (2026-11-10)


### ⚠ BREAKING CHANGES

* **norms:** the agent username pattern no longer defaults to "openhands". Boards that relied on the default lose agent detection until they run `tkt norms init --from github:jpshackelford/tickster` in the repo or set agent_username_pattern on the board.

### Features

* **cli:** add --all-authors to issue list and pr list ([#46](https://github.com/jpshackelford/tickster/issues/46)) ([300bcc9](https://github.com/jpshackelford/tickster/commit/300bcc9d67edd4b1edeca1ce09757b4262328e90)), closes [#45](https://github.com/jpshackelford/tickster/issues/45)
* **cli:** tkt pr show / tkt issue show: item timeline with comment and review text ([#69](https://github.com/jpshackelford/tickster/issues/69)) ([fa2def1](https://github.com/jpshackelford/tickster/commit/fa2def132bc1ca4b2a91be3e06e1e1b226942baa))
* **history:** mark AI-opened items with s/S ([#93](https://github.com/jpshackelford/tickster/issues/93)) ([5b25107](https://github.com/jpshackelford/tickster/commit/5b25107b7ba7c7808b8c07eb430d0f97b43ec671)), closes [#81](https://github.com/jpshackelford/tickster/issues/81)
* **history:** recognise AI actors in history strings and JSON ([#66](https://github.com/jpshackelford/tickster/issues/66)) ([cc3fe53](https://github.com/jpshackelford/tickster/commit/cc3fe53b12b88d4024d303943da5159b98f21c6a))
* **norms:** per-repo .agents/tickster.toml with a versioned schema, plus tkt norms ([#61](https://github.com/jpshackelford/tickster/issues/61)) ([df89f14](https://github.com/jpshackelford/tickster/commit/df89f14d2afc1c412700b6889b28929f0952a160)), closes [#50](https://github.com/jpshackelford/tickster/issues/50)
* **pr:** add tkt pr changes --since SHA with a significance verdict ([#62](https://github.com/jpshackelford/tickster/issues/62)) ([b04e0f1](https://github.com/jpshackelford/tickster/commit/b04e0f11435ca3cfec7b4787d4b6c139c9caa68d)), closes [#52](https://github.com/jpshackelford/tickster/issues/52)
* **pr:** per-reviewer state: requested, latest review and commit, re-review needed ([#67](https://github.com/jpshackelford/tickster/issues/67)) ([334489b](https://github.com/jpshackelford/tickster/commit/334489be98f831cb57c95287434d2eafc2b2281e)), closes [#51](https://github.com/jpshackelford/tickster/issues/51)
* **pr:** read [commits] norms in 'pr changes' and add --explain ([#89](https://github.com/jpshackelford/tickster/issues/89)) ([cde7c5a](https://github.com/jpshackelford/tickster/commit/cde7c5a6ad5f204c360c68a6128a6871530ac351))
* **pr:** tkt pr steps shows manual test, test findings and retest from the repo norms ([#83](https://github.com/jpshackelford/tickster/issues/83)) ([b188f73](https://github.com/jpshackelford/tickster/commit/b188f732dfb712e13214bc9ff052b9a3d796ca8e)), closes [#54](https://github.com/jpshackelford/tickster/issues/54)
* **pr:** tkt pr steps, Phase A: review, CI, findings and re-review status ([#68](https://github.com/jpshackelford/tickster/issues/68)) ([281a8cd](https://github.com/jpshackelford/tickster/commit/281a8cd4cc884610361740c43e6d5389c8e26d67))
* **snapshot:** record PR head SHA, review decision and merge state ([#63](https://github.com/jpshackelford/tickster/issues/63)) ([9264498](https://github.com/jpshackelford/tickster/commit/9264498984fcdd0ee9174f94b1c93dccf0cf03e3)), closes [#42](https://github.com/jpshackelford/tickster/issues/42)
* **snapshot:** say why a diff row is gone and ignore mergeability warm-up ([73ab0c9](https://github.com/jpshackelford/tickster/commit/73ab0c9426b287033d927b7256c8d788faea2522)), closes [#16](https://github.com/jpshackelford/tickster/issues/16) [#65](https://github.com/jpshackelford/tickster/issues/65)


### Bug Fixes

* **cli:** correct review example in --help epilog ([#85](https://github.com/jpshackelford/tickster/issues/85)) ([f249fe9](https://github.com/jpshackelford/tickster/commit/f249fe98c76fbb26a17395cc35d740ea10449f50)), closes [#74](https://github.com/jpshackelford/tickster/issues/74)
* **cli:** print one-line errors for four error paths ([#86](https://github.com/jpshackelford/tickster/issues/86)) ([a7df4e7](https://github.com/jpshackelford/tickster/commit/a7df4e744ba007e907c04f25158962013e143afd)), closes [#75](https://github.com/jpshackelford/tickster/issues/75)
* **issue:** default `issue list` to open issues ([#60](https://github.com/jpshackelford/tickster/issues/60)) ([f41cd83](https://github.com/jpshackelford/tickster/commit/f41cd838ab430067f143e547283090565f2c4b89)), closes [#49](https://github.com/jpshackelford/tickster/issues/49)
* **issue:** show a PR that says Fixes #N as linked ([#88](https://github.com/jpshackelford/tickster/issues/88)) ([47b0519](https://github.com/jpshackelford/tickster/commit/47b051911ad8728ca404004695cf44051a2493e7)), closes [#78](https://github.com/jpshackelford/tickster/issues/78)
* keep stdout valid JSON with --diff-format json ([#59](https://github.com/jpshackelford/tickster/issues/59)) ([2b09310](https://github.com/jpshackelford/tickster/commit/2b093107ad13ea90d39059daaf354788c1c76cba))
* **list:** crop History with '&gt;' and keep Steps and numbers whole on narrow terminals ([2d9ba8b](https://github.com/jpshackelford/tickster/commit/2d9ba8b523daa8465210dc1dac8a7e915bb951b6)), closes [#80](https://github.com/jpshackelford/tickster/issues/80) [#90](https://github.com/jpshackelford/tickster/issues/90)
* **list:** don't fit or crop tables when stdout is not a terminal ([7ca3bf7](https://github.com/jpshackelford/tickster/commit/7ca3bf7ad18b52c343762fdb085d70637a9f59d6)), closes [#96](https://github.com/jpshackelford/tickster/issues/96) [#97](https://github.com/jpshackelford/tickster/issues/97)
* **list:** don't wrap legends and notes when stdout is not a terminal ([#99](https://github.com/jpshackelford/tickster/issues/99)) ([74ca0ad](https://github.com/jpshackelford/tickster/commit/74ca0adc51787d8f07576b8d1c9d2fe00fc6358b))
* **list:** print errors to stderr and exit 141 on a closed pipe ([#110](https://github.com/jpshackelford/tickster/issues/110)) ([44e266f](https://github.com/jpshackelford/tickster/commit/44e266faec6cb21d100d71f2e484def3c47a4295))
* **norms:** tell a missing repo from a missing norms file ([#112](https://github.com/jpshackelford/tickster/issues/112)) ([203622b](https://github.com/jpshackelford/tickster/commit/203622b48ba212fa16d99eaaa1083679ecadfc47)), closes [#108](https://github.com/jpshackelford/tickster/issues/108)
* output polish for step-change separator, --max-body help, article and retry warning ([#91](https://github.com/jpshackelford/tickster/issues/91)) ([b741c8e](https://github.com/jpshackelford/tickster/commit/b741c8e8028b730fcd47e720cc06c59576e4f538)), closes [#79](https://github.com/jpshackelford/tickster/issues/79)
* **pagination:** follow GraphQL pagination for timeline events, review threads and labels ([#64](https://github.com/jpshackelford/tickster/issues/64)) ([dba8f1a](https://github.com/jpshackelford/tickster/commit/dba8f1a6c54a9bd627c480981127ca0303534664)), closes [#26](https://github.com/jpshackelford/tickster/issues/26)
* **pr:** reject a --since that is not a commit SHA in pr changes ([#87](https://github.com/jpshackelford/tickster/issues/87)) ([9bdbada](https://github.com/jpshackelford/tickster/commit/9bdbadae959de0d3eb3fb722286b564ff02fe9c6)), closes [#76](https://github.com/jpshackelford/tickster/issues/76)
* **pr:** tolerate null author/actor in PR timeline events ([#57](https://github.com/jpshackelford/tickster/issues/57)) ([7a6f658](https://github.com/jpshackelford/tickster/commit/7a6f658e5536176dd15793bf25f19f11d20a4e0c)), closes [#25](https://github.com/jpshackelford/tickster/issues/25)
* **search:** fetch smaller search pages and retry GitHub 502/504 ([#58](https://github.com/jpshackelford/tickster/issues/58)) ([a9cccb9](https://github.com/jpshackelford/tickster/commit/a9cccb9e3a75fcc3f8769bd2578993d4458301ae)), closes [#47](https://github.com/jpshackelford/tickster/issues/47)
* **snapshot:** do not flag conflicts on the first diff after upgrading ([#114](https://github.com/jpshackelford/tickster/issues/114)) ([f4a5322](https://github.com/jpshackelford/tickster/commit/f4a532297426a1d67a6ee85607b61ef2d691f165)), closes [#113](https://github.com/jpshackelford/tickster/issues/113)
* **snapshot:** don't shrink or ellipsize snapshot show / list tables when piped ([#117](https://github.com/jpshackelford/tickster/issues/117)) ([2ce0534](https://github.com/jpshackelford/tickster/commit/2ce0534a1213c60e4186e6bb14e95f530704ffc7))
* **snapshot:** name corrupt snapshots in errors and announce renamed ones ([#111](https://github.com/jpshackelford/tickster/issues/111)) ([ec93211](https://github.com/jpshackelford/tickster/commit/ec93211f678c8e44cc670ce0d46aa8cb607c1a23))
* **snapshot:** report last_activity changes in diffs ([#43](https://github.com/jpshackelford/tickster/issues/43)) ([5ff5fbb](https://github.com/jpshackelford/tickster/commit/5ff5fbb219a67784651bdb384d24caafa7bd1f5c)), closes [#27](https://github.com/jpshackelford/tickster/issues/27)


### Documentation

* add an automation how-to for polling, reading changes and deciding PR steps ([#95](https://github.com/jpshackelford/tickster/issues/95)) ([585f4d6](https://github.com/jpshackelford/tickster/commit/585f4d62d8bf803b06be20031fec1edf58c39e5d)), closes [#73](https://github.com/jpshackelford/tickster/issues/73)
* add Upgrading to 1.0 section ([#84](https://github.com/jpshackelford/tickster/issues/84)) ([08b93f7](https://github.com/jpshackelford/tickster/commit/08b93f7574424845f2806b264c6b62adb8fa5ffb)), closes [#70](https://github.com/jpshackelford/tickster/issues/70)
* say that the first diff after upgrading to 1.0 reports AI-actor rows as history-rewritten ([#115](https://github.com/jpshackelford/tickster/issues/115)) ([26c7760](https://github.com/jpshackelford/tickster/commit/26c7760b81f527db71a1f7c0a803fe9c73d217ae))
* say the [bot] suffix is not guaranteed; list github-actions as an agent ([#92](https://github.com/jpshackelford/tickster/issues/92)) ([077cb70](https://github.com/jpshackelford/tickster/commit/077cb70de099990f56696656f25f0d7fa4cfadd6)), closes [#72](https://github.com/jpshackelford/tickster/issues/72)
* **show:** list every JSON key of pr show and issue show ([#94](https://github.com/jpshackelford/tickster/issues/94)) ([1b62934](https://github.com/jpshackelford/tickster/commit/1b62934afde01716e8fa471eef2a6a81a480da97))
* **worklog:** add [#78](https://github.com/jpshackelford/tickster/issues/78) entry ([ec658f2](https://github.com/jpshackelford/tickster/commit/ec658f2b9390d370514e9de1b2920221ca6d92d2))
* **worklog:** record expansion of [#78](https://github.com/jpshackelford/tickster/issues/78) ([996282d](https://github.com/jpshackelford/tickster/commit/996282d05b170ffae3931a95a252c7ff329fa3ca))
* **worklog:** record expansion of [#79](https://github.com/jpshackelford/tickster/issues/79) ([efa44c1](https://github.com/jpshackelford/tickster/commit/efa44c19b06a3b57196604192b4119bfb6f0e107))
* **worklog:** record expansion of [#80](https://github.com/jpshackelford/tickster/issues/80) ([5d23243](https://github.com/jpshackelford/tickster/commit/5d232431be7f13f8f2eb0ace25f8d5759241bdd7))
* **worklog:** record expansion of [#81](https://github.com/jpshackelford/tickster/issues/81) ([db8341c](https://github.com/jpshackelford/tickster/commit/db8341cb2c0fb1d5d88b516f8707ccb4348cc856))
* **worklog:** record expansion of [#82](https://github.com/jpshackelford/tickster/issues/82) ([a9996c4](https://github.com/jpshackelford/tickster/commit/a9996c45b2f345c14b7d305b82523fe979508f33))
* **worklog:** record implementation of [#74](https://github.com/jpshackelford/tickster/issues/74) ([3fde6d5](https://github.com/jpshackelford/tickster/commit/3fde6d5632522c6529d569fc8217c5e8571f5435))
* **worklog:** record implementation of [#75](https://github.com/jpshackelford/tickster/issues/75) ([0e4f974](https://github.com/jpshackelford/tickster/commit/0e4f9746b8ad3bf114063e0c963d1b4d19af8200))
* **worklog:** record implementation of [#76](https://github.com/jpshackelford/tickster/issues/76) ([9f666d5](https://github.com/jpshackelford/tickster/commit/9f666d561ae1187971c507ef11df2b13e4c9b544))
* **worklog:** record merge of [#85](https://github.com/jpshackelford/tickster/issues/85) ([7423d9c](https://github.com/jpshackelford/tickster/commit/7423d9c5a6f1d293eb369dbe50039048fbdec2ab))
* **worklog:** record merge of [#86](https://github.com/jpshackelford/tickster/issues/86) ([4ba03b1](https://github.com/jpshackelford/tickster/commit/4ba03b1c33c856223f95d8fc54db8a22cefcebd5))

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
