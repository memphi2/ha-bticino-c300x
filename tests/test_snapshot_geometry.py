"""Snapshot defaults and pixel geometry, without a device or frontend runtime."""

import asyncio
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image, ImageDraw
from test_stream_snapshot_capture import drain
from test_stream_snapshot_http import Request, setup

from custom_components.bticino_c300x import snapshot_capture as capture
from custom_components.bticino_c300x.config_flow_snapshot import snapshot_step
from custom_components.bticino_c300x.config_schemas import snapshot_schema
from custom_components.bticino_c300x.config_snapshots import (
    SNAPSHOT_DEFAULTS,
    SnapshotOptions,
    snapshot_options,
    snapshot_values,
)


@pytest.mark.parametrize("size", [None, (688, 480), (400, 240), (400, 288)])
@pytest.mark.parametrize("storage", ["data", "options"])
def test_defaults_and_saved_dimensions_are_consistent_without_migration(size, storage):
    stored = {} if size is None else {"snapshot_width": size[0], "snapshot_height": size[1]}
    entry = SimpleNamespace(data={}, options={})
    setattr(entry, storage, stored.copy())
    expected = size or (800, 480)
    assert SnapshotOptions().size == (800, 480)
    assert snapshot_options(entry).size == expected
    current = snapshot_values({**entry.data, **entry.options})
    assert snapshot_schema(current)({}) == current
    saved, form = snapshot_step(lambda **kwargs: kwargs, "visitor_snapshot", current, None)
    assert saved is None
    rendered = form["data_schema"]({})
    assert (rendered["snapshot_width"], rendered["snapshot_height"]) == expected
    saved, form = snapshot_step(lambda **kwargs: kwargs, "visitor_snapshot", current, rendered)
    assert form is None
    assert saved == current
    assert getattr(entry, storage) == stored
    assert snapshot_schema()({}) == SNAPSHOT_DEFAULTS


def test_explicit_options_override_initial_size_without_mutation():
    entry = SimpleNamespace(
        data={"snapshot_width": 688, "snapshot_height": 480},
        options={"snapshot_width": 400, "snapshot_height": 240},
    )
    assert snapshot_options(entry).size == (400, 240)
    assert entry.data == {"snapshot_width": 688, "snapshot_height": 480}
    assert entry.options == {"snapshot_width": 400, "snapshot_height": 240}


@pytest.mark.parametrize("size", [None, (688, 480), (400, 240), (400, 288)])
def test_capture_storage_and_http_preserve_dimensions_and_all_frame_edges(
    tmp_path, monkeypatch, size,
):
    async def run():
        manager, _, view = setup(tmp_path, monkeypatch)
        manager.entry.data["video_enabled"] = True
        manager.entry.options["snapshot_timestamp"] = False
        if size is not None:
            manager.entry.options.update(snapshot_width=size[0], snapshot_height=size[1])
        expected = size or (800, 480)
        # Distinct edge markers detect cropping, rotation or an extra resize.
        frame = Image.new("RGB", expected, "white")
        draw = ImageDraw.Draw(frame)
        width, height = expected
        markers = [
            ((0, 0, 23, 23), (255, 0, 0), (3, 3)),
            ((width - 24, 0, width - 1, 23), (0, 255, 0), (width - 4, 3)),
            ((0, height - 24, 23, height - 1), (0, 0, 255), (3, height - 4)),
            ((width - 24, height - 24, width - 1, height - 1), (0, 0, 0),
             (width - 4, height - 4)),
        ]
        for box, color, _point in markers:
            draw.rectangle(box, fill=color)
        content = BytesIO()
        frame.save(content, format="BMP")
        api = SimpleNamespace(async_doorbell_snapshot=AsyncMock(
            return_value=(content.getvalue(), "image/bmp"),
        ))
        manager.entry.runtime_data = SimpleNamespace(
            api=api, capabilities={"doorbell_video": {"supported": True}},
        )
        monkeypatch.setattr(capture, "snapshot_options", lambda entry: replace(
            snapshot_options(entry), delay_seconds=0,
        ))
        manager.capture_requested("geometry")
        await drain(manager)
        api.async_doorbell_snapshot.assert_awaited_once_with(*expected)
        assert manager.latest is not None
        image_id = manager.latest.name
        saved = manager.image
        assert manager.store.read(image_id, 14) == saved
        for identifier in ("latest", image_id):
            response = await view.get(Request(manager), "one", identifier)
            assert response.body == saved
            with Image.open(BytesIO(response.body)) as image:
                assert image.size == expected
                for _box, color, point in markers:
                    assert all(abs(a - b) < 12 for a, b in zip(image.getpixel(point), color, strict=True))
        # Exercise the archive disk-read branch as well as both cached branches.
        manager.image = None
        assert (await view.get(Request(manager), "one", image_id)).body == saved
        manager.close()

    asyncio.run(run())
