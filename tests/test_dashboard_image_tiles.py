"""Camera and image entities as picture tiles, scaled down by Home Assistant."""

import asyncio
import io
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from aiohttp import web
from homeassistant.config_entries import ConfigEntryState
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

BASE = "http://192.0.2.10:8123"


def _environment(states, *, base=BASE, overrides=None, entities=None):
    entities = entities or [state.entity_id for state in states]
    by_id = {state.entity_id: state for state in states}
    entry = SimpleNamespace(
        entry_id="entry", domain="bticino_c300x", state=ConfigEntryState.LOADED,
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
    # The display writes the caption into the picture. Pictures of configured
    # actions have none and stay as they were.
    assert item["caption"] == "Front door"
    root = Path(__file__).resolve().parents[1] / "device_qml"
    assert '"caption": String(source[i].caption || "")' in (root / "js" / "c300x_ha.js").read_text(encoding="utf-8")
    assert 'text: imageTile.tileItem.caption || ""' in (root / "HomeAssistant.qml").read_text(encoding="utf-8")
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
    assert image_tile_base_url("http://192.0.2.10:8123/api/webhook/abc") == BASE
    assert image_tile_base_url("") == ""
    assert image_tile_base_url("ftp://host/x") == ""
    # The display's Qt has no SSL: an https address would only give a blank tile.
    assert image_tile_base_url("https://ha.example/api/webhook/abc") == ""


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


def test_a_damaged_picture_is_refused_whatever_the_decoder_raises(monkeypatch):
    import struct

    from PIL import ImageOps

    def broken(_image):
        raise struct.error("unpack requires a buffer of 2 bytes")

    monkeypatch.setattr(ImageOps, "exif_transpose", broken)
    with pytest.raises(ValueError):
        scaled_jpeg(_jpeg(64, 64), 728, 200)


def test_a_picture_taken_sideways_is_turned_upright():
    buffer = io.BytesIO()
    exif = Image.Exif()
    exif[0x0112] = 6
    Image.new("RGB", (1600, 900), "navy").save(buffer, "JPEG", exif=exif)
    with Image.open(io.BytesIO(scaled_jpeg(buffer.getvalue(), 728, 200))) as image:
        assert image.height == 200 and image.width < image.height


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
        ({"sig": "\u00e9" * 32}, (entry_id, entity_id)),
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

    # The same address again within a few seconds reads the camera once; the
    # address of a newer picture is never answered with the older one.
    request, ids = _request(hass, source)
    asyncio.run(view.get(request, *ids))
    assert len(fetched) == 1
    hass.states = SimpleNamespace(get={"camera.door": _camera("tok-2")}.get)
    newer = next(item["source"] for item in _items(hass, entry) if item.get("kind") == "image")
    assert newer != source
    request, ids = _request(hass, newer)
    asyncio.run(view.get(request, *ids))
    assert len(fetched) == 2
    # The revision is signed too: an address cannot be varied to force reads.
    request, ids = _request(hass, source, rev="made-up")
    with pytest.raises(web.HTTPNotFound):
        asyncio.run(view.get(request, *ids))

    async def together():
        hass.data.clear()
        first, ids = _request(hass, source)
        second, _ = _request(hass, source)
        await asyncio.gather(view.get(first, *ids), view.get(second, *ids))

    asyncio.run(together())
    assert len(fetched) == 3, "two requests at once read the camera once"
    fetched.pop()

    # Switching the display feature off or unloading the entry ends the access.
    hass.data.clear()
    request, ids = _request(hass, source)
    entry.options["device_ui_enabled"] = False
    with pytest.raises(web.HTTPNotFound):
        asyncio.run(view.get(request, *ids))
    entry.options["device_ui_enabled"] = True
    entry.state = ConfigEntryState.NOT_LOADED
    with pytest.raises(web.HTTPNotFound):
        asyncio.run(view.get(request, *ids))
    assert len(fetched) == 2


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


def test_hostile_pictures_are_refused_before_they_are_decoded():
    huge = io.BytesIO()
    Image.new("L", (5000, 5000)).save(huge, "PNG")
    assert len(huge.getvalue()) < 100_000, "small file, 25 million pixels"
    with pytest.raises(ValueError):
        scaled_jpeg(huge.getvalue(), 728, 200)
    other = io.BytesIO()
    Image.new("RGB", (64, 64)).save(other, "TIFF")
    with pytest.raises(ValueError):
        scaled_jpeg(other.getvalue(), 728, 200)


def test_an_entity_without_a_picture_has_no_tile_and_never_reaches_the_payload_half_built():
    for state in (None, State("camera.door", "unavailable")):
        states = [state] if state else []
        hass, entry = _environment(states, entities=["camera.door"])
        items = _items(hass, entry)
        assert not [item for item in items if item.get("kind") == "image"]
    hass, entry = _environment([_camera()])
    for item in _items(hass, entry):
        assert not [key for key in item if key.startswith("_")]


def test_a_picture_entity_stored_for_the_alarm_page_is_ignored():
    from custom_components.bticino_c300x.dashboard_config import (
        configured_alarm_page_entity_id,
    )

    entry = SimpleNamespace(data={}, options={"alarm_page_entity_id": "camera.door"})
    assert configured_alarm_page_entity_id(entry) is None
    entry.options["alarm_page_entity_id"] = "light.hall"
    assert configured_alarm_page_entity_id(entry) == "light.hall"


def test_pictures_are_read_through_home_assistants_camera_and_image_entities(monkeypatch):
    from homeassistant.components import camera
    from homeassistant.exceptions import HomeAssistantError

    calls = []

    async def get_image(hass, entity_id, **options):
        calls.append((entity_id, options["timeout"], options["width"], options["height"]))
        return SimpleNamespace(content=b"camera-bytes", content_type="image/jpeg")

    monkeypatch.setattr(camera, "async_get_image", get_image)
    read = dashboard_images._async_source_image
    assert asyncio.run(read(SimpleNamespace(data={}), "camera.door", 359, 120)) == b"camera-bytes"
    assert calls == [("camera.door", 10, 359, 120)]

    class Picture:
        async def async_image(self):
            return b"image-bytes"

    component = SimpleNamespace(get_entity=lambda entity_id: Picture() if entity_id == "image.map" else None)
    hass = SimpleNamespace(data={"image": component})
    assert asyncio.run(read(hass, "image.map", 728, 200)) == b"image-bytes"
    for target in ("image.gone",):
        with pytest.raises(dashboard_images.TileImageUnavailable):
            asyncio.run(read(hass, target, 728, 200))

    for error in (HomeAssistantError("off"), TimeoutError(), RuntimeError("integration bug")):
        async def fail(*_args, _error=error, **_kwargs):
            raise _error

        monkeypatch.setattr(camera, "async_get_image", fail)
        with pytest.raises(dashboard_images.TileImageUnavailable):
            asyncio.run(read(SimpleNamespace(data={}), "camera.door", 728, 200))


def test_the_view_is_registered_and_the_address_base_is_recorded():
    root = Path(__file__).resolve().parents[1] / "custom_components" / "bticino_c300x"
    assert "hass.http.register_view(cast(Any, C300XTileImageView()))" in (root / "media.py").read_text()
    assert "runtime_data.display_image_base_url = image_tile_base_url(webhook_url)" in (
        root / "runtime_manager.py").read_text()


def test_a_palette_picture_is_scaled_smoothly():
    """Pillow shrinks palette and 1-bit pictures by dropping pixels unless they are converted first."""

    stripes = Image.new("P", (2048, 400))
    stripes.putpalette([0, 0, 0, 255, 255, 255] + [0] * 756)
    stripes.putdata([(x % 2) for _y in range(400) for x in range(2048)])
    buffer = io.BytesIO()
    stripes.save(buffer, "PNG")
    with Image.open(io.BytesIO(scaled_jpeg(buffer.getvalue(), 728, 200))) as image:
        levels = list(image.convert("L").getdata())
    mean = sum(levels) / len(levels)
    spread = (sum((level - mean) ** 2 for level in levels) / len(levels)) ** 0.5
    assert spread < 30, "fine stripes average to grey instead of turning into coarse bands"


def test_a_failed_read_is_not_repeated_by_the_requests_waiting_behind_it(monkeypatch):
    hass, entry = _environment([_camera()])
    source = next(item["source"] for item in _items(hass, entry) if item.get("kind") == "image")
    reads = []

    async def fail(*_args):
        reads.append(1)
        await asyncio.sleep(0.01)
        raise dashboard_images.TileImageUnavailable("camera off")

    monkeypatch.setattr(dashboard_images, "_async_source_image", fail)
    view = C300XTileImageView()

    async def together():
        requests = [_request(hass, source) for _ in range(3)]
        return await asyncio.gather(
            *(view.get(request, *ids) for request, ids in requests), return_exceptions=True)

    results = asyncio.run(together())
    assert all(isinstance(result, web.HTTPServiceUnavailable) for result in results)
    assert len(reads) == 1
    assert hass.data[dashboard_images._CACHE_KEY]["locks"] == {}
