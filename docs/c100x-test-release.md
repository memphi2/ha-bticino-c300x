# C100X Issue #51: Agent-Only Test Preparation

Status: local preparation, not a published beta or authorization to install.
Target: **C100X, original firmware 1.5.8**, branch `c100x_1.5.8`.
No release number has been selected. The current `2.8.2` metadata is inherited
development metadata, not a C100X release designation. Do not distribute an old
local ZIP merely because it has that version.

## What This First Test Covers

The first authorized device test should establish agent startup, authenticated
status/setup reads, model/firmware reporting, discovery, and continued vendor
operation. It is not a display, routing migration, camera or audio trial.

- The C100X-aware agent, installer and update guards are implemented offline.
  Routing restoration checks complete known firmware identity; GUI-free restore
  and uninstall recovery guards have temporary-copy regression tests.
- Additional display pages, physical-key navigation, silent/wake Notify and
  read-only text memos exist as offline implementations. **They are not activated.**
- Display pages, GUI restart, ringer mute and key tone remain unavailable through
  the supported C100X installation. Explicit GUI-install requests must fail
  before writing device files, not silently report a successful activation.
- Notify sound, speech/TTS, voice memos and memo mutations are not part of this
  test. No alternative sound script or forced capability flag is supported.
- Starting the agent is not permission to create a media user, patch routing,
  migrate Companion/MQTT, activate streams, change codecs or operate a door.

The issue #51 field report describes Companion installed and non-stock SIP
routes. SIP users come from official app provisioning; Companion's presence
does not establish that it created those users. Preserve accounts, credentials,
routes and existing Companion configuration. The four reported tool/service/hash
questions are cleared offline and are **not** outstanding prerequisites. Exact
GUI activation/readiness/recovery on the device remains unproven. See the
[field-report evidence](c100x-field-report.md).

## Package and Channel Isolation

| Boundary | Current protection and limitation |
| --- | --- |
| Local artifact name | Builder defaults to `ha-bticino-c100x-issue51-local.zip` and refuses the normal C300X asset name in this branch. |
| Device bundle | `c100x_compatible: true` and `c100x_only: true` participate in the bundle hash. Neither is a hardware-support or signature assertion. |
| HA update / SSH repair | This branch rejects the C100X-only package for C300X, including firmware 3.0.6, before upload/write. API updates also reject unknown model identity. |
| Native updater | The new updater rejects C100X-only bundles on a non-C100X device and rejects unmarked incompatible bundles on C100X. Older updaters cannot enforce a field they never implemented: use the reviewed HA preflight, never a raw old updater upload. |
| Legacy shell installer | Blocked in this checkout: its generic upload path has no C100X model preflight. Do not remove the policy file to enable it. |
| Public publication | `publish_release.py` refuses this checkout while `c100x-test-policy.json` exists. There is no bypass flag. The existing workflow additionally requires canonical-main validation evidence; this branch is not a working alternate release channel. |
| HA integration | Domain, discovery service and config-entry identity remain `bticino_c300x`. This package would replace the existing integration on the same HA instance. **Use a separate disposable HA test instance**, with no C300X stable or firmware-3.0.6 beta entries. Renaming the ZIP is not HA isolation. |

These guards prevent accidental use through this branch's supported paths, not
manual privileged overwrites or deliberately relabelled packages. They do not
retrofit guards into old C300X software. Do not use HACS to replace a production
integration for this test, or attach this ZIP to the stable/fw306 release.

### Version and Channel Decision

Recommended first step: a privately handed-off, checksum-bound local test build,
identified by commit and SHA256, without a public tag or HACS channel.

For a later public beta, choose an unused canonical `X.Y.ZbN` version only after
the maintainer selects the release plan. A beta tag in the existing repository is
one shared prerelease stream, **not** a C100X-specific HACS channel; even
`prerelease=true` and `latest=false` do not separate it from the fw306 beta.
A dedicated distribution repository or a reviewed model-aware shared release
policy is required before claiming separate channels. Both still need the HA
domain/instance restriction above. A `+c100x` or `-c100x` suffix is rejected by
the current version validator; do not work around it by relabelling metadata.

Changing the version later requires a new build lock, package and checksums.
No release-policy gate is relaxed by this preparation.

## Before Any Installation

1. The maintainer approves the exact commit, artifact SHA256, tester, device and first-test
   scope. Rebuild/verify from that commit; keep the matching source and recovery
   package. No installation follows automatically from producing a ZIP.
2. Confirm the device is C100X 1.5.8 and retain working privileged SSH/recovery
   access. Explicit credentials take priority; the original-firmware-verified
   factory default does not prove the device still uses it. Never put credentials,
   tokens, SIP secrets or complete configuration in an issue report.
3. Record the existing agent, startup entries, GUI/routing identities, vendor app
   operation and Companion configuration. Securely preserve exact pre-test files
   and metadata outside the device as well as on-device recovery data. Do not
   overwrite a non-stock route with a stock original to make a check pass.
4. Agree how the pre-test agent/startup/configuration will be restored, including
   a failed-start case. On this Companion-modified device, generic uninstall is
   not equivalent to restoration of its pre-test state. If that recovery path
   is unknown, stop before installation, not after a failed startup.
5. Prepare the separate HA test instance with only this package. Check the
   displayed device/model and explicit host before accepting SSH installation.
   Existing production HA instances and their stable/beta packages stay untouched.

## First Authorized Installation and Checks

