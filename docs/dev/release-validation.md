# Release Validation

This checklist is for release candidates on real hardware. It is not required
for normal users.

## Scope

Validate that the current Home Assistant integration, bundled Lovelace card and
packaged C300X device agent work together on a real C300X.

## Stable Releases

Stable versions use `X.Y.Z`, tagged `vX.Y.Z`.

Versions are canonical and shared by the integration manifest, project metadata,
changelog and release notes. The tagged commit must be the validated `main` HEAD,
with release checks, browser checks and verified provenance/SBOM attestations.
Development branches are not a shortcut around the release gate.

### Canonical CI Evidence

Release tags do not repeat the full HA matrix, HACS, Hassfest or browser suite.
PRs and pushes to `main` and `beta` still run all of them. Stable releases require
the current `main` tip. Beta/RC tags retain the existing branch policy: use the
current `beta` tip first, or `main` if only main matches the tagged commit.
When both tips match, beta is selected and failed beta checks cannot fall back
to main checks. The local `v2.9.0_fw3.0.6` development branch is not an additional
release source. The firmware-3.0.6 `2.9.0b2` candidate is intended for canonical
`beta`, not for a merge into `main`.

Local candidate preparation may proceed after the beta review, including its
version bump, native rebuild and package approval. Before proceeding beyond
local preparation, finish and publish stable **2.8.2 first**, then recompare
and port any final changes into the beta worktree one way only. Run the
full local checks on the final beta candidate **before opening its PR**; the
focused port checks are not a substitute. After authorized integration into
canonical `beta`, require all normal exact-commit beta-push checks. Only then
prepare the authorized tag-bound prerelease publication. Do not push, tag,
stage a remote transport draft or publish while the stable-first/review/full
gate conditions remain outstanding. Local candidate metadata stays
`local-unverified`; it must not claim CI success.

Release requires successful **push runs on that selected branch** of the
canonical `validate.yml`, `browser.yml` and `codeql.yml` workflows for the exact
released commit. Tag, checkout, release workflow source and selected remote
branch tip must agree. A successful PR, schedule, manually dispatched run, or
run on the other branch is not interchangeable release evidence. Publication
remains tag-bound; no branch override, merge bypass or firmware detection is added.
The gate checks out the immutable release run SHA; publication checks out the
commit emitted by that gate, never a newly resolved tag. Manual release retries
must run from the release tag with the same run and workflow source SHA.

`scripts/verify_main_validation.py` checks workflow IDs/paths and repository
IDs, then every required job and step in the latest run's exact attempt.
Dependabot policy, HACS, Hassfest, both HA legs, browser and all four CodeQL
languages must succeed. Skipped, missing, failed, cancelled, duplicate or
unexpected jobs fail closed. Partial reruns cannot combine jobs from different
attempts; use **Re-run all jobs**. An older success cannot override a newer
failure. Evidence must be no more than seven days old, including when retried.

After each main/beta-push HA leg has passed the full validation and official
container runtime checks, `scripts/validation_evidence.py` records the actual
installed HA version and verifies it matches the resolved target. It uploads
`ha-validation-<target>-<run_attempt>` with seven-day retention. Its small JSON
binds repository, branch ref, source SHA, workflow ref/SHA/content digest, run ID
and attempt.
The minimum must equal the declared project minimum; current HA is the actual
rolling version tested, not the local project baseline or a new PyPI query.

The release verifier downloads by artifact ID from that run, checks GitHub's
SHA256 archive digest, size, expiry, run/repository binding and payload identity.
It does not execute or extract artifact files. Missing, foreign, stale,
conflicting or malformed evidence fails publication. GitHub Actions' read API,
the reviewed workflows at the released source commit, and immutable uploaded
artifact bytes are the trust boundary, not artifact names or self-reported
success. Workflow definitions and jobs are reviewed source; this gate does not
replace branch protection, code review or security policy.

The canonical branch gate emits a digest of the verified aggregate. The publish
job fetches and verifies evidence again against that digest before building, and rechecks
it immediately before publication. Concurrent reruns, a branch switch, or movement
of the selected branch/tag fail these checks. `build-metadata.json` embeds the
selected source branch, exact versions, job IDs, workflow/run/attempt bindings
and artifact IDs/digests. No fifth public asset
is added. CI metadata generation requires digest-pinned evidence; local metadata
without evidence is explicitly `local-unverified` and claims no validated jobs
or HA versions (the configured version baselines remain informational).

