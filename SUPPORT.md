# Support Policy

## Supported Release Line

- `2.2.x`: current stable
- Pre-release versions containing `b` or `rc` are opt-in testing releases,
  not replacements for the latest stable release. Enable beta versions in HACS
  only when you want to test them.

## Compatibility Baseline

- Minimum Home Assistant: `2026.7.0`
- Validated Home Assistant: `2026.7.x` and `2026.10.x`
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
