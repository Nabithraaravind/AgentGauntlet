# Contributing

AgentGauntlet is early. The useful way to help right now is to keep each milestone small, typed, and tested.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/) 0.11.33 or newer.

```bash
uv sync
uv run pre-commit install
```

Copy `.env.example` to `.env` only when you need a paid model. Do not commit `.env`.

## Checks

These are the same commands CI runs:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

`pytest` fails if coverage of `agentgauntlet` drops below 85%.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` a user-visible capability
- `fix:` a bug fix
- `test:` tests only
- `docs:` documentation only
- `chore:` tooling and maintenance

Keep commits small enough that a reviewer can explain the diff. Do not commit secrets, API keys, or local `runs/`.

## Benchmark numbers

Do not write measured scores into `README.md` or `docs/` unless they come from a run checked into the repo. Use `TBD` until then.
