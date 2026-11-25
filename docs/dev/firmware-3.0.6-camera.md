# Firmware 3.0.6 Low Camera Evidence

Local beta review, 2026-11-22. Original firmware is a read-only private input;
no firmware bytes or vendor files are included in this repository or package.
No device, Home Assistant instance, remote branch or release was changed.

## Stable Port

Compared stable 2.8.2 through `4abc5ce1` and lint-only `9f36b271` with beta
base `562b02b5`, using patch identity plus source review for adapted commits:

| Stable | Beta disposition |
| --- | --- |
| `17c5aee3` shutdown wakeup | Exact patch-equivalent `20456010` already present |
| `9732cab5` routing identity | Adapted in `fcca4a51`; retains 3.0.6 routing restore |
| `c5a1e988` pinned CI evidence | Adapted in `244e988c`; preserves beta-first prerelease policy |
| `cc4ec121` camera menu order | Adapted in `6bac29ff` |
| `f5c440d8`, `e6baa5ad` geometry evidence | Historical older-firmware evidence retained, not 3.0.6 proof |
| `6d0743d4` snapshot/card | Ported; explicit snapshot sizes and measured media ratios preserved |
| `d0bc10be` removal safety | Ported with beta routing and Qt5 recovery kept |
| `5a5c4c87` camera lifecycle | Ported; atomic transactions, process-generation status, note persistence guard |
| `a160528e` docs/translations | Ported while retaining beta identity and Qt5 architecture |
| `ff38b7a0`, `4abc5ce1` stable build locks | Not copied; beta executable/lock rebuilt for its own inputs |
| `9f36b271` MQTT import / strict zip lint | Already equivalent in beta |
| `06f7396f` removal structural tests | Ported; guarded stop remains before restoration |

## Original Pipeline

Private root: `c300x-fwpatch/work/rootfs-3.0.6`.

- `home/bticino/bin/bt_av_media` SHA-256:
  `39816d1e8d0cd40a39d389d683d541d71e71c216c688dac63e9a111c02081e4b`.
  This is a different ARM Thumb/GStreamer 1.0 executable. The older ARM patch
  offsets and stock/patched hashes are not a 3.0.6 patch specification.
- Factory answering-machine configuration: Width/Height 800x480,
  WidthLow/HeightLow 400x288, Low 180 kbit/s at 10 fps. The stack crop is
  688x480; Low dimensions are separate parameters, not crop getter results.
- Thumb `0x18f0c` / `0x18f68` store parsed Low width/height at object
  `+0x4c` / `+0x50`. The caller at `0x191d2..0x19204` copies these into
  entry-stack `+48` / `+52` for the pipeline's virtual method.
- Pipeline entry `0xdc2c`; `0xdc62..0xdc70` preserve those dimensions at
  local-stack `+0x64` / `+0x68`. The Low branch creates
  `imxipuvideotransform` (`filter_rtp`), `videorate` (`vrate_low`),
  `vpuenc_h264` (`h264-enc-2`), RTP payloader and `multiudp_low_res`.
- Caps creation at `0xed28` takes those Low dimensions directly as
  `video/x-raw`, format `I420`. Earlier caps at `0xecc2` take the separate
  main dimensions. LCD `window-width` / `window-height` at `0xe58a` /
  `0xe5ac` take main Width/Height, not the Low values.
- Original `libgstvpu.so` SHA-256:
  `56b5acf666de668f3babc32af0f6fbce8731d5586aab58e2eb0abdffdce53692`.
  Its raw encoder caps include I420, width 64..1920 and height 64..1088
  in steps of eight. These advertised caps alone are not hardware proof.

`tests/test_fw306_low_caps_firmware.py` executes the original caps-building
instructions with Unicorn and intercepts every GStreamer call. It verifies
factory 400x288 and added 320x240, 480x288, 640x384, 720x432 reach separate Low caps,
while main caps remain 800x480. It never starts a pipeline or accesses hardware.
The optional test requires Unicorn and the private original firmware; without
them it skips explicitly. Disassemble this executable with
`arm-linux-gnueabihf-objdump -d -M force-thumb`, not default ARM decoding.

## Bounded Choices and Limits

Keep factory 400x288 and existing 352x288, 640x480, 704x576, 720x576.
Add only 320x240 (compact 4:3), 480x288, 640x384 and 720x432 (LCD ratio 5:3).
Every choice stays at or below the 720x576 input and is aligned to sixteen
pixels. Do not expose arbitrary caps ranges, upscale to 800x480, or offer
960x576 on Low. Existing bitrate 100..2000 and fps 5..25 limits are unchanged.

