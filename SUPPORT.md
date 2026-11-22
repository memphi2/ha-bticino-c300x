# Support Policy

## C100X Development Branch

Only the `c100x_1.5.8` branch contains the experimental C100X 1.5.8 work.
Its offline checks are not device acceptance testing. See the
[C100X support matrix](docs/c100x-experimental.md) for unavailable features,
SSH credential prerequisites, update protection and the outstanding hardware
tests. Do not install a C300X-only stable/beta package over this agent.
No public C100X release channel is assigned by this branch.

## Supported Release Line

- `2.8.x`: current stable (2.8.2)
- `2.7.x`: previous stable; upgrade to 2.8.x for maintenance fixes
- `2.5.x`: no longer maintained; upgrade to 2.8.x
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
