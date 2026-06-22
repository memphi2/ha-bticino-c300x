# Native Agent API Contract

This document describes the native-agent endpoints that Home Assistant treats as
architecture contracts. Endpoints listed here must remain read-only unless they
are explicitly documented as maintenance actions.

## Self-Test

`GET /api/v1/self-test`

Authentication: normal device-agent bearer token.

Side effects: none. The endpoint must not write files, modify display files or
firewall rules, restart services, start RTSP media, or open talkback RTP.

Contract version: `api_version: "1.1"`.

The endpoint aggregates existing read-only state into a single status payload:

```json
{
  "api_version": "1.1",
  "agent_version": "1.4.2",
  "firmware_family": "1.7.x",
  "ok": true,
  "checks": {
    "capabilities": {"ok": true, "reason": "ok"},
    "firewall": {"ok": true, "reason": "media_ports_open"},
    "rtsp": {"ok": true, "reason": "rtsp_ready"},
    "talkback_rtp": {"ok": true, "reason": "talkback_rtp_ready"},
    "homeassistant_user": {"ok": true, "reason": "homeassistant_user_ok"},
    "device_routing": {"ok": true, "reason": "device_routing_ok"},
    "startup": {"ok": true, "reason": "startup_link_ok"}
  }
}
```

Each check must include `ok` and `reason`. Additional fields are diagnostic and
must not contain tokens, SIP secrets, webhook URLs, or raw file contents.

## Check Scope

- `capabilities`: verifies the running agent can report its own contract
  metadata.
- `firewall`: reads the configured IPv4/IPv6 firewall scripts and checks for
  the managed media-port blocks. It does not run iptables or ip6tables.
- `rtsp`: reads the in-process video bridge status. It does not activate media
  and does not open a client connection.
- `talkback_rtp`: verifies the configured talkback RTP infrastructure state and
  firewall readiness. It does not send RTP packets.
- `homeassistant_user`: reads Flexisip user and route files and reports whether
  a usable media identity is available.
- `device_routing`: reads the local media routing setup and Display setup status.
  It does not apply or restore setup changes.
- `startup`: checks whether the agent init script and rc link are present.

## Compatibility Matrix

| Agent version | Self-test API | Firmware family | Notes |
| --- | --- | --- | --- |
| 1.4.2 | 1.1 | 1.7.x | Current packaged agent. |
| 1.3.0 | 1.1 | 1.7.x | Adds display watchdog recovery and bundled mobile Ring Call workflow support. |
| 1.2.3 | 1.1 | 1.7.x | Consolidates display UI actions and dashboard traffic handling. |
| 1.2.2 | 1.1 | 1.7.x | Bootstraps and requires the dedicated Home Assistant media user for local media identity. |
| 1.2.1 | 1.1 | 1.7.x | Keeps the Home Assistant media user on the internal route only. |
| 1.2.0 | 1.1 | 1.7.x | Adds read-only architecture self-test. |

Older agents do not expose `/api/v1/self-test`. Home Assistant must treat that
as unsupported rather than attempting automatic repair.
