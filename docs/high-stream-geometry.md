# High-Stream Geometry Investigation

Status on 2026-11-22: the final direct two-instruction test produced a real
960x576 High stream, and the user confirmed correct visible geometry.
This is bounded live-test evidence, not release approval or proof of error-free
decoding. Native integration and its rollback review remain separate work.

## Original Firmware

The tested C300X runs firmware 1.7.19. Its `bt_av_media` SHA-256 matches the
offline original:
`97b61ad80e67c1b3ea494956568645b93c7fe3ef359f77af9c7e2ad6dff1bf9e`.

The `advanced_iu` pipeline starts with UYVY 720x576 at 25 fps. Its crop removes
eight columns from each side, leaving 704x576. The LCD window is 800x480 and
uses `force-aspect-ratio=false`. Display geometry therefore does not establish
the transmitted stream's pixel aspect ratio.

Two High caps filters constrain the width, including the filter after frame
rate conversion. Changing only one produces incompatible negotiation at the
configured 24 fps. The IPU feeds a shared tee: a change to this negotiated
size also affects the inputs to LCD, Low, recording and optional raw-output
branches. It is not an isolated encoder setting.

The proposed 960x576 raster retains all 576 rows and matches the LCD's 5:3
shape. It horizontally upscales the cropped source; it adds no camera detail
and does not by itself prove the optically correct aspect ratio.

## What Passed

- Original ARM GStreamer libraries under QEMU link a reconstructed graph with
  both High caps filters set to 960x576. The single-filter change fails as
  expected. These are NULL-state checks, not hardware execution.
- Original IPU fixation code chooses PAR 3/4 when the output PAR is omitted.
  Explicit PAR 1/1 is therefore required for this proposed square-pixel output.
- A separate, bounded device pipeline accepted twelve synthetic I420 buffers
  at 704x576, scaled them through `imxipuvideotransform`, and encoded them using
  the original `imxvpuenc_h264`. Output was captured on the development host.
- The result contains twelve H.264 frames at 960x576. Rechecking the entire
  capture using FFmpeg with `-xerror` completes without decoding errors.

This synthetic pipeline used neither the camera source nor the manufacturer's
High control flow. Its input was configured for six frames per second, but the
raw H.264 output does not provide usable timing metadata: FFprobe reports
`1200000/1`. No achieved-frame-rate or 24-fps performance claim follows from it.
There is also no encoded pixel-aspect-ratio field in that capture. No optical,
letterboxing, concurrent-branch or teardown conclusion follows from it.

### Visible Picture Check

A subsequent isolated device test used an existing camera preview cached in
HA, not a newly activated camera stream. The host prepared a 704x576 JPEG;
twelve copies travelled over SSH stdin into `jpegdec`, the IPU transform and
the original VPU encoder. The H.264 output travelled back over stdout. No
image was saved on the device and no manufacturer service was restarted.

All twelve output frames decoded without error at 960x576. Visual inspection
shows the supplied camera scene rather than a blank buffer. Noise is already
present in the source preview. Boot ID, original media PID and executable hash
were unchanged, and the media bridge remained idle afterward.

This proves visible picture processing at the candidate output size. It is a
still-picture laboratory test involving JPEG decoding, not the requested
production media path and not a proposal to transcode camera video. The source
preview had already been resized by HA, so this test cannot establish optical
aspect ratio, source detail, live camera negotiation or frame-rate performance.

## Earlier Wrapper/Preload Trial: Failed

A temporary RAM-only wrapper and a hash-pinned preload library were prepared
to change only the two original High caps construction sites. Offline tests
covered the original variadic ABI, unaffected calls, guard mismatches and
removal of preload inheritance across exec. Firmware files on flash and device
configuration were not replaced.

The test armed an independent recovery process before binding the wrapper.
It then requested a restart through the original application supervisor rather
than launching an unowned replacement media process. The expected media
process did not become available. SSH subsequently refused connections, so
the host could not perform its normal unmount/restart rollback.

