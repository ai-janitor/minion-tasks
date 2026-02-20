from minion_tasks import load_flow
from minion_tasks.dag import Transition


def test_next_status_base(flows_dir):
    flow = load_flow("base", flows_dir)
    assert flow.next_status("in_progress", passed=True) == "fixed"
    assert flow.next_status("fixed", passed=True) == "verified"
    assert flow.next_status("fixed", passed=False) == "assigned"
    assert flow.next_status("closed") is None


def test_next_status_hotfix_skips(flows_dir):
    flow = load_flow("hotfix", flows_dir)
    # in_progress → fixed (skipped) → verified (skipped) → closed
    assert flow.next_status("in_progress", passed=True) == "closed"


def test_workers_for_fixed_coder(flows_dir):
    flow = load_flow("base", flows_dir)
    assert flow.workers_for("fixed", "coder") == ["oracle", "recon"]


def test_workers_for_assigned_returns_none(flows_dir):
    flow = load_flow("base", flows_dir)
    assert flow.workers_for("assigned", "coder") is None


def test_workers_for_closed(flows_dir):
    flow = load_flow("base", flows_dir)
    assert flow.workers_for("closed", "coder") == ["lead"]


def test_valid_transitions_assigned(flows_dir):
    flow = load_flow("base", flows_dir)
    transitions = flow.valid_transitions("assigned")
    assert transitions == {"in_progress", "abandoned", "stale", "obsolete"}


def test_requires_fixed(flows_dir):
    flow = load_flow("base", flows_dir)
    # requires is on in_progress (before transitioning to fixed)
    assert flow.requires("in_progress") == ["submit_result"]
    assert flow.requires("assigned") == []


def test_is_terminal(flows_dir):
    flow = load_flow("base", flows_dir)
    assert flow.is_terminal("closed") is True
    assert flow.is_terminal("open") is False
    assert flow.is_terminal("nonexistent") is False


def test_build_skips_fixed(flows_dir):
    flow = load_flow("build", flows_dir)
    assert flow.stages["fixed"].skip is True
    # in_progress → (fixed skipped) → verified
    assert flow.next_status("in_progress", passed=True) == "verified"


def test_hotfix_valid_transitions_in_progress(flows_dir):
    """Hotfix in_progress should show closed (after skip resolution), not fixed."""
    flow = load_flow("hotfix", flows_dir)
    transitions = flow.valid_transitions("in_progress")
    assert "closed" in transitions
    assert "fixed" not in transitions


def test_transition_bugfix_pass(flows_dir):
    flow = load_flow("bugfix", flows_dir)
    result = flow.transition("in_progress", "coder")
    assert result == Transition(to_status="fixed", eligible_classes=["oracle", "recon"])


def test_transition_bugfix_review_fail(flows_dir):
    """Review rejection at 'fixed' sends back to assigned (same agent continues)."""
    flow = load_flow("bugfix", flows_dir)
    result = flow.transition("fixed", "coder", passed=False)
    assert result == Transition(to_status="assigned", eligible_classes=None)


def test_transition_hotfix_skips_to_closed(flows_dir):
    flow = load_flow("hotfix", flows_dir)
    result = flow.transition("in_progress", "coder")
    assert result == Transition(to_status="closed", eligible_classes=["lead"])


def test_transition_terminal_returns_none(flows_dir):
    flow = load_flow("bugfix", flows_dir)
    result = flow.transition("closed", "coder")
    assert result is None
