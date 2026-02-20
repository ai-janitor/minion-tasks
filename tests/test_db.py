import warnings

import pytest

from minion_tasks import TaskDB
from minion_tasks.dag import Transition

FLOWS_DIR = pytest.importorskip("pathlib").Path(__file__).resolve().parent.parent / "task-flows"


@pytest.fixture
def db():
    return TaskDB(":memory:", flows_dir=FLOWS_DIR)


@pytest.fixture
def db_with_task(db):
    """DB with a bugfix task at 'open' status."""
    db.create_project("proj", "test project")
    db.create_task("BUG-1", "proj", "bugfix", "test bug", class_required="coder")
    return db


def test_create_project(db):
    result = db.create_project("proj", "test project")
    assert result["id"] == "proj"
    assert result["status"] == "active"
    fetched = db.get_project("proj")
    assert fetched["description"] == "test project"


def test_create_task(db_with_task):
    task = db_with_task.get_task("BUG-1")
    assert task["id"] == "BUG-1"
    assert task["project_id"] == "proj"
    assert task["task_type"] == "bugfix"
    assert task["status"] == "open"
    assert task["class_required"] == "coder"


def test_transition_valid(db_with_task):
    db_with_task.transition_task("BUG-1", "assigned", agent="fighter")
    task = db_with_task.get_task("BUG-1")
    assert task["status"] == "assigned"
    assert task["assigned_to"] == "fighter"
    log = db_with_task.get_transitions("BUG-1")
    assert len(log) == 1
    assert log[0]["valid"] == 1


def test_transition_invalid_logged(db_with_task):
    # open → in_progress is not a valid transition (must go through assigned)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        db_with_task.transition_task("BUG-1", "in_progress", agent="fighter")
        assert len(w) == 1
        assert "not valid" in str(w[0].message)
    log = db_with_task.get_transitions("BUG-1")
    assert log[0]["valid"] == 0
    # Task still moved (warn, not block)
    assert db_with_task.get_task("BUG-1")["status"] == "in_progress"


def test_complete_bugfix_pass(db_with_task):
    db = db_with_task
    db.transition_task("BUG-1", "assigned", agent="fighter")
    db.transition_task("BUG-1", "in_progress", agent="fighter")
    result = db.complete("BUG-1", agent="fighter")
    assert result == Transition(to_status="fixed", eligible_classes=["oracle", "recon"])
    assert db.get_task("BUG-1")["status"] == "fixed"


def test_complete_bugfix_review_fail(db_with_task):
    """Review rejection at 'fixed' sends back to assigned."""
    db = db_with_task
    db.transition_task("BUG-1", "assigned", agent="fighter")
    db.transition_task("BUG-1", "in_progress", agent="fighter")
    db.complete("BUG-1", agent="fighter")  # → fixed
    result = db.complete("BUG-1", agent="whitemage", passed=False)
    assert result == Transition(to_status="assigned", eligible_classes=None)
    assert db.get_task("BUG-1")["status"] == "assigned"


def test_complete_hotfix_skips(db):
    db.create_project("proj", "test")
    db.create_task("HOT-1", "proj", "hotfix", "urgent fix", class_required="coder")
    db.transition_task("HOT-1", "assigned", agent="fighter")
    db.transition_task("HOT-1", "in_progress", agent="fighter")
    result = db.complete("HOT-1", agent="fighter")
    assert result == Transition(to_status="closed", eligible_classes=["lead"])
    assert db.get_task("HOT-1")["status"] == "closed"


def test_list_tasks_filters(db):
    db.create_project("p1", "project one")
    db.create_project("p2", "project two")
    db.create_task("T-1", "p1", "bugfix", "bug one", class_required="coder")
    db.create_task("T-2", "p1", "bugfix", "bug two", class_required="recon")
    db.create_task("T-3", "p2", "bugfix", "bug three", class_required="coder")
    db.transition_task("T-1", "assigned", agent="fighter")

    assert len(db.list_tasks(project_id="p1")) == 2
    assert len(db.list_tasks(status="open")) == 2
    assert len(db.list_tasks(class_required="coder")) == 2
    assert len(db.list_tasks(project_id="p1", status="assigned")) == 1


def test_get_transitions_ordered(db_with_task):
    db = db_with_task
    db.transition_task("BUG-1", "assigned", agent="fighter")
    db.transition_task("BUG-1", "in_progress", agent="fighter")
    db.complete("BUG-1", agent="fighter")
    log = db.get_transitions("BUG-1")
    assert len(log) == 3
    statuses = [(t["from_status"], t["to_status"]) for t in log]
    assert statuses == [
        ("open", "assigned"),
        ("assigned", "in_progress"),
        ("in_progress", "fixed"),
    ]
