# Support Policy

## Supported Release Line

- `2.10.x`: beta 2.10.0b1 for firmware 3.0.6 (home page buttons checked on a station, the rest offline only); includes 2.9.0
- `2.9.x`: current stable (2.9.0)
- `2.8.x`: previous stable; upgrade to 2.9.x for maintenance fixes
- `2.7.x`: no longer maintained; upgrade to 2.9.x
- `2.6.0`: withdrawn because the energy page did not load on the display
- `2.2.0`: withdrawn because its display update can cause repeated device restarts

## Compatibility Baseline

- Minimum Home Assistant: `2026.10.0`
- Home Assistant validation baseline: `2026.10.x` and `2026.11.x`
- CI tests the fixed minimum and resolves the latest stable Home Assistant on every run.
- Python: `3.14`
- C300X firmware: `1.7.x, 2.0.2 or 3.0.6 (experimental)`

## Maintenance Scope

Security and compatibility fixes target the current minor release line only,
unless a release note states otherwise.

## Native Agent Rebuilds

A native-agent rebuild is required when any of these paths change:

- `native_agent/src`
- `native_agent/scripts`
- `native_agent/VERSION`
- `native_agent/Makefile`
- `native_agent/config.example.json`
- `device_qml`
- `custom_components/bticino_c300x/device_agent/init`
- `scripts/stage_device_agent_bundle.py`
- `scripts/device_file_strip.py`
