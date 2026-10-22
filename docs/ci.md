# CI

`.github/workflows/ci.yml` runs ruff, mypy, pytest, and `tasks/validate.py` on Python 3.11 and 3.12.

`pytest --gauntlet --gauntlet-config gauntlet.yaml` runs the scripted gate and exits if a threshold is missed.

The reusable action is `action.yml` at the repository root:

```yaml
- uses: Nabithraaravind/AgentGauntlet@v1
  with:
    subset: retail-001
    k: "1"
```

`.github/workflows/gauntlet.yml` calls that action on this repository and, on a pull request, comments with the Markdown score. The release workflow publishes to PyPI on a `v*` tag using trusted publishing. It does not store an API token.
