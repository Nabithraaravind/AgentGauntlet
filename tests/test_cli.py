"""The Typer commands on one scripted trial."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentgauntlet.agents import ReactAgent
from agentgauntlet.cli import _agent, app, format_compare, main, select_tasks
from agentgauntlet.runner.engine import RunSummary, TrialOutcome
from agentgauntlet.tasks import load_tasks

runner = CliRunner()


def test_main_prints_help(monkeypatch: pytest.MonkeyPatch) -> None:
    """The console script shows the command list."""
    monkeypatch.setattr(sys, "argv", ["gauntlet", "--help"])
    with pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code == 0


def test_react_agent_is_built_without_a_model_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """Constructing the React agent does not call LiteLLM."""
    monkeypatch.delenv("OLLAMA_API_BASE", raising=False)
    plain = _agent("react", "ollama/qwen2.5:7b-instruct")
    assert isinstance(plain, ReactAgent)
    assert plain.name.startswith("react:")
    assert plain.api_base is None
    monkeypatch.setenv("OLLAMA_API_BASE", "http://127.0.0.1:11434")
    pointed = _agent("react", "ollama/qwen2.5:7b-instruct")
    assert isinstance(pointed, ReactAgent)
    assert pointed.api_base == "http://127.0.0.1:11434"


def test_list_init_and_select() -> None:
    """List prints retail ids, init writes a gate file, and all means every task."""
    listed = runner.invoke(app, ["list", "tasks", "--domain", "retail"])
    assert listed.exit_code == 0
    assert "retail-001" in listed.stdout
    assert "travel-001" not in listed.stdout
    everything = runner.invoke(app, ["list", "tasks"])
    assert everything.exit_code == 0
    assert "travel-001" in everything.stdout
    unknown = runner.invoke(app, ["list", "widgets"])
    assert unknown.exit_code == 1
    assert select_tasks("all", load_tasks())
    assert len(select_tasks("travel", load_tasks())) == 25
    assert [task.id for task in select_tasks("retail-001", load_tasks())] == ["retail-001"]


def test_init_writes_the_sample(tmp_path: Path) -> None:
    """Init creates a YAML file the gate can read."""
    dest = tmp_path / "nested" / "gauntlet.yaml"
    result = runner.invoke(app, ["init", str(dest)])
    assert result.exit_code == 0
    assert "retail-001" in dest.read_text(encoding="utf-8")


def test_run_report_replay_and_compare(tmp_path: Path) -> None:
    """A scripted trial can be reported, replayed, and compared with itself."""
    runs = tmp_path / "runs"
    first = runner.invoke(
        app,
        [
            "run",
            "--run-id",
            "smoke",
            "--runs-dir",
            str(runs),
            "--tasks",
            "retail-001",
            "--k",
            "1",
            "--timeout",
            "30",
        ],
    )
    assert first.exit_code == 0
    second = runner.invoke(
        app,
        ["run", "--run-id", "smoke2", "--runs-dir", str(runs), "--tasks", "retail-001", "--k", "1"],
    )
    assert second.exit_code == 0
    reported = runner.invoke(app, ["report", str(runs / "smoke"), "--html", "--markdown"])
    assert reported.exit_code == 0
    assert "1.000" in reported.stdout
    assert (runs / "smoke" / "report.html").is_file()
    html = (runs / "smoke" / "report.html").read_text(encoding="utf-8")
    assert "retail-001" in html
    assert 'data-chart="reliability"' in html
    replayed = runner.invoke(app, ["replay", str(runs / "smoke"), "retail-001"])
    assert replayed.exit_code == 0
    assert "A1043" in replayed.stdout
    compared = runner.invoke(app, ["compare", str(runs / "smoke"), str(runs / "smoke2")])
    assert compared.exit_code == 0
    assert "no regressions" in compared.stdout
    assert format_compare(["retail-001: 1.00 -> 0.00"]) == "retail-001: 1.00 -> 0.00\n"
    default_report = runner.invoke(app, ["report", str(runs / "smoke")])
    assert default_report.exit_code == 0
    markdown_only = runner.invoke(app, ["report", str(runs / "smoke"), "--markdown"])
    assert markdown_only.exit_code == 0
    assert "1.000" in markdown_only.stdout
    blank = runs / "blank" / "retail-001"
    blank.mkdir(parents=True)
    (blank / "trial-00.jsonl").write_text(
        "\n".join(
            [
                '{"type":"trial","run_id":"blank","task_id":"retail-001","trial":0,'
                '"seed":17,"agent":"scripted","domain":"retail","tools":[]}',
                '{"type":"step","index":0,"kind":"message","role":"assistant","text":""}',
                '{"type":"result","status":"completed","final_answer":"done","tool_calls":0}',
            ]
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    quiet = runner.invoke(app, ["replay", str(runs / "blank"), "retail-001"])
    assert quiet.exit_code == 0
    assert "done" in quiet.stdout


def test_run_fails_when_a_trial_does_not_finish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A trial that does not complete makes the command exit 1."""

    async def fake(
        tasks: list[object],
        agent: object,
        config: object,
        *,
        on_trial: object = None,
    ) -> RunSummary:
        outcome = TrialOutcome(
            task_id="retail-001",
            trial=0,
            status="error",
            skipped=False,
            path=tmp_path / "missing.jsonl",
        )
        if callable(on_trial):
            on_trial(outcome)
        run_id = str(getattr(config, "run_id", "x"))
        return RunSummary(run_id=run_id, trials=[outcome])

    monkeypatch.setattr("agentgauntlet.cli.run_benchmark", fake)
    result = runner.invoke(
        app, ["run", "--tasks", "retail-001", "--runs-dir", str(tmp_path / "runs"), "--k", "1"]
    )
    assert result.exit_code == 1


def test_cli_rejects_unknown_inputs(tmp_path: Path) -> None:
    """A bad task, agent, run id, or missing trajectory is a non-zero exit."""
    runs = tmp_path / "runs"
    missing = runner.invoke(app, ["run", "--tasks", "nope", "--runs-dir", str(runs)])
    assert missing.exit_code == 1
    bad_agent = runner.invoke(app, ["run", "--agent", "magic", "--runs-dir", str(runs)])
    assert bad_agent.exit_code == 1
    bad_id = runner.invoke(app, ["run", "--run-id", "../nope", "--runs-dir", str(runs)])
    assert bad_id.exit_code == 2
    bad_attack = runner.invoke(
        app, ["run", "--attack", "missing", "--runs-dir", str(runs), "--tasks", "retail-001"]
    )
    assert bad_attack.exit_code == 2
    absent = runner.invoke(app, ["replay", str(runs / "missing"), "retail-001"])
    assert absent.exit_code == 1
    no_report = runner.invoke(app, ["report", str(runs / "missing"), "--markdown"])
    assert no_report.exit_code == 1
    no_html = runner.invoke(app, ["report", str(runs / "missing"), "--html"])
    assert no_html.exit_code == 1
    no_compare = runner.invoke(app, ["compare", str(runs / "missing"), str(runs / "other")])
    assert no_compare.exit_code == 1
