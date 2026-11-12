# Release Validation

This checklist is for release candidates on real hardware. It is not required
for normal users.

## Scope

Validate that the current Home Assistant integration, bundled Lovelace card and
packaged C300X device agent work together on a real C300X.

## Stable and Beta Channels

- Stable: `X.Y.Z`, tagged `vX.Y.Z`.
- Beta: `X.Y.ZbN`, tagged `vX.Y.ZbN`, starting at `b1`.
- Release candidate: `X.Y.ZrcN`, tagged `vX.Y.ZrcN`, starting at `rc1`.

Versions are canonical and shared by the integration manifest, project metadata,
changelog and release notes. A beta label is not permission to skip validation.
Both channels require the tagged commit to be the validated `main` HEAD, the
release checks, browser checks and verified provenance/SBOM attestations. The
optional `beta` development branch runs normal Validate, Browser and CodeQL
checks; it is not a shortcut around the main release gate.

The publisher derives the channel from the tag. Beta/RC releases are marked
as GitHub prereleases and explicitly excluded from Latest. New releases are
drafts until their four downloaded assets match the validated local artifacts.
Reruns verify existing assets, notes and channel without overwriting them;
conflicts or API errors stop publication. Tags are checked against the source
commit again immediately before publishing a draft.

Each channel ships `ha-bticino-c300x.zip`, `SHA256SUMS`, `build-metadata.json`
and `sbom.spdx.json`. The ZIP includes the frontend and device-agent bundle.
Agent reuse and version-bump checks include preceding beta/RC tags, ordered
numerically (`b2 < b10 < rc1 < stable`) and restricted to merged older versions.
Changes to native inputs require an agent version bump and rebuild, including
between two betas. Integration-only changes may retain the verified agent;
never relabel an old binary to give it the integration's beta version.
Display files under `device_qml` ship in the bundle without entering the
binary: their content is covered by the bundle hash, which the agent-update
check compares, so a display-only change is delivered to the device on the
verified agent and does not require a version bump.

