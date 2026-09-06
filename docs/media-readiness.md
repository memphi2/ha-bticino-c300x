# Media Readiness

`Media readiness` is the first diagnostic entity to check when camera, Ring
Call, Home Call or talkback does not work.

It aggregates the device-agent connection, self-test, media user and callback
state into one status. Forwarding is reported separately because it selects the
incoming Ring Call target but does not gate on-demand media.

## Status Values

| Status | Meaning | What to do |
| --- | --- | --- |
| `ready` | Required media checks passed. | Add or use the C300X card. |
| `warning` | Media is not fully proven, but no blocking failure was found. | Review warnings; optional IPv6 warnings can usually be ignored. |
| `blocked` | A required media prerequisite failed. | Open the Repair issue and run the suggested fix. |
| `unavailable` | Home Assistant cannot reach the device agent. | Check network/token/agent status or run the Repair. |

## Main Attributes

| Attribute | Meaning |
| --- | --- |
| `agent_reachable` | Home Assistant can reach the native C300X agent. |
| `agent_version_ok` | Agent version metadata is available and usable. |
| `media_user_ok` | The Home Assistant media user and routing are ready. |
| `forwarding_homeassistant` | Ring Call forwarding is set to Home Assistant. `false` does not block on-demand media. |
| `rtsp_ok` | RTSP/media infrastructure is ready according to the agent self-test. |
| `talkback_rtp_ok` | Talkback RTP infrastructure is ready according to the agent self-test. |
| `callback_url_ok` | The C300X can use the configured Home Assistant callback URL. |
| `ring_call_supported` | The installed agent reports Ring Call capability. |
| `home_call_supported` | The installed agent reports Home Call capability. |
| `doorbell_video_supported` | The installed agent reports doorbell video capability. |
| `failed_checks` | Blocking checks that currently need attention. |
| `warnings` | Non-blocking checks or incomplete proof. |
| `recommended_action` | Stable action code used by Repairs and diagnostics. |

## Failed Checks and Fixes

| Failed check | Typical cause | Repair action |
| --- | --- | --- |
| `agent_reachable` | Agent offline, wrong host/port, token mismatch, device rebooting. | Re-check agent reachability and token; reload/update agent if needed. |
| `capabilities` | Agent answered without usable media capabilities. | Update or reconfigure the device agent. |
| `firewall` | Required IPv4 media ports are not open on the C300X. | Apply the C300X firewall Repair. |
| `rtsp` | RTSP server or stream config is not ready. | Update/reconfigure the agent, then re-check readiness. |
| `talkback_rtp` | Talkback RTP port is not open or not reported ready. | Apply the firewall Repair. IPv6 is optional. |
| `homeassistant_user` | Dedicated media user is missing. | Run Home Assistant media-user setup. |
| `device_routing` | Local media-user route files are incomplete. | Run Home Assistant media-user setup. |
| `callback_url` | The callback URL uses HTTPS, `.local`, loopback, link-local or an unreachable host. | Configure a reachable local HTTP callback base URL. |
| `startup` | Device-agent startup link is missing. | Run the device-agent update/repair flow. |

## Ring Call Forwarding Warnings

`forwarding_homeassistant` and `forwarding_unprovisioned` are non-blocking
warnings. On-demand video and its talkback, as well as Home Call, remain
available when their own prerequisites pass. Keep **Forwarding** set to
**Smartphone** when the Door Entry app should receive calls. Select **Home
Assistant** explicitly only when Ring Calls should instead be answerable from
Home Assistant.

Forwarding is never changed by a media Repair.

## Fix Now

When Readiness is not ready, Home Assistant creates a Repair issue whenever a
known safe fix exists.

The guided Repair can:

- re-check agent reachability,
- refresh agent setup metadata,
- apply the IPv4 media firewall,
- repair the Home Assistant media-user/routing setup,
- guide you to set a reachable callback URL.

Repairs are explicit. They do not run just because Home Assistant starts.

If a Repair changes device-side media setup, wait for it to finish, then check
`Media readiness` again before testing the card.

## IPv6

IPv6 is optional. A failure that only reports missing optional IPv6 firewall
state should be a warning, not a blocker. Enable IPv6 firewall support only when
your Home Assistant instance actually reaches the C300X over stable IPv6.
