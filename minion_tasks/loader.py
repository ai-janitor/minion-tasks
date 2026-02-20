"""YAML loading, inheritance resolution, and validation for task flow DAGs."""

from __future__ import annotations

from pathlib import Path

import yaml

from ._schema import REQUIRED_TOP_KEYS
from .dag import Stage, TaskFlow

# Search order: env var, ~/.minion-tasks/task-flows/, bundled with package
def _find_flows_dir() -> Path:
    import os
    import sysconfig

    env = os.getenv("MINION_TASKS_FLOWS_DIR")
    if env:
        return Path(env)
    user_dir = Path.home() / ".minion-tasks" / "task-flows"
    if user_dir.exists():
        return user_dir
    shared = Path(sysconfig.get_path("data")) / "share" / "minion-tasks" / "task-flows"
    if shared.exists():
        return shared
    return Path(__file__).resolve().parent.parent / "task-flows"


_DEFAULT_FLOWS_DIR = _find_flows_dir()


def _load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _merge_stages(base_stages: dict, override_stages: dict | None) -> dict:
    """Deep-merge override stages into base. Override keys replace base keys per-stage."""
    if not override_stages:
        return dict(base_stages)
    merged = {}
    for name, base_cfg in base_stages.items():
        if name in override_stages:
            merged[name] = {**base_cfg, **override_stages[name]}
        else:
            merged[name] = dict(base_cfg)
    for name, cfg in override_stages.items():
        if name not in merged:
            merged[name] = dict(cfg)
    return merged


def _resolve_inheritance(raw: dict, flows_dir: Path) -> dict:
    """If flow has `inherits`, load the parent and merge."""
    parent_name = raw.get("inherits")
    if not parent_name:
        return raw
    parent_path = flows_dir / f"{parent_name}.yaml"
    if not parent_path.exists():
        raise FileNotFoundError(f"Parent flow '{parent_name}' not found at {parent_path}")
    parent_raw = _load_yaml(parent_path)
    parent_raw = _resolve_inheritance(parent_raw, flows_dir)
    merged_stages = _merge_stages(parent_raw.get("stages", {}), raw.get("stages"))
    result = {**parent_raw, **raw}
    result["stages"] = merged_stages
    result.pop("inherits", None)
    return result


def _validate(raw: dict, name: str) -> None:
    """Basic validation — required keys, non-terminal stages need next."""
    missing = REQUIRED_TOP_KEYS - set(raw.keys())
    if missing:
        raise ValueError(f"Flow '{name}' missing required keys: {missing}")
    stages = raw.get("stages", {})
    if not stages:
        raise ValueError(f"Flow '{name}' has no stages")
    for stage_name, cfg in stages.items():
        if cfg.get("skip"):
            continue
        if cfg.get("terminal"):
            continue
        if "next" not in cfg:
            raise ValueError(
                f"Flow '{name}', stage '{stage_name}': non-terminal stage must have 'next'"
            )


def _build_stage(name: str, cfg: dict) -> Stage:
    return Stage(
        name=name,
        description=cfg.get("description", ""),
        next=cfg.get("next"),
        fail=cfg.get("fail"),
        workers=cfg.get("workers"),
        requires=cfg.get("requires", []),
        terminal=cfg.get("terminal", False),
        skip=cfg.get("skip", False),
    )


def load_flow(task_type: str, flows_dir: str | Path | None = None) -> TaskFlow:
    """Load a task flow DAG by type name. Resolves inheritance from _base.yaml."""
    flows_path = Path(flows_dir) if flows_dir else _DEFAULT_FLOWS_DIR
    filename = f"_{task_type}.yaml" if task_type == "base" else f"{task_type}.yaml"
    flow_path = flows_path / filename
    if not flow_path.exists():
        raise FileNotFoundError(f"Task flow '{task_type}' not found at {flow_path}")
    raw = _load_yaml(flow_path)
    raw = _resolve_inheritance(raw, flows_path)
    _validate(raw, task_type)
    stages = {name: _build_stage(name, cfg) for name, cfg in raw["stages"].items()}
    return TaskFlow(
        name=raw["name"],
        description=raw.get("description", ""),
        stages=stages,
        dead_ends=raw.get("dead_ends", []),
    )


def list_flows(flows_dir: str | Path | None = None) -> list[str]:
    """List available task type names."""
    flows_path = Path(flows_dir) if flows_dir else _DEFAULT_FLOWS_DIR
    names = []
    for p in sorted(flows_path.glob("*.yaml")):
        name = p.stem
        if name.startswith("_"):
            name = name[1:]
        names.append(name)
    return names