**This wrapper/preload trial activated no camera stream and captured no live
High frames.**
The device subsequently rebooted. The available evidence does not identify
whether the reboot came from the manufacturer watchdog, the armed recovery
process or another part of the shutdown path. It also does not establish that
the preload library was reached. Do not attribute this failure to 960x576
negotiation or treat it as a successful media test.

After recovery, direct checks confirmed:

- A new boot ID and no remaining experimental directory or bind mount.
- The original executable path, hash and manufacturer process ownership.
- No experimental library in the media process mappings.
- Unchanged `bt_answering_machine` and `stack_open.xml` hashes.
- A read-only root filesystem and an idle media bridge.
- A subsequent 180-second observation with unchanged boot ID and media PID.

## Final Direct Two-Instruction Trial: Live Picture Confirmed

The later successful trial used a direct change to two instructions in the
original `bt_av_media` binary, not the failed wrapper/preload mechanism.
At file offsets **`0x14a24`** and **`0x14de4`**, the original instructions copy
the crop-getter result into the width arguments for the two High caps sites.
The replacements load **960** with `mov` instead. These offsets are instruction
sites, **not original literal-width values**. The change does not add a frontend
crop, browser transcoder or JPEG-to-video workaround.

The recorded live evidence is:

- `simple-high.mkv`: **960x576**, reported **24 fps**, **121 frames** in an
  approximately **six-second** capture.
- The native display framebuffer remained **800x480**. Both rasters have a
  **5:3** aspect ratio; the user confirmed the live picture's geometry was
  correct.
- A subsequent **180-second idle observation** retained the same boot ID and
  media PID.

The clip has an **initial-GOP decode error**, also observed in the reference
capture. FFmpeg with `-xerror` failed when decoding the whole clip; extracting
a frame with `-ss 2` succeeded. The user confirmation and successful later
frame establish visible live output, **not an error-free whole capture**.
The short capture and its reported frame rate are not a sustained throughput
benchmark. The error's presence in the reference does not establish its cause
or make it safe to ignore.

### Final Stock Restoration

After the direct trial, the device was restored and verified against the
original executable SHA-256:
`97b61ad80e67c1b3ea494956568645b93c7fe3ef359f77af9c7e2ad6dff1bf9e`.

The final verification recorded boot ID
`f5fd1503-542a-44d6-9bc3-022f63850d71`, unchanged configuration hashes, a read-only
root filesystem, and the running media PID's executable matching the original.
No experimental hooks remained. This stock-restoration verification is separate
from the same-boot/same-PID idle observation during the successful trial.

## Firmware 2.0.2: Read-Only Offline Comparison

The comparison used the original extracted firmware trees
`c300x-fwpatch/work/rootfs-1.7.19` and `rootfs-2.0.2`. Originals were read only;
candidate hashes were calculated from modified buffers in host memory. No
firmware binaries or copied vendor instruction listings are included here.
This evidence is separate from the **1.7.19** live trial above: no 2.0.2 device,
camera stream, GUI or encoder was exercised.

### Exact Image Identity

Both original media programs are 186932-byte ARM hard-float ELF executables.
Their only differences are the 20 GNU build-ID descriptor bytes at file offsets
`0x1a0` through `0x1b3` (the first differing byte is position 417, counted from
one). Every other byte, including code, data, imports and relocations, matches.

| Firmware | Image | SHA-256 |
| --- | --- | --- |
| 1.7.19 | Original | `97b61ad80e67c1b3ea494956568645b93c7fe3ef359f77af9c7e2ad6dff1bf9e` |
| 1.7.19 | Two-site 960 candidate | `baac8d478db5c4ae1baa46da963b379941d2952cfe047f3030b6a3182579821c` |
| 2.0.2 | Original | `e08227abb4bbc8ec47cdb6a2cf875c1b32c70ad0a295482b5ee7d73672b7479b` |
| 2.0.2 | Two-site 960 candidate | `b8b278f801284f8e573700554054e886e5ab256c08f09a609c15bdff2bb73e1d` |

