# Orchestration Hints

## Project
- Repository: jpshackelford/tickster
- Type: cli

## Automation
- ID: 3a60277a-4b4a-4f62-a3a6-02e92bccde7d
- Quiet threshold: 2

## Setup Commands
```bash
which tkt || uv tool install git+https://github.com/jpshackelford/tickster
tkt repo add jpshackelford/tickster 2>/dev/null || true
```

## Phases
- Issue expansion: enabled
- Priority assessment: enabled
- Manual testing: required
- Self-review: disabled
- Docs update before testing: enabled

## Plugin Source
github:OpenHands/extensions-private/plugins/sample-dark-factory@main

## Deployment
This automation runs on an OpenHands Enterprise deployment, not on app.all-hands.dev.
Before the first OpenHands API call, set `OPENHANDS_HOST` from the `<HOST>` value in your system prompt.
Use it for every call: spawning and checking workers, and disabling or enabling this automation.
Never fall back to `https://app.all-hands.dev`.

## Scope
Labels are the guard. Follow them exactly:
- Implement only issues labelled `ready`. Work them in `priority:*` order.
- Expand only issues opened by `jpshackelford`. This is a public repository. Leave issues from anyone else for a human to triage.
- Never expand, prioritize or implement an issue labelled `hold`, and never remove `hold`. A human releases held issues when their dependencies merge.
- Don't change a `priority:*` label that a human set.
- The multi-provider work is out of scope: #28 and #30 to #38 (source-neutral refactors, the Linear and HappyFox drivers). Don't start it, even as a prerequisite. Issues that mention #32 or #33 say they build on the current GitHub-only code.
- release-please owns the release PR (title `chore(main): release …`). It carries `hold`. Leave it alone.
