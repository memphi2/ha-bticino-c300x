# Home Assistant Quality Scale

Target: Platinum
Current status: Not Platinum yet

This repository tracks quality-scale status in `custom_components/bticino_c300x/quality_scale.yaml`.

## Current Position

The integration is local-push based, capability-gated, async, unload-safe, and provides diagnostics plus repair issues.

## Platinum Blockers

- `brands`
- `config-flow-test-coverage`
- `test-coverage`
- `strict-typing`

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
