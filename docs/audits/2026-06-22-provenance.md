# Provenance Audit Snapshot

Audit date: 2026-06-22

This is a historical local audit snapshot for the listed commit. It is retained
as release evidence and may reference files that changed later.

Audit base:

- Commit: `3139de2`
- Branch: `1.4.0`
- Local uncommitted documentation changes at audit time: `PRIVACY.md`,
  `SECURITY.md`, and this report.

This audit covers the repository content tracked by git. Ignored local release
artifacts, local captures, local device backups, local secrets, and generated
native-agent bundle payloads are out of scope unless explicitly noted below.

## Method

The audit used the following local checks:

- `git ls-files` to enumerate tracked repository content.
- Extension and top-level directory classification for all tracked files.
- `find` and `git ls-files` checks for firmware, APK, PCAP, archive, object, and
  native binary payloads.
- `git grep` checks for third-party provenance markers, copied-code markers,
  license headers, SPDX headers, secrets, private endpoints, and known forbidden
  C300X identifiers.
- `file` and `sha256sum` checks for tracked image assets.
- Review of `NOTICE`, `docs/legal.md`, `device_qml/README.md`,
  `scripts/check_repo.py`, `scripts/stage_device_agent_bundle.py`, and
  `scripts/build_hacs_release.py`.
- `python3 scripts/check_repo.py`.

## Inventory

Tracked file count: 361

Tracked file classes:

- Python: 200
- Markdown: 44
- C source: 26
- C headers: 22
- YAML/YML: 17
- JSON: 12
- JavaScript: 10
- PNG: 9
- Shell: 6
- JPEG: 4
- QML: 2
- Assembly: 1
- Other text/config/no extension: 8

Tracked top-level areas:

- `custom_components`: Home Assistant integration code, metadata, blueprints,
  frontend card files, project brand images, and the tracked device-agent init
  script.
- `native_agent`: project-owned native C agent source, scripts, docs, and smoke
  tests.
- `device_qml`: project-owned C300X QML additions and local helper JavaScript.
- `docs`: project documentation and README screenshots.
- `tests`: unit and policy tests.
- `.github`: workflows and release notes.
- `scripts`: release, validation, installation, and helper scripts.

## Result

No tracked file was found that appears to be a BTicino/Legrand firmware image,
extracted firmware tree, Android APK, raw PCAP/PCAPNG capture, private device
backup, vendored controller source tree, package lockfile, `node_modules`
payload, or native build output.

No foreign SPDX, copyright, GPL, LGPL, MIT, BSD, or MPL license header was found
in tracked source files. The repository-level license and notice files are
present:

- `LICENSE`: Apache License, Version 2.0.
- `NOTICE`: project copyright notice, trademark notice, SlyOldFox research
  attribution, and repository hygiene restrictions.

No known hardcoded device-specific SIP domain or account marker was found for
the forbidden examples `2208002` or `bs.iotleg.com`.

`python3 scripts/check_repo.py` passed.

## Third-Party References

The project references BTicino, Legrand, Home Assistant, HACS, Nabu Casa,
OpenAI, Codex, and SlyOldFox's `c300x-controller` for compatibility,
attribution, or descriptive context.

The SlyOldFox / `c300x-controller` entry is present in project notices and legal
documentation only. No `SlyOldFox` or `c300x-controller` source marker was found
in runtime code.

`tcpdump2mqtt` appears as a legacy on-device path handled by the native agent
and tests. No `tcpdump2mqtt` source tree or script payload is vendored in this
repository.

The Home Assistant integration does not require external Python packages
through Home Assistant packaging metadata. Optional WebRTC development tests
still use `aiortc==1.14.0`, and the optional SSH installer loads Paramiko lazily
while accepting only the validated `paramiko==3.5.1` version. These dependencies
are not vendored into this repository.

## Assets

Tracked brand assets:

```text
cd64c8c333ae2cfde2f32a8681054c1a5755a2edafadec1183501cd774088834  custom_components/bticino_c300x/brand/icon.png
cd64c8c333ae2cfde2f32a8681054c1a5755a2edafadec1183501cd774088834  custom_components/bticino_c300x/brand/logo.png
```

Both files are 256x256 PNG images and have identical content. `docs/legal.md`
documents them as project-owned generic artwork, not vendor logos or copied
product imagery.

Tracked README image assets:

