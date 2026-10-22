"""The pytest flags call the gate and exit only when it fails."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from agentgauntlet import pytest_plugin
from agentgauntlet.gate import GateConfig

importlib.reload(pytest_plugin)


class _Options:
    def __init__(self, gauntlet: bool, config: str | None) -> None:
        self._values: dict[str, object] = {
            "--gauntlet": gauntlet,
            "--gauntlet-config": config,
        }

    def getoption(self, name: str) -> object:
        return self._values[name]


class _Session:
    def __init__(self, gauntlet: bool, config: str | None = None) -> None:
        self.config = _Options(gauntlet, config)


def test_plugin_registers_the_gate_flags() -> None:
    """The two flags exist so a normal pytest command can start the gate."""

    class _Parser:
        def __init__(self) -> None:
            self.names: list[str] = []

        def addoption(self, name: str, **_kwargs: object) -> None:
            self.names.append(name)

    parser = _Parser()
    pytest_plugin.pytest_addoption(parser)  # type: ignore[arg-type]
    assert parser.names == ["--gauntlet", "--gauntlet-config"]


def test_plugin_does_nothing_without_the_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """A normal pytest run does not start the gate."""

    def explode(config: GateConfig, runs_dir: Path) -> list[str]:
        raise AssertionError((config, runs_dir))

    monkeypatch.setattr("agentgauntlet.gate.execute_gate", explode)
    pytest_plugin.pytest_sessionstart(_Session(False))  # type: ignore[arg-type]


def test_plugin_loads_a_config_and_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A gate file is read, and an empty failure list does not exit."""
    path = tmp_path / "gauntlet.yaml"
    path.write_text("tasks: [retail-002]\n", encoding="utf-8")
    seen: dict[str, object] = {}

    def record(config: GateConfig, runs_dir: Path) -> list[str]:
        seen["tasks"] = config.tasks
        seen["runs"] = runs_dir
        return []

    monkeypatch.setattr("agentgauntlet.gate.execute_gate", record)
    pytest_plugin.pytest_sessionstart(_Session(True, str(path)))  # type: ignore[arg-type]
    assert seen["tasks"] == ["retail-002"]


def test_plugin_exits_when_the_gate_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Threshold text becomes the pytest exit message."""
    monkeypatch.setattr("agentgauntlet.gate.execute_gate", lambda _config, _runs: ["pass@1 is low"])
    with pytest.raises(BaseException, match="pass@1 is low") as caught:
        pytest_plugin.pytest_sessionstart(_Session(True))  # type: ignore[arg-type]
    assert type(caught.value).__name__ == "Exit"
