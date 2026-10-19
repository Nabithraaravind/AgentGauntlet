"""Smoke tests that prove the package installs and versions match."""

from __future__ import annotations

import tomllib
from importlib.metadata import version
from pathlib import Path

import agentgauntlet

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_version_matches_pyproject() -> None:
    """The installed version is the version declared in ``pyproject.toml``."""
    pyproject_path = _REPO_ROOT / "pyproject.toml"
    with pyproject_path.open("rb") as handle:
        declared = tomllib.load(handle)["project"]["version"]

    assert agentgauntlet.__version__ == declared
    assert agentgauntlet.__version__ == version("agentgauntlet")


def test_public_api_lists_version() -> None:
    """``__all__`` names the symbols this package promises to keep."""
    assert agentgauntlet.__all__ == ["__version__"]
