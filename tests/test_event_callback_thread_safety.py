"""Exercise scheduler callbacks with real HA, isolated from suite-wide stubs."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_reconnect_expiry_and_registry_listener_run_on_ha_loop() -> None:
    probe = r'''
import asyncio
import tempfile
import threading
from types import SimpleNamespace

from homeassistant.core import HassJob, HassJobType, HomeAssistant
import custom_components.bticino_c300x.events as events
from custom_components.bticino_c300x.data import C300XConnectionState

async def main():
    with tempfile.TemporaryDirectory() as config_dir:
        hass = HomeAssistant(config_dir)
        loop_thread = threading.get_ident()
        called = asyncio.Event()
        repairs_threads = []
        scheduled = []
        real_call_later = events.async_call_later

        def capture(hass, delay, action):
            scheduled.append(action)
            return real_call_later(hass, delay, action)

        def sync_repairs(hass, entry):
            repairs_threads.append(threading.get_ident())
            assert threading.get_ident() == loop_thread
            called.set()

        events.async_call_later = capture
        events._sync_repair_issues = sync_repairs
        events.DEFAULT_RECONNECT_GRACE_SECONDS = 0
        entry = SimpleNamespace(entry_id="entry-1")
        state = C300XConnectionState()
        state.mark_reconnecting("event_subscription_registration", 30, "disconnected")
        events._schedule_unavailable_expiry(hass, entry, state)
        assert HassJob(scheduled[0]).job_type is HassJobType.Callback
        await asyncio.wait_for(called.wait(), timeout=5)
        assert repairs_threads == [loop_thread]
        assert not state.available
        assert state.expire_unavailable is None
        assert HassJob(events._AgentEventRegistration._schedule_registry_refresh).job_type is HassJobType.Callback
        await hass.async_block_till_done()
        hass.import_executor.shutdown(wait=True)

asyncio.run(main())
'''
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
