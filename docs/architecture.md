# Architecture

## Goal

Provide a local, secure, push-based BTicino C300X integration for Home Assistant with a native device agent.

## Components

### Home Assistant integration

Path: `custom_components/bticino_c300x/`

Responsibilities:

- Config flow and options flow.
- Capability-gated entities/services.
- Authenticated API calls to the device agent.
- Event webhook registration and event-state handling.
- Diagnostics and repair issues.

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
`activation.executed`, `answering_machine.messages_changed`, and `memos.changed`. Home Assistant maps
these to its stable event entity values. Old controller aliases are intentionally
not part of the current contract.

## Design Constraints

- No polling architecture for core device state.
- Idle traffic should be near zero.
- No runtime Node.js dependency on device.
- Mutating APIs use POST and explicit auth.
- Show only capabilities the agent actually reports.
