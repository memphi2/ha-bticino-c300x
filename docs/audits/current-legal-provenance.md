# Current Legal and Provenance Audit Snapshot

Audit date: 2026-07-05

This is a technical repository provenance and release-readiness audit. It is
not a legal opinion and does not replace review by qualified counsel.

Audit base:

- Branch: `1.7.0`
- Commit: `3c054aa`
- Local release line: `1.7.0`
- The branch was one commit ahead of `origin/1.7.0` at audit time.
- Local uncommitted audit-gate changes existed while this report was written:
  `scripts/check_legal_audit.py`, `scripts/check_validate.py`,
  `scripts/check_repo.py`, and `docs/release-validation.md`.

Scope:

- Tracked repository source content before adding this report.
- Legal/security/privacy documentation.
- Runtime package metadata.
- Dependency lock files as validation/development inputs.
- Freshly built ignored local `.release` artifact as current `1.7.0` package
  evidence.
- Public GitHub Code Search and web-search fingerprint checks for obvious
  external clone/source-copy matches.
- Project naming, brand-asset and trademark-notice hygiene.

Out of scope:

- Legal advice.
- Private repositories and non-indexed internet content.
- Full forensic clone/similarity analysis across the whole internet.
- Authorship proof by cryptographic identity.
- Jurisdiction-specific patent or trademark legal clearance.

External references used for license identifier sanity:

- Apache Software Foundation Apache License 2.0 text:
  <https://www.apache.org/licenses/LICENSE-2.0.txt>
- SPDX Apache-2.0 entry:
  <https://spdx.org/licenses/Apache-2.0>

External references used for trademark and brand-context sanity:

- BTicino describes BTicino as a premium brand of the Legrand Group:
  <https://www.bticino.com/about-us>
- BTicino pages identify BTicino as a company of the Legrand Group:
  <https://www.bticino.com/about-us/press-and-media>
- WIPO trademark overview:
  <https://www.wipo.int/en/web/trademarks>
- Home Assistant logo refresh and brand-assets pointer:
  <https://www.home-assistant.io/blog/2023/09/17/a-refreshed-logo-for-home-assistant/>
- Works with Home Assistant badge requirements:
  <https://works-with.home-assistant.io/>

## Method

The audit used these local checks:

- `git ls-files` inventory.
- `file`, `sha256sum`, `unzip -l`, and `unzip -Z1` for asset/package checks.
- Regex checks for firmware/archive/capture/binary payload suffixes.
- Regex checks for forbidden foreign/runtime directories.
- Regex checks for stock vendor QML page names.
- `git grep` checks for third-party/reference markers and license headers.
- `scripts/check_repo.py`.
- `scripts/check_legal_audit.py`.
- Targeted privacy/security and release-package tests.
- Native-agent config check through `make -C native_agent check`.
- Public GitHub Code Search exact-fingerprint queries excluding this
  repository.
- General web exact-fingerprint queries excluding this repository where the
  search engine supported that syntax.

## Inventory

Tracked source inventory before this report:

- Tracked files: 420
- Python: 214
- Markdown: 57
- C source: 33
- C headers: 29
- JavaScript: 16
- YAML/YML: 19
- JSON: 13
- PNG: 8
- MJS: 8
- Shell: 6
- JPEG: 4
- QML: 2
- Text: 2
- Assembly: 1
- TOML: 1
- Requirements input: 1
- Other/no extension: 6

Tracked top-level areas:

- `.github`: workflows and release notes.
- `blueprints`: repository blueprint copies.
- `custom_components`: Home Assistant integration, frontend card, metadata,
  bundled blueprints, brand assets, and the device-agent init script.
- `device_qml`: project-owned additive C300X display pages and helper JS.
- `docs`: user, maintainer, legal, release and audit documentation.
- `native_agent`: project-owned native C agent source, scripts and tests.
- `scripts`: release, validation, install and helper tools.
- `tests`: unit, policy and frontend tests.

## Result

No tracked repository file matched the forbidden tracked-source patterns for:

- BTicino/Legrand firmware images or extracted firmware trees.
- Android APKs or extracted mobile payloads.
- PCAP/PCAPNG captures.
- Native object/shared-library/archive payloads.
- Package archives such as zip/tar/gz/xz/7z.
- Foreign/runtime directories such as `vendor`, `third_party`, `external`,
  `firmware`, `extracted`, `original_firmware`, `node_modules`, or `dist`.
