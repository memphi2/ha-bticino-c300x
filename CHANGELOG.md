# Changelog

## v1.1.0 - 2026-06-11

### Added

- Adds HA-side Ring Call capture diagnostics that keep a raw mono WAV next to
  the captured MP4 for local speech analysis.
- Adds local Wyoming Whisper transcription for the newest retained Ring Call raw
  WAV without requiring image analysis or cloud AI.
- Adds an optional strict phrase-match evaluation service that can unlock the
  configured C300X door only when explicitly requested with `unlock_on_match`.

### Changed

- Updates the packaged native C300X device agent to `1.1.0`.
- Reduces Ring Call capture audio distortion risk by removing dynamic
  normalization and keeping only moderate gain plus limiting for the MP4 audio
  track. The raw WAV remains unfiltered for Whisper.

### Upgrade Notes

- Restart Home Assistant after updating so the new services are registered.
- Ring Call capture files are local runtime artifacts and must stay outside the
  repository.

## v1.0.2 - 2026-06-08

### Fixed

- Prominently addresses the `C300X RTSP bridge did not become ready` failure
  reported in issue #12: active firewall patches now also initialize the live
  IPv4/IPv6 firewall rules immediately, without requiring a C300X reboot.
- Fixes the managed C300X firewall patch so reboot-persistent IPv4 and IPv6
  rules open the API, RTSP and talkback RTP ports required by the app-like media
  workflows.
- Refreshes already active firewall patches during native-agent updates when the
  packaged firewall patch source changes.
- Detects incomplete GUI/QML core media-close hooks as a partial patch state
  instead of reporting them as cleanly patched.

### Changed

- Updates the packaged native C300X device agent to `1.0.2`.

### Upgrade Notes

- After updating, install/update the native device agent from Home Assistant so
  the updated firewall helper and agent binary are copied to the C300X.
- If RTSP/talkback ports stay closed after a C300X reboot, re-apply the active
  firewall patch once from the integration repair/configuration flow.

## v1.0.1 - 2026-06-07

### Fixed

- Fixes bundled Lovelace card loading in Home Assistant's Add to dashboard / By
  card picker. The picker metadata is now loaded separately from the actual card
  module and frontend cache busting is based on file content.

### Notes

- The native C300X device agent is unchanged from `1.0.0`; this is a Home
  Assistant frontend/repair hotfix.
- After updating, restart Home Assistant and hard-reload the browser or mobile
  app WebView so the old Lovelace card module is not reused from frontend cache.

## v1.0.0 - 2026-06-07

### Added

- Adds the three app-like media workflows: on-demand camera, real doorbell Ring
  Call answer/hang-up with video, device audio and talkback, and audio-only Home
  Call.
- Adds the dedicated Home Assistant media-user flow so video, Ring Call and Home
  Call can use a separate `homeassistant` device-side identity when available.
- Bundles Lovelace cards for the doorstation and Home Call workflows with
  visual editor support and multi-device entity matching.
- Shows the reported C300X firmware version in the Home Assistant device
  information.
- Adds documentation examples for mobile door-call notifications, Android
  high-priority/alarm-stream delivery and iOS critical alerts.

### Changed

- Updates the native C300X device agent to `1.0.0`.
- Consolidates redundant diagnostic entities into compact status attributes.
- Keeps the bundled Lovelace card as the supported dashboard control for
  on-demand/Ring Call and Home Call workflows.

### Breaking Changes

- Several previously separate entities were removed or moved into attributes to
  reduce entity noise. This affects doorbell-video availability, latest
  message/memo metadata, agent connection diagnostics, agent write counters,
  agent info and QML patch status.
- Technical camera attributes such as raw bridge dumps, stream paths, recorder
  paths and internal media ports are no longer exposed as public camera
  attributes.
- Dashboards and automations that used the removed entities must be updated to
  use the remaining status entities, camera attributes or the bundled Lovelace
  cards.

### Upgrade Notes

- Restart the C300X after installing or updating the `1.0.0` native agent so no
  old media or display-bridge process keeps running.
- Restart Home Assistant after updating the integration so the bundled frontend
  card and the new entity model are loaded cleanly.
