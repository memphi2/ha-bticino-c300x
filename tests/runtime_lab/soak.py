"""Finite, synthetic load/unload resource regression probe."""

from __future__ import annotations

import asyncio
import gc
import os
import tracemalloc
import weakref
from pathlib import Path

from harness import RuntimeLab

from custom_components.bticino_c300x import const, events

LIMITS = {
    "tasks": 2,
    "timers": 3,
    "listeners": 0,
    "fds": 2,
    "python_bytes": 2 * 1024 * 1024,
    "rss_bytes": 16 * 1024 * 1024,
}


def snapshot(lab):
    loop = asyncio.get_running_loop()
    return {
        "tasks": sum(not task.done() for task in asyncio.all_tasks()),
        "timers": sum(not handle.cancelled() for handle in loop._scheduled),
        "listeners": sum(lab.hass.bus.async_listeners().values()),
        "fds": len(list(Path("/proc/self/fd").iterdir())),
        "python_bytes": tracemalloc.get_traced_memory()[0],
        "rss_bytes": int(Path("/proc/self/statm").read_text().split()[1])
        * os.sysconf("SC_PAGE_SIZE"),
    }


async def run(root: Path, cycles: int):
    tracemalloc.start()
    try:
        async with RuntimeLab(root) as lab:
            entry = await lab.add_entry()
            assert await lab.hass.config_entries.async_unload(entry.entry_id)
            references = []
            samples = []
            for index in range(cycles + 3):
                requests_before = sum(lab.agent.requests.values())
                assert await lab.hass.config_entries.async_setup(entry.entry_id)
                await lab.settle()
                references.append(weakref.ref(entry.runtime_data.api))
                # A disconnect followed by recovery exercises retry/grace timers.
                lab.agent.fail_list = True
                assert events.async_request_agent_event_registration(lab.hass, entry)
                await lab.wait_for(
                    lambda: (
                        entry.runtime_data.connection_state.event_subscription_last_error
                        is not None
                    )
                )
                lab.agent.fail_list = False
                await lab.wait_for(
                    lambda: (
                        entry.runtime_data.connection_state.event_subscription_last_error
                        is None
                    )
                )
                for _ in range(4):
                    assert (
                        await lab.push("system.metrics_changed", lab.agent.metrics())
                    )[0] == 200
                assert await lab.hass.config_entries.async_unload(entry.entry_id)
                await lab.settle()
                gc.collect()
                await asyncio.sleep(0.1)
                assert not lab.hass.data[const.DOMAIN][const.DATA_RUNTIME_ENTRIES]
                assert "synthetic-events" not in lab.hass.data["webhook"]
                assert not lab.agent.unexpected, lab.agent.unexpected
                # HA may retain the most recently unloaded entry's runtime.
                assert all(ref() is None for ref in references[:-1]), (
                    "An older API client survived unload/reload"
                )
                requests = sum(lab.agent.requests.values()) - requests_before
                assert requests <= 30, f"Unexpected request amplification: {requests}"
                if index >= 2:
                    sample = snapshot(lab)
                    sample["requests"] = requests
                    samples.append(sample)
            baseline = samples[0]
            growth = {
                key: max(sample[key] for sample in samples[1:]) - baseline[key]
                for key in LIMITS
            }
            for key, limit in LIMITS.items():
                assert growth[key] <= limit, (key, growth[key], limit, samples)
            return {
                "scenario": "soak",
                "cycles": cycles,
                "warmup_cycles": 3,
                "limits": LIMITS,
                "growth": growth,
                "samples": samples,
                "scope": "Loopback HA runtime only; not C300X CPU, writes or physical media",
            }
    finally:
        tracemalloc.stop()
