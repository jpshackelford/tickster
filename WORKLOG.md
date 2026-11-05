# Worklog

Coordination log for the sample-dark-factory orchestrator. Its configuration is in `.agents/resources/orchestration.md`.
The orchestrator appends entries and commits them to `main`. Humans can leave `## INSTRUCTION:` entries for it.

## Log

### 2026-11-05 UTC - Setup

Factory configured. Labels set the scope:
- `ready` plus `priority:*`: in scope now
- `hold`: out of scope, or waiting on a dependency. A human removes `hold` when the dependency merges.

No workers have launched yet.