The original build IDs are `f16f21bbb7070232b9b4f981e0b804b34403a375`
(1.7.19) and `0e73809bcb1b2c4c6afbccb10dacbdd20f859c8b` (2.0.2).
Build IDs remain part of each whole-file identity; this comparison does **not**
justify ignoring them, accepting unknown hashes or restoring another firmware's
backup. The two exact original/candidate pairs must remain separately bound.

### Caps and Control Flow

Whole-image comparison and ARM disassembly establish the same two instruction
sites in both originals, not merely coincident offsets:

- File offset `0x14a24` (virtual address `0x24a24`): the replacement loads 960
  into `r7`. That register supplies the width argument to caps construction at
  `0x24a90`; height still comes from the crop-height getter and this caps stage
  retains 25 fps. The caps filter is stored at object offset `0x2a4`.
- File offset `0x14de4` (virtual address `0x24de4`): the replacement loads 960
  into `r5`. This width reaches caps construction at `0x24e54`, alongside the
  crop height and configured High frame rate in `r9`. The second filter is at
  object offset `0x2cc`.
- Frame rates 0 and 25 select the direct path at `0x26fe4`: the first caps
  filter feeds the High encoder. Other frame rates select the path at
  `0x259e8` through `vrate_high`, the second caps filter and the same encoder.
  Both width sites therefore need the replacement.
- The aspect branch at `0x24490` selects these sites only when configured
  width exceeds 1.5 times height. The other branch retains its fixed 720x576
  caps. LCD window-width/window-height assignments and crop-meta assignments
  remain unchanged. Keep the LCD configuration at **800x480**, not 960x576.

### Configuration and Library Provenance

The original answering-machine configuration is byte-identical between the
trees, SHA-256
`8bcf48382aab203a86888522e1a735e5ecd858bd0a8934136ab1cb71f687e53d`:
Width/Height 800/480, BitrateRtpH/FpsRtpH 800/15 and Low dimensions 400/288,
bitrate 180, frame rate 10. The separate answering-machine **executable** is
not byte-identical; the relevant High/Low configuration key strings exist in
both, which is not proof that its entire implementation is unchanged.

`stack_open.xml` is also byte-identical, SHA-256
`21d964df2ff5392ed9643face0dfdad36b329443f10f2970b86cbae0e68c4d74`.
Its original crop is left/top/width/height **16/48/688/480**. The geometry
candidate requires **8/0/704/576**; do not mistake the candidate crop described
above for the original configuration in these extracted firmware trees.

All 24 direct ELF dependencies resolve inside each firmware tree; 23 are
byte-identical. All 235 strong undefined symbols, including versioned imports,
resolve against their direct dependency exports in this static comparison.
The differing library is `liblghal.so.0.0`: its crop-check and crop-set routines
retain the five-integer calling contract, control flow and ioctl request types
(`0xc02c563a`, `0x4014563c`, readback `0xc014563b`). Their entry addresses move
from `0x9fc0`/`0xa19c` to `0x9fd0`/`0xa1ac`; relocation and literal references
differ. Neither the complete HAL nor those function bytes are claimed identical.

The original GStreamer IPU, VPU, V4L2, videorate, crop, scale, convert and core
plugins are byte-identical, as are the GStreamer video/i.MX helper libraries,
`libimxvpuapi` and `libvpu.so.4`. This supports the same static media-path
interpretation. It is **not** a new-agent ABI build, runtime negotiation test,
hardware encoder result or proof of unaffected concurrent branches on 2.0.2.

## Remaining Gates

The real-camera geometry trial is now complete; the earlier shim failure must
not be presented as the outcome of the direct two-instruction test. Conversely,
the direct test does not validate the failed shim's lifecycle or justify
shipping that wrapper/preload mechanism.

The native patch still needs integrated version/hash guards, failure and
rollback regression coverage, and release/package validation. Concurrent Low,
LCD and recording branch behavior, sustained operation, and HA WebRTC,
snapshot and card end-to-end behavior require their own checks. Existing
custom snapshot dimensions must remain unchanged. Neither the successful live
trial nor the final stock restoration is a release or deployment approval.
