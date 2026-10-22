"""``pytest --gauntlet`` runs the threshold gate instead of adding new tests.

The gate uses the scripted agent. A missing limit is not checked.

Example:
    pytest --gauntlet --gauntlet-config gauntlet.yaml
"""

from __future__ import annotations

from pathlib import Path

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the gate flags."""
    parser.addoption("--gauntlet", action="store_true", default=False, help="Run the gate.")
    parser.addoption("--gauntlet-config", default=None, help="YAML tasks and thresholds.")


def pytest_sessionstart(session: pytest.Session) -> None:
    """Run the gate when ``--gauntlet`` is set. Exit if a threshold is missed."""
    if not session.config.getoption("--gauntlet"):
        return
    from agentgauntlet.gate import GateConfig, execute_gate, load_gate

    raw = session.config.getoption("--gauntlet-config")
    config = load_gate(Path(raw)) if isinstance(raw, str) else GateConfig()
    failures = execute_gate(config, Path("runs"))
    if failures:
        pytest.exit("\n".join(failures), returncode=1)
