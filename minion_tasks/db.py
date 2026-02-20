"""SQLite persistence — projects, tasks (pointers), and transition audit log."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .dag import Transition
from .loader import load_flow

DB_PATH = os.getenv(
    "MINION_TASKS_DB_PATH",
    os.path.expanduser("~/.minion-tasks/tasks.db"),
)

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    status      TEXT NOT NULL DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects(id),
    task_type       TEXT NOT NULL DEFAULT 'bugfix',
    description     TEXT NOT NULL,
    file_path       TEXT,
    status          TEXT NOT NULL DEFAULT 'open',
    class_required  TEXT,
    assigned_to     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transitions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL REFERENCES tasks(id),
    from_status TEXT NOT NULL,
    to_status   TEXT NOT NULL,
    agent       TEXT,
    valid       INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class TaskDB:
    def __init__(self, db_path: str | None = None, flows_dir: str | Path | None = None):
        path = db_path or DB_PATH
        if path != ":memory:":
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self._conn = sqlite3.connect(path, timeout=5)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA_SQL)
        self._flows_dir = Path(flows_dir) if flows_dir else None

    # --- helpers ---

    def _row_to_dict(self, row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        return dict(row)

    def _load_flow(self, task_type: str):
        return load_flow(task_type, self._flows_dir)

    # --- Projects ---

    def create_project(self, id: str, description: str) -> dict:
        self._conn.execute(
            "INSERT INTO projects (id, description) VALUES (?, ?)",
            (id, description),
        )
        self._conn.commit()
        return self.get_project(id)

    def get_project(self, id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM projects WHERE id = ?", (id,)).fetchone()
        return self._row_to_dict(row)

    def list_projects(self, status: str | None = None) -> list[dict]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM projects WHERE status = ?", (status,)
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM projects").fetchall()
        return [dict(r) for r in rows]

    # --- Tasks ---

    def create_task(
        self,
        id: str,
        project_id: str,
        task_type: str,
        description: str,
        file_path: str | None = None,
        class_required: str | None = None,
    ) -> dict:
        self._conn.execute(
            """INSERT INTO tasks (id, project_id, task_type, description, file_path, class_required)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (id, project_id, task_type, description, file_path, class_required),
        )
        self._conn.commit()
        return self.get_task(id)

    def get_task(self, id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (id,)).fetchone()
        return self._row_to_dict(row)

    def list_tasks(
        self,
        project_id: str | None = None,
        status: str | None = None,
        class_required: str | None = None,
        assigned_to: str | None = None,
    ) -> list[dict]:
        clauses, params = [], []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if class_required:
            clauses.append("class_required = ?")
            params.append(class_required)
        if assigned_to:
            clauses.append("assigned_to = ?")
            params.append(assigned_to)
        where = " AND ".join(clauses)
        sql = "SELECT * FROM tasks"
        if where:
            sql += f" WHERE {where}"
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    # --- Transitions ---

    def transition_task(self, task_id: str, to_status: str, agent: str | None = None) -> dict:
        """Move task to a new status. Validates against DAG, logs with valid flag."""
        task = self.get_task(task_id)
        if task is None:
            raise ValueError(f"Task '{task_id}' not found")

        from_status = task["status"]
        flow = self._load_flow(task["task_type"])
        valid_targets = flow.valid_transitions(from_status)
        is_valid = to_status in valid_targets

        if not is_valid:
            import warnings
            warnings.warn(
                f"Transition {from_status} → {to_status} not valid for flow '{task['task_type']}'. "
                f"Valid: {valid_targets}. Logging with valid=0.",
                stacklevel=2,
            )

        self._conn.execute(
            "UPDATE tasks SET status = ?, assigned_to = COALESCE(?, assigned_to), "
            "updated_at = datetime('now') WHERE id = ?",
            (to_status, agent, task_id),
        )
        self._conn.execute(
            "INSERT INTO transitions (task_id, from_status, to_status, agent, valid) "
            "VALUES (?, ?, ?, ?, ?)",
            (task_id, from_status, to_status, agent, 1 if is_valid else 0),
        )
        self._conn.commit()
        return self.get_task(task_id)

    def complete(self, task_id: str, agent: str, passed: bool = True) -> Transition | None:
        """Assignee says 'done' — DAG routes to next stage, DB updated."""
        task = self.get_task(task_id)
        if task is None:
            raise ValueError(f"Task '{task_id}' not found")

        flow = self._load_flow(task["task_type"])
        result = flow.transition(task["status"], task["class_required"] or "", passed)
        if result is None:
            return None

        # Update DB
        self._conn.execute(
            "UPDATE tasks SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (result.to_status, task_id),
        )
        self._conn.execute(
            "INSERT INTO transitions (task_id, from_status, to_status, agent, valid) "
            "VALUES (?, ?, ?, ?, 1)",
            (task_id, task["status"], result.to_status, agent),
        )
        self._conn.commit()
        return result

    def get_transitions(self, task_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM transitions WHERE task_id = ? ORDER BY created_at, id",
            (task_id,),
        ).fetchall()
        return [dict(r) for r in rows]
