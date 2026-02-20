# minion-tasks

DAG-based task flow engine for multi-agent coordination. Define task pipelines in YAML, track projects and tasks in SQLite, let the DAG handle all routing.

## What it does

Different task types need different pipelines:

- **bugfix** — code, review, test, close (full pipeline)
- **hotfix** — code, close (skip review + test)
- **feature** — code, review, test, close
- **research** — investigate, report, close

Each pipeline is a YAML file in `task-flows/`. Workers just say "I'm done" — the DAG decides where the task goes next and who picks it up.

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/ai-janitor/minion-tasks/main/scripts/install.sh | bash
```

Or manually:

```bash
# pipx (recommended)
pipx install git+https://github.com/ai-janitor/minion-tasks.git

# uv
uv tool install git+https://github.com/ai-janitor/minion-tasks.git

# pip
pip install git+https://github.com/ai-janitor/minion-tasks.git
```

## Quick start

```bash
# Create a project and task
mtask create-project myapp -d "My application"
mtask create-task BUG-001 -p myapp --type bugfix -d "auth crash on empty token" --class coder

# Worker claims and completes
mtask claim-task BUG-001 fighter
mtask transition BUG-001 in_progress --agent fighter
mtask complete BUG-001 --agent fighter
# => BUG-001 -> fixed [oracle, recon]  (DAG routes to reviewer)

# Reviewer rejects
mtask complete BUG-001 --agent whitemage --failed
# => BUG-001 -> assigned  (DAG sends back to coder)
```

## Worker commands

Workers need 4 commands:

```bash
mtask --compact list-tasks --class coder --status open   # what can I work on?
mtask claim-task BUG-001 fighter                          # I'll take this
mtask complete BUG-001 --agent fighter                    # I'm done
mtask complete BUG-001 --agent fighter --failed           # it failed
```

## Lead commands

```bash
mtask create-project <id> -d "..."
mtask create-task <id> -p <project> --type bugfix -d "..." --class coder
mtask transition <task_id> <status> --agent <name>        # force-move
mtask transitions <task_id>                                # audit trail
mtask list-flows                                           # available pipelines
mtask show-flow bugfix                                     # inspect a pipeline
mtask next-status bugfix in_progress                       # what comes next?
```

## Output modes

```bash
mtask list-tasks                              # JSON (default, for scripts)
mtask --compact list-tasks --class coder      # compact (for agent context)
mtask --human list-tasks                      # table (for operators)
```

## Custom flows

Add a YAML file to `task-flows/`:

```yaml
name: hotfix
inherits: _base
stages:
  fixed:
    skip: true
  verified:
    skip: true
```

Flows inherit from `_base.yaml` and override only what's different.

## License

MIT
