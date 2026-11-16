"""Permanent removal attempts both independent persistent-data cleanups."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import storage
from test_notify import entry_for, notify_context, service_name

import custom_components.bticino_c300x as integration
from custom_components.bticino_c300x import notify_names, repair_issues, visitor_journal
from custom_components.bticino_c300x.notify import (
    async_setup_notify,
    async_unload_notify,
)


@pytest.mark.parametrize("failed", [(), ("journal",), ("name",), ("journal", "name")])
def test_removal_attempts_both_cleanups_and_preserves_errors(monkeypatch, failed):
    errors = {name: OSError(f"{name} failed") for name in failed}
    removers = [AsyncMock(side_effect=errors.get(name)) for name in ("journal", "name")]
    monkeypatch.setattr(visitor_journal, "async_remove_journal", removers[0])
    monkeypatch.setattr(notify_names, "async_remove_name", removers[1])
    monkeypatch.setattr(repair_issues, "async_clear_entry_repair_issues", lambda *_: None)
    hass = SimpleNamespace(data={})
    entry = SimpleNamespace(entry_id="one")

    if errors:
        with pytest.raises(ExceptionGroup) as caught:
            asyncio.run(integration.async_remove_entry(hass, entry))
        assert caught.value.exceptions == tuple(errors.values())
        assert all(error.__traceback__ is not None for error in caught.value.exceptions)
    else:
        asyncio.run(integration.async_remove_entry(hass, entry))
    for remove in removers:
        remove.assert_awaited_once_with(hass, entry.entry_id)


@pytest.mark.parametrize("stage,prior_failure", [("journal", False), ("name", False), ("name", True)])
def test_removal_cancellation_stops_cleanup_and_preserves_prior_error(monkeypatch, stage, prior_failure):
    async def run():
        started = asyncio.Event()
        prior = OSError("journal failed") if prior_failure else None

        async def wait_for_cancel(*_):
            started.set()
            await asyncio.Future()

        journal = AsyncMock(side_effect=wait_for_cancel if stage == "journal" else prior)
        name = AsyncMock(side_effect=wait_for_cancel if stage == "name" else None)
        monkeypatch.setattr(visitor_journal, "async_remove_journal", journal)
        monkeypatch.setattr(notify_names, "async_remove_name", name)
        monkeypatch.setattr(repair_issues, "async_clear_entry_repair_issues", lambda *_: None)
        task = asyncio.create_task(integration.async_remove_entry(
            SimpleNamespace(data={}), SimpleNamespace(entry_id="one"),
        ))
        try:
            await asyncio.wait_for(started.wait(), 1)
        finally:
            task.cancel("removal cancelled")
            with pytest.raises(asyncio.CancelledError, match="removal cancelled") as caught:
                await task
        assert task.cancelled()
        assert journal.await_count == 1
        assert name.await_count == (stage == "name")
        if prior_failure:
            assert isinstance(caught.value.__cause__, ExceptionGroup)
            assert caught.value.__cause__.exceptions == (prior,)
        else:
            assert caught.value.__cause__ is None

    asyncio.run(run())


@pytest.mark.parametrize("failed", [("journal",), ("name",), ("journal", "name")])
def test_removal_real_storage_failures_are_independent(tmp_path, monkeypatch, failed):
    async def run():
        async with notify_context(tmp_path, monkeypatch) as (hass, entry):
            entry.runtime_data.connection_state = SimpleNamespace(expire_unavailable=None)
            old_name = service_name(hass, entry)
            async_unload_notify(hass, entry)
            journal = storage.Store(hass, 1, f"bticino_c300x.visitor_journal.{entry.entry_id}")
            await journal.async_save({"visits": []})
            names = notify_names.notify_names(hass)
            name_path = Path(names._store.path)
            unlink = storage.os.unlink
            write = storage.write_utf8_file_atomic
            journal_error = PermissionError("journal unlink denied")

            def unlink_journal(path, *args, **kwargs):
                if "journal" in failed and str(path) == journal.path:
                    raise journal_error
                return unlink(path, *args, **kwargs)

            def write_names(path, *args, **kwargs):
                if "name" in failed and str(path) == str(name_path):
                    raise storage.WriteError("name reservation write denied")
                return write(path, *args, **kwargs)

            with monkeypatch.context() as patch:
                patch.setattr(storage.os, "unlink", unlink_journal)
                patch.setattr(storage, "write_utf8_file_atomic", write_names)
                with pytest.raises(ExceptionGroup) as caught:
                    await integration.async_remove_entry(hass, entry)

            errors = caught.value.exceptions
            assert len(errors) == len(failed)
            if "journal" in failed:
                assert errors[0] is journal_error
            if "name" in failed:
                assert isinstance(errors[-1], ServiceValidationError)
                assert "not persisted" in str(errors[-1])
            assert await hass.async_add_executor_job(Path(journal.path).exists) == ("journal" in failed)
            persisted = json.loads(await hass.async_add_executor_job(name_path.read_text))["data"]
            assert persisted == ({entry.entry_id: old_name} if "name" in failed else {})
            assert names._unsaved == ("name" in failed)

            # After a write failure, the existing reservation owner retries its
            # pending save before allowing a replacement to reuse the name.
            replacement = entry_for("replacement")
            try:
                await async_setup_notify(hass, replacement)
                assert service_name(hass, replacement) == old_name
                persisted = json.loads(await hass.async_add_executor_job(name_path.read_text))["data"]
                assert persisted == {replacement.entry_id: old_name}
            finally:
                async_unload_notify(hass, replacement)
                replacement.runtime_data.resources.close()

    asyncio.run(run())
