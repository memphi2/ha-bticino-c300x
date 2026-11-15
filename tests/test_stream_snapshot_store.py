"""Bounded local storage for images supplied by an existing card stream."""

from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from custom_components.bticino_c300x import snapshot_store as storage


def jpeg(size=(64, 48)):
    output = BytesIO()
    image = Image.new("RGB", size, "red")
    exif = Image.Exif()
    exif[270] = "private metadata"
    image.save(output, format="JPEG", exif=exif)
    return output.getvalue()


def fake_hass(tmp_path):
    return SimpleNamespace(data={}, config=SimpleNamespace(
        config_dir=str(tmp_path),
        media_dirs={"local": str(tmp_path / "media")},
        path=lambda *parts: str(tmp_path.joinpath(*parts)),
    ))


def test_a_valid_image_is_stored_as_delivered():
    """The capture encodes the image once. Storing it must not decode and
    encode it again, which would lose quality and could change its size."""

    content = jpeg((688, 480))
    assert storage.normalize_snapshot(content) is content


@pytest.mark.parametrize("content", [b"", b"not jpeg", b"x" * (storage.MAX_SNAPSHOT_BYTES + 1)])
def test_invalid_images_rejected(content):
    with pytest.raises(ValueError):
        storage.normalize_snapshot(content)


def test_non_jpeg_and_excessive_pixels_rejected():
    output = BytesIO()
    Image.new("RGB", (10, 10)).save(output, format="PNG")
    for content in (output.getvalue(), jpeg((2000, 1100))):
        with pytest.raises(ValueError):
            storage.normalize_snapshot(content)


def test_device_isolation_deduplication_and_retention(tmp_path, monkeypatch):
    monkeypatch.setattr(storage.time, "time", lambda: 1700000000)
    first = storage.SnapshotStore(fake_hass(tmp_path), "one")
    second = storage.SnapshotStore(fake_hass(tmp_path), "two")
    item = first.save(jpeg(), "session", 14)
    assert first.save(jpeg(), "session", 14) == item
    assert first.read("latest", 14)
    assert second.read(item.name, 14) is None
    assert first.read("../" + item.name, 14) is None
    second.save(jpeg(), "session", 14)
    assert first.items(1, now=1700000000 + 86400) == []
    assert len(second.items(14, now=1700000000 + 86400)) == 1


def test_owned_files_obey_count_and_byte_limits(tmp_path, monkeypatch):
    store = storage.SnapshotStore(fake_hass(tmp_path), "one")
    monkeypatch.setattr(storage, "MAX_DEVICE_IMAGES", 2)
    for index in range(4):
        monkeypatch.setattr(storage.time, "time", lambda index=index: 1700000000 + index)
        store.save(jpeg(), str(index), 14)
    assert len(store.items(14)) == 2
    unrelated = store.root / "user.jpg"
    unrelated.write_bytes(b"keep")
    oversized = store.root / ("c300x-1700000003000-" + "a" * 32 + ".jpg")
    oversized.write_bytes(b"x" * (storage.MAX_SNAPSHOT_BYTES + 1))
    monkeypatch.setattr(storage, "MAX_DEVICE_BYTES", len(storage.normalize_snapshot(jpeg())))
    assert len(store.items(14)) == 1
    assert not oversized.exists()
    assert unrelated.read_bytes() == b"keep"


def test_symlinks_and_www_rejected(tmp_path):
    hass = fake_hass(tmp_path)
    store = storage.SnapshotStore(hass, "one")
    outside = tmp_path / "outside"
    outside.mkdir()
    store.root.parent.mkdir(parents=True)
    store.root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        store.save(jpeg(), "session", 14)
    hass.config.media_dirs = {"local": str(tmp_path / "www")}
    with pytest.raises(ValueError, match="www"):
        storage.SnapshotStore(hass, "two").save(jpeg(), "session", 14)
    assert not list(outside.iterdir())


def test_file_symlink_is_neither_served_nor_deleted(tmp_path):
    store = storage.SnapshotStore(fake_hass(tmp_path), "one")
    store.root.mkdir(parents=True)
    outside = tmp_path / "private.jpg"
    outside.write_bytes(jpeg())
    name = "c300x-1700000000000-" + "a" * 32 + ".jpg"
    link = store.root / name
    link.symlink_to(outside)
    assert store.read(name, 14) is None
    assert link.is_symlink()
    assert outside.read_bytes() == jpeg()


def test_failed_atomic_write_leaves_no_temporary_file(tmp_path, monkeypatch):
    store = storage.SnapshotStore(fake_hass(tmp_path), "one")

    def fail_replace(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(type(tmp_path), "replace", fail_replace)
    with pytest.raises(OSError, match="disk unavailable"):
        store.save(jpeg(), "session", 14)
    assert list(store.root.iterdir()) == []


def test_interrupted_write_cleanup_is_bounded_and_ownership_scoped(tmp_path, monkeypatch):
    store = storage.SnapshotStore(fake_hass(tmp_path), "one")
    store.root.mkdir(parents=True)
    names = [f".c300x-1700000000000-{index:032x}.jpg.tmp" for index in range(3)]
    for name in names:
        (store.root / name).write_bytes(b"partial")
    unrelated = store.root / ".user.jpg.tmp"
    unrelated.write_bytes(b"keep")
    outside = tmp_path / "outside"
    outside.write_bytes(b"keep outside")
    link = store.root / ".c300x-1700000000000-ffffffffffffffffffffffffffffffff.jpg.tmp"
    link.symlink_to(outside)
    monkeypatch.setattr(storage, "MAX_TEMP_CLEANUP", 2)
    assert store.items(14) == []
    assert sum((store.root / name).exists() for name in names) == 1
    store.items(14)
    assert all(not (store.root / name).exists() for name in names)
    assert unrelated.read_bytes() == b"keep"
    assert link.is_symlink()
    assert outside.read_bytes() == b"keep outside"
