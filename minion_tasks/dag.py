"""TaskFlow — query transitions, workers, and requirements from a loaded DAG."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Stage:
    name: str
    description: str
    next: str | None = None
    fail: str | None = None
    workers: dict[str, list[str]] | list[str] | None = None
    requires: list[str] = field(default_factory=list)
    terminal: bool = False
    skip: bool = False


@dataclass
class TaskFlow:
    name: str
    description: str
    stages: dict[str, Stage]
    dead_ends: list[str] = field(default_factory=list)

    def _resolve_skip(self, stage_name: str | None, seen: set[str] | None = None) -> str | None:
        """Follow skip chain until we hit a non-skipped stage or None."""
        if stage_name is None:
            return None
        if seen is None:
            seen = set()
        if stage_name in seen:
            return None
        seen.add(stage_name)
        stage = self.stages.get(stage_name)
        if stage is None:
            return stage_name
        if stage.skip:
            return self._resolve_skip(stage.next, seen)
        return stage_name

    def next_status(self, current: str, passed: bool = True) -> str | None:
        """Given current status and pass/fail, return the next status.
        Resolves skip stages — if next stage has skip=true, jump to the one after."""
        stage = self.stages.get(current)
        if stage is None or stage.terminal:
            return None
        target = stage.next if passed else stage.fail
        return self._resolve_skip(target)

    def workers_for(self, status: str, class_required: str) -> list[str] | None:
        """Which agent classes can work on this stage for a task with given class_required.
        Returns None if the already-assigned agent continues."""
        stage = self.stages.get(status)
        if stage is None:
            return None
        workers = stage.workers
        if workers is None:
            return None
        if isinstance(workers, list):
            return workers
        if class_required in workers:
            return workers[class_required]
        return workers.get("default")

    def requires(self, status: str) -> list[str]:
        """Preconditions before transitioning INTO this status."""
        stage = self.stages.get(status)
        if stage is None:
            return []
        return stage.requires

    def valid_transitions(self, current: str) -> set[str]:
        """All valid next statuses from current (including dead_ends)."""
        stage = self.stages.get(current)
        if stage is None or stage.terminal:
            return set()
        result = set(self.dead_ends)
        next_resolved = self._resolve_skip(stage.next)
        if next_resolved:
            result.add(next_resolved)
        if stage.fail:
            result.add(stage.fail)
        return result

    def transition(self, current: str, class_required: str, passed: bool = True) -> Transition | None:
        """Single-call routing: next status + eligible worker classes."""
        to_status = self.next_status(current, passed)
        if to_status is None:
            return None
        eligible = self.workers_for(to_status, class_required)
        return Transition(to_status=to_status, eligible_classes=eligible)

    def is_terminal(self, status: str) -> bool:
        """Is this a terminal stage?"""
        stage = self.stages.get(status)
        if stage is None:
            return False
        return stage.terminal


@dataclass
class Transition:
    to_status: str
    eligible_classes: list[str] | None  # None = current assignee continues