- Stock vendor QML page names `HomePage.qml`, `MainApp.qml`, or `MemoPage.qml`.

No foreign SPDX, copyright, GPL, LGPL, MIT, BSD, or MPL source header was found
in runtime source. The repository-level license and notice are present:

- `LICENSE`: Apache License, Version 2.0.
- `NOTICE`: project notice, trademark notice, SlyOldFox research attribution,
  and repository hygiene restrictions.

`custom_components/bticino_c300x/manifest.json` has an empty
`requirements` list. This means the HACS/Home Assistant install package does
not request Python runtime dependencies through Home Assistant package
resolution. Validation/development dependencies remain locked in
`requirements-dev.txt` and `requirements-dev-min-ha.txt`.

`paramiko==3.5.1`, `av==18.0.0`, and `PyTurboJPEG==2.4.0` are validation or
optional/lazy-path dependencies in the development locks, not vendored source
code and not integration runtime requirements.

## Third-Party References

The repository references BTicino, Legrand, Home Assistant, HACS, Nabu Casa,
OpenAI, Codex, Anthropic, Claude, SlyOldFox and `c300x-controller` for
compatibility,
attribution, legal hygiene, historical release notes, or tests.

The SlyOldFox / `c300x-controller` attribution is present in `NOTICE`,
documentation and historical release notes. No copied `c300x-controller` source
tree or source marker was found in runtime code by the focused audit gate.

`TcpDump2Mqtt` appears as a legacy on-device migration/compatibility topic in
integration code, tests and documentation. No `TcpDump2Mqtt` source tree or
script payload is vendored in this repository.

## Public Clone / Similarity Search

Public GitHub Code Search was queried with exact project fingerprints while
excluding the canonical upstream repository. No external result was returned
for these successful queries:

```text
"C300X_DOORBELL_CARD_TEMPLATE" NOT repo:<upstream>/ha-bticino-c300x
"c300x-native-agent-ipv4-firewall-v2-api-rtsp-talkback" NOT repo:<upstream>/ha-bticino-c300x
"async_ensure_doorstation_audio_gain" NOT repo:<upstream>/ha-bticino-c300x
"C300X_RING_PREVIEW_STATE" NOT repo:<upstream>/ha-bticino-c300x
"C300X_MAX_ACTIVATIONS" NOT repo:<upstream>/ha-bticino-c300x
"Legal/provenance audit passed" NOT repo:<upstream>/ha-bticino-c300x
"C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS" NOT repo:<upstream>/ha-bticino-c300x
"c300x-device-file-backups" NOT repo:<upstream>/ha-bticino-c300x
"bticino_c300x.run_ring_wyoming_analysis" NOT repo:<upstream>/ha-bticino-c300x
```

Additional GitHub Code Search queries were stopped by the GitHub API rate
limit. The completed sample is therefore a public-index fingerprint search, not
a complete internet-scale forensic clone analysis.

General web exact-fingerprint searches did not identify external copies of the
project-specific symbols. The web search did surface known C300X community
projects and public manuals; those are already treated as external projects or
public product documentation, not vendored source in this repository.

## Trademark / Naming Review

The repository and integration use the BTicino, Classe 300X, C300X, Legrand,
Home Assistant and HACS names descriptively for compatibility and user
orientation. `README.md`, `NOTICE` and `docs/legal.md` explicitly mark the
project as unofficial and not affiliated with, endorsed by, sponsored by, or
certified by those owners.

Tracked brand assets are limited to the project-owned generic `icon.png` and
`logo.png` hashes recorded below. No BTicino, Legrand, Home Assistant, HACS,
Nabu Casa or other third-party logo file is tracked. The README uses a generic
HACS custom badge and does not use the dedicated Works with Home Assistant
badge.

This is clean for repository hygiene, but not a trademark clearance opinion.
Keep the compatibility wording descriptive, keep the unofficial/non-affiliation
notices visible, and do not add vendor logos, product-image crops,
certification badges, or wording that implies official status without a
separate legal review.

## Assets

Tracked brand assets:

```text
cd64c8c333ae2cfde2f32a8681054c1a5755a2edafadec1183501cd774088834  custom_components/bticino_c300x/brand/icon.png
cd64c8c333ae2cfde2f32a8681054c1a5755a2edafadec1183501cd774088834  custom_components/bticino_c300x/brand/logo.png
```

