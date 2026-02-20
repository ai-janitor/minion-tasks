# minion-tasks

DAG-based task flow engine with SQLite persistence. Tracks projects and individual tasks through YAML-defined pipelines.

## Problem

minion-commsv2 has task lifecycle enforcement but flow logic is hardcoded across `auth.py`, `tasks.py`, `poll.sh`, and `FRAMEWORK.md`. Every task follows the same `open→assigned→in_progress→fixed→verified→closed` pipeline, but different task types need different paths:

- A **bugfix** needs full code review + testing
- A **hotfix** skips review, goes straight to close
- A **research** task produces findings that spawn implementation tasks
- A **build** task needs testing but not code review

## Architecture

```
┌──────────────────────────────────────────────┐
│              minion-tasks                     │
│                                               │
│  ┌─────────────┐   ┌──────────────────────┐  │
│  │  task-flows/ │   │     SQLite DB        │  │
│  │  (YAML DAGs)│   │                      │  │
│  │  _base.yaml │   │  projects            │  │
│  │  bugfix.yaml│   │  tasks (pointers)    │  │
│  │  hotfix.yaml│   │  transitions (log)   │  │
│  │  ...        │   │                      │  │
│  └──────┬──────┘   └──────────┬───────────┘  │
│         │                     │               │
│  ┌──────┴─────────────────────┴───────────┐  │
│  │            Python API                   │  │
│  │  load_flow() → TaskFlow (DAG queries)   │  │
│  │  Project / Task CRUD                    │  │
│  │  Transition validation + logging        │  │
│  └─────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
         │
         │ consumed by
         ▼
┌──────────────────┐
│  minion-commsv2   │
│  (auth, tasks,    │
│   poll.sh)        │
└──────────────────┘
```

## Core Design Decisions

1. **Tasks are pointers, not containers** — A task record stores a file path and a brief description. The actual spec, results, code, and context live in the files the task points to. The DB tracks location and lifecycle state, not data.

2. **YAML is the brain** — Each task type has its own YAML file describing stages, workers, transitions, and requirements. Code is dumb plumbing that reads YAML.

3. **Inheritance from base** — Every type-specific YAML inherits from `_base.yaml` and overrides only what's different. One base template, one DAG file per task type, all version-controlled.

4. **SQLite for state** — Projects and tasks live in SQLite. Transitions are logged for audit trail. No in-memory state, no server process.

5. **Transitions are validated, not blocked** — The system warns on invalid transitions but doesn't hard-block. Leads can force-move tasks when needed.

6. **DAG owns routing** — The DAG knows how to transition AND who gets the task next. A single `transition()` call returns the next status and eligible worker classes. Callers never need to know the routing logic.

7. **`complete()` hook drives the pipeline** — When an assignee finishes their stage, they call `complete()`. The DAG resolves the transition (next status + who picks it up), updates the task, logs the transition, and returns routing info. The assignee doesn't need to know the DAG — they just say "I'm done."

8. **Task lookup by class** — Tasks require `class_required` for the DAG to route to the right worker class at each stage, and `assigned_to` for tracking the specific agent working the task.

## Data Model

### Tasks Are Pointers

A task record contains:
- **File path** — location of the spec/work file on disk
- **Brief description** — one-line summary (what, not how)
- **Task type** — which DAG flow to follow (bugfix, hotfix, research, etc.)
- **Status** — current stage in the DAG
- **Project** — which project this task belongs to
- **Assigned agent** — who's working on it
- **Class required** — which agent class can work on it

A task does NOT contain:
- Spec details (those live in the file)
- Results or output (those live in files)
- Comments or discussion (those go through comms)
- Code diffs or patches

### SQLite Schema

