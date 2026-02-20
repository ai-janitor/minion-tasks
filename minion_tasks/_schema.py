"""Validation constants for task flow YAML schema."""

REQUIRED_STAGE_KEYS = {"description"}
TERMINAL_STAGE_KEYS = {"description", "terminal", "workers"}
VALID_STAGE_KEYS = {"description", "next", "fail", "workers", "requires", "terminal", "skip"}
REQUIRED_TOP_KEYS = {"name", "description", "stages"}
VALID_TOP_KEYS = {"name", "description", "stages", "inherits", "dead_ends"}