The configuration path already supplies dimensions; a binary patch is not
needed for these Low options. No 3.0.6 geometry patch was added. High patch
support remains restricted to exact older firmware identities and the High
path. No C100X detection or offsets were imported.

Non-factory Low negotiation, encoder throughput, actual visual framing,
Door Entry compatibility and stability remain **unproven on hardware**.
Matching the raster ratio alone does not prove correct scene proportions.
The LCD remains 800x480; snapshots preserve it by default, but existing custom
snapshot sizes remain untouched. The card follows actual image/video metadata,
without frontend transcoding, cropping or forcing a different aspect ratio.

## Verification

Focused verification only; no full gate or device test. Groups overlap and
must not be added together as a unique-test total.

- Camera quality, geometry, commit/rollback, update lock, removal safety and
  new Low-option regressions: **294 passed** on the final source.
- Caps emulation, Low options, quality, touch, maintenance auth, geometry
  patch and patch-target-name checks: **308 passed, 1 optional skip**.
  The skipped original Qt4 touch-library test was rerun with
  `C300X_QT4_ROOTFS` pointing to 1.7.19 and passed. Both original-glibc ARM/QEMU
  geometry lifecycle cases also passed separately.
- Original display artifacts, QML patch round-trip, RCC loading, Qt5 recovery,
  wrapper lifecycle/identity, beta update/downgrade guards and Low regressions:
  **206 passed**. Original QtQml compile check separately: **1 passed**,
  Qt **5.15.7**, all **15** delivered components, zero compile failures.
  Use `--basetemp=/var/tmp/...`: the original root's `/tmp -> /var/tmp`
  symlink affects QEMU/Qt path canonicalization. The initial `/tmp` run failed
  module discovery; no source change was needed for the `/var/tmp` rerun.
  Vendor C++ types remain explicit substitutes, not hardware proof.
- API/config/snapshot contracts, translations, camera options, validation
  evidence, dependency checks and release binding: **698 passed**.
- Release-package/binding and final translations: **97 passed**.
- Picture-frame/snapshot frontend unit tests: **17 passed**. Browser smoke:
  matching 5:3 snapshot/live/stopped pictures at widths **240, 320, 390, 1024**,
  inline and expanded, with rendered edge-pixel checks; wrapped text,
  responsive buttons, actions, RTC cycles and cleanup passed. Screenshots
  remain local under `.artifacts/browser/`; desktop/mobile examples inspected.
- Ruff on changed Python files and the unchanged legal/provenance checker
  passed. Both technical firmware documents now live under `docs/dev/`;
  `docs/dev/audits/` retains only `current-legal-provenance.md`.
- ARM agent and embedded Qt5 overlay built against original 1.7.19 libraries;
  ABI checks passed against **both 1.7.19 and 3.0.6**. The reviewed beta lock
  records agent version **2.9.0b1** and executable SHA-256
  `087c8bdfbb45513213385659685242aeab5ca56ecb47b67d32c6abd22dcab538`.
- Local candidate `.release/ha-bticino-c300x.zip` passed
  `check_release_contents.py --agent-binary ... --build-lock ...`.
  SBOM, checksums and metadata are generated locally after the source commit;
  no canonical CI success, publication or device readiness is claimed.

The historical package hashes in the separate display audit describe its
earlier checkpoint, not this rebuilt camera/maintenance candidate.

## Local 2.9.0b2 Preparation

The camera review reported no remaining findings. Stable was rechecked at
`06f7396f`; that final local source is already included by the port. If stable
changes again before publication, recompare its final published source before
advancing this candidate. Beta-specific code never goes back into stable.

The integration and native agent are bumped together to **2.9.0b2**, with a
fresh build against 1.7.19 and passing ABI checks against 1.7.19 and 3.0.6.
Its executable SHA-256 is
`eeda7bc0d723a808fd7fc3691a33c6d21d6004b913c5a97c1fa11b0ca3c807d4`.
The earlier 2.9.0b1 hash above remains a historical port checkpoint.

The existing beta-first prerelease/main-only stable evidence policy required
no production change. Additional b2 tag, channel, source-SHA and non-push
rejection coverage passed with the focused release suites: **328 passed**.
The final candidate still requires independent release-policy review and all
full gates before PR. No push, tag, transport draft or publication is authorized
until stable 2.8.2 publication and the outstanding gates are complete. Local
metadata continues to report `local-unverified`.