```sql
CREATE TABLE projects (
    id          TEXT PRIMARY KEY,           -- e.g. "minion-tasks", "minion-commsv2"
    description TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    status      TEXT NOT NULL DEFAULT 'active'  -- active, archived
);

CREATE TABLE tasks (
    id              TEXT PRIMARY KEY,       -- e.g. "BUG-001", "FEAT-003"
    project_id      TEXT NOT NULL REFERENCES projects(id),
    task_type       TEXT NOT NULL DEFAULT 'bugfix',  -- maps to YAML flow
    description     TEXT NOT NULL,          -- one-line summary
    file_path       TEXT,                   -- pointer to spec/work file on disk
    status          TEXT NOT NULL DEFAULT 'open',
    class_required  TEXT,                   -- which agent class can work this
    assigned_to     TEXT,                   -- agent name
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE transitions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL REFERENCES tasks(id),
    from_status TEXT NOT NULL,
    to_status   TEXT NOT NULL,
    agent       TEXT,                      -- who triggered the transition
    valid       INTEGER NOT NULL DEFAULT 1, -- 1 = valid per DAG, 0 = forced/warned
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

## YAML Flow Schema

See `task-flows/` directory. Each YAML file defines:

- **stages** — nodes in the DAG (open, assigned, in_progress, fixed, verified, closed)
- **next** — happy-path transition from each stage
- **fail** — rejection path (review/test failure)
- **workers** — which agent classes can work each stage, keyed by `class_required`
- **requires** — preconditions before entering a stage
- **skip** — skip a stage entirely (hotfix skips review + test)
- **dead_ends** — always-available terminal transitions (abandoned, stale, obsolete)

### Type-Specific Overrides

```yaml
# hotfix.yaml — skip review and test
name: hotfix
inherits: _base
stages:
  fixed:
    skip: true
  verified:
    skip: true
```

## Python API

### Flow API (DAG queries)

```python
from minion_tasks import load_flow, list_flows

flow = load_flow("bugfix")
flow.next_status("in_progress")           # → "fixed"
flow.next_status("fixed", passed=False)   # → "assigned" (back to coder)
flow.workers_for("fixed", "coder")        # → ["oracle", "recon"]
flow.valid_transitions("assigned")        # → {"in_progress", "abandoned", "stale", "obsolete"}
flow.requires("in_progress")              # → ["submit_result"]
flow.is_terminal("closed")               # → True

# Single-call transition — next status + who gets it
result = flow.transition("in_progress", class_required="coder")
# → Transition(to_status="fixed", eligible_classes=["oracle", "recon"])

result = flow.transition("in_progress", class_required="coder", passed=False)
# → Transition(to_status="assigned", eligible_classes=None)  # back to same agent
```

### Project/Task API (CRUD + transitions)

```python
from minion_tasks import TaskDB

db = TaskDB("tasks.db")

# Projects
db.create_project("minion-tasks", "DAG-based task flow engine")
db.list_projects()

# Tasks — pointers to files with brief descriptions
db.create_task(
    id="BUG-001",
    project_id="minion-tasks",
    task_type="bugfix",
    description="loader crashes on circular inheritance",
    file_path="work/BUG-001-circular-inheritance/README.md",
    class_required="coder",
)

# Transitions — validated against the DAG
db.transition_task("BUG-001", to_status="assigned", agent="fighter")
db.transition_task("BUG-001", to_status="in_progress", agent="fighter")

# complete() hook — assignee says "I'm done", DAG routes to next stage
result = db.complete("BUG-001", agent="fighter")
# → Transition(to_status="fixed", eligible_classes=["oracle", "recon"])
# Task status updated, transition logged, ready for next worker

# complete() with failure (review/test rejected)
result = db.complete("BUG-001", agent="whitemage", passed=False)
# → Transition(to_status="assigned", eligible_classes=None)
# Task sent back to original assignee

# Query
db.get_task("BUG-001")
db.list_tasks(project_id="minion-tasks", status="open")
db.list_tasks(class_required="coder", status="open")  # lookup by class
db.get_transitions("BUG-001")  # audit log
```

## CLI

Entry point: `mtask` (Click). JSON output by default, `--human` for tables. Mirrors minion-commsv2 conventions.

### Project Commands

```bash
mtask create-project <id> --description "..."
mtask list-projects [--status active|archived]
mtask get-project <id>
```

### Task Commands

```bash
# Create a task pointer
mtask create-task <id> --project <project_id> --type bugfix \
  --description "one-liner" [--file path/to/spec.md] [--class coder]

# Query tasks — all filters optional, combine freely
mtask list-tasks [--project <id>] [--status open] [--class coder] [--assigned-to fighter]
mtask get-task <id>

