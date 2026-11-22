# High-Stream Geometry Investigation

Status on 2026-11-22: experimental, not supported or included in a release.
The real camera High path at 960x576 has **not** been validated.

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

## Actual Application Trial

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

**No camera stream was activated and no live High frames were captured.**
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

## Remaining Gate

First establish a safe activation lifecycle from the exact manufacturer code;
repeating the failed application-group restart is not an acceptable next test.
Only then can a bounded real camera trial establish negotiated geometry,
24-fps operation, visual comparison with the LCD, concurrent branch behavior
and clean teardown. HA WebRTC, snapshots and recordings require their own
end-to-end checks. No experimental wrapper, preload library or firmware binary
modification belongs in the agent package on the evidence available so far.
