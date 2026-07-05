# Architecture

## Goal

Provide a local, secure, push-based BTicino C300X integration for Home Assistant with a native device agent.

For the user-visible feature surface, see
[Feature reference](feature-reference.md). This page focuses on internal
ownership and data flow.

## Components

### Home Assistant integration

Path: `custom_components/bticino_c300x/`

Responsibilities:

- Config flow and options flow.
- Capability-gated entities/services.
- Authenticated API calls to the device agent.
- Event webhook registration and event-state handling.
- Diagnostics and repair issues.
- Bundled Lovelace card registration and resource refresh.
- Home Assistant WebRTC provider/go2rtc media delegation.

### Native device agent

Path: `native_agent/`

Source docs:

- [Native agent runtime notes](native-agent.md)
- [Native agent source README](../native_agent/README.md)
- [Native agent API contract](../native_agent/API.md)

Responsibilities:

- Local `/api/v1` HTTP API with bearer auth.
- Push callbacks for ring/lock/call/ringer/forwarding/video-message/memo events.
- OpenWebNet command execution.
- Optional local media doorstation media module.
- Optional display bridge endpoint for QML dashboard requests.
- Explicit maintenance/update actions for device-agent, display, firewall, MQTT
  migration and media-user setup.

### Device QML UI

Path: `device_qml/`

Source docs:

- [Device QML UI README](../device_qml/README.md)

Responsibilities:

- Render native C300X dashboard pages.
- Call the local agent UI API on loopback.
- Avoid Lovelace embedding on the device.
- Never store or expose HA tokens.

## Data Flow

```text
C300X event source
  -> native agent
  -> signed callback to HA event webhook
  -> HA updates entities/event state

HA service/action
  -> HA integration
  -> authenticated native agent /api/v1 command
  -> device execution
```

## Event Contract

The native agent publishes canonical dotted event names such as
`doorbell.pressed`, `door_unlock.started`, `stair_light.activated`,
`stair_light.released`, `activation.executed`,
`answering_machine.messages_changed`, and `memos.changed`. Home Assistant maps
these to its stable event entity values. Old controller aliases are
intentionally not part of the current contract.

Doorbell, call and media state should be derived from native-agent/device
events. Browser/card state may request or display media, but it should not be
the authority for call lifecycle.

## Media Flow

```text
Browser/Card
  -> Home Assistant camera WebRTC provider
  -> go2rtc
  -> native-agent RTSP source
  -> C300X local media path
```

The preview, answered Ring Call, on-demand and Home Call paths are separate at
the integration/card state layer but share the same native media ownership
rules. Talkback is available only through a secure browser context that can
provide microphone access.

## Configuration Writes

Most runtime work is read-only or event-driven. Device writes are limited to
explicit user actions:

- first install/update/remove of the native agent,
- token/bootstrap changes,
- Home Assistant media-user setup or repair,
- forwarding, ringer, answering-machine and memo/message commands,
- Display patch and GUI reload,
- firewall and MQTT maintenance,
- configured device activation synchronization.

## Design Constraints

- No polling architecture for core device state.
- Idle traffic should be near zero.
- No runtime Node.js dependency on device.
- Mutating APIs use POST and explicit auth.
- Show only capabilities the agent actually reports.
