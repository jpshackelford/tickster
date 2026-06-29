# Board Management

The `tkt board` command provides tools for managing GitHub Projects that track
AI-assisted development workflows. It enables you to monitor issues and PRs
across multiple repositories in a single Kanban-style board.

## Prerequisites

- A `GITHUB_TOKEN` environment variable with appropriate permissions:
  - `repo` scope for accessing repository data
  - `project` scope for managing GitHub Projects
  - `notifications` scope for incremental sync

## Quick Start

```bash
# 1. Create a new board
tkt board init --create "My Agent Board"

# 2. Add repositories to watch
tkt board config repos add owner/repo1
tkt board config repos add owner/repo2

# 3. Populate the board with your issues/PRs
tkt board scan

# 4. Check what needs attention
tkt board status --attention
```

## Commands

### `tkt board init`

Initialize or configure a GitHub Project board.

```bash
# Create a new project (user-scoped by default)
tkt board init --create "Project Name"

# Create a project-scoped board (tracks fixed set of items for a project)
tkt board init --create "Feature X" --scope project --overview https://github.com/owner/repo/issues/1

# Configure an existing project by number
tkt board init --project-number 5

# Configure an existing project by GraphQL ID
tkt board init --project-id PVT_kwHOABcd12

# Preview without making changes
tkt board init --create "Test Board" --dry-run
```

**Options:**
| Option | Description |
|--------|-------------|
| `--create NAME` | Create a new project with this name |
| `--project-number N` | Configure existing user project by number |
| `--project-id ID` | Configure existing project by GraphQL ID |
| `--board NAME` | Name for this board in config (default: slugified project name) |
| `--scope SCOPE` | Board scope: `user` (default) or `project` |
| `--overview URL` | URL of overview item (required for project-scoped boards) |
| `--dry-run` | Show what would be done without making changes |

**Board Scopes:**
- **User-scoped** (default): Automatically tracks all issues/PRs where you're involved across watched repos. The `scan` command finds items based on your activity.
- **Project-scoped**: Tracks a fixed set of items related to a specific project/initiative. Items must be added manually with `tkt board add-item`. The `--overview` option specifies an anchor issue/PR that describes the project.

This command:
- Creates a new GitHub Project (or connects to an existing one)
- Configures the Status field with workflow columns
- Saves the project configuration to `~/.tkt/config.toml`

### `tkt board scan`

Scan repositories for issues and PRs to add to the board.

```bash
# Scan all watched repos
tkt board scan

# Scan specific repos
tkt board scan --repos owner/repo1,owner/repo2

# Auto-discover repos: scan all repos owned by a user
tkt board scan --user jpshackelford --since 21

# Auto-discover repos: scan all repos in an organization
tkt board scan --org my-org --since 14

# Only include items updated in the last 30 days
tkt board scan --since 30

# Preview without making changes
tkt board scan --dry-run --verbose
```

The scan uses GitHub's Search API to find items where you are:
- The author
- An assignee
- Mentioned
- Requested for review

#### Auto-Discovery Mode

The `--user` and `--org` flags enable auto-discovery mode, which finds all
repositories with recent activity rather than requiring pre-configured repo
lists. This is useful when you work across many repos and don't want to
manually add each one.

```bash
# Find all your recent work in your personal repos
tkt board scan --user myusername --since 21

# Track work across an entire organization
tkt board scan --org my-company --since 14
```

With `--verbose`, auto-discovery mode shows which repos were found:

```
Discovered 5 repos with activity:
  myuser/repo1: 3 items
  myuser/repo2: 7 items
  myuser/repo3: 1 items
```

Note: `--repos`, `--user`, and `--org` are mutually exclusive.

### `tkt board sync`

Incrementally sync the board with GitHub state.

```bash
# Incremental sync using notifications
tkt board sync

# Force full reconciliation of all items
tkt board sync --full

# Preview changes
tkt board sync --dry-run --verbose
```

The incremental sync uses GitHub's Notifications API to efficiently detect
changes since the last sync, rather than re-scanning all items.

### `tkt board status`

Display current board status.

