from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.bticino_c300x.api import C300XAgentApiError
from custom_components.bticino_c300x.const import SMARTPHONE_FORWARDING_MODES
from custom_components.bticino_c300x.select import (
    C300XAudioCodecSelect,
    C300XSmartphoneForwardingModeSelect,
)
from custom_components.bticino_c300x.switch import (
    C300XAnsweringMachineSwitch,
    C300XMaintenanceSshSwitch,
)


class _DownApi:
    """An agent that is not reachable: every call fails like the real client."""

    def __getattr__(self, name: str) -> Any:
        async def fail(*_args: Any, **_kwargs: Any) -> None:
            raise C300XAgentApiError("agent unreachable at 192.0.2.10")

        return fail


def _entry() -> SimpleNamespace:
    return SimpleNamespace(
        entry_id="entry-1",
        title="C300X",
        data={},
        options={},
        runtime_data=SimpleNamespace(
            api=_DownApi(),
            agent_info={},
            capabilities={},
            connection_state=SimpleNamespace(available=True),
        ),
    )


def _silent(entity: Any) -> Any:
    entity.async_write_ha_state = lambda: None
    return entity


@pytest.mark.parametrize(
    ("entity", "call", "message"),
    [
        (
            lambda e: C300XSmartphoneForwardingModeSelect(e),
            lambda x: x.async_select_option(SMARTPHONE_FORWARDING_MODES[0]),
            "forwarding",
        ),
        (
            lambda e: C300XAudioCodecSelect(e),
            lambda x: x.async_select_option("pcmu"),
            "audio codec",
        ),
        (
            lambda e: C300XAnsweringMachineSwitch(e),
            lambda x: x.async_turn_on(),
            "answering machine",
        ),
        (
            lambda e: C300XMaintenanceSshSwitch(e),
            lambda x: x.async_turn_on(),
            "SSH",
        ),
    ],
    ids=["forwarding", "audio-codec", "answering-machine", "ssh"],
)
def test_an_unreachable_agent_is_reported_as_a_home_assistant_error(entity, call, message) -> None:
    built = _silent(entity(_entry()))

    with pytest.raises(HomeAssistantError, match=message) as raised:
        asyncio.run(call(built))

    # No internal address in the text the user sees.
    assert "192.0.2.10" not in str(raised.value)
    assert isinstance(raised.value.__cause__, C300XAgentApiError)
