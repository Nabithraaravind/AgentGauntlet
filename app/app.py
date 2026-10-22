"""Gradio leaderboard. It reads ``results/`` and does not call a model.

Example:
    uv run --group app python app/app.py
"""

from __future__ import annotations

from pathlib import Path

import gradio as gr

from agentgauntlet.reporting.leaderboard import load_leaderboard

_EMPTY = (
    "No measured runs are in `results/` yet. "
    "This page stays empty until a real model run is recorded."
)


def build(results_dir: Path) -> gr.Blocks:
    """Build the leaderboard. An empty directory explains that no score exists."""
    rows = load_leaderboard(results_dir)
    with gr.Blocks(title="AgentGauntlet") as demo:
        gr.Markdown("# AgentGauntlet")
        if rows:
            gr.Dataframe(value=rows)
        else:
            gr.Markdown(_EMPTY)
    return demo


def main() -> None:
    """Launch the app against the repository ``results`` directory."""
    root = Path(__file__).resolve().parents[1] / "results"
    build(root).launch()


if __name__ == "__main__":
    main()