`docs/legal.md` documents these as project-owned generic artwork. The focused
legal gate now fails if either hash changes without review.

Tracked README screenshot assets:

```text
94423faa17b9dc2154b7278edb79319a229beaac422d5bf92c7c7f4b8a078b21  docs/images/readme/configuration.png
6eef001f1b49d4d31dd5f195a9fe05b37170ad83961cd03db189b2e205fdc397  docs/images/readme/controls.png
b3c9f1237a8319b03347c19aaeccb504fda8807ae2ffec4e3e5605530a24ad51  docs/images/readme/diagnostic.png
1f5f3bc9ebe7cbc2a12d1292af542b64c1224a4b43d29d1717b3e89b59584f7d  docs/images/readme/display-alarmo.jpeg
6294d91bf765d608cacbb5b3b15e6ee1c12eb9a15beca8260dc77b7727a89f5a  docs/images/readme/display-c300x-dashboard.jpeg
396f934ca7c9fe5497338fa13e58e97a1fe3f5f96605e83dfb0608898bbbb001  docs/images/readme/display-custom-ha-page.jpeg
53539865ce730b98cfbcdc043a6d600307ddadf948e519235d747442fc4b7367  docs/images/readme/display-ha-weather.jpeg
2bd4f49ca3ba85502c49d014be7021ce0c94cdb3909f77287b85451e06a38831  docs/images/readme/events.png
8f7d6d9315e67be722b182d133cd979a7b2faa6a9f71a24f223d1e7cada769da  docs/images/readme/ha-door-camera-inline-dark.png
027829692eedce6a50911f1d0bd88d8f0b3aa7b78d80ac0f24d7f972e4a4326b  docs/images/readme/sensors.png
```

The screenshot assets should be re-reviewed before each release for private
addresses, tokens, faces and household-identifying information.

## Device QML

Tracked QML files:

- `device_qml/Alarm.qml`
- `device_qml/HomeAssistant.qml`

These are project-owned additive pages. The repository does not track stock
vendor pages such as `HomePage.qml`, `MainApp.qml`, or `MemoPage.qml`.
`device_qml/README.md` documents that stock pages are transformed on the
user-owned device and backed up there, not copied into this repository.

The QML pages reference C300X runtime image paths such as
`images/settings/act_btn.svg`. Those referenced image files are not stored in
this repository.

## Native Agent and Release Bundle

Tracked native-agent source lives under `native_agent/`. Generated native build
outputs are ignored under `native_agent/build/`.

The only tracked file below
`custom_components/bticino_c300x/device_agent/` is:

- `custom_components/bticino_c300x/device_agent/init/c300x-native-agent`

Generated release bundle files such as the ARMHF binary, staged QML files,
scripts and `bundle.json` are intentionally not tracked in git. They are
generated/reused by the release packaging path and validated through bundle
hash metadata.

Current release metadata also records sanitized native-agent sysroot evidence
when `C300X_DEVICE_SYSROOT` is configured for a fresh ARMHF build. The evidence
uses library hashes and a combined fingerprint, not local sysroot paths.

An ignored local `.release/ha-bticino-c300x.zip` was rebuilt during this audit:

```text
79845873d49845d74073cfbc4c11767578353dad359f2b5e1fb7408cddf1b345  .release/ha-bticino-c300x.zip
17187b683ba902c4a3456eff076466c808de1abca2d66d747673f4b4cd44311e  .release/build-metadata.json
946e18eb583947eb9d3fd76ca555d66ed6996ad758c42cf9f431053c564fd492  .release/sbom.spdx.json
```

The artifact identifies itself as release `v1.7.0` with integration version
`1.7.0`, native-agent version `1.7.0`, git commit
`3c054aae56fea0224299b2d1cea5be6115d0b48c`, and 154 zip entries.

The package content includes `LICENSE`, `NOTICE`, `PRIVACY.md`, `SECURITY.md`,
`docs/legal.md`, `manifest.json`, `device_agent/bundle.json`, and
`device_agent/armhf/c300x-agent-native`.

No forbidden firmware/APK/capture/vendor path was found in the zip listing.
`unzip -t` reported no compressed-data errors and
`sha256sum -c .release/SHA256SUMS` passed for the zip, build metadata and SPDX
SBOM.

