#!/usr/bin/env python3
"""Check native media tools and event contracts inside the selected HA image."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def write(message: str) -> None:
    sys.stdout.write(f"{message}\n")
    sys.stdout.flush()


def run(*command: str) -> str:
    return subprocess.run(
        command, check=True, capture_output=True, text=True, timeout=30
    ).stdout


async def check_frames(directory: Path) -> None:
    from custom_components.bticino_c300x.ring_capture import (
        _async_extract_capture_frames,
    )

    for name, settings in (
        ("unknown", []),
        ("limited", ["-color_range", "tv", "-colorspace", "bt709",
                     "-color_primaries", "bt709", "-color_trc", "bt709"]),
        ("full", ["-vf", "scale=out_range=full", "-color_range", "pc"]),
    ):
        clip = directory / f"{name}.mp4"
        run("ffmpeg", "-v", "error", "-f", "lavfi", "-i",
            "testsrc2=size=400x288:rate=10:duration=3", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", *settings, str(clip))
        output = directory / name
        output.mkdir()
        await _async_extract_capture_frames(clip, output, duration_seconds=3)
        frames = list(output.glob("*.jpg"))
        if len(frames) != 3:
            raise RuntimeError(f"{name}: expected 3 JPEG frames, got {len(frames)}")
        for frame in frames:
            stream = json.loads(run(
                "ffprobe", "-v", "error", "-show_streams", "-of", "json", str(frame)
            ))["streams"][0]
            if (stream["width"], stream["height"], stream["color_range"]) != (400, 288, "pc"):
                raise RuntimeError(f"{name}: unexpected JPEG format: {stream}")
        write(f"{name}: 3 full-range JPEG frames")


def check_events() -> None:
    asyncio.run(_async_check_events())


async def _async_check_events() -> None:
    from homeassistant.helpers import translation

    from custom_components.bticino_c300x.agent_contracts import OutdoorUnit
    from custom_components.bticino_c300x.const import DOMAIN
    from custom_components.bticino_c300x.event import (
        C300XStationRingEventEntity,
        C300XUnitDoorbellEventEntity,
    )

    integration = ROOT / "custom_components" / DOMAIN
    metadata = SimpleNamespace(file_path=integration, has_translations=True, name="BTicino C300X")
    entry = SimpleNamespace(entry_id="container-test", title="C300X", data={}, options={},
                            runtime_data=SimpleNamespace(agent_info={}, capabilities={
                                "doorbell_events": True, "locks": True, "touch_tone": True,
                            }))
    unit = OutdoorUnit(id="21", where="21", action_where="21", lock_where="21",
                       name="Front gate", source="config", default=True)
    for language in ("en", "de", "fr", "it"):
        hass = Mock(
            spec=["data", "config", "async_add_executor_job"],
            data={}, config=SimpleNamespace(language=language, top_level_components={DOMAIN}),
            async_add_executor_job=asyncio.to_thread,
        )
        # Replace discovery only: HA reads the catalogs and builds its real cache.
        with patch.object(translation, "async_get_integrations",
                          AsyncMock(return_value={DOMAIN: metadata})):
            await translation.async_get_translations(hass, language, "entity", {DOMAIN})
        catalog = json.loads((integration / "translations" / f"{language}.json").read_text())
        # The station rings at once; the unit rings once the caller is known.
        for index, (entity, key) in enumerate((
            (C300XStationRingEventEntity(entry), "doorbell_pressed"),
            (C300XUnitDoorbellEventEntity(entry, unit), "call_caller_identified"),
        )):
            cls, expected = type(entity), "ring"
            entity.hass = hass
            if expected not in entity.event_types:
                raise RuntimeError(f"{cls.__name__}: event type {expected} not advertised")
            payload = {"entry_id": entry.entry_id, "event_key": key, "call_id": f"boot-{index}",
                       "unit_id": None if index == 0 else unit.id,
                       # call_sync names the unit that rings.
                       "ring_unit_id": None if index == 0 else unit.id,
                       "event_type": "Display label", "event_at": f"2026-01-01T00:00:0{index}Z"}
            # Only state publication is replaced; HA's event processing stays real.
            with patch.object(entity, "async_write_ha_state"):
                entity._agent_event(SimpleNamespace(data=payload))
            if entity.state_attributes["event_type"] != expected:
                raise RuntimeError(f"{cls.__name__}: technical event type overwritten")
            if entity.state_attributes.get("call_id") != payload["call_id"]:
                raise RuntimeError(f"{cls.__name__}: call id lost")
            label = translation.async_translate_state_attr(
                hass, entity.state_attributes["event_type"], "event", DOMAIN,
                entity.translation_key, entity.device_class, "event_type",
            )
            if not label or label == expected:
                raise RuntimeError(f"{language}/{entity.translation_key}: event type {expected} not translated")
            catalog_label = catalog["entity"]["event"][entity.translation_key][
                "state_attributes"]["event_type"]["state"][expected]
            if label != catalog_label:
                raise RuntimeError(f"{language}/{entity.translation_key}: wrong event translation {label!r}")
            write(f"{language}/{cls.__name__}: event_type={expected}, label={label}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expect-ha", required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    from homeassistant.const import __version__

    if __version__ != args.expect_ha:
        raise RuntimeError(f"Expected HA {args.expect_ha}, running {__version__}")
    write(f"Home Assistant {__version__}")
    write(run("ffmpeg", "-version"))
    check_events()
    with tempfile.TemporaryDirectory(prefix="c300x-container-test-") as temporary:
        asyncio.run(check_frames(Path(temporary)))
        from scripts.check_capture_startup import async_check_capture_startup

        asyncio.run(async_check_capture_startup(Path(temporary) / "late-headers"))
        write("Late H.264 headers: MP4 and 3 full-range JPEG frames")
    write("HA container runtime checks passed")


if __name__ == "__main__":
    main()
