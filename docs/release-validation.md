# Release Validation

This checklist is for release candidates on real hardware. It is not required
for normal users.

## Scope

Validate that the current Home Assistant integration, bundled Lovelace card and
packaged C300X device agent work together on a real C300X.

## Clean Install Path

- HACS install or update succeeds.
- Home Assistant restart succeeds without blocking I/O warnings from this
  integration.
- The integration setup flow completes.
- Agent install or update completes from the setup/Repair flow.
- `Media readiness` becomes `ready` or shows a clear actionable Repair.
- Bundled Lovelace cards are available in the card picker after hard reload.

## Media Matrix

| Scenario | Expected result |
| --- | --- |
| On-demand Stream | Video starts, stops and can start again. |
| On-demand with Smartphone forwarding | Video remains available, readiness shows only a Ring Call warning and no Repair is created. |
| On-demand Talkback | Microphone works from a secure frontend. |
| Ring Call Preview | Card shows preview only when real ring media is ready. |
| Ring Call Answer | Preview transitions to answered call without losing media. |
| Ring Call Hangup | Card returns to idle and the device call ends. |
| Two browser Ring preview | Supported preview viewers do not break the answered flow. |
| Ring capture while idle | Capture writes MP4/WAV/JPEG/JSON to allowed paths. |
| Ring capture while busy | Capture fails cleanly instead of stealing the live session. |
| Home Call start/stop | Display rings, state updates, hangup cleans up. |
| On-demand after Home Call | First stream attempt works after Home Call cleanup. |

## Readiness and Repairs

Verify each repair path when possible:

- agent unreachable,
- agent update/capability mismatch,
- firewall/talkback RTP,
- Home Assistant media user/routing,
- callback URL unreachable,
- display/event watchdog.

Each issue should have a clear title, clear reason and a matching Repair flow
when a safe fix exists.

Also verify that Smartphone or Blocked forwarding produces only a non-blocking
Ring Call warning and that the media Repair never changes forwarding.

## Display Pages

If Display patch is enabled:

- dynamic home page loads,
- dashboard page keeps configured entity order,
- alarm page shows clear armed/disarmed and sensor status,
- weather page shows condition, forecast, sunrise and sunset when available,
- button feedback is visible,
- no sustained device CPU increase remains after GUI reload.

## Performance

After idle settle:

- no active media sessions,
- no stale RTSP consumers,
- no unexpected writes,
- no sustained device CPU watchdog events,
- Home Assistant CPU and memory remain stable.

During media:

- streams stop on hangup/close,
- watchdog closes high-load sessions instead of keeping the device busy,
- diagnostics report useful state changes.

## LTS Evidence

Each release must publish deterministic release artifacts:

- HACS zip,
- `SHA256SUMS`,
- `build-metadata.json`,
- SPDX SBOM,
- GitHub artifact attestation.

`build-metadata.json` records the supported Home Assistant range, Python
version, C300X firmware target, native-agent version, agent reuse status and the
validated release jobs. For fresh native-agent builds it also records
`native_agent_sysroot` evidence from `C300X_DEVICE_SYSROOT`: no local path, only
availability, content hashes for the relevant ARMHF sysroot libraries and a
combined fingerprint. Treat that file as the release evidence for why the asset
was considered LTS-compatible at build time.

Agent binary reuse is allowed only if none of these paths changed:

- `native_agent/src`
- `native_agent/scripts`
- `native_agent/VERSION`
- `native_agent/Makefile`
- `native_agent/config.example.json`
- `device_qml`
- `custom_components/bticino_c300x/device_agent/init`
- `scripts/stage_device_agent_bundle.py`

If any path above changed, do not release with a reused native-agent binary.
Build with a verified `C300X_DEVICE_SYSROOT`, run the ABI/stack gates, and keep
the resulting sysroot evidence in `build-metadata.json`.

## Legal and Provenance Audit

Run the focused legal/provenance gate before each release:

```bash
.venv/bin/python scripts/check_legal_audit.py
```

This verifies the tracked repository does not contain firmware/APK/capture
payloads, foreign runtime directories, stock vendor QML pages, copied
third-party controller markers in runtime code, runtime Python requirements, or
undocumented brand-asset changes. The normal local/CI validation command also
runs this gate through `scripts/check_validate.py`.

## Privacy and Artifacts

Do not commit:

- packet captures,
- logs with tokens or private URLs,
- private media clips,
- generated runtime files,
- local device backups,
- extracted firmware or vendor files.

Keep release screenshots free of private addresses, tokens, faces and household
details.
