"""CLI tests using Click's CliRunner — isolated :memory: DB per test."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from minion_tasks.cli import main

FLOWS_DIR = Path(__file__).resolve().parent.parent / "task-flows"


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def db_env(tmp_path):
    """Point TaskDB at a temp file so each test is isolated."""
    db_path = str(tmp_path / "test.db")
    import os

    old = os.environ.get("MINION_TASKS_DB_PATH")
    os.environ["MINION_TASKS_DB_PATH"] = db_path
    yield db_path
    if old is None:
        del os.environ["MINION_TASKS_DB_PATH"]
    else:
        os.environ["MINION_TASKS_DB_PATH"] = old


@pytest.fixture
def seeded_db(runner, db_env):
    """Create a project + task for tests that need existing data."""
    runner.invoke(main, ["create-project", "test-proj", "-d", "Test project"])
    runner.invoke(
        main,
        [
            "create-task", "BUG-001",
            "--project", "test-proj",
            "--type", "bugfix",
            "--description", "loader crashes on circular inheritance",
            "--class", "coder",
        ],
    )
    return db_env


# --- Project round-trip ---


def test_create_and_get_project(runner, db_env):
    result = runner.invoke(main, ["create-project", "proj1", "-d", "My project"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["id"] == "proj1"
    assert data["status"] == "active"

    result = runner.invoke(main, ["get-project", "proj1"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["description"] == "My project"


# --- Task round-trip ---


def test_create_and_get_task(runner, db_env):
    runner.invoke(main, ["create-project", "p1", "-d", "proj"])
    result = runner.invoke(
        main,
        ["create-task", "T-1", "-p", "p1", "--type", "bugfix", "-d", "test task", "--class", "coder"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["id"] == "T-1"
    assert data["status"] == "open"
    assert data["class_required"] == "coder"

    result = runner.invoke(main, ["get-task", "T-1"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["description"] == "test task"


# --- list-tasks filters ---


def test_list_tasks_filter_by_class(runner, seeded_db):
    result = runner.invoke(main, ["list-tasks", "--class", "coder"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 1
    assert data[0]["id"] == "BUG-001"

    result = runner.invoke(main, ["list-tasks", "--class", "oracle"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 0


# --- claim-task ---


def test_claim_task(runner, seeded_db):
    result = runner.invoke(main, ["claim-task", "BUG-001", "fighter"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "assigned"
    assert data["assigned_to"] == "fighter"


def test_claim_task_not_open(runner, seeded_db):
    runner.invoke(main, ["claim-task", "BUG-001", "fighter"])
    result = runner.invoke(main, ["claim-task", "BUG-001", "thief"])
    assert result.exit_code == 1
    assert "not 'open'" in result.output or "not 'open'" in (result.stderr or "")


# --- transition ---


def test_transition_valid(runner, seeded_db):
    runner.invoke(main, ["claim-task", "BUG-001", "fighter"])
    result = runner.invoke(main, ["transition", "BUG-001", "in_progress", "--agent", "fighter"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "in_progress"


# --- complete ---


def test_complete_returns_routing(runner, seeded_db):
    runner.invoke(main, ["claim-task", "BUG-001", "fighter"])
    runner.invoke(main, ["transition", "BUG-001", "in_progress", "--agent", "fighter"])
    result = runner.invoke(main, ["complete", "BUG-001", "--agent", "fighter"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["to_status"] == "fixed"
    assert isinstance(data["eligible_classes"], list)


def test_complete_failed(runner, seeded_db):
    """Fail path available at 'fixed' stage — sends back to 'assigned'."""
    runner.invoke(main, ["claim-task", "BUG-001", "fighter"])
    runner.invoke(main, ["transition", "BUG-001", "in_progress", "--agent", "fighter"])
    # Complete in_progress → fixed (happy path)
    runner.invoke(main, ["complete", "BUG-001", "--agent", "fighter"])
    # Now at 'fixed' — complete with --failed → back to assigned
    result = runner.invoke(main, ["complete", "BUG-001", "--agent", "whitemage", "--failed"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["to_status"] == "assigned"


# --- transitions audit log ---


def test_transitions_audit_log(runner, seeded_db):
    runner.invoke(main, ["claim-task", "BUG-001", "fighter"])
    runner.invoke(main, ["transition", "BUG-001", "in_progress", "--agent", "fighter"])
    result = runner.invoke(main, ["transitions", "BUG-001"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert len(data) == 2
    assert data[0]["from_status"] == "open"
    assert data[0]["to_status"] == "assigned"
    assert data[1]["to_status"] == "in_progress"


# --- Flow commands (no DB) ---


def test_list_flows(runner):
    result = runner.invoke(main, ["list-flows"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "bugfix" in data
    assert "hotfix" in data


def test_show_flow_bugfix(runner):
    result = runner.invoke(main, ["show-flow", "bugfix"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["name"] == "bugfix"
    assert len(data["stages"]) > 0


# --- Compact output ---


def test_compact_list_tasks(runner, seeded_db):
    result = runner.invoke(main, ["--compact", "list-tasks", "--class", "coder"])
    assert result.exit_code == 0
    assert "BUG-001" in result.output
    assert "bugfix" in result.output
    assert "coder" in result.output


def test_compact_claim(runner, seeded_db):
    result = runner.invoke(main, ["--compact", "claim-task", "BUG-001", "fighter"])
    assert result.exit_code == 0
    assert "BUG-001" in result.output
    assert "assigned" in result.output
    assert "fighter" in result.output


def test_compact_complete(runner, seeded_db):
    runner.invoke(main, ["claim-task", "BUG-001", "fighter"])
    runner.invoke(main, ["transition", "BUG-001", "in_progress", "--agent", "fighter"])
    result = runner.invoke(main, ["--compact", "complete", "BUG-001", "--agent", "fighter"])
    assert result.exit_code == 0
    assert "fixed" in result.output


def test_compact_transitions(runner, seeded_db):
    runner.invoke(main, ["claim-task", "BUG-001", "fighter"])
    result = runner.invoke(main, ["--compact", "transitions", "BUG-001"])
    assert result.exit_code == 0
    assert "open → assigned" in result.output
    assert "✓" in result.output