```bash
# Summary view
tkt board status

# Show items in each column
tkt board status --verbose

# Only show items needing human attention
tkt board status --attention

# Output as JSON (for scripting)
tkt board status --json
```

### `tkt board config`

View and manage board configuration.

```bash
# Show current configuration
tkt board config

# Show configuration with defaults
tkt board config --show-defaults

# Add a watched repository
tkt board config repos add owner/repo

# Remove a watched repository
tkt board config repos remove owner/repo

# Set a configuration value
tkt board config set scan_lookback_days 60
tkt board config set agent_username_pattern openhands
```

### `tkt board apply`

Apply a YAML board configuration (advanced).

```bash
# Apply default configuration
tkt board apply

# Apply a custom config file
tkt board apply --config ~/.tkt/boards/custom.yaml

# Use a built-in template
tkt board apply --template agent-workflow

# Preview changes
tkt board apply --dry-run

# Remove columns not in config
tkt board apply --prune
```

### `tkt board add-item`

Manually add issues or PRs to a board.

```bash
# Add by URL
tkt board add-item https://github.com/owner/repo/pull/123

# Add by reference (multiple formats supported)
tkt board add-item owner/repo#123
tkt board add-item repo#456              # When repo is unique in board config
tkt board add-item #789                  # When board has exactly one repo

# Add to specific column
tkt board add-item owner/repo#123 --column "Backlog"

# Add to a specific board
tkt board add-item owner/repo#123 --board my-project

# Preview without making changes
tkt board add-item owner/repo#123 --dry-run
```

This command is particularly useful for:
- **Project-scoped boards**: Where items must be added manually
- **Adding items from repos not in your watched list**
- **Bulk importing specific items**

### `tkt board templates`

List available built-in board templates.

```bash
tkt board templates
```

### `tkt board macros`

List available macros for rule conditions in YAML configs.

```bash
tkt board macros
```

### `tkt board sync-config`

Sync board configuration with a private GitHub Gist for persistence across
ephemeral environments.

```bash
# Sync config (bidirectional merge)
tkt board sync-config

# Preview what would happen
tkt board sync-config --dry-run
```

This command enables you to persist your board configuration to GitHub, so you
can restore it in new sessions (e.g., when using ephemeral environments like
OpenHands Cloud).

**How it works:**

1. First sync creates a private gist named `tkt-config.toml`
2. Subsequent syncs merge local ↔ remote using timestamps
3. Newer configuration wins for each board
4. Deleted boards are tracked via tombstones (propagate across syncs)
5. Gist is auto-discovered by filename convention

**Example workflow:**

```bash
# Session 1: Initial setup
tkt board init --create "My Board"
tkt board scan --user myuser --since 21
tkt board sync-config
# → Saved to gist: https://gist.github.com/myuser/abc123

# Session 2: New ephemeral environment
tkt board sync-config
# → Found config gist, restored 1 board(s)
# → Ready to use immediately!
```

**Merge behavior:**

| Scenario | Outcome |
|----------|---------|
| Board only in local | Added to gist |
| Board only in gist | Restored locally |
| Board in both, local newer | Local version uploaded |
| Board in both, gist newer | Gist version downloaded |
| Board deleted locally | Deletion propagates to gist |
| Board deleted in gist | Deletion propagates locally |

**Required token:** Needs `gist` scope. Set `GIST_TOKEN` environment variable
(or use `GITHUB_TOKEN` if it has gist scope).

## Workflow Columns

Items are automatically assigned to columns based on their state:

