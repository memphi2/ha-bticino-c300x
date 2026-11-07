"""Inspect real SQLite history and attributes, including private memo text."""

from __future__ import annotations

import json
from pathlib import Path

from harness import RuntimeLab
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.tasks import SynchronizeTask
from homeassistant.helpers.dispatcher import async_dispatcher_send
from sqlalchemy import text

from custom_components.bticino_c300x.const import SIGNAL_AGENT_DIAGNOSTICS_CHANGED


async def rows(lab):
    recorder = get_instance(lab.hass)
    await lab.settle()
    # Always queue a barrier, including when the Recorder thread has dequeued
    # its last event but has not yet committed it.
    future = lab.hass.loop.create_future()
    recorder.queue_task(SynchronizeTask(future))
    await future

    def query():
        with recorder.engine.connect() as connection:
            return connection.execute(
                text(
                    "SELECT m.entity_id, s.state, a.shared_attrs FROM states s "
                    "JOIN states_meta m USING(metadata_id) "
                    "LEFT JOIN state_attributes a USING(attributes_id) ORDER BY s.state_id"
                )
            ).all()

    return await recorder.async_add_executor_job(query)


async def run(root: Path):
    async with RuntimeLab(root, recorder=True) as lab:
        await lab.add_entry(enabled_sensors=("device_cpu", "agent_diagnostics"))
        cpu = lab.entity("device_cpu")
        memo = lab.entity("text_memos")
        diagnostics = lab.entity("agent_diagnostics")
        await lab.hass.services.async_call(
            "homeassistant", "update_entity", {"entity_id": memo}, blocking=True
        )
        assert (
            lab.hass.states.get(memo).attributes["latest_text"] == lab.agent.memo_text
        )
        diagnostic_payload = {
            "agent_write_count": 0,
            "loop_iterations": 100,
            "open_fd_count": 8,
        }
        assert (await lab.push("agent.diagnostics_changed", diagnostic_payload))[
            0
        ] == 200
        assert (await lab.push("system.metrics_changed", lab.agent.metrics()))[0] == 200
        assert lab.hass.states.get(cpu).state == "1.0"
        before = await rows(lab)
        assert {cpu, memo, diagnostics} <= {row[0] for row in before}
        # Healthy watchdog observations must not create a second CPU history.
        # Force the diagnostics signal instead of relying on callback timing.
        lab.entry.runtime_data.agent_cpu_watchdog.evaluate(
            {"cpu_usage_percent": 2.0}, lab.hass.loop.time()
        )
        async_dispatcher_send(
            lab.hass, SIGNAL_AGENT_DIAGNOSTICS_CHANGED, lab.entry.entry_id
        )
        await lab.settle()
        assert lab.hass.states.get(diagnostics).attributes["media_watchdog_last_percent"] is None
        assert await rows(lab) == before, "Watchdog snapshots grew Recorder history"
        for _ in range(20):
            assert (await lab.push("system.metrics_changed", lab.agent.metrics()))[
                0
            ] == 200
            assert (await lab.push("agent.diagnostics_changed", diagnostic_payload))[
                0
            ] == 200
        assert await rows(lab) == before, "Identical measurements grew Recorder history"
        for value in (2.0, 3.0, 4.0):
            assert (
                await lab.push(
                    "system.metrics_changed",
                    {**lab.agent.metrics(), "cpu_usage_percent": value},
                )
            )[0] == 200
        after = await rows(lab)
        cpu_before = [row for row in before if row[0] == cpu]
        cpu_after = [row for row in after if row[0] == cpu]
        assert len(cpu_after) - len(cpu_before) == 3
        assert [row[1] for row in cpu_after[-3:]] == ["2.0", "3.0", "4.0"]
        assert any(row[0] == memo and row[1] == "1" for row in after)
        assert lab.agent.memo_text not in str(after)
        for entity_id, _, attributes in after:
            recorded = json.loads(attributes or "{}")
            if entity_id == memo:
                assert "latest_text" not in recorded
            if entity_id == diagnostics:
                assert (
                    not {"loop_iterations", "open_fd_count", "updated_at"}
                    & recorded.keys()
                )
        watchdog = lab.entry.runtime_data.agent_cpu_watchdog
        watchdog.evaluate({"cpu_usage_percent": 95.0}, 0.0)
        assert watchdog.evaluate({"cpu_usage_percent": 96.0}, 300.0)
        async_dispatcher_send(lab.hass, SIGNAL_AGENT_DIAGNOSTICS_CHANGED, lab.entry.entry_id)
        triggered = await rows(lab)
        assert any(
            entity_id == diagnostics and state == "media_watchdog_tripped"
            and json.loads(attributes)["media_watchdog_last_percent"] == 96.0
            for entity_id, state, attributes in triggered
        )
        return {
            "scenario": "recorder",
            "idle_events": 40,
            "idle_rows_added": 0,
            "changed_cpu_rows_added": 3,
            "watchdog_trigger_recorded": True,
            "memo_text_live": True,
            "memo_text_recorded": False,
        }
