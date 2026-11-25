"""Work of a repair step that outlives the request that started it.

Home Assistant runs a flow step inside the HTTP request that submitted it and
cancels the step when the client goes away: a closed tab, a phone that locks,
a proxy with a request limit. A step that updates the station and then reloads
the entry must not end there. Cut in the reload, the entry stays in
``setup_error`` with its repair already closed; cut earlier, the station is
updated and Home Assistant does none of the steps that follow an update.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any, Final

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_RUNNING: Final = f"{DOMAIN}_repair_work"

# Another flow's work for the same entry ran and has ended: its result went to
# that flow, this one has to look at the entry again.
OTHER_FLOW_FINISHED: Final = object()


class RepairStepWork:
    """The work of one repair flow, owned by Home Assistant instead of a request."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._entry_id = entry_id
        # Running, or finished with a result that no request has received yet.
        self._task: asyncio.Task[Any] | None = None

    async def async_run(self, work: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
        """Run ``work`` to its end and return its result to whoever still waits.

        A request that is cancelled leaves the work running. The next submit
        of the same flow waits for that work, or gets the result it missed,
        and starts nothing new. The submit of another flow for the same entry
        waits as well and gets ``OTHER_FLOW_FINISHED``: two updates must never
        write to one station at the same time.
        """

        task = self._task
        if task is None:
            running: dict[str, asyncio.Task[Any]] = self._hass.data.setdefault(_RUNNING, {})
            other = running.get(self._entry_id)
            if other is not None:
                # Does not cancel the other flow's work with this request.
                await asyncio.wait([other])
                return OTHER_FLOW_FINISHED
            task = self._task = self._create_task(work())
            if not task.done():
                running[self._entry_id] = task

                def finished(done: asyncio.Task[Any]) -> None:
                    if running.get(self._entry_id) is done:
                        del running[self._entry_id]

                task.add_done_callback(finished)
        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled():
                # Home Assistant is stopping: the work itself was ended.
                self._task = None
            raise
        except BaseException:
            self._task = None
            raise
        self._task = None
        return result

    def _create_task(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        # Not a task of the config entry: the reload at the end of the work
        # unloads the entry, which waits for or cancels the entry's own tasks.
        create_task = getattr(self._hass, "async_create_task", None)
        name = f"{DOMAIN} repair work {self._entry_id}"
        if callable(create_task):
            task: asyncio.Task[Any] = create_task(coro, name)
            return task
        return asyncio.create_task(coro, name=name)
