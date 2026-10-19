"""Replay every reference solution and exit non-zero if one cannot reach its state.

Example:
    python tasks/validate.py
"""

from __future__ import annotations

import sys

from agentgauntlet.tasks.loader import TaskLoadError
from agentgauntlet.tasks.replay import validate_library


def main() -> int:
    """Validate the packaged library. Return 0 when every task is solvable."""
    try:
        problems, count = validate_library()
    except TaskLoadError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    if problems:
        sys.stderr.write("\n".join(problems) + "\n")
        return 1
    sys.stderr.write(f"Validated {count} tasks.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
