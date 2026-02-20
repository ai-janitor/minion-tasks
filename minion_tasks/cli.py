"""Click CLI entrypoint — `mtask <subcommand>`.

JSON output by default, --human for tables, --compact for agent context.
"""

from __future__ import annotations

import json
import sys

import click


def _output(data, human: bool = False, compact: bool = False) -> None:
    """Route output: JSON (default), compact (agent context), or human (tables)."""
    if isinstance(data, dict) and "error" in data:
        click.echo(json.dumps(data, indent=2, default=str), err=True)
        sys.exit(1)
    if compact:
        click.echo(_format_compact(data))
    elif human:
        _print_human(data)
    else:
        click.echo(json.dumps(data, indent=2, default=str))


def _print_human(data) -> None:
    if isinstance(data, list):
        if not data:
            click.echo("(none)")
            return
        if isinstance(data[0], dict):
            keys = list(data[0].keys())
            widths = {k: max(len(k), *(len(str(row.get(k, ""))) for row in data)) for k in keys}
            header = "  ".join(k.upper().ljust(widths[k]) for k in keys)
            click.echo(header)
            for row in data:
                click.echo("  ".join(str(row.get(k, "")).ljust(widths[k]) for k in keys))
        else:
            for item in data:
                click.echo(item)
    elif isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (list, dict)):
                click.echo(f"{k}: {json.dumps(v, indent=2, default=str)}")
            else:
                click.echo(f"{k}: {v}")
    else:
        click.echo(data)


def _format_compact(data) -> str:
    """Format CLI output as concise text for agent context injection."""
    if isinstance(data, list):
        if not data:
            return "(none)"
        if isinstance(data[0], dict):
            lines = []
            for row in data:
                # Task list compact
                if "task_type" in row:
                    assigned = row.get("assigned_to") or "—"
                    lines.append(
                        f"{row['id']} {row['task_type']} {row['status']} "
                        f"{row.get('class_required', '—')} {assigned} — {row['description']}"
                    )
                # Project list compact
                elif "description" in row and "status" in row:
                    lines.append(f"{row['id']} {row['status']} — {row['description']}")
                # Transition log compact
                elif "from_status" in row:
                    agent_str = f" ({row['agent']})" if row.get("agent") else ""
                    valid_mark = "✓" if row.get("valid", 1) else "✗"
                    lines.append(f"{row['from_status']} → {row['to_status']}{agent_str} {valid_mark}")
                else:
                    lines.append(json.dumps(row, default=str))
            return "\n".join(lines)
        return "\n".join(str(x) for x in data)

    if isinstance(data, dict):
        # Transition result from complete()
        if "to_status" in data and "eligible_classes" in data:
            task_id = data.get("task_id", "")
            classes = data.get("eligible_classes") or []
            prefix = f"{task_id} → " if task_id else "→ "
            if classes:
                return f"{prefix}{data['to_status']} [{', '.join(classes)}]"
            return f"{prefix}{data['to_status']}"

        # Claim result
        if "assigned_to" in data and "status" in data and "id" in data:
            return f"{data['id']} → {data['status']} ({data['assigned_to']})"

        # Single task
        if "task_type" in data:
            assigned = data.get("assigned_to") or "—"
            return (
                f"{data['id']} {data['task_type']} {data['status']} "
                f"{data.get('class_required', '—')} {assigned} — {data['description']}"
            )

        # Single project
        if "description" in data and "status" in data and "id" in data:
            return f"{data['id']} {data['status']} — {data['description']}"

        # Flow info
        if "stages" in data:
            lines = [f"flow: {data.get('name', '?')}"]
            for s in data["stages"]:
                if isinstance(s, dict):
                    skip = " [skip]" if s.get("skip") else ""
                    term = " [terminal]" if s.get("terminal") else ""
                    next_s = f" → {s['next']}" if s.get("next") else ""
                    lines.append(f"  {s['name']}{next_s}{skip}{term}")
                else:
                    lines.append(f"  {s}")
            return "\n".join(lines)

        return json.dumps(data, default=str)

    return str(data)


def _get_db(ctx):
    """Lazy DB init — cached in ctx.obj. Re-reads env var each time (not module-level)."""
    if "db" not in ctx.obj:
        import os

        from minion_tasks import TaskDB

        db_path = os.getenv("MINION_TASKS_DB_PATH")
        ctx.obj["db"] = TaskDB(db_path=db_path)
    return ctx.obj["db"]


@click.group()
@click.option("--human", is_flag=True, help="Human-readable table output")
@click.option("--compact", is_flag=True, help="Compact output for agent context")
@click.pass_context
def main(ctx, human, compact):
    """mtask — DAG-based task flow engine CLI."""
    ctx.ensure_object(dict)
    ctx.obj["human"] = human
    ctx.obj["compact"] = compact


# --- Project Commands ---


@main.command("create-project")
@click.argument("id")
@click.option("--description", "-d", required=True, help="Project description")
@click.pass_context
def create_project(ctx, id, description):
    """Create a new project."""
    db = _get_db(ctx)
    result = db.create_project(id, description)
    _output(result, ctx.obj["human"], ctx.obj["compact"])


@main.command("list-projects")
@click.option("--status", default=None, help="Filter by status (active, archived)")
@click.pass_context
def list_projects(ctx, status):
    """List all projects."""
    db = _get_db(ctx)
    result = db.list_projects(status=status)
    _output(result, ctx.obj["human"], ctx.obj["compact"])


@main.command("get-project")
@click.argument("id")
@click.pass_context
def get_project(ctx, id):
    """Get project details."""
    db = _get_db(ctx)
    result = db.get_project(id)
    if result is None:
        _output({"error": f"Project '{id}' not found"})
    _output(result, ctx.obj["human"], ctx.obj["compact"])


