import pytest

from minion_tasks import load_flow, list_flows


def test_load_base(flows_dir):
    flow = load_flow("base", flows_dir)
    assert flow.name == "base"
    assert "open" in flow.stages
    assert "assigned" in flow.stages
    assert "in_progress" in flow.stages
    assert "fixed" in flow.stages
    assert "verified" in flow.stages
    assert "closed" in flow.stages


def test_load_hotfix_skips(flows_dir):
    flow = load_flow("hotfix", flows_dir)
    assert flow.stages["fixed"].skip is True
    assert flow.stages["verified"].skip is True


def test_load_nonexistent(flows_dir):
    with pytest.raises(FileNotFoundError):
        load_flow("nonexistent", flows_dir)


def test_invalid_yaml_missing_next(tmp_path):
    bad_yaml = tmp_path / "broken.yaml"
    bad_yaml.write_text(
        "name: broken\n"
        "description: bad\n"
        "stages:\n"
        "  open:\n"
        "    description: no next\n"
    )
    with pytest.raises(ValueError, match="must have 'next'"):
        load_flow("broken", tmp_path)


def test_list_flows(flows_dir):
    names = list_flows(flows_dir)
    assert "base" in names
    assert "bugfix" in names
    assert "hotfix" in names
    assert "research" in names
    assert "feature" in names
    assert "build" in names


def test_inheritance_merges_stages(flows_dir):
    """Bugfix inherits all base stages unchanged."""
    flow = load_flow("bugfix", flows_dir)
    assert flow.name == "bugfix"
    assert len(flow.stages) == 6
    assert flow.dead_ends == ["abandoned", "stale", "obsolete"]


def test_research_overrides_workers(flows_dir):
    flow = load_flow("research", flows_dir)
    fixed = flow.stages["fixed"]
    assert fixed.workers == {"default": ["oracle"], "recon": ["oracle"]}
