# Home Assistant Quality Scale

Target: Platinum
Current status: Not Platinum yet

This repository tracks quality-scale status in `custom_components/bticino_c300x/quality_scale.yaml`.
This page explains the current blocker set and is validated by
`scripts/check_quality_scale.py`.

## Current Position

The integration is local-push based, capability-gated, async, unload-safe, and
provides diagnostics plus repair issues. Fixture-backed tests cover setup,
options, reconfigure, dashboard branching, invalid input handling, and Repair
flows. The local coverage ratchet is currently 95%, and the strict typing gate
covers the HA-facing integration modules, shared helpers, media paths, agent
contracts, and release/validation scripts.

## Platinum Blockers

- `brands`
- `test-coverage`

## Local Gates

```bash
.venv/bin/python scripts/check_repo.py
.venv/bin/python scripts/check_quality_scale.py
.venv/bin/python scripts/check_coverage.py
.venv/bin/python scripts/check_typing.py
.venv/bin/ruff check .
.venv/bin/python -m pytest
make -C native_agent check
```

Live HA-test gate:

```bash
HA_TEST_URL=... HA_TEST_ACCESS_TOKEN=... .venv/bin/python scripts/smoke_ha.py
```
