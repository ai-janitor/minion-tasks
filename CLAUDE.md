# minion-tasks

DAG-based task flow engine. YAML-defined pipelines for minion-commsv2 task lifecycle.

## Dev Reference

| What | Where |
|------|-------|
| YAML flow definitions | `task-flows/` |
| Base template (all types inherit) | `task-flows/_base.yaml` |
| YAML loader + inheritance | `src/minion_tasks/loader.py` |
| TaskFlow query API | `src/minion_tasks/dag.py` |
| Schema constants | `src/minion_tasks/_schema.py` |
| Tests | `tests/` |

## Running Tests

```bash
uv run pytest
```

## Adding a New Task Type

1. Create `task-flows/<type>.yaml`
2. Set `inherits: _base` to get the full pipeline
3. Override only the stages that differ (set `skip: true` to skip stages)
4. Tests auto-discover flows via `list_flows()`
