#!/usr/bin/env python3
"""Require a real TurboJPEG 3 load and JPEG roundtrip in the validation Python."""

from __future__ import annotations

import argparse
import ctypes
import sys
from pathlib import Path


def check(expected: Path | None = None) -> Path:
    import numpy as np
    from turbojpeg import TJPF_RGB, TJSAMP_444, TurboJPEG

    # Use the same default resolution as HA, never an explicit library override.
    jpeg = TurboJPEG()
    if not hasattr(ctypes.CDLL("libturbojpeg.so.0"), "tj3Init"):
        raise RuntimeError("TurboJPEG 3 API is unavailable")
    loaded = {
        Path(fields[5]).resolve()
        for line in Path("/proc/self/maps").read_text(encoding="utf-8").splitlines()
        if len(fields := line.split(maxsplit=5)) == 6
        and Path(fields[5]).name.startswith("libturbojpeg.so")
    }
    if len(loaded) != 1:
        raise RuntimeError(f"Expected one loaded TurboJPEG library, found {loaded}")
    library = loaded.pop()
    if expected is not None and library != expected.resolve():
        raise RuntimeError(f"Loaded {library}, expected {expected}")
    pixels = np.full((16, 16, 3), (32, 128, 224), dtype=np.uint8)
    encoded = jpeg.encode(pixels, quality=95, pixel_format=TJPF_RGB, jpeg_subsample=TJSAMP_444)
    decoded = jpeg.decode(encoded, pixel_format=TJPF_RGB)
    if not encoded.startswith(b"\xff\xd8") or decoded.shape != pixels.shape:
        raise RuntimeError("TurboJPEG JPEG roundtrip produced an invalid image")
    if np.max(np.abs(decoded.astype(np.int16) - pixels.astype(np.int16))) > 3:
        raise RuntimeError("TurboJPEG JPEG roundtrip pixel error exceeds tolerance")

    from homeassistant.components.camera.img_util import TurboJPEGSingleton

    if not isinstance(TurboJPEGSingleton.instance(), TurboJPEG):
        raise RuntimeError("Home Assistant camera fell back from TurboJPEG")
    return library


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-library", type=Path)
    args = parser.parse_args()
    try:
        library = check(args.expect_library)
    except Exception as error:
        sys.stderr.write(f"FAIL: TurboJPEG load/roundtrip: {error}\nRun scripts/setup_turbojpeg.py and export its loader path before validation.\n")
        return 1
    sys.stdout.write(f"TurboJPEG 3 JPEG roundtrip and HA camera load passed: {library}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