The supported entry point is the reviewed package's HA SSH bootstrap, not the
blocked developer shell installer. Bootstrap writes agent payload/configuration,
startup integration and, by its current default, the firewall allowance; it
starts/restarts the **agent**, not the vendor GUI. Review these writes explicitly.
The C100X bootstrap must leave legacy MQTT/Companion migration untouched.

1. Install the approved package on the isolated HA test instance; authorize only
   the agreed C100X host. Leave GUI/display installation disabled.
2. After agent installation, stop at feature selection for the first inspection.
   Do not enable video/audio, display, MQTT migration or media-user setup. Do not
   continue through a repair that proposes changing routing or existing users.
3. Check authenticated setup/status, C100X/1.5.8 identity, discovery and available
   capabilities. Display/mute/key-tone/GUI-restart capabilities must remain false.
   An exposed unsupported toggle is a failed acceptance check, not an invitation
   to try it. No-auth access must remain disabled.
4. Compare GUI/routing/provisioned-account identities and Companion state with
   the pre-test record. Check normal physical keys and vendor app operation.
   A changed binary hash or missing account is a stop condition.
5. Observe agent uptime and errors while idle. Record the actual observation
   duration, not a generic stability claim. Reboot persistence, door actions,
   ring/media/audio and update/remove tests need separately agreed phases.

## Recovery and Stop Conditions

Stop on unexpected reboot, loss of vendor calls/app service, GUI changes,
authentication loss, non-stock identity refusal, or failed restoration. Do not
repeat a failing installation, force a capability, delete backups, restart the
entire vendor stack, or replace provisioned SIP accounts to recover.

Use the agreed exact pre-test agent/configuration/startup recovery procedure.
Keep installation errors, hashes and recovery files. Report whether the agent
is stopped, still running, or unknown; a retained file is not process readiness.
Restoring files on disk does not unload QML or an executable already in memory.
No automatic GUI rollback or successful device recovery is claimed here.

Uninstall first verifies that the agent has stopped. After TERM it waits at most
ten one-second intervals; an unknown process state, failed signal without verified
exit, or timeout aborts before restoration or deletion. C100X display and routing
restoration still require their verified identities and recovery paths; unknown
modified files are not overwritten to force removal.

Startup recovery stays armed through final cleanup. If deletion fails, private
startup recovery files are retained and no reboot is scheduled. Startup entries
are restored only if the entire remaining agent tree still matches its pre-delete
identity, including content, modes, ownership and symlink targets. If the agent
tree is partial, changed or unverifiable, startup remains disabled; use the printed
recovery location to repair the installation before restoring startup or rebooting.
This does not recreate already deleted files. Keep the external pre-test backup.

Uninstall acceptance remains a separately authorized hardware phase with verified
routing backups. It cannot establish recovery of arbitrary Companion changes or
unload an already running GUI. Do not run uninstall on the issue #51 device as a
substitute for its pre-test backup.

## Evidence and Remaining Work

Existing offline evidence includes exact original-firmware routing checks,
temporary-copy display upgrades/recovery, old-reader bundle delivery, host key/
layout tests and compilation of 29 generated QML files using original Qt 5.10.1
under QEMU. Compilation does not instantiate vendor QML or validate hardware.
See [experimental support](c100x-experimental.md) and the
[page/control matrix](c100x-display-parity.md) for commands and scope.

Before a public beta: select its version/distribution channel, complete the
exact-source package/build-lock review, reconcile applicable stable safety fixes,
and run the required PR-stage gates. No full gates were authorized during this
preparation. Before display trials: establish isolated call-safe GUI supervision,
failed-start readiness and runtime rollback, then test them on authorized hardware.
Those are real remaining gaps; this agent-only test does not complete page parity.

The tester report should contain commit, artifact SHA256, agent/model/firmware,
test steps and outcomes, observation duration, capability flags, recovery result,
and redacted errors. Never include credentials, tokens or private SIP routes.

### Local Preparation Checks

The preparation ran focused groups, not a full suite:

- 150 tests for package/model isolation, legacy delivery, publication and package
  contracts. Native update fixtures use temporary paths and synthetic system calls.
- 238 tests for bootstrap/identity, factory login, display gating and translations.
  The existing separate Alarmo option remains available even with display disabled.
- 278 tests for removal, routing identity and shutdown regression after the safety
  port. These include original C100X BusyBox under QEMU, actual native restoration
  on temporary firmware copies, installed-adapter failure recovery, bounded stop
  and partial cleanup, plus host/ASan/UBSan shutdown tests. System operations are
  mocked; firmware originals are read-only. This is not device recovery evidence.

The ARM rebuild passes the 24,576-byte stack limit (maximum 24,200 bytes) and
ABI checks against original 1.7.19, 2.0.2, 3.0.6 and C100X 1.5.8 sysroots.
These results do not establish GUI startup or device readiness. No generated QML
changed in this preparation; the earlier original-Qt compile evidence is not
represented as a new hardware or compile run.

Reproduce the local artifact after reviewing the final build lock:

```sh
PY=../ha-bticino-c300x/.venv/bin/python
"$PY" scripts/build_hacs_release.py --skip-build
"$PY" scripts/check_release_contents.py .release/ha-bticino-c100x-issue51-local.zip \
  --agent-binary native_agent/build/armhf/c300x-agent-native \
  --build-lock native_agent/build-lock.json
"$PY" scripts/native_build_lock.py --zip .release/ha-bticino-c100x-issue51-local.zip
sha256sum .release/ha-bticino-c100x-issue51-local.zip
```

The ZIP includes this checklist and the linked C100X support/evidence documents.
It is a **local test candidate**, not an approved release or install request.
