"""Camera and image entities as picture tiles, scaled down by Home Assistant."""

import asyncio
import io
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from aiohttp import web
from homeassistant.core import State
from PIL import Image

from custom_components.bticino_c300x import dashboard_images
from custom_components.bticino_c300x.dashboard import async_dashboard_payload
from custom_components.bticino_c300x.dashboard_entities import (
    ALARM_PAGE_ENTITY_DOMAINS,
    normalize_dashboard_entity_ids,
)
from custom_components.bticino_c300x.dashboard_images import (
    C300XTileImageView,
    image_tile_base_url,
    scaled_jpeg,
)

BASE = "http://192.168.1.10:8123"


def _environment(states, *, base=BASE, overrides=None, entities=None):
    entities = entities or [state.entity_id for state in states]
    by_id = {state.entity_id: state for state in states}
    entry = SimpleNamespace(
        entry_id="entry", domain="bticino_c300x",
        data={"shared_secret": "s3cret"},
        options={
            "device_ui_enabled": True,
            "dashboard_entities": entities,
            "dashboard_entity_display_overrides": overrides or {},
        },
        runtime_data=SimpleNamespace(display_image_base_url=base),
    )
    hass = SimpleNamespace(
        data={}, config=SimpleNamespace(language="en", units=SimpleNamespace(temperature_unit="C")),
        states=SimpleNamespace(get=by_id.get),
        config_entries=SimpleNamespace(async_get_entry=lambda entry_id: entry if entry_id == "entry" else None),
        async_add_executor_job=lambda func, *args: asyncio.get_running_loop().run_in_executor(None, func, *args),
    )
    return hass, entry


def _items(hass, entry):
    payload = asyncio.run(async_dashboard_payload(hass, entry))
    return [item for page in payload["data"]["pages"] for item in page.get("items", [])]


def _camera(token="tok-1"):
    return State("camera.door", "idle", {"friendly_name": "Front door", "access_token": token})


def test_camera_and_image_entities_can_be_picked_for_a_page_but_not_for_the_alarm_page():
    assert normalize_dashboard_entity_ids(["camera.door", "image.map"], strict=True) == ("camera.door", "image.map")
    assert not {"camera", "image"} & set(ALARM_PAGE_ENTITY_DOMAINS)


def test_a_camera_is_a_picture_tile_that_loads_a_scaled_image_from_home_assistant():
    hass, entry = _environment([_camera()])
    (item,) = [item for item in _items(hass, entry) if item.get("kind") == "image"]
    url = urlsplit(item["source"])
    query = parse_qs(url.query)
    assert f"{url.scheme}://{url.netloc}" == BASE
    assert url.path == "/api/bticino_c300x/tile_image/entry/camera.door"
    assert set(query) == {"w", "h", "rev", "sig"}
    assert (item["width"], item["height"], query["w"], query["h"]) == (728, 200, ["728"], ["200"])
    assert item["name"] == "Front door"
    # Nothing but the address tells the display that a new picture exists.
    assert "access_token" not in item["source"] and "tok-1" not in item["source"]


def test_the_address_changes_when_the_picture_does():
    def source(states):
        hass, entry = _environment(states)
        return next(item["source"] for item in _items(hass, entry) if item.get("kind") == "image")

    assert source([_camera("tok-1")]) == source([_camera("tok-1")])
    assert source([_camera("tok-1")]) != source([_camera("tok-2")])
    first = State("image.map", "2026-11-20T08:00:00+00:00")
    second = State("image.map", "2026-11-20T08:05:00+00:00")
    assert source([first]) != source([second])


@pytest.mark.parametrize(("height", "pixels"), [("half", 120), ("full", 290), (None, 200)])
def test_the_tile_height_setting_sets_the_picture_height(height, pixels):
    overrides = {"camera.door": {"height": height}} if height else {}
    hass, entry = _environment([_camera()], overrides=overrides)
    item = next(item for item in _items(hass, entry) if item.get("kind") == "image")
    assert item["height"] == pixels and f"h={pixels}" in item["source"]


def test_two_pictures_fit_side_by_side_with_the_half_width_setting():
    states = [_camera(), State("camera.garden", "idle", {"access_token": "g"})]
    overrides = {"camera.door": {"width": "half"}, "camera.garden": {"width": "half", "height": "half"}}
    hass, entry = _environment(states, overrides=overrides)
    door, garden = [item for item in _items(hass, entry) if item.get("kind") == "image"]
    assert (door["width"], door["height"], door["tile_width"]) == (359, 200, "half")
    assert (garden["width"], garden["height"]) == (359, 120)
    assert "w=359" in door["source"]
    # The display lays a picture tile out at half width only when told to;
    # pictures of configured actions keep the full width.
    qml = (Path(__file__).resolve().parents[1] / "device_qml" / "HomeAssistant.qml").read_text(encoding="utf-8")
    assert '(isWeather || (isImage && sizeW !== "half") || isChoice || isSlider ? itemColumn.width' in qml
    assert "property int tileWidth: (width - spacing) / 2" in qml and (728 - 10) // 2 == 359