Prepare a new version and its dated notes only when that release is intended.
Adding beta support or creating a development branch does not publish a beta.
See [beta installation and return to stable](advanced-maintenance.md#beta-versions)
for the user-facing opt-in workflow.

## Isolated Integration Tests

`pytest tests/test_ha_runtime.py` starts real Home Assistant in a subprocess
with temporary configuration and an authenticated loopback-only fake agent.
It checks webhook authentication, push state changes, registry renaming,
service routing, reload, registration retry after disconnect and cancellation
of an in-flight registration on unload. Unexpected requests and unhandled
async exceptions fail the test. No device credentials are read.

The browser frontend, go2rtc process and mDNS resolver are excluded from this
fixture. These tests do not establish physical device or media stability.

The same pytest wrapper runs three measured resource cycles after three warmup
cycles. For the longer Linux-only probe, run
`python tests/runtime_lab/run.py --scenario soak --cycles 30` (also scheduled
weekly in CI). The JSON report includes request counts, tasks, timers, bus
listeners, file descriptors, traced Python memory and resident memory. It rejects
retained old API clients and growth beyond the explicit limits in `soak.py`.
All traffic is synthetic loopback traffic; this is not a device-load measurement.

`python tests/runtime_lab/run.py --scenario recorder` uses real SQLite Recorder
storage. Forty identical metrics/diagnostic pushes must add zero history rows;
three changed CPU readings must add exactly three. Memo text must remain visible
live but absent from recorded attributes, as must volatile diagnostic counters.
This checks write amplification and attribute privacy, not long-term retention.

The `contract` scenario creates two real HA entries with camera and button
platforms, renames their entities and reloads them. Its allowlisted export uses
HA's display-registry fields, not fabricated unique IDs or production data.
The pytest wrapper feeds it directly to the card's JavaScript resolver/actions:
camera/readiness discovery and button routing must stay on the selected device,
including when the second device's light entity is disabled. Synthetic HA button
service calls also verify the agent API routes. No export is checked into Git.

## Browser Regression Tests

Run `npm ci --prefix tests/browser --ignore-scripts` and
`node tests/browser/smoke.mjs`. Chrome must be installed; `CHROME_BIN` overrides
its executable path. CI runs this separately from Python tests.

The actual card is rendered at 320, 390 and 1024 pixels in four languages.
Tests check action bounds/labels, unavailable and pending buttons, door/light
routing, repeated WebRTC start/stop, microphone muting and detach cleanup.
A synthetic canvas feeds a real browser-to-browser WebRTC connection; pixel
checks require decoded video. HA host elements and signaling are fixtures,
microphone input is Chrome's fake device and no C300X is contacted. Screenshots
are written to ignored `.artifacts/browser/`. These are not real-HA frontend or
device interoperability tests.

## Clean Install Path

- Marketplace or HACS install/update succeeds on the corresponding HA version.
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
| PCMU On-demand, microphone off | Repeated start/stop and normal 60-second session renewal preserve audio/video without a device reboot or firmware-process restart. |
| On-demand with Smartphone forwarding | Video remains available, readiness shows only a Ring Call warning and no Repair is created. |
| On-demand Talkback | Microphone works from a secure frontend. |
| Ring Call Preview | Card shows preview only when real ring media is ready. |
| Ring Call Answer | Preview transitions to answered call without losing media. |
| Ring Call Hangup | Card returns to idle and the device call ends. |
| Two browser Ring preview | Supported preview viewers do not break the answered flow. |
| Ring capture during a real Ring Call | Omitted `capture_mode` and explicit `ring` preserve the existing answer/record/hangup flow. Capture writes MP4, audio when requested, JPEG frames and JSON metadata to allowed paths. |
| Ring capture without a Ring Call | With `include_audio: true`, the default `ring` mode fails cleanly and does not silently start an on-demand session. Existing blueprints keep this mode. |
| On-demand capture from idle | Explicit `capture_mode: on_demand` records without ringing. Test `include_audio: true` and `false`, durations of 1, 5 and 15 seconds, exact response paths and capture-mode metadata with native agent 2.1.0. |
| Capture while busy or ownership is unclear | Capture rejects conflicting live, Home Call or external sessions without taking them over. |
| On-demand capture completion, failure and cancellation | Its recording client closes after success, ffmpeg failure or cancellation, including before RTSP startup. Other or replacement sessions remain intact; a subsequent capture can start. |
| On-demand capture with an announcement | `announcement_path` is rejected before media starts; Ring Call announcements retain their existing behavior. |
| Home Call start/stop | Display rings, state updates, hangup cleans up. |
| On-demand after Home Call | First stream attempt works after Home Call cleanup. |

For the PCMU reboot regression, verify the running agent version and active
device codec first. Observe boot ID, uptime and the answering-machine/media
processes for at least 180 seconds after each stop; a successful stream alone
does not establish that the device remained healthy. Record cold-boot and
short-gap tests separately rather than inferring them from long-idle runs.
Keep raw captures and device identifiers private.

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
- SPDX 2.3 SBOM validated by the official SPDX tools,
- SLSA provenance and SPDX SBOM attestations verified against the release
  workflow, tag ref and commit before publication.

The SBOM distinguishes archive contents from direct external runtime dependencies.
Python imports are read from the packaged sources; the optional SSH installer pin
comes from the packaged installer, not the build environment. Native system and
optional media/TLS libraries are identified separately. Unknown HA/device library
versions are omitted, not guessed. This is not a resolved inventory of every
transitive package installed on a user's systems, nor a vulnerability clearance.

Manual Release runs must also execute from the release tag (`--ref vX.Y.Z`),
not from `main` with a different tag input. Publication rejects a signing
workflow ref or commit that differs from the checked-out release. This keeps
the signed identity aligned with the actual release sources using the
[GitHub attestation verification checks](https://cli.github.com/manual/gh_attestation_verify).

`build-metadata.json` records the supported Home Assistant range, Python
version, C300X firmware target, native-agent version, agent reuse status and the
validated release jobs. For fresh native-agent builds it also records
`native_agent_sysroot` evidence from `C300X_DEVICE_SYSROOT`: no local path, only
availability, content hashes for the relevant ARMHF sysroot libraries and a
combined fingerprint. Treat that file as the release evidence for why the asset
was considered LTS-compatible at build time.

After downloading a release, verify both signed claims with a current GitHub
CLI:

```bash
gh attestation verify ha-bticino-c300x.zip \
  --repo <owner>/ha-bticino-c300x
gh attestation verify ha-bticino-c300x.zip \
  --repo <owner>/ha-bticino-c300x \
  --predicate-type https://spdx.dev/Document/v2.3
```

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
