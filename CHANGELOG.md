# Changelog

## v0.3.1 - 2026-06-02

### Added

- Home Assistant Repairs can update a mismatched native C300X agent without
  asking for SSH credentials again when the installed agent supports self-update.
- Guarded Legacy MQTT migration controls can disable or remove the old
  `TcpDump2Mqtt` runtime and enable the native MQTT bridge with preserved broker
  settings.
- Agent diagnostics now expose safe runtime health details such as write
  counters, wake reason, open file descriptors, and video-bridge state.

### Changed

- Device-agent bundles use deterministic file hashes so unchanged payloads are
  skipped instead of rewritten.
- Native-agent status/update buffers were moved off the stack and the ARMHF
  stack budget is now enforced in CI.

## v0.2.0 - 2026-05-31

Initial public release candidate for the native BTicino Classe 300X / C300X
Home Assistant integration.

### Added

- Home Assistant custom integration with config flow, options flow,
  translations, diagnostics, services, and capability-gated entities.
- Native C device agent with authenticated local API, push callbacks, event
  subscriptions, optional mDNS bootstrap discovery, and explicit maintenance
  controls.
- Doorbell camera support through the native video bridge, with Home Assistant
  camera/WebRTC integration.
- Door unlock, stair light, ringer mute, smartphone forwarding, answering
  machine, video-message, text-memo, and voice-memo surfaces where supported by
  the installed agent.
- Optional C300X display integration with project-owned Alarmo and Home
  Assistant dashboard pages.
- Guarded GUI, firewall, and IPv6 firewall maintenance flows with status
  reporting and explicit user control.

### Security and Privacy

- Local-first, push-based architecture without a polling controller or Node.js
  runtime on the device.
- Separate API and maintenance tokens, with bootstrap `noAuth` intended only for
  initial setup.
- Diagnostics avoid token values and private callback details.
- Repository hygiene checks reject firmware/APK payloads, copied stock QML
  pages, foreign runtime directories, obvious private values, and third-party
  controller references in runtime code.
- SSH installer dependency intentionally pinned to `paramiko==3.5.1` for legacy
  C300X `ssh-rsa` compatibility.

### Notes

- The C300X must already be rooted or SSH-enabled before the native agent can be
  installed.
- Firmware patching/rooting is intentionally outside this repository.
- The project includes trademark, attribution, and third-party-code hygiene
  documentation.
- Thanks to SlyOldFox for the public C300X groundwork and original community
  controller work.
- Thanks to Niels Faber for building and maintaining Alarmo for Home Assistant.
