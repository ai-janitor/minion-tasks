from pathlib import Path

import pytest

FLOWS_DIR = Path(__file__).resolve().parent.parent / "task-flows"


@pytest.fixture
def flows_dir():
    return FLOWS_DIR