Release content/tag checks, the reviewed native build lock, packaging, SBOM,
provenance and SBOM attestations, and remote downloaded-asset verification remain
mandatory. No merge/admin bypass or device/HA activation is part of this gate.
Artifact and attempt bindings use the documented
[GitHub Actions artifact API](https://docs.github.com/en/rest/actions/artifacts)
and [workflow jobs API](https://docs.github.com/en/rest/actions/workflow-jobs).
Branch selection uses exact references from the
[matching references API](https://docs.github.com/en/rest/git/refs#list-matching-references),
not similarly named branches returned by its prefix lookup. A missing beta ref
can fall back to main for prereleases; API failures cannot.

New releases are drafts until their four downloaded assets match the validated
local artifacts.
Reruns verify existing assets, notes and channel without overwriting them;
conflicts or API errors stop publication. Tags are checked against the source
commit again immediately before publishing a draft.

Each release ships `ha-bticino-c300x.zip`, `SHA256SUMS`, `build-metadata.json`
and `sbom.spdx.json`. The ZIP includes the frontend and device-agent bundle.
Agent reuse and version-bump checks consider merged older versions in version
order. Changes to native inputs require an agent version bump and rebuild.
Integration-only changes may retain the verified agent; never relabel an old
binary to give it the integration's new version.
Display files under `device_qml` ship in the bundle without entering the
binary: their content is covered by the bundle hash, which the agent-update
check compares, so a display-only change is delivered to the device on the
verified agent and does not require a version bump.

Prepare a new version and its dated notes only when that release is intended.
Creating a development branch does not publish a release.

## Isolated Integration Tests

The HA matrix tests the fixed minimum from `project-versions.json` and the
latest non-yanked stable release from PyPI on every Validate run. Preview releases
are excluded. The resolver pins that exact version before installing tools, so a
dependency conflict fails the job instead of silently testing an older HA.
The resolved version is logged and passed from canonical branch evidence into build
metadata. `current_homeassistant` in the version file is the local validation
baseline, not a cap on the rolling CI target. Raising the minimum remains manual.

Validate also runs `scripts/check_ha_container_runtime.py` in
the official HA container for each resolved version. These required checks use
the image's own ffmpeg/ffprobe and HA event entities, not the Ubuntu host tools.
They verify JPEG extraction from H.264 clips with unknown, limited and full color
range, recording startup when H.264 parameter sets arrive after the initial
packets, and technical event types for automation triggers. The exact HA version
and image digest are logged. Missing tools or failed checks fail the job.
Containers run without network access, with a read-only checkout and root
filesystem, and temporary test files only. These synthetic clips do not replace
reproduction with a reporter's original failing recording.

Development hosts and CI runners use Ubuntu 26.04. Its `libturbojpeg0` candidate
is still 2.1.5, but HA's PyTurboJPEG 2.x requires native TurboJPEG 3 or newer.
Installing the Python wrapper or Ubuntu package alone does not resolve this.
Do not downgrade HA's wrapper or suppress its camera fallback warning.

On Linux amd64, prepare an isolated library before camera tests or typing:

```bash
PYTHON=/path/to/ha-validation-venv/bin/python
TURBOJPEG_LIB_DIR="$("$PYTHON" scripts/setup_turbojpeg.py)" || exit 1
export LD_LIBRARY_PATH="$TURBOJPEG_LIB_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
"$PYTHON" scripts/check_turbojpeg.py
```

`setup_turbojpeg.py` downloads the official
[libjpeg-turbo 3.2.1 release](https://github.com/libjpeg-turbo/libjpeg-turbo/releases/tag/3.2.1)
asset `libjpeg-turbo-official_3.2.1_amd64.deb`. Its SHA256 is
`21c7af6e505386dda0fa05e9eab5a8d288947f2e09ade8d7a48ff393ed08182d`,
verified against GitHub's published asset digest (asset ID `682859044`). The
checked-in pin, not a live release lookup, authorizes the bytes on every run.
Only the regular TurboJPEG shared-library payload is copied; package scripts,
symlinks, tools and the separate libjpeg library are never installed/extracted.
`dpkg-deb` is required, but no root access or package installation is used.

The cache defaults to `$XDG_CACHE_HOME/c300x-dev` (otherwise
`~/.cache/c300x-dev`), or `$RUNNER_TEMP/c300x-dev` on CI. `--cache-dir` can select
another directory outside the checkout. A corrupt cached package fails closed;
remove that cached `.deb` explicitly before retrying a verified download.
No binaries or upstream sources are vendored, bundled or installed in HA/C300X.
System libraries and Python dependency pins are unchanged. The loader export
applies only to the development shell and its children; start a fresh Python
process after exporting it. Do not apply it to a running HA installation.

Validate uses this setup in **both minimum/current HA matrix legs**; Release
requires that exact branch-run evidence. `--github-env` verifies the loaded cache
path in a fresh subprocess before exporting it for later steps.
`check_validate.py` also checks the default loader,
TurboJPEG 3 API, actual mapped library, JPEG encode/decode pixels and HA camera
singleton before other gates. Missing/incompatible libraries fail the gate;
no warning filters or fallback-success exceptions are added. A supported system
TurboJPEG 3 can pass the same check without the cache; the configured Ubuntu
26.04 repository currently does not provide that alternative. The official HA
container checks remain independent and use the container's own libraries.

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

The actual card is rendered at 240, 320, 390 and 1024 pixels in four languages.
Tests check action bounds/labels, unavailable and pending buttons, door/light
routing, repeated WebRTC start/stop, microphone muting and detach cleanup.
A synthetic canvas feeds a real browser-to-browser WebRTC connection; pixel
checks require decoded video. HA host elements and signaling are fixtures,
microphone input is Chrome's fake device and no C300X is contacted. Screenshots
are written to ignored `.artifacts/browser/`. These are not real-HA frontend or
device interoperability tests.

## Display Layout Checks

The optional `scripts/check_energy_layout.py` renders the production Energy QML
offscreen in an existing PySide6 environment:

```bash
/path/to/qt-python scripts/check_energy_layout.py \
  --fixture-python /path/to/ha-python --check --output .artifacts/energy
```

It checks four languages, all subpages, normal and reduced heights, tab switching
and long labels/large values. Screenshots, text bounds and diagnostics stay in
the ignored artifacts directory. `--revision COMMIT` renders an older QML file
without changing the checkout. `--stock-skin DIRECTORY` can read local skin
images; no vendor assets are bundled or uploaded.

Qt Quick 1.1 imports and two vendor components are adapted for the local Qt 6
renderer. This verifies layout, not Qt 4 firmware or device performance.
PySide6 is a development-only tool, not an integration dependency.

### Offline Qt 4 Runtime

For the original Qt 4.8.7 engine, use a private, extracted C300X 1.7.19
firmware root filesystem, `arm-linux-gnueabihf-gcc` and `qemu-arm`:

```bash
python scripts/setup_qt4_runtime.py --sysroot /private/rootfs-1.7.19
python -m pytest tests/test_energy_consumers_layout.py::test_consumers_qt4_runtime_labels tests/test_qt4_runtime_setup.py
```

Setup builds and verifies the ARM probe in `$XDG_CACHE_HOME/c300x-dev/qt4-runtime`
(default `~/.cache/c300x-dev/qt4-runtime`). Pytest discovers it automatically.
Changed probe sources or damaged cache files fail explicitly: rerun setup.
The existing `C300X_QT4_QEMU`, `C300X_QT4_ROOTFS`, `C300X_QT4_PROBE` and
`C300X_QT4_IMPORTS` overrides remain supported when all four are set.
The separate compile-only checks use `C300X_QT4_COMPILE_PROBE` and
`C300X_QT4_COMPILE_IMPORTS` for the compiler and its placeholder modules.
Do not use the compile-only executable as the runtime probe.

The probe checks the actual Qt version and executes the unchanged consumer
JavaScript through a non-rendering QML test component, including 214 numeric
formatting checks. It uses a narrow Qt 4.8.7 ABI adapter because firmware
development headers are unavailable. It does not render the display, load
vendor plugins, prove device startup safety or replace hardware testing.
Only trusted test QML should be passed to it. Firmware libraries stay in the
private sysroot; setup neither copies them into the repository nor contacts,
writes to or restarts a device. CI without that private runtime still skips
the optional firmware-specific tests.

## Display Bundle Upgrade Tests

The staged manifest (`update_file_set_version`) and the agent capability
(`self_update_file_set_version`) must advertise the same update file set, today
6. An installed updater with a lower file set cannot install the new paths; the
HA Repair then runs its second pass before the active display is patched or
reloaded.

`tests/test_agent_update_display_bootstrap.py` compiles the unchanged updater
from `e1192c7f4abfaad508f46a9add6402a5eb530856` and starts with its actual
display sources already patched into temporary GUI files. It exercises the
HA upload, verification, bootstrap completion and QML restoration code. Only
transport, agent restart, GUI process control and unrelated HA services are
simulated. Missing/corrupt new files and activation failure must preserve the
old GUI and pending repair flags; retry completes installation before reload.
Every generated source is compared with the package, then `restore-all` must
recover the original GUI. The separate legacy-bootstrap test retains the inert
Distribution input required by file-set 4; it must not become an active view.

After every display change, run the compile-only probe
(`C300X_QT4_COMPILE_PROBE`, `C300X_QT4_COMPILE_IMPORTS`): it compiles the
display components under QEMU ARM against the private firmware 1.7.19 Qt 4.8.7
libraries and stock Styles module, with an import-only `BtObjects` placeholder,
and must report `compile_failed=0`. It does not instantiate or render the GUI,
execute the vendor plugin, or test device startup/reboot behaviour; it is
separate from the Qt 6 layout checks and is not hardware validation.

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
| On-demand capture from idle | Explicit `capture_mode: on_demand` records without ringing. Test `include_audio: true` and `false`, durations of 1, 5 and 15 seconds, exact response paths and capture-mode metadata with the packaged native agent. |
| On-demand capture when admission reports busy or unclear ownership | Reported live, Ring, Home Call or external sessions cause rejection before recording begins. |
| Ring begins during on-demand connection setup (hardware) | Begin an on-demand capture from idle and ring the doorbell during RTSP setup, with audio enabled and disabled. Record whether capture fails or receives Ring video through the existing native route. Verify that capture sends no Ring answer/hangup or global stop and that closing its recording client leaves the Ring intact. Successful metadata retains `capture_mode: on_demand` as the requested mode. |
| On-demand capture completion, failure and cancellation | Its recording client closes after success, ffmpeg failure or cancellation, including before RTSP startup. Other or replacement sessions remain intact; a subsequent capture can start. |
| On-demand capture with an announcement | `announcement_path` is rejected before media starts; Ring Call announcements retain their existing behavior. |
| Home Call start/stop | Display rings, state updates, hangup cleans up. |
| On-demand after Home Call | First stream attempt works after Home Call cleanup. |
| Saved media browsing | Older/newer navigates entry-owned snapshots and recordings in the same window without device requests. A click on the picture opens the large window and closing it keeps a running stream. Play, seek, volume, mute and, in the large window, full screen work; leaving the recording stops playback. |
| Ring arrives during archive playback | Archive playback stops and the existing Ring Call controls take priority; Home Call and door/light actions retain their configured behavior. |
| Narrow media card | Controls, name and status remain visible at the supported HA grid minimum, including an active microphone and Home Call-only mode. |

## Event Semantics

- First confirmed touch-tone, ringer and forwarding values synchronize the
  corresponding entities without public change events or setting writes.
- Availability loss and same-value recovery update those entities without
  replacing their last valid comparison value or triggering change events.
- Confirmed value changes, including a different value observed on recovery,
  produce one event; a following identical device notification adds none.
- Message-directory access loss and unchanged recovery are state snapshots.
  Actual additions, deletions and read-state changes still produce events,
  including changes in an accessible memo collection while the other is offline.
- Repeated doorbell, door/light, activation and call occurrences are not
  suppressed merely because their payload values match.

## Media Device Checks

For the PCMU reboot regression, verify the running agent version and active
device codec first. Observe boot ID, uptime and the answering-machine/media
processes for at least 180 seconds after each stop; a successful stream alone
does not establish that the device remained healthy. Record cold-boot and
short-gap tests separately rather than inferring them from long-idle runs.
Keep raw captures and device identifiers private.

## Firmware Versions

Firmware `1.7.19` and `2.0.2` share one agent binary and one set of display
files. Before a release, and before a version of that kind is added:

1. Run `scripts/check_firmware_rootfs.py` with the `1.7.19` root file system
   as baseline against `2.0.2`. It must pass.
2. Build the ARMHF agent once against each of these root file systems
   (`C300X_DEVICE_SYSROOT`) and compare the binaries. They must be identical.
3. Apply `scripts/device_routing_builder.py` to the stock routing target of
   each of these versions. It must accept the file and report the patched hash.

Firmware `3.0.6` (experimental) fails step 1, has its own routing table and
keeps its display files as Qt resources in `BtClass`, so steps 1 to 3 do not
apply; see
[Supported Firmware Versions](native-agent.md#supported-firmware-versions).
For it, run `armhf-abi-check` with its root file system in
`C300X_ABI_SYSROOTS`, then the device tests below. On this beta the Display
patch row checks the Qt 5 resource overlay; the status must show
`qt5_overlay: active`.

Device tests per firmware version, because the vendor media, SIP and D-Bus
programs differ between versions:

| Check | Expected result |
| --- | --- |
| First installation on a rooted stock device | Installs without extra Python modules on the device; no `device_install_failed`. |
| Self-test | `device_routing` reports `stock` before and `patched` after the routing patch; restoring the backup returns the stock hash. |
| Display patch | The Home Assistant page and the other display pages appear; the Repair reports the current file set. |
| Ring Call, default codec | Real doorbell ring: preview, answer, two-way audio, hang-up. Needs a device paired with the vendor app. |
| Ring Call, PCMU | Same with PCMU; boot ID and uptime unchanged afterwards. |
| On-demand video and Home Call | Start, audio in both directions, stop; device stays up. |

Firmware `2.0.2`: steps 1 to 3 pass. The device tests are open; the
contributor of the `2.0.2` routing table runs the agent on such a device, and
Ring Call was not tested there because the device is not paired.

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
- energy page, when switched on, shows its views and only the sources set up in Home Assistant,
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
validated release jobs. Its `native_agent_sysroot` section describes the
environment generating that metadata: availability, hashes of relevant ARMHF
libraries and a combined fingerprint, without local paths. Hosted packaging
has no private sysroot, so those fields report unavailable even when the agent
was built and ABI-checked locally. The local-build handoff does not transfer
compiler or sysroot provenance; the reviewed build lock binds executable bytes
to approved source inputs, not independently attested build conditions.

After downloading a release, verify both signed claims with a current GitHub
CLI:

```bash
gh attestation verify ha-bticino-c300x.zip \
  --repo <owner>/ha-bticino-c300x
gh attestation verify ha-bticino-c300x.zip \
  --repo <owner>/ha-bticino-c300x \
  --predicate-type https://spdx.dev/Document/v2.3
```

The reviewed build lock covers these native and bundle input paths:

- `native_agent/src`
- `native_agent/scripts`
- `native_agent/qt5`
- `native_agent/VERSION`
- `native_agent/Makefile`
- `native_agent/config.example.json`
- `device_qml`
- `custom_components/bticino_c300x/device_agent/init`
- `scripts/stage_device_agent_bundle.py`
- `scripts/device_file_strip.py`
- `scripts/build_hacs_release.py`
- `scripts/check_agent_abi.py`
- `scripts/native_build_lock.py`

Changes to these paths invalidate the previous approval. Native code changes
require rebuilding with a verified `C300X_DEVICE_SYSROOT` and running the
ABI/stack gates. Display-content-only changes may retain the executable, but
still require a rebuilt bundle and renewed source-bound approval. Retain local
build/ABI evidence separately; hosted `build-metadata.json` does not inherit it.

### Reviewed Local Native Build

Hosted CI does not have the private device sysroot. Before preparing a release,
build the ARM agent locally with that sysroot and run the ABI and stack checks.
Then generate the source-bound approval record:

```bash
.venv/bin/python scripts/native_build_lock.py \
  --generate native_agent/build/armhf/c300x-agent-native
.venv/bin/python scripts/native_build_lock.py --check-inputs
```

Review and commit `native_agent/build-lock.json` together with the final release
sources. It records the packaged executable's SHA-256, the agent version and a
digest of native and bundle inputs. Build settings are represented by a hash,
not private filesystem paths. Any covered source change invalidates the lock;
regenerate it only after reviewing and rebuilding the affected inputs.

CI checks both the source digest and executable hash before packaging. A ZIP
downloaded from a release is only a transport for these approved bytes, not
independent proof that its executable was built from the current source. The
lock is maintainer approval of a local build, not a reproducible-build claim or
an independent attestation of the private compiler/sysroot contents.

For a fresh native build, prepare a draft at the final release tag containing
only `ha-bticino-c300x.zip`, with the body exactly
`C300X native build transport`. Build that ZIP from the committed release tree;
do not upload local metadata into this transport draft. After all gates pass,
CI requires the ZIP to match its regenerated package byte for byte, adds its
verified metadata and checked-in notes, then verifies downloads before
publication. It never replaces conflicting assets or an existing published
release. An interrupted metadata upload can require manual cleanup of the
unpublished draft before retrying.

## Dependency Update Coverage

Normal GitHub Actions and Python tool updates are grouped quarterly, with at
most one open version-update PR per ecosystem. Python major-version changes
remain manual compatibility work. The groups apply only to version updates:
security-update PRs do not wait for the quarterly schedule and use GitHub's
separate security PR limit.

The HA versions used in CI live in separate
`requirements/ha-min/requirements.txt` and
`requirements/ha-current/requirements.txt` manifests. Validate and Release
install those exact manifests together with their direct tool pins. Neither HA
target is excluded from its Dependabot entry. Routine HA version updates remain
manual; `open-pull-requests-limit: 0` does not disable security-update PRs.

Dependabot alerts and automatic security-update PRs must be enabled in the
repository settings; a local configuration change cannot enable them. Alerts,
security-update PRs and version-update schedules are distinct; an ignored update
version does not suppress the advisory itself.

There is no package-specific SSH dependency ignore range. AsyncSSH updates
follow the normal policy and require legacy-device compatibility tests. The
minimum-HA **tool** file is maintained manually and excluded from automatic
updates; that exception does not cover the minimum HA manifest.

`requirements-dev.txt` and `requirements-dev-min-ha.txt` contain direct tools,
not generated transitive lockfiles. Do not restore a matching `.in` file:
Dependabot would treat the pair as pip-compile input/output and regenerate the
transitive pins. `scripts/check_dependency_updates.py` checks parsed YAML,
manifest contents and CI wiring, including forbidden coverage restrictions.
Security PRs are not auto-merged; align `project-versions.json` and
compatibility metadata with a changed HA pin and pass both validation targets
before merging.

See the [Dependabot configuration reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference).

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

### Public Content Audit

Maintainers can run `python scripts/audit_github_privacy.py --file <local-file>`
for offline triage, or explicitly opt into read-only GitHub access with
`--repository <owner>/<repo> --allow-network`. The latter inspects release
metadata/assets, issue/PR text, comments and reviews. It can use `GH_TOKEN` for
GitHub API authentication; that credential is not forwarded to asset redirects.
Nothing is uploaded, edited, commented on, closed or deleted.

Reports contain numbered source identifiers and finding categories, not matched
text, private paths or credentials. JSON `complete: false` and exit status 2 mean
the audit could not finish, including size, request or pagination limits. Exit 1
means possible findings; exit 0 means no matches within the stated scope.

Archive inspection never extracts files and enforces member, byte and download
limits. These are heuristic warnings requiring manual review, not proof that
content is private, safe or legally cleared. Images are not OCR-scanned; linked
attachments, Git history and discussions are outside the audit's scope. The
tool is not run automatically against GitHub by CI or the integration.
