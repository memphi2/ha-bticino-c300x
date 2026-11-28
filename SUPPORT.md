# Support Policy

## Supported Models

- **Classe 300X (C300X):** the release lines below.
- **Classe 100X (C100X), firmware 1.5.8:** experimental, in test in
  [issue #51](https://github.com/memphi2/ha-bticino-c300x/issues/51). Setup
  asks for a confirmation first. Features per model:
  [Models and features](docs/reference.md#models-and-features); setup:
  [Classe 100X](docs/classe-100x/1-setup.md).

## Supported Release Line

- `3.0.x`: current stable (3.0.0): one package for the Classe 300X and the Classe 100X (Classe 100X experimental, checked offline only); includes 2.10.0
- `2.10.x`: previous stable; upgrade to 3.0.x for maintenance fixes
- `2.9.x`: no longer maintained; upgrade to 3.0.x
- `2.8.x`: no longer maintained; upgrade to 3.0.x
- `2.7.x`: no longer maintained; upgrade to 3.0.x
- `2.6.0`: withdrawn because the energy page did not load on the display
- `2.2.0`: withdrawn because its display update can cause repeated device restarts

## Compatibility Baseline

- Minimum Home Assistant: `2026.10.0`
- Home Assistant validation baseline: `2026.10.x` and `2026.11.x`
- CI tests the fixed minimum and resolves the latest stable Home Assistant on every run.
- Python: `3.14`
- C300X firmware: `1.7.x, 2.0.2 or 3.0.6`
- C100X firmware: `1.5.8` (in test, issue #51)

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
- `scripts/c100x_bundle_builder.py`
- `scripts/c100x_qml_builder.py`
