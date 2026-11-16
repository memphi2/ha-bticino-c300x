"""Physical persistence failures must not change notification ownership."""

import asyncio
import json
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import storage
from test_notify import entry_for, notify_context, send, service_name

from custom_components.bticino_c300x.notify import (
    async_setup_notify,
    async_unload_notify,
)
from custom_components.bticino_c300x.notify_names import async_remove_name, notify_names


@pytest.mark.parametrize("existing", [False, True])
def test_atomic_write_failure_blocks_registration_until_persisted(tmp_path, monkeypatch, existing):
    async def run():
        async with notify_context(tmp_path, monkeypatch, enabled=existing) as (hass, first):
            first.options["device_ui_enabled"] = True
            second = entry_for("second")
            names = notify_names(hass)
            path = Path(names._store.path)
            before = await hass.async_add_executor_job(path.read_bytes) if existing else None
            candidate = second if existing else first
            try:
                with monkeypatch.context() as patch:
                    writer = Mock(side_effect=storage.WriteError("disk full"))
                    patch.setattr(storage, "write_utf8_file_atomic", writer)
                    for _ in range(2):
                        with pytest.raises(ServiceValidationError, match="not persisted"):
                            await async_setup_notify(hass, candidate)
                        assert names._unsaved
                        assert not candidate.unload_callbacks
                    assert writer.call_count == 2
                if existing:
                    assert await hass.async_add_executor_job(path.read_bytes) == before
                else:
                    assert not await hass.async_add_executor_job(path.exists)
                await async_setup_notify(hass, second)
                await async_setup_notify(hass, first)
                first_name, second_name = service_name(hass, first), service_name(hass, second)
                assert first_name == "bticino_c300x_front_door"
                assert first_name != second_name
                assert not names._unsaved
                assert json.loads(await hass.async_add_executor_job(path.read_text))["data"] == {
                    "first": first_name, "second": second_name,
                }
            finally:
                async_unload_notify(hass, second)
                second.runtime_data.resources.close()
        async with notify_context(tmp_path, monkeypatch, key="second") as (hass, second):
            first = entry_for("first")
            try:
                await async_setup_notify(hass, first)
                assert service_name(hass, first) == first_name
                assert service_name(hass, second) == second_name
                for entry in (first, second):
                    await send(hass, entry)
                    entry.runtime_data.api.async_send_display_alert.assert_awaited_once()
            finally:
                async_unload_notify(hass, first)
                first.runtime_data.resources.close()
    asyncio.run(run())


def test_failed_removal_write_is_retried_before_name_reuse(tmp_path, monkeypatch):
    async def run():
        async with notify_context(tmp_path, monkeypatch) as (hass, first):
            names = notify_names(hass)
            path = Path(names._store.path)
            before = await hass.async_add_executor_job(path.read_bytes)
            async_unload_notify(hass, first)
            second = entry_for("second")
            try:
                with monkeypatch.context() as patch:
                    patch.setattr(storage, "write_utf8_file_atomic", Mock(side_effect=storage.WriteError("disk full")))
                    with pytest.raises(ServiceValidationError, match="not persisted"):
                        await async_remove_name(hass, first.entry_id)
                    with pytest.raises(ServiceValidationError, match="not persisted"):
                        await async_setup_notify(hass, second)
                assert await hass.async_add_executor_job(path.read_bytes) == before
                assert names._unsaved
                assert not second.unload_callbacks
                await async_setup_notify(hass, second)
                assert service_name(hass, second) == "bticino_c300x_front_door"
                assert json.loads(await hass.async_add_executor_job(path.read_text))["data"] == {"second": service_name(hass, second)}
            finally:
                async_unload_notify(hass, second)
                second.runtime_data.resources.close()
    asyncio.run(run())


@pytest.mark.parametrize("cancellations", [1, 2, 3])
def test_cancelled_atomic_write_finishes_before_reservation_retry(tmp_path, monkeypatch, cancellations):
    async def run():
        async with notify_context(tmp_path, monkeypatch, enabled=False) as (hass, first):
            first.options["device_ui_enabled"] = True
            names = notify_names(hass)
            started, release = threading.Event(), threading.Event()
            original = storage.write_utf8_file_atomic

            def delayed_write(*args, **kwargs):
                started.set()
                assert release.wait(5)
                return original(*args, **kwargs)

            with monkeypatch.context() as patch:
                patch.setattr(storage, "write_utf8_file_atomic", delayed_write)
                setup = asyncio.create_task(async_setup_notify(hass, first))
                try:
                    assert await hass.async_add_executor_job(started.wait, 5)
                    for _ in range(cancellations):
                        setup.cancel()
                        for _ in range(3):
                            await asyncio.sleep(0)
                        assert names.lock.locked()
                        assert not setup.done()
                finally:
                    release.set()
                    with pytest.raises(asyncio.CancelledError):
                        await setup
            assert names._unsaved
            assert not first.unload_callbacks
            await async_setup_notify(hass, first)
            assert not names._unsaved
            assert json.loads(await hass.async_add_executor_job(Path(names._store.path).read_text))["data"] == {
                "first": service_name(hass, first),
            }
    asyncio.run(run())