# --- Task Commands ---


@main.command("create-task")
@click.argument("id")
@click.option("--project", "-p", required=True, help="Project ID")
@click.option("--type", "task_type", default="bugfix", help="Task type (flow name)")
@click.option("--description", "-d", required=True, help="One-line task description")
@click.option("--file", "file_path", default=None, help="Path to spec/work file")
@click.option("--class", "class_required", default=None, help="Required agent class")
@click.pass_context
def create_task(ctx, id, project, task_type, description, file_path, class_required):
    """Create a task pointer."""
    db = _get_db(ctx)
    try:
        result = db.create_task(
            id=id,
            project_id=project,
            task_type=task_type,
            description=description,
            file_path=file_path,
            class_required=class_required,
        )
        _output(result, ctx.obj["human"], ctx.obj["compact"])
    except Exception as e:
        _output({"error": str(e)})


@main.command("list-tasks")
@click.option("--project", default=None, help="Filter by project ID")
@click.option("--status", default=None, help="Filter by status")
@click.option("--class", "class_required", default=None, help="Filter by class_required")
@click.option("--assigned-to", default=None, help="Filter by assigned agent")
@click.pass_context
def list_tasks(ctx, project, status, class_required, assigned_to):
    """List tasks with optional filters."""
    db = _get_db(ctx)
    result = db.list_tasks(
        project_id=project,
        status=status,
        class_required=class_required,
        assigned_to=assigned_to,
    )
    _output(result, ctx.obj["human"], ctx.obj["compact"])


@main.command("get-task")
@click.argument("id")
@click.pass_context
def get_task(ctx, id):
    """Get task details."""
    db = _get_db(ctx)
    result = db.get_task(id)
    if result is None:
        _output({"error": f"Task '{id}' not found"})
    _output(result, ctx.obj["human"], ctx.obj["compact"])


@main.command("claim-task")
@click.argument("task_id")
@click.argument("agent")
@click.pass_context
def claim_task(ctx, task_id, agent):
    """Claim an open task — sets assigned_to + transitions to assigned."""
    db = _get_db(ctx)
    task = db.get_task(task_id)
    if task is None:
        _output({"error": f"Task '{task_id}' not found"})
        return
    if task["status"] != "open":
        _output({"error": f"Task '{task_id}' is '{task['status']}', not 'open'"})
        return
    result = db.transition_task(task_id, "assigned", agent=agent)
    _output(result, ctx.obj["human"], ctx.obj["compact"])


# --- Transition Commands ---


@main.command("transition")
@click.argument("task_id")
@click.argument("to_status")
@click.option("--agent", default=None, help="Agent triggering transition")
@click.pass_context
def transition(ctx, task_id, to_status, agent):
    """Manually transition a task to a new status."""
    db = _get_db(ctx)
    try:
        result = db.transition_task(task_id, to_status, agent=agent)
        _output(result, ctx.obj["human"], ctx.obj["compact"])
    except ValueError as e:
        _output({"error": str(e)})


@main.command("complete")
@click.argument("task_id")
@click.option("--agent", required=True, help="Agent completing the task")
@click.option("--failed", is_flag=True, help="Mark as failed (rejection path)")
@click.pass_context
def complete(ctx, task_id, agent, failed):
    """Assignee says 'done' — DAG routes to next stage."""
    db = _get_db(ctx)
    try:
        result = db.complete(task_id, agent=agent, passed=not failed)
        if result is None:
            _output({"error": f"No transition available from current status of '{task_id}'"})
            return
        out = {
            "task_id": task_id,
            "to_status": result.to_status,
            "eligible_classes": result.eligible_classes,
        }
        _output(out, ctx.obj["human"], ctx.obj["compact"])
    except ValueError as e:
        _output({"error": str(e)})


@main.command("transitions")
@click.argument("task_id")
@click.pass_context
def transitions(ctx, task_id):
    """Show transition audit log for a task."""
    db = _get_db(ctx)
    result = db.get_transitions(task_id)
    _output(result, ctx.obj["human"], ctx.obj["compact"])


# --- Flow Commands (no DB) ---


@main.command("list-flows")
@click.pass_context
def list_flows_cmd(ctx):
    """List available flow types."""
    from minion_tasks import list_flows

    result = list_flows()
    _output(result, ctx.obj["human"], ctx.obj["compact"])


@main.command("show-flow")
@click.argument("type_name")
@click.pass_context
def show_flow(ctx, type_name):
    """Show a flow's stages and transitions."""
    from minion_tasks import load_flow

    try:
        flow = load_flow(type_name)
    except FileNotFoundError as e:
        _output({"error": str(e)})
        return

    stages = []
    for name, stage in flow.stages.items():
        stages.append({
            "name": name,
            "description": stage.description,
            "next": stage.next,
            "fail": stage.fail,
            "workers": stage.workers,
            "requires": stage.requires,
            "terminal": stage.terminal,
            "skip": stage.skip,
        })

    out = {
        "name": flow.name,
        "description": flow.description,
        "stages": stages,
        "dead_ends": flow.dead_ends,
    }
    _output(out, ctx.obj["human"], ctx.obj["compact"])


@main.command("next-status")
@click.argument("type_name")
@click.argument("current")
@click.option("--failed", is_flag=True, help="Query fail path instead of happy path")
@click.pass_context
def next_status(ctx, type_name, current, failed):
    """Query routing: what status comes next?"""
    from minion_tasks import load_flow

    try:
        flow = load_flow(type_name)
    except FileNotFoundError as e:
        _output({"error": str(e)})
        return

    result = flow.next_status(current, passed=not failed)
    out = {"type": type_name, "current": current, "next": result}
    _output(out, ctx.obj["human"], ctx.obj["compact"])