Release bundle metadata:

```text
bundle version: 1.7.0
agent version: 1.7.0
runtime hash: sha256:3b341d018217fb8ba2915e363ed6023af44848bcf537185872383a0de846557f
bundle hash: sha256:5748237c39a2d83bca0bd5a49dbc41b92e7379cff0656e4584c3b10dd360ab5b
```

## Release Gate Added

This audit added a repeatable focused gate:

```bash
.venv/bin/python scripts/check_legal_audit.py
```

The gate checks:

- forbidden tracked payload suffixes,
- forbidden foreign/runtime directories,
- stock vendor QML page names,
- third-party/reference markers in runtime code,
- required legal/privacy/security documents,
- empty Home Assistant runtime requirements,
- project-owned brand asset hashes,
- required unofficial/non-affiliation/trademark wording in README, NOTICE and
  `docs/legal.md`.

`scripts/check_validate.py` now runs this gate as `Legal/provenance audit`, so
it is part of the normal local and CI validation path before release.

`docs/release-validation.md` now lists the legal/provenance audit explicitly in
the release checklist.

## Commands Run

```text
.venv/bin/python scripts/check_legal_audit.py
.venv/bin/ruff check scripts/check_legal_audit.py scripts/check_validate.py scripts/check_repo.py
.venv/bin/python scripts/check_repo.py
.venv/bin/python -m pytest tests/test_privacy_security.py tests/test_release_package.py -q
make -C native_agent check
gh search code '"C300X_DOORBELL_CARD_TEMPLATE" NOT repo:<upstream>/ha-bticino-c300x' --limit 20 --json repository,path,url
gh search code '"c300x-native-agent-ipv4-firewall-v2-api-rtsp-talkback" NOT repo:<upstream>/ha-bticino-c300x' --limit 20 --json repository,path,url
gh search code '"async_ensure_doorstation_audio_gain" NOT repo:<upstream>/ha-bticino-c300x' --limit 20 --json repository,path,url
gh search code '"C300X_RING_PREVIEW_STATE" NOT repo:<upstream>/ha-bticino-c300x' --limit 20 --json repository,path,url
gh search code '"C300X_MAX_ACTIVATIONS" NOT repo:<upstream>/ha-bticino-c300x' --limit 20 --json repository,path,url
gh search code '"Legal/provenance audit passed" NOT repo:<upstream>/ha-bticino-c300x' --limit 20 --json repository,path,url
gh search code '"C300X_VIDEO_RING_PREVIEW_MAX_RTSP_CLIENTS" NOT repo:<upstream>/ha-bticino-c300x' --limit 20 --json repository,path,url
gh search code '"c300x-device-file-backups" NOT repo:<upstream>/ha-bticino-c300x' --limit 20 --json repository,path,url
gh search code '"bticino_c300x.run_ring_wyoming_analysis" NOT repo:<upstream>/ha-bticino-c300x' --limit 20 --json repository,path,url
.venv/bin/python scripts/build_hacs_release.py
.venv/bin/python scripts/write_release_assets.py --zip .release/ha-bticino-c300x.zip --tag v1.7.0 --repository <upstream>/ha-bticino-c300x --sha256sums .release/SHA256SUMS --metadata .release/build-metadata.json --sbom .release/sbom.spdx.json
unzip -t .release/ha-bticino-c300x.zip
cd .release && sha256sum -c SHA256SUMS
```

Results:

- `scripts/check_legal_audit.py`: passed.
- Ruff on changed validation scripts: passed.
- `scripts/check_repo.py`: passed.
- Privacy/security and release-package tests: 20 passed.
- Native-agent config check: passed.
- Completed public GitHub Code Search fingerprint queries: no external hits.
- New release zip build: passed.
- Release zip integrity test: passed.
- Release artifact SHA256SUMS: passed.

## Open Limits

The result is clean for the repository and freshly built local `1.7.0` release
artifact, within the stated technical scope.

Remaining limits:

- Public clone search covered exact fingerprint queries in public GitHub Code
  Search and general web search only. It cannot prove absence from private
  repositories, unpublished archives, or non-indexed sites.
- No jurisdiction-specific patent or trademark clearance was performed.
- No legal opinion was issued.
