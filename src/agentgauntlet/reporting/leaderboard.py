"""Load checked-in result files for the Gradio app.

A file in ``results/`` is a JSON object with a model name and the metrics that
were actually measured. This loader does not invent a row when the directory
is empty.

Example:
    from pathlib import Path

    from agentgauntlet.reporting.leaderboard import load_leaderboard

    load_leaderboard(Path("results"))
"""

from __future__ import annotations

import json
from pathlib import Path


def load_leaderboard(results_dir: Path) -> list[dict[str, object]]:
    """Return one row per JSON file, sorted by model name."""
    if not results_dir.is_dir():
        return []
    rows: list[dict[str, object]] = []
    for path in sorted(results_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        model = payload.get("model")
        if not isinstance(model, str):
            continue
        rows.append(
            {
                "model": model,
                "pass_at_1": payload.get("pass_at_1"),
                "pass_hat_5": payload.get("pass_hat_5"),
                "asr": payload.get("asr"),
                "cost_per_success": payload.get("cost_per_success"),
            }
        )
    rows.sort(key=lambda row: str(row["model"]))
    return rows
