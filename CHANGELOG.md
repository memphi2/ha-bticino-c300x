# Changelog

## v0.6.0 - 2026-06-05

### Changed

- Updates the native C300X device agent to `0.6.0`.
- Adds a brand-new app-style doorbell streaming path for the on-demand live
  view, using the same long-running local camera activation as the C300X mobile
  app instead of the short ring preview.
- Opens the Home Assistant camera as video-only by default so browsers can
  autoplay the live view. Interactive WebRTC sessions can still request audio
  and talkback.

### Fixed

- Camera start recovers cleanly after failed or interrupted media sessions.
- Repeated camera starts no longer trip over stale native-agent media state.

## v0.5.1 - 2026-06-04

### Changed

- Fixes Home Assistant 2026.6 thread-safety warnings from doorbell video TTL
  callbacks.
- Buffers early WebRTC ICE candidates until the peer connection has a remote
  description, avoiding noisy `addIceCandidate` race warnings.
- Gives Alarmo arm-mode buttons on the C300X display immediate visual feedback:
  yellow while checking/sending, green when accepted, and red when blocked or
  rejected.

### Notes

- Includes the full `0.5.0` feature set: callback URL override, French
  localization, event replay cleanup, and doorbell video recovery improvements.
- The native C300X device agent is unchanged from `0.5.0`; this is a Home
  Assistant integration hotfix.

## v0.5.0 - 2026-06-03

### Update note

- During an update, handle the **device agent update** Repair first. Other
  C300X Repairs can appear temporarily while Home Assistant and the device
  agent are not on the same bundle yet; ignore those until the agent update
  Repair has completed and the integration has reloaded.

### Added

- Dedicated local callback base URL override for reverse-proxy and HTTPS
  frontend setups where the C300X agent must call Home Assistant over local
  HTTP.
- French Home Assistant translations and French C300X display labels.

### Changed

- Replayed event snapshots no longer re-trigger doorbell notifications after a
  Home Assistant restart.
- Doorbell video activation recovers automatically when a device display or app
  video-close callback is missed.
- Callback setup now rejects unsuitable targets such as HTTPS, `.local`,
  loopback, link-local and malformed port URLs before they break device events
  or display actions.

## v0.4.0 - 2026-06-02

### Added

- Configurable native SIP/Flexisip identities and endpoint settings for the
  C300X media bridge.
- WebRTC talkback state reporting for Home Assistant, including HTTPS
  requirement, requested/active state, packet count, and last error.
- Optional local Home Assistant frontend HTTPS helper for browser microphone
  testing; the native C300X agent itself remains HTTP-only on the local LAN.

### Changed

- Doorbell WebRTC audio handling now distinguishes door-station audio playback
  from browser microphone talkback direction.
- Legal notes explicitly document codec-binary and codec-patent boundaries for
  the device-provided H.264/AVC stream and Speex talkback audio.

## v0.3.3 - 2026-06-02

### Added

- Home Assistant Repairs can update a mismatched native C300X agent through the
  maintenance API when the installed agent supports self-update.
- First-install and fallback repair flows can still install the packaged agent
  over SSH when no self-update-capable agent is available.
- Native MQTT bridge support mirrors the legacy C300X topics while keeping the
  broker settings in the agent configuration.
- Guarded legacy MQTT controls can disable the old `TcpDump2Mqtt` autostart
  path without rewriting Flexisip.
- Agent diagnostics expose safe runtime health details such as write counters,
  wake reason, open file descriptors, video-bridge state, and Flexisip reference
  state.

### Changed

- Device-agent bundles use deterministic file hashes so unchanged payloads,
  scripts, GUI files and firewall patches are skipped instead of rewritten.
- Update and maintenance paths refresh only patches that are already active.
- The doorbell camera path stays on the native on-demand video bridge and
  remains independent from the legacy MQTT runtime.
- Native-agent runtime buffers and MQTT status handling are sized for the C300X
  environment, and the ARMHF stack budget is enforced in CI.

### Security and Privacy

- Maintenance actions stay token-protected and explicit.
- SSH credentials are used only for bootstrap/fallback install flows and are not
  stored.
- Diagnostics avoid token values, broker passwords, private callback URLs and
  user-specific device details.
- Repository hygiene checks continue to reject firmware/APK payloads, copied
  stock QML pages, foreign runtime directories, and third-party controller code.

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
