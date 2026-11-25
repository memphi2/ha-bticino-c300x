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
from collections.abc import Callable, Coroutine, Mapping
from typing import Any, Final

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN
from .repair_issues import repair_issue_id

_RUNNING: Final = f"{DOMAIN}_repair_work"

# Work of another flow for the same entry ended while this submit waited, and
# the repair of this flow is no longer needed: there is nothing left to run.
OTHER_FLOW_FINISHED: Final = object()


class RepairStepWork:
    """The work of one repair flow, owned by Home Assistant instead of a request."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._entry_id = entry_id
        # Running, or finished with a result that no request has received yet,
        # and what was submitted to start it.
        self._task: asyncio.Task[Any] | None = None
        self._submitted: Any = None

    async def async_run(
        self,
        work: Callable[[], Coroutine[Any, Any, Any]],
        submitted: Any,
        still_needed: Callable[[], bool],
    ) -> Any:
        """Run ``work`` to its end and return its result to whoever still waits.

        A request that is cancelled leaves the work running. The next submit
        of the same flow waits for that work, or gets the result it missed,
        and starts nothing new.

        ``submitted`` is what the client sent. A result that leaves the form
        open, a failure, is not handed to a submit with other input: that
        submit runs its own work, so a corrected input is not answered with
        the failure of the old one. A result that ended the flow is final.

        Work for one entry never overlaps: two repairs must not write to one
        station at the same time. A submit that finds work of another flow
        running waits for it and then runs its own, unless ``still_needed``
        says the repair is done; then it gets ``OTHER_FLOW_FINISHED``.
        """

        while True:
            task = self._task
            if task is None:
                task = await self._async_start(work, submitted, still_needed)
                if task is None:
                    return OTHER_FLOW_FINISHED
            started_with = self._submitted
            try:
                result = await asyncio.shield(task)
            except asyncio.CancelledError:
                if task.cancelled():
                    # Home Assistant is stopping: the work itself was ended.
                    self._forget(task)
                raise
            except BaseException:
                self._forget(task)
                raise
            self._forget(task)
            if started_with == submitted or not _leaves_form_open(result):
                return result

    async def _async_start(
        self,
        work: Callable[[], Coroutine[Any, Any, Any]],
        submitted: Any,
        still_needed: Callable[[], bool],
    ) -> asyncio.Task[Any] | None:
        running: dict[str, asyncio.Task[Any]] = self._hass.data.setdefault(_RUNNING, {})
        waited = False
        while (other := running.get(self._entry_id)) is not None and not other.done():
            # Does not cancel the other flow's work with this request.
            await asyncio.wait([other])
            waited = True
        if self._task is not None:
            # Another request of this flow started its work during the wait.
            return self._task
        if waited and not still_needed():
            return None
        task = self._task = self._create_task(work())
        self._submitted = submitted
        if not task.done():
            running[self._entry_id] = task

            def finished(done: asyncio.Task[Any]) -> None:
                if running.get(self._entry_id) is done:
                    del running[self._entry_id]

            task.add_done_callback(finished)
        return task

    def _forget(self, task: asyncio.Task[Any]) -> None:
        if self._task is task:
            self._task = None
            self._submitted = None

    def _create_task(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        # Not a task of the config entry: the reload at the end of the work
        # unloads the entry, which waits for or cancels the entry's own tasks.
        create_task = getattr(self._hass, "async_create_task", None)
        name = f"{DOMAIN} repair work {self._entry_id}"
        if callable(create_task):
            task: asyncio.Task[Any] = create_task(coro, name)
            return task
        return asyncio.create_task(coro, name=name)


def _leaves_form_open(result: Any) -> bool:
    """Whether a step result shows its form again instead of ending the flow."""

    return isinstance(result, Mapping) and result.get("type") == "form"


async def async_run_repair_step(
    flow: Any,
    work: RepairStepWork,
    issue_type: str,
    step: Callable[[dict[str, Any] | None], Coroutine[Any, Any, Any]],
    user_input: dict[str, Any] | None,
) -> Any:
    """Run a submitted repair step so that a dropped request cannot end it.

    ``step`` is the body of the step. Showing its form runs in the request;
    a submit runs as work that Home Assistant owns. A submit that had to wait
    for another flow's work for the entry runs afterwards with its own input,
    unless the issue is gone by then: that means repaired.
    """

    if user_input is None:
        return await step(None)
    issue_id = repair_issue_id(issue_type, flow._entry_id)

    def still_needed() -> bool:
        return ir.async_get(flow.hass).async_get_issue(DOMAIN, issue_id) is not None

    result = await work.async_run(
        lambda: step(user_input), (step.__name__, user_input), still_needed
    )
    if result is OTHER_FLOW_FINISHED:
        return flow.async_create_entry(data={})
    return result
