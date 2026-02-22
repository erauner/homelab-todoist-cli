# Todoist CLI

A full-featured command-line interface for Todoist with support for descriptions, comments, and advanced filtering.

## Features

- **Full API support**: descriptions, comments, labels, priorities
- **Filtering**: Use native Todoist filter syntax via `td query` (`today`, `overdue`, boolean ops, etc.)
- **Rich output**: Colored terminal output with table formatting
- **Compatible config**: Uses same config location as `sachaos/todoist`

## Installation

### From Nexus (after CI publishes)

```bash
pip install --index-url https://nexus.erauner.dev/repository/pypi-hosted/simple todoist-cli
```

### From source

```bash
git clone https://github.com/erauner/homelab-todoist-cli
cd homelab-todoist-cli
uv sync
uv run td --help
```

## Configuration

Set your API token (get it from Todoist Settings -> Integrations -> Developer):

```bash
# Option 1: Environment variable
export TODOIST_API_TOKEN=your_token_here

# Option 2: Config file (same as sachaos/todoist)
td config --token your_token_here
# Saved to ~/.config/todoist/config.json

# Autodoist API URL defaults to:
#   https://autodoist.erauner.dev
# Override only if needed:
export AUTODOIST_URL=https://autodoist.erauner.dev
# or persist override in config:
td config --autodoist-url https://autodoist.erauner.dev
```

## Usage

### List tasks

```bash
td list                          # All tasks
td list --project "Work"         # Tasks in Work project
td list --label "urgent"         # Tasks with label
td list --table                  # Table format
td list -d                       # Show descriptions
td list --priority               # Sort by priority
```

> **Note:** `td list` uses the standard tasks endpoint and supports project/label filtering only.
> For native Todoist filter syntax (e.g. `today`, `overdue`, `p1`, boolean logic), use `td query`.

### Query tasks (native Todoist filter syntax)

`td query` calls `GET /rest/v2/tasks?filter=...` so you can use Todoist's full filter language.

```bash
td query "today"                                # Tasks due today
td query "overdue"                              # Overdue tasks
td query "(today | overdue) & #Work"            # Boolean logic + project
td query "@urgent & !#Someday"                  # Label + NOT project
td query "#Personal & (tomorrow | next 7 days)" # Project + date ranges
td query "today, overdue"                       # Comma sections (Todoist filter sections)

td query "(today | overdue) & #Work" --limit 25
td query "@urgent & (p1 | p2)" --json
```

### Add tasks

```bash
td add "Buy groceries"
td add "Write report" --due "tomorrow" --priority 4
td add "Research topic" --description "Look into X, Y, Z" --project "Work"
td add "Call mom" --labels "personal,phone" --due "today 5pm"
td add "Draft outline" --parent-id <parent_task_id>   # Create subtask under a parent task
td add-focus "Handle prod incident" --priority 4   # Create and set as @focus immediately
```

### Quick add (natural language)

```bash
td quick "Buy milk tomorrow #Shopping p2"
```

### Show task details

```bash
td show <task_id>           # Shows description and comments
td show <task_id> --no-comments
```

### Manage tasks

```bash
td close <task_id>          # Complete a task
td delete <task_id>         # Delete a task
td modify <task_id> --content "New title" --priority 3
td modify <task_id> --description "Updated description"
```

### Comments

```bash
td comment <task_id> "This is a comment"                       # append (default)
td comment <task_id> "Refined plan..." --mode update-last      # edit latest comment
td comment <task_id> "New next action..." --mode overwrite-latest-plan
td comment <task_id> "Duplicate text" --force                  # bypass dedupe
td comments <task_id>       # List all comments
```

### Projects and labels

```bash
td projects                 # List all projects
td labels                   # List all labels
```

### Autodoist integration (focus singleton helpers)

```bash
td autodoist health
td autodoist state
td autodoist tasks --label focus
td autodoist focus                 # dry-run reconcile
td autodoist focus --apply         # apply reconcile
td autodoist set-focus <task_id>   # force winner and reconcile
td autodoist action <task_id> set-focus
td autodoist action <task_id> clear-focus
td autodoist action <task_id> remove-next-action
td autodoist action <task_id> make-winner
```

## Comparison with sachaos/todoist

| Feature           | sachaos/todoist | td (this CLI) |
|-------------------|-----------------|---------------|
| List tasks        |       ✅         |      ✅       |
| Add tasks         |       ✅         |      ✅       |
| Due dates         |       ✅         |      ✅       |
| Priorities        |       ✅         |      ✅       |
| Labels            |       ✅         |      ✅       |
| **Description**   |       ❌         |      ✅       |
| **Comments**      |       ❌         |      ✅       |
| Filter syntax     |       ✅         |      ✅       |
| Project/label filter |    ✅         |      ✅       |
| Rich output       |       ✅         |      ✅       |

## Development

```bash
# Setup
uv sync --extra dev

# Run tests
uv run pytest

# Lint
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# Build
uv build
```

## License

MIT