def test_without_a_known_address_the_tile_is_left_out():
    hass, entry = _environment([_camera()], base="")
    assert not [item for item in _items(hass, entry) if item.get("kind") == "image"]
    assert image_tile_base_url("http://192.168.1.10:8123/api/webhook/abc") == BASE
    assert image_tile_base_url("") == ""
    assert image_tile_base_url("ftp://host/x") == ""


def _jpeg(width, height, mode="RGB"):
    buffer = io.BytesIO()
    Image.new(mode, (width, height), "navy").save(buffer, "PNG" if mode != "RGB" else "JPEG")
    return buffer.getvalue()


def test_pictures_are_scaled_to_fit_the_tile_and_kept_small():
    for source in (_jpeg(1920, 1080), _jpeg(400, 2000), _jpeg(1920, 1080, "RGBA"), _jpeg(1920, 1080, "P")):
        result = scaled_jpeg(source, 728, 200)
        with Image.open(io.BytesIO(result)) as image:
            assert image.format == "JPEG" and image.mode == "RGB"
            assert image.width <= 728 and image.height <= 200
            assert image.width == 728 or image.height == 200
    small = scaled_jpeg(_jpeg(100, 50), 728, 200)
    with Image.open(io.BytesIO(small)) as image:
        assert image.size == (100, 50), "a small picture is not blown up"
    with pytest.raises(ValueError):
        scaled_jpeg(b"not a picture", 728, 200)


def _request(hass, source, **changes):
    url = urlsplit(source)
    query = {key: values[0] for key, values in parse_qs(url.query).items()}
    query.update(changes)
    query = {key: value for key, value in query.items() if value is not None}
    return SimpleNamespace(app={"hass": hass}, query=query), url.path.rsplit("/", 2)[1:]


def test_the_view_serves_only_signed_addresses_of_configured_picture_entities(monkeypatch):
    hass, entry = _environment([_camera(), State("camera.other", "idle", {"access_token": "x"})],
                               entities=["camera.door"])
    source = next(item["source"] for item in _items(hass, entry) if item.get("kind") == "image")
    fetched = []

    async def fetch(_hass, entity_id, width, height):
        fetched.append((entity_id, width, height))
        return _jpeg(1920, 1080)

    monkeypatch.setattr(dashboard_images, "_async_source_image", fetch)
    view = C300XTileImageView()

    request, (entry_id, entity_id) = _request(hass, source)
    response = asyncio.run(view.get(request, entry_id, entity_id))
    assert response.content_type == "image/jpeg" and response.headers["Cache-Control"] == "no-store"
    with Image.open(io.BytesIO(response.body)) as image:
        assert image.width <= 728 and image.height <= 200
    assert fetched == [("camera.door", 728, 200)]

    for changes, ids in (
        ({"sig": "0" * 32}, (entry_id, entity_id)),
        ({"sig": None}, (entry_id, entity_id)),
        ({"h": "4000"}, (entry_id, entity_id)),
        ({"w": "359"}, (entry_id, entity_id)),
        ({"w": "5000"}, (entry_id, entity_id)),
        ({"w": None}, (entry_id, entity_id)),
        ({}, (entry_id, "camera.other")),
        ({}, ("another", entity_id)),
        ({}, (entry_id, "light.kitchen")),
    ):
        request, _ = _request(hass, source, **changes)
        with pytest.raises(web.HTTPNotFound):
            asyncio.run(view.get(request, *ids))
    assert len(fetched) == 1, "a refused request never reads a camera"


def test_a_camera_that_fails_gives_an_error_instead_of_a_broken_picture(monkeypatch):
    hass, entry = _environment([_camera()])
    source = next(item["source"] for item in _items(hass, entry) if item.get("kind") == "image")

    async def fail(*_args):
        raise dashboard_images.TileImageUnavailable("camera off")

    monkeypatch.setattr(dashboard_images, "_async_source_image", fail)
    request, ids = _request(hass, source)
    with pytest.raises(web.HTTPServiceUnavailable):
        asyncio.run(C300XTileImageView().get(request, *ids))

    async def garbage(*_args):
        return b"<html>"

    monkeypatch.setattr(dashboard_images, "_async_source_image", garbage)
    with pytest.raises(web.HTTPServiceUnavailable):
        asyncio.run(C300XTileImageView().get(request, *ids))


def test_only_a_new_picture_counts_as_a_change_of_the_display():
    from custom_components.bticino_c300x.dashboard_updates import (
        dashboard_state_event_changes_display,
    )

    hass, entry = _environment([_camera()])

    def changed(old, new):
        return dashboard_state_event_changes_display(
            hass, entry, {"entity_id": "camera.door", "old_state": old, "new_state": new})

    idle = _camera("tok-1")
    assert not changed(idle, State("camera.door", "streaming", dict(idle.attributes)))
    assert changed(idle, _camera("tok-2"))
    assert changed(idle, State("camera.door", "idle", {**idle.attributes, "friendly_name": "Gate"}))