```text
94423faa17b9dc2154b7278edb79319a229beaac422d5bf92c7c7f4b8a078b21  docs/images/readme/configuration.png
6eef001f1b49d4d31dd5f195a9fe05b37170ad83961cd03db189b2e205fdc397  docs/images/readme/controls.png
b3c9f1237a8319b03347c19aaeccb504fda8807ae2ffec4e3e5605530a24ad51  docs/images/readme/diagnostic.png
1f5f3bc9ebe7cbc2a12d1292af542b64c1224a4b43d29d1717b3e89b59584f7d  docs/images/readme/display-alarmo.jpeg
c37b61710fc6edfb1ca5adbdc715e810743b908aad95735eee7a0979ca099ef9  docs/images/readme/display-bridge-output.png
6294d91bf765d608cacbb5b3b15e6ee1c12eb9a15beca8260dc77b7727a89f5a  docs/images/readme/display-c300x-dashboard.jpeg
396f934ca7c9fe5497338fa13e58e97a1fe3f5f96605e83dfb0608898bbbb001  docs/images/readme/display-custom-ha-page.jpeg
53539865ce730b98cfbcdc043a6d600307ddadf948e519235d747442fc4b7367  docs/images/readme/display-ha-weather.jpeg
2bd4f49ca3ba85502c49d014be7021ce0c94cdb3909f77287b85451e06a38831  docs/images/readme/events.png
8f7d6d9315e67be722b182d133cd979a7b2faa6a9f71a24f223d1e7cada769da  docs/images/readme/ha-door-camera-inline-dark.png
027829692eedce6a50911f1d0bd88d8f0b3aa7b78d80ac0f24d7f972e4a4326b  docs/images/readme/sensors.png
```

The screenshot assets are documented product screenshots of this integration
and its local display/HA UI behavior. They should remain free of private
addresses, tokens, faces, and household-identifying data before each release.

## Device QML

Tracked QML files:

- `device_qml/Alarm.qml`
- `device_qml/HomeAssistant.qml`

These are project-owned additive pages. The repository intentionally does not
track stock vendor pages such as `HomePage.qml`, `MainApp.qml`, or
`MemoPage.qml`. `device_qml/README.md` documents that stock pages are
transformed on the user's device and backed up there, not copied into the
repository.

The QML pages reference built-in image paths from the C300X runtime, for example
`images/settings/act_btn.svg`. Those referenced assets are not stored in this
repository.

## Native Agent Bundle

Tracked native-agent source lives under `native_agent/`. The generated ARMHF
binary and staged bundle payload are intentionally excluded from git:

- `native_agent/build/`
- `custom_components/bticino_c300x/device_agent/armhf/`
- `custom_components/bticino_c300x/device_agent/qml/`
- `custom_components/bticino_c300x/device_agent/scripts/`
- `custom_components/bticino_c300x/device_agent/bundle.json`

The only tracked file under `custom_components/bticino_c300x/device_agent/` is:

- `custom_components/bticino_c300x/device_agent/init/c300x-native-agent`

Local ignored bundle files were present during this audit. Their hashes were:

```text
e5ce89ec59a4f7768730d9fdfe03b21f524529f48622e5c976398e397daa9508  custom_components/bticino_c300x/device_agent/bundle.json
fdee3dda896297a20e95d995f0e219f8c20636987cda6597c25bdf2fc297f5a2  custom_components/bticino_c300x/device_agent/armhf/c300x-agent-native
```

Those files are generated or release-staged artifacts and are not part of the
tracked source provenance result.

## Repository Gate

`scripts/check_repo.py` enforces the main provenance and hygiene policy:

- required release, security, privacy, and legal documents;
- forbidden firmware, archive, object, native build, extracted, vendor,
  third-party, and runtime directories;
- forbidden stock QML page names;
- forbidden source-reference markers in runtime code;
- forbidden common secret and private endpoint patterns;
- legal hygiene phrases in `docs/legal.md`;
- package/release metadata consistency.

The gate passed for this audit.

## Open Limits

This audit is a local repository provenance audit. It does not prove authorship
by cryptographic identity, does not perform external internet-scale clone
detection, and does not replace a lawyer's legal opinion.

For a stricter machine-readable license regime, the next optional step would be
to introduce SPDX/REUSE metadata for all covered files. That would be a separate
churn-heavy change and was intentionally not done in this audit.