| Column | Description |
|--------|-------------|
| **Icebox** | Auto-closed items (e.g., by stale bot); awaiting triage |
| **Backlog** | Triaged issues ready to be worked |
| **Agent Coding** | Agent actively working on implementation |
| **Human Review** | Draft PRs needing human attention |
| **Agent Refinement** | Agent addressing review feedback |
| **Final Review** | Non-draft PRs awaiting approval |
| **Approved** | PR approved, ready to merge |
| **Done** | Merged PRs |
| **Closed** | Closed issues (won't fix / ignored) |

### Column Assignment Rules

Items flow through columns based on these rules (evaluated in priority order):

1. **Done**: Merged PRs
2. **Approved**: PRs with `APPROVED` review decision
3. **Icebox**: Closed items that were closed by a bot
4. **Closed**: Other closed items
5. **Agent Refinement**: PRs with `CHANGES_REQUESTED` review decision
6. **Final Review**: Non-draft PRs
7. **Human Review**: Draft PRs
8. **Agent Coding**: Open issues with an agent assigned
9. **Backlog**: Everything else (default)

## Configuration

### Config File Location

User configuration is stored at `~/.tkt/config.toml`:

```toml
[board]
project_id = "PVT_kwHOABcd1234"
project_number = 5
username = "your-github-username"
watched_repos = ["owner/repo1", "owner/repo2"]
scan_lookback_days = 90
agent_username_pattern = "openhands"
```

### Configuration Options

| Option | Default | Description |
|--------|---------|-------------|
| `project_id` | — | GitHub Project GraphQL ID |
| `project_number` | — | GitHub Project number |
| `username` | auto-detected | GitHub username for searches |
| `watched_repos` | `[]` | List of repositories to track |
| `scan_lookback_days` | `90` | Default lookback period for scans |
| `agent_username_pattern` | `"openhands"` | Pattern to identify agent accounts |

### Cache Location

Local state is cached at `~/.tkt/board-cache.db` (SQLite). This enables:
- Offline status queries
- Change detection for sync operations
- Faster incremental updates

### API Logging for Debugging

For debugging or generating test fixtures, you can enable API request/response
logging by setting an environment variable:

```bash
# Enable API logging
export TKT_LOG_API=1

# Run any board command - all API calls will be logged
tkt board scan --dry-run
```

Log files are saved to `~/.tkt/api_logs/` with incrementing sequence numbers:
- `0001_request.json` - Request details (method, URL, headers, body)
- `0001_response.json` - Response details (status, headers, body)
- `0002_request.json` - Next request
- etc.

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `TKT_LOG_API` | (not set) | Set to `1`, `true`, `yes`, or `on` to enable logging |
| `TKT_LOG_API_DIR` | `~/.tkt/api_logs/` | Custom directory for log files |

Authorization tokens are automatically redacted in logged headers for security.
This feature is useful for:
- Debugging API issues
- Generating fixture data for tests
- Understanding the API calls made by each command

## YAML Board Configuration

For advanced customization, you can define boards using YAML files stored in
`~/.tkt/boards/`. The schema (board metadata, repos, columns, and rules) is
shown in the example below; run `tkt board macros` to list the available rule
macros.

Example configuration:

```yaml
board:
  name: "Agent Development Board"
  description: "Track AI-assisted development workflow"

repos:
  - owner/repo1
  - owner/repo2

columns:
  - name: Backlog
    color: BLUE
    description: "Ready to work"

  - name: In Progress
    color: YELLOW
    description: "Currently being worked"

  - name: Done
    color: GREEN
    description: "Completed"

rules:
  - column: Done
    priority: 100
    when:
      type: pr
      merged: true

  - column: In Progress
    priority: 50
    when:
      state: open
      $has_agent_assigned: true

  - column: Backlog
    priority: 0
    default: true
```

### Available Macros

Macros provide complex conditions for rules. Use them with the `$` prefix:

| Macro | Description |
|-------|-------------|
| `$closed_by_bot` | True if item was closed by a bot (stale bot, etc.) |
| `$has_agent_assigned` | True if an agent account is assigned |
| `$has_label: <name>` | True if item has the specified label |
| `$ci_status: <status>` | Check CI status: `success`, `failure`, `pending` |

## Typical Workflow

1. **Initial Setup** (once)
   ```bash
   tkt board init --create "Dev Board"
   tkt board config repos add myorg/backend
   tkt board config repos add myorg/frontend
   tkt board scan
   ```

2. **Daily Use**
   ```bash
   # Quick sync and check what needs attention
   tkt board sync
   tkt board status --attention
   ```

3. **Periodic Full Sync**
   ```bash
   # Weekly full reconciliation
   tkt board sync --full
   ```