- If media entities or agent capabilities stay inconsistent after the upgrade,
  use `Remove device agent`, remove the integration entry, then reinstall the
  integration and native agent cleanly.
- Microphone talkback requires a secure Home Assistant frontend such as HTTPS or
  Home Assistant Cloud. Without browser microphone access, the cards try to
  start receive-only audio where supported.
- For separate rooting or SSH-enablement workflows, select firmware target
  `1.7.19`; this integration is validated against the `1.7.x` firmware family.

### Notes

- The bundled Lovelace cards are the supported dashboard UI for on-demand video,
  Ring Call answer/hang-up and Home Call.

## v0.7.0 - 2026-06-05

### Added

- Adds the native in-house Home Call path with Home Assistant services to start
  and stop calls.
- Adds explicit doorbell video stop controls for dashboards and mobile
  notification call-end actions.
- Adds the separate native doorbell ring media mode used by real ring-call
  sessions.
- Bundles the Lovelace doorstation/Home Call card with the integration and
  loads it automatically through Home Assistant's frontend module registry.

### Changed

- Updates the native C300X device agent to `0.7.0`.
- Keeps doorbell audio requested for media sessions while preventing a missing
  or slow audio track from delaying the first video frames.

### Fixed

- Corrects Home Call stop while still ringing to match app-like call handling.
- Clears stale doorbell media state on closed media windows and TTL fallback.
- Keeps the Home Assistant video availability state focused on HA-usable video
  instead of any unrelated external media session.

## v0.6.1 - 2026-06-05

### Fixed

- Requests door-station audio whenever the browser media session can receive
  audio, while keeping microphone talkback capability separate.
- Buffers early camera connection candidates until the media session has a
  remote description, avoiding noisy `addIceCandidate` race warnings without
  dropping browser candidates.

### Notes

- The native C300X device agent is unchanged from `0.6.0`; this is a Home
  Assistant integration hotfix.

## v0.6.0 - 2026-06-05

### Changed

- Updates the native C300X device agent to `0.6.0`.
- Adds a brand-new app-like doorbell streaming path for the on-demand live
  view.
- Opens the Home Assistant camera as video-only by default so browsers can
  autoplay the live view. Interactive media sessions can still request audio
  and talkback.

### Fixed

- Camera start recovers cleanly after failed or interrupted media sessions.
- Repeated camera starts no longer trip over stale native-agent media state.

## v0.5.1 - 2026-06-04

### Changed

- Fixes Home Assistant 2026.6 thread-safety warnings from doorbell video TTL
  callbacks.
- Buffers early camera connection candidates until the media session has a remote
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

- Configurable local media identity settings for the C300X media path.
- Talkback state reporting for Home Assistant, including HTTPS
  requirement, requested/active state, and last local error.
- Optional local Home Assistant frontend HTTPS helper for browser microphone
  testing; the native C300X agent itself remains HTTP-only on the local LAN.

### Changed

- Doorbell audio handling now distinguishes door-station audio playback
  from browser microphone talkback direction.
- Legal notes explicitly document codec-binary and codec-patent boundaries.

## v0.3.3 - 2026-06-02

### Added

- Home Assistant Repairs can update a mismatched native C300X agent through the
  maintenance API when the installed agent supports self-update.
- First-install and fallback repair flows can still install the packaged agent
  over SSH when no self-update-capable agent is available.
- Native MQTT bridge support mirrors the legacy C300X topics while keeping the
  broker settings in the agent configuration.
- Guarded legacy MQTT controls can disable the old `TcpDump2Mqtt` autostart
  path without rewriting unrelated media startup files.
- Agent diagnostics expose safe runtime health details such as write counters,
  wake reason, open file descriptors, video state, and media startup reference
  state.

### Changed

- Device-agent bundles use deterministic file hashes so unchanged payloads,
  scripts, GUI files and firewall patches are skipped instead of rewritten.
- Update and maintenance paths refresh only patches that are already active.
- The doorbell camera path stays on the app-like on-demand media path and
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
- Doorbell camera support through Home Assistant camera handling.
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
