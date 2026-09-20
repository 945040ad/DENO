"""Test isolation: no real database file, no auth provider, no network by default."""

import os
import tempfile
from pathlib import Path

import pytest

# Must run before any deno_* import: settings are read at import time.
_TMP = Path(tempfile.mkdtemp(prefix="deno-tests-"))
os.environ["ENVIRONMENT"] = "test"
os.environ["SUPABASE_URL"] = ""
os.environ["LOG_JSON"] = "false"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    live_dir = Path(__file__).parent / "live"
    for item in items:
        if live_dir in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.live)