# Claim a task — sets assigned_to + transitions to assigned in one call
mtask claim-task <task_id> <agent_name>
```

#### `list-tasks` shorthand

The most common agent query: "what can I work on?"

```bash
# Tasks available for my class
mtask list-tasks --class coder --status open

# What's assigned to me?
mtask list-tasks --assigned-to fighter
```

#### `claim-task`

Convenience command that does two things atomically:
1. Sets `assigned_to` to the agent
2. Calls `transition_task()` to move status to `assigned`

Fails if task is not in `open` status (already claimed).

```bash
mtask claim-task BUG-001 fighter
# → {"id": "BUG-001", "status": "assigned", "assigned_to": "fighter", ...}
```

### Transition Commands

```bash
# Manual transition (leads can force-move)
mtask transition <task_id> <to_status> [--agent <name>]

# Assignee says "I'm done" — DAG routes to next stage
mtask complete <task_id> --agent <name> [--failed]
# → {"to_status": "fixed", "eligible_classes": ["oracle", "recon"]}

# Audit log
mtask transitions <task_id>
```

### Flow Commands (DAG queries, no DB needed)

```bash
# List available flow types
mtask list-flows

# Show a flow's stages and transitions
mtask show-flow <type>
# → stages, next/fail paths, workers, requirements

# Query routing: what happens next?
mtask next-status <type> <current_status> [--failed]
mtask workers-for <type> <status> --class <class_required>
```

### Output Modes

JSON is the default — structured data for integration with minion-commsv2 and other tools. `--compact` strips noise for agent context injection (minimal tokens). `--human` for lead/operator readability.

```bash
# JSON (default) — integration, piping, scripts
mtask list-tasks --class coder --status open
# [{"id": "BUG-001", "task_type": "bugfix", "status": "open", ...}, ...]

# Compact — agent context (minimal tokens)
mtask --compact list-tasks --class coder --status open
# BUG-001 bugfix open coder — loader crashes on circular inheritance
# BUG-003 bugfix open coder — skip resolution infinite loop

mtask --compact complete BUG-001 --agent fighter
# BUG-001 → fixed [oracle, recon]

# Human — readable tables for operators
mtask --human list-tasks --class coder --status open
# ID       TYPE    STATUS  CLASS   ASSIGNED  DESCRIPTION
# BUG-001  bugfix  open    coder   —         loader crashes on circular inheritance
# BUG-003  bugfix  open    coder   —         skip resolution infinite loop
```

`--compact` and `--human` are global flags (before the command), same as minion-commsv2. Errors always go to stderr with non-zero exit.

## Integration with minion-commsv2 (future)

| minion-commsv2 location | Currently | After integration |
|-------------------------|-----------|-------------------|
| `auth.py` `VALID_TRANSITIONS` | Hardcoded dict | Generated from `flow.valid_transitions()` |
| `tasks.py` `update_task()` | Reads `VALID_TRANSITIONS` | Calls `flow.valid_transitions(current)` |
| `tasks.py` `create_task()` | No `--type` flag | Accepts `task_type`, stores in DB |
| `poll.sh` Priority 3-4 | Hardcoded class lists | Reads `flow.workers_for(status, class_required)` |
| DB `tasks` table | No `task_type` column | Add `task_type TEXT DEFAULT 'bugfix'` |

## File Structure

```
minion-tasks/
├── pyproject.toml
├── REQUIREMENTS.md
├── CLAUDE.md
├── task-flows/
│   ├── _base.yaml
│   ├── bugfix.yaml
│   ├── hotfix.yaml
│   ├── research.yaml
│   ├── feature.yaml
│   └── build.yaml
├── minion_tasks/
│   ├── __init__.py
│   ├── cli.py             # Click CLI — `mtask` entry point
│   ├── loader.py          # YAML loading, inheritance, validation
│   ├── dag.py             # TaskFlow class — DAG query API
│   ├── _schema.py         # validation constants
│   └── db.py              # SQLite — projects, tasks, transitions
├── scripts/
│   └── install.sh         # webinstall (pipx → uv → pip)
└── tests/
    ├── conftest.py
    ├── test_loader.py
    ├── test_dag.py
    └── test_db.py
```
