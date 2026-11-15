# Support Policy

## Supported Release Line

- `2.4.x`: current stable (2.4.1)
- `2.2.0`: withdrawn because its display update can cause repeated device restarts

## Compatibility Baseline

- Minimum Home Assistant: `2026.10.0`
- Home Assistant validation baseline: `2026.10.x` and `2026.11.x`
- CI tests the fixed minimum and resolves the latest stable Home Assistant on every run.
- Python: `3.14`
- C300X firmware: `1.7.x`

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
