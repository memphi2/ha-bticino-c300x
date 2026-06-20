from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import dataclass, field
from typing import Any

if "homeassistant.components.button" not in sys.modules:
    homeassistant = sys.modules.setdefault(
        "homeassistant",
        types.ModuleType("homeassistant"),
    )
    components = sys.modules.setdefault(
        "homeassistant.components",
        types.ModuleType("homeassistant.components"),
    )
    button = types.ModuleType("homeassistant.components.button")
    config_entries = sys.modules.setdefault(
        "homeassistant.config_entries",
        types.ModuleType("homeassistant.config_entries"),
    )
    const = sys.modules.setdefault(
        "homeassistant.const",
        types.ModuleType("homeassistant.const"),
    )
    core = sys.modules.setdefault(
        "homeassistant.core",
        types.ModuleType("homeassistant.core"),
    )
    exceptions = sys.modules.setdefault(
        "homeassistant.exceptions",
        types.ModuleType("homeassistant.exceptions"),
    )
    helpers = sys.modules.setdefault(
        "homeassistant.helpers",
        types.ModuleType("homeassistant.helpers"),
    )
    dispatcher = types.ModuleType("homeassistant.helpers.dispatcher")
    config_validation = types.ModuleType("homeassistant.helpers.config_validation")
    issue_registry = types.ModuleType("homeassistant.helpers.issue_registry")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    entity = sys.modules.setdefault(
        "homeassistant.helpers.entity",
        types.ModuleType("homeassistant.helpers.entity"),
    )
    entity_platform = sys.modules.setdefault(
        "homeassistant.helpers.entity_platform",
        types.ModuleType("homeassistant.helpers.entity_platform"),
    )

    class ButtonEntity:  # pragma: no cover - import-time stub only
        def async_write_ha_state(self) -> None:
            self.wrote_state = True

        def async_on_remove(self, _callback: Any) -> None:
            return

    class ConfigEntry:  # pragma: no cover - import-time stub only
        pass

    class Entity:  # pragma: no cover - import-time stub only
        pass

    class DeviceInfo(dict):  # pragma: no cover - import-time stub only
        pass

    class EntityCategory:  # pragma: no cover - import-time stub only
        CONFIG = "config"

    class HomeAssistant:  # pragma: no cover - import-time stub only
        pass

    class HomeAssistantError(Exception):  # pragma: no cover - import-time stub only
        pass

    button.ButtonEntity = ButtonEntity
    config_entries.ConfigEntry = ConfigEntry
    const.EntityCategory = EntityCategory
    core.HomeAssistant = HomeAssistant
    core.callback = lambda func: func
    exceptions.HomeAssistantError = HomeAssistantError
    config_validation.config_entry_only_config_schema = lambda _domain: dict
    dispatcher.async_dispatcher_connect = lambda *args, **kwargs: lambda: None
    dispatcher.async_dispatcher_send = lambda *args, **kwargs: None
    issue_registry.IssueSeverity = types.SimpleNamespace(
        ERROR="error",
        WARNING="warning",
    )
    issue_registry.async_create_issue = lambda **kwargs: None
    issue_registry.async_delete_issue = lambda **kwargs: None
    entity_registry.EVENT_ENTITY_REGISTRY_UPDATED = "entity_registry_updated"
    entity_registry.EventEntityRegistryUpdatedData = dict
    entity_registry.async_get = lambda _hass: types.SimpleNamespace(
        async_get=lambda _entity_id: None
    )
    helpers.config_validation = config_validation
    entity.Entity = Entity
    entity.DeviceInfo = DeviceInfo
    entity_platform.AddEntitiesCallback = object
    helpers.dispatcher = dispatcher
    helpers.entity = entity
    helpers.entity_platform = entity_platform
    components.button = button
    homeassistant.components = components
    sys.modules["homeassistant.components.button"] = button
    sys.modules["homeassistant.helpers.config_validation"] = config_validation
    sys.modules["homeassistant.helpers.dispatcher"] = dispatcher
    sys.modules["homeassistant.helpers.issue_registry"] = issue_registry
    sys.modules["homeassistant.helpers.entity_registry"] = entity_registry

from custom_components.bticino_c300x.api_errors import (  # noqa: E402
    C300XAgentApiError,
    C300XAgentApiUnsupportedError,
)
from custom_components.bticino_c300x.button import (
    C300XDeleteLatestTextMemoButton,  # noqa: E402
    C300XDeleteLatestVideoMessageButton,
    C300XDeleteLatestVoiceMemoButton,
    C300XDeviceActivationButton,
    C300XDoorUnlockButton,
    C300XRebootButton,
    C300XReloadGuiButton,
    C300XRemoveAgentButton,
    C300XRestartAgentButton,
    C300XStairLightButton,
    C300XStopDoorbellVideoButton,
    _activation_icon,
    async_setup_entry,
)
from custom_components.bticino_c300x.capabilities import (
    answering_machine_message_delete_supported,
    maintenance_action_is_advertised,
    maintenance_action_is_supported,
    memo_delete_supported,
)  # noqa: E402
from custom_components.bticino_c300x.const import (  # noqa: E402
    CONF_DEVICE_UI_ENABLED,
    CONF_MAINTENANCE_TOKEN,
    CONF_VIDEO_ENABLED,
)
from custom_components.bticino_c300x.qml_patch import (  # noqa: E402
    async_apply_qml_core_patch_and_confirm,
    async_apply_qml_patch_and_confirm,
    async_restore_qml_core_patch_and_confirm,
    async_restore_qml_patch_and_confirm,
)


def test_maintenance_buttons_default_visibility() -> None:
    for button_class in (
        C300XRebootButton,
        C300XRestartAgentButton,
        C300XReloadGuiButton,
    ):
        assert not hasattr(button_class, "_attr_entity_registry_enabled_default")
    assert C300XRemoveAgentButton._attr_entity_registry_enabled_default is False


class _FakeHass:
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.config = types.SimpleNamespace(config_dir="/tmp")

    def async_create_task(self, coro: Any) -> asyncio.Task[Any]:
        return asyncio.create_task(coro)

    def verify_event_loop_thread(self, _what: str) -> None:
        return


class _FakeMemoApi:
    def __init__(
        self,
        refreshed_memos: dict[str, Any] | None = None,
        refreshed_video_messages: dict[str, Any] | None = None,
        qml_status: dict[str, Any] | None = None,
    ) -> None:
        self.delete_calls: list[str] = []
        self.video_delete_calls: list[str] = []
        self.qml_patch_actions: list[str] = []
        self.firewall_actions: list[str] = []
        self.activation_calls: list[str] = []
        self.remove_agent_calls = 0
        self.reboot_calls = 0
        self.restart_agent_calls = 0
        self.reload_gui_calls = 0
        self.stop_video_calls = 0
        self.memos_calls = 0
        self.video_messages_calls = 0
        self._refreshed_memos = refreshed_memos or {}
        self._refreshed_video_messages = refreshed_video_messages or {}
        self._qml_status = qml_status

    async def async_delete_memo(self, memo_id: str) -> dict[str, Any]:
        self.delete_calls.append(memo_id)
        return {"ok": True, "deleted": True, "id": memo_id}

    async def async_memos(self) -> dict[str, Any]:
        self.memos_calls += 1
        return self._refreshed_memos

    async def async_delete_answering_machine_message(
        self,
        message_id: str,
    ) -> dict[str, Any]:
        self.video_delete_calls.append(message_id)
        return {"ok": True, "deleted": True, "id": message_id}

    async def async_activations(self) -> dict[str, Any]:
        return {
            "available": True,
            "supported": True,
            "items": [
                {
                    "id": "front_lock",
                    "name": "Front lock",
                    "type": "lock",
                    "address_mode": "manual",
                    "address": "20",
                    "source": "config",
                    "executable": True,
                },
                {
                    "id": "unknown",
                    "name": "Unknown",
                    "type": "unknown",
                    "source": "config",
                    "executable": False,
                },
            ],
        }

    async def async_run_device_activation(
        self,
        activation_id: str,
    ) -> dict[str, Any]:
        self.activation_calls.append(activation_id)
        return {"ok": True, "id": activation_id}

    async def async_stop_doorbell_video(self) -> dict[str, Any]:
        self.stop_video_calls += 1
        return {"ok": True}

    async def async_answering_machine_messages(self) -> dict[str, Any]:
        self.video_messages_calls += 1
        return self._refreshed_video_messages

    async def async_apply_qml_patch(
        self,
        *,
        dynamic_homepage: bool = False,
    ) -> dict[str, Any]:
        _ = dynamic_homepage
        self.qml_patch_actions.append("apply")
        return {
            "available": True,
            "patched": True,
            "state": "patched",
            "core_patched": True,
            "core_state": "patched",
        }

    async def async_apply_qml_core_patch(self) -> dict[str, Any]:
        self.qml_patch_actions.append("core_apply")
        return {
            "available": True,
            "patched": False,
            "state": "original",
            "core_patched": True,
            "core_state": "patched",
        }

    async def async_restore_qml_core_patch(self) -> dict[str, Any]:
        self.qml_patch_actions.append("core_restore")
        return {
            "available": True,
            "patched": False,
            "state": "original",
            "core_patched": False,
            "core_state": "original",
        }

    async def async_restore_qml_patch(self) -> dict[str, Any]:
        self.qml_patch_actions.append("restore")
        return {
            "available": True,
            "patched": False,
            "state": "original",
            "core_patched": True,
            "core_state": "patched",
        }

    async def async_qml_patch_status(self) -> dict[str, Any]:
        if self._qml_status is not None:
            return self._qml_status
        if self.qml_patch_actions[-1:] == ["apply"]:
            return {
                "available": True,
                "patched": True,
                "state": "patched",
                "core_patched": True,
                "core_state": "patched",
            }
        if self.qml_patch_actions[-1:] == ["core_apply"]:
            return {
                "available": True,
                "patched": False,
                "state": "original",
                "core_patched": True,
                "core_state": "patched",
            }
        if self.qml_patch_actions[-1:] == ["restore"]:
            return {
                "available": True,
                "patched": False,
                "state": "original",
                "core_patched": True,
                "core_state": "patched",
            }
        return {
            "available": True,
            "patched": False,
            "state": "original",
            "core_patched": False,
            "core_state": "original",
        }

    async def async_reload_gui(self) -> dict[str, Any]:
        self.reload_gui_calls += 1
        return {"ok": True, "action": "reload_gui"}

    async def async_remove_agent(self) -> dict[str, Any]:
        self.remove_agent_calls += 1
        return {"ok": True, "action": "remove_agent", "scheduled": True}

    async def async_restart_agent(self) -> dict[str, Any]:
        self.restart_agent_calls += 1
        return {"ok": True, "action": "restart_agent", "scheduled": True}

    async def async_reboot(self) -> dict[str, Any]:
        self.reboot_calls += 1
        return {"ok": True, "action": "reboot", "scheduled": True}

    async def async_apply_firewall(self) -> dict[str, Any]:
        self.firewall_actions.append("apply")
        return {"available": True, "patched": True, "state": "patched"}

    async def async_restore_firewall(self) -> dict[str, Any]:
        self.firewall_actions.append("restore")
        return {"available": True, "patched": False, "state": "original"}

    async def async_apply_ipv6_firewall(self) -> dict[str, Any]:
        self.firewall_actions.append("apply_ipv6")
        return {
            "available": True,
            "family": "ipv6",
            "patched": True,
            "state": "patched",
        }

    async def async_restore_ipv6_firewall(self) -> dict[str, Any]:
        self.firewall_actions.append("restore_ipv6")
        return {
            "available": True,
            "family": "ipv6",
            "patched": False,
            "state": "original",
        }


class _FailingMemoApi(_FakeMemoApi):
    def __init__(self, method: str, error: Exception) -> None:
        super().__init__()
        self._method = method
        self._error = error

    def _maybe_raise(self, method: str) -> None:
        if self._method == method:
            raise self._error

    async def async_activations(self) -> dict[str, Any]:
        self._maybe_raise("activations")
        return await super().async_activations()

    async def async_run_device_activation(self, activation_id: str) -> dict[str, Any]:
        self._maybe_raise("run_device_activation")
        return await super().async_run_device_activation(activation_id)

    async def async_stop_doorbell_video(self) -> dict[str, Any]:
        self._maybe_raise("stop_doorbell_video")
        return await super().async_stop_doorbell_video()

    async def async_reboot(self) -> dict[str, Any]:
        self._maybe_raise("reboot")
        return await super().async_reboot()

    async def async_remove_agent(self) -> dict[str, Any]:
        self._maybe_raise("remove_agent")
        return await super().async_remove_agent()

    async def async_restart_agent(self) -> dict[str, Any]:
        self._maybe_raise("restart_agent")
        return await super().async_restart_agent()

    async def async_reload_gui(self) -> dict[str, Any]:
        self._maybe_raise("reload_gui")
        return await super().async_reload_gui()

    async def async_memos(self) -> dict[str, Any]:
        self._maybe_raise("memos")
        return await super().async_memos()

    async def async_answering_machine_messages(self) -> dict[str, Any]:
        self._maybe_raise("answering_machine_messages")
        return await super().async_answering_machine_messages()

    async def async_delete_memo(self, memo_id: str) -> dict[str, Any]:
        self._maybe_raise("delete_memo")
        return await super().async_delete_memo(memo_id)

    async def async_delete_answering_machine_message(
        self,
        message_id: str,
    ) -> dict[str, Any]:
        self._maybe_raise("delete_answering_machine_message")
        return await super().async_delete_answering_machine_message(message_id)


@dataclass
class _FakeConnectionState:
    available: bool = True


@dataclass
class _FakeRuntimeData:
    capabilities: dict[str, Any] = field(default_factory=dict)
    api: _FakeMemoApi | None = None
    connection_state: _FakeConnectionState = field(default_factory=_FakeConnectionState)
    answering_machine_messages: dict[str, Any] = field(default_factory=dict)
    answering_machine_messages_updated_at: Any = None
    answering_machine_messages_refresh_task: asyncio.Task[Any] | None = None
    memos: dict[str, Any] = field(default_factory=dict)
    memos_updated_at: Any = None
    memos_refresh_task: asyncio.Task[Any] | None = None
    qml_patch_status: dict[str, Any] = field(default_factory=dict)
    qml_patch_status_updated_at: Any = None
    device_user_status: dict[str, Any] = field(default_factory=dict)


@dataclass
class _FakeEntry:
    entry_id: str = "entry-1"
    title: str = "C300X"
    data: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    runtime_data: _FakeRuntimeData = field(default_factory=_FakeRuntimeData)


def test_supports_maintenance_action_requires_agent_capability_and_token() -> None:
    entry = _FakeEntry(
        data={CONF_MAINTENANCE_TOKEN: "maintenance-token"},
        runtime_data=_FakeRuntimeData(
            {
                "maintenance": {
                    "supported": True,
                    "ssh_start": True,
                    "reboot": True,
                    "agent_remove": True,
                    "agent_restart": True,
                    "firewall_apply": True,
                }
            }
        ),
    )

    assert maintenance_action_is_supported(
        entry.runtime_data.capabilities,
        "ssh_start",
        entry.data.get(CONF_MAINTENANCE_TOKEN),
    )
    assert maintenance_action_is_supported(
        entry.runtime_data.capabilities,
        "reboot",
        entry.data.get(CONF_MAINTENANCE_TOKEN),
    )
    assert maintenance_action_is_supported(
        entry.runtime_data.capabilities,
        "agent_remove",
        entry.data.get(CONF_MAINTENANCE_TOKEN),
    )
    assert maintenance_action_is_supported(
        entry.runtime_data.capabilities,
        "agent_restart",
        entry.data.get(CONF_MAINTENANCE_TOKEN),
    )
    assert not maintenance_action_is_supported(
        entry.runtime_data.capabilities,
        "ssh_stop",
        entry.data.get(CONF_MAINTENANCE_TOKEN),
    )
    assert maintenance_action_is_supported(
        entry.runtime_data.capabilities,
        "firewall_apply",
        entry.data.get(CONF_MAINTENANCE_TOKEN),
    )


def test_supports_maintenance_action_rejects_missing_token() -> None:
    entry = _FakeEntry(
        runtime_data=_FakeRuntimeData(
            {"maintenance": {"supported": True, "ssh_start": True}}
        ),
    )

    assert not maintenance_action_is_supported(
        entry.runtime_data.capabilities,
        "ssh_start",
        entry.data.get(CONF_MAINTENANCE_TOKEN),
    )


def test_supports_maintenance_action_rejects_missing_capability() -> None:
    entry = _FakeEntry(data={CONF_MAINTENANCE_TOKEN: "maintenance-token"})

    assert not maintenance_action_is_supported(
        entry.runtime_data.capabilities,
        "ssh_start",
        entry.data.get(CONF_MAINTENANCE_TOKEN),
    )


def test_maintenance_action_advertised_does_not_require_ha_token() -> None:
    capabilities = {"maintenance": {"supported": True, "ssh_start": True}}

    assert maintenance_action_is_advertised(capabilities, "ssh_start")
    assert not maintenance_action_is_supported(capabilities, "ssh_start", "")


def test_maintenance_buttons_are_always_created_but_capability_gated() -> None:
    async def _run() -> None:
        entry = _FakeEntry(
            runtime_data=_FakeRuntimeData(
                capabilities={
                    "maintenance": {
                    "supported": True,
                    "agent_remove": False,
                    "agent_restart": False,
                    "gui_reload": False,
                    "reboot": False,
                }
                }
            )
        )
        entities: list[Any] = []

        await async_setup_entry(
            _FakeHass(),  # type: ignore[arg-type]
            entry,  # type: ignore[arg-type]
            entities.extend,
        )

        maintenance_entities = {
            type(entity): entity
            for entity in entities
            if isinstance(
                entity,
                (
                    C300XReloadGuiButton,
                    C300XRemoveAgentButton,
                    C300XRestartAgentButton,
                    C300XRebootButton,
                ),
            )
        }
        assert set(maintenance_entities) == {
            C300XReloadGuiButton,
            C300XRemoveAgentButton,
            C300XRestartAgentButton,
            C300XRebootButton,
        }
        assert all(not entity.available for entity in maintenance_entities.values())

        entry.runtime_data.capabilities["maintenance"]["agent_remove"] = True
        entry.runtime_data.capabilities["maintenance"]["agent_restart"] = True
        entry.runtime_data.capabilities["maintenance"]["gui_reload"] = True
        entry.runtime_data.capabilities["maintenance"]["reboot"] = True
        assert all(entity.available for entity in maintenance_entities.values())

    asyncio.run(_run())


def test_remove_agent_button_is_created_without_agent_capabilities() -> None:
    async def _run() -> None:
        entry = _FakeEntry()
        entities: list[Any] = []

        await async_setup_entry(
            _FakeHass(),  # type: ignore[arg-type]
            entry,  # type: ignore[arg-type]
            entities.extend,
        )

        remove_agent = next(
            entity
            for entity in entities
            if isinstance(entity, C300XRemoveAgentButton)
        )
        assert remove_agent._attr_entity_registry_enabled_default is False
        assert remove_agent.available is False

    asyncio.run(_run())


def test_activation_buttons_are_created_from_agent_discovery() -> None:
    async def _run() -> None:
        api = _FakeMemoApi()
        entry = _FakeEntry(
            runtime_data=_FakeRuntimeData(
                capabilities={"activations": {"supported": True}},
                api=api,
            )
        )
        entities: list[Any] = []

        await async_setup_entry(
            _FakeHass(),  # type: ignore[arg-type]
            entry,  # type: ignore[arg-type]
            entities.extend,
        )

        activation_buttons = [
            entity
            for entity in entities
            if isinstance(entity, C300XDeviceActivationButton)
        ]
        assert len(activation_buttons) == 1
        button = activation_buttons[0]
        assert button._attr_name == "Front lock"
        assert button._attr_icon == "mdi:lock-open-variant"
        assert button.extra_state_attributes == {
            "activation_id": "front_lock",
            "activation_type": "lock",
            "address_mode": "manual",
            "address": "20",
            "source": "config",
        }

        await button.async_press()

        assert api.activation_calls == ["front_lock"]

    asyncio.run(_run())


def test_activation_discovery_ignores_agent_failures() -> None:
    async def _run() -> None:
        for error in (
            C300XAgentApiUnsupportedError("unsupported"),
            C300XAgentApiError("failed"),
        ):
            entry = _FakeEntry(
                runtime_data=_FakeRuntimeData(
                    capabilities={"activations": {"supported": True}},
                    api=_FailingMemoApi("activations", error),
                )
            )
            entities: list[Any] = []

            await async_setup_entry(
                _FakeHass(),  # type: ignore[arg-type]
                entry,  # type: ignore[arg-type]
                entities.extend,
            )

            assert not any(
                isinstance(entity, C300XDeviceActivationButton) for entity in entities
            )
            assert entry.runtime_data.activations == {
                "available": False,
                "supported": False,
                "items": [],
            }

    asyncio.run(_run())


def test_device_activation_button_translates_agent_errors() -> None:
    async def _run() -> None:
        for error in (
            C300XAgentApiUnsupportedError("unsupported"),
            C300XAgentApiError("failed"),
        ):
            entry = _FakeEntry(
                runtime_data=_FakeRuntimeData(
                    api=_FailingMemoApi("run_device_activation", error)
                )
            )
            button = C300XDeviceActivationButton(
                entry,  # type: ignore[arg-type]
                {"id": "front_lock", "name": "Front lock", "executable": True},
            )

            try:
                await button.async_press()
            except exceptions.HomeAssistantError:
                pass
            else:
                raise AssertionError("activation agent error was not translated")

    asyncio.run(_run())


def test_stop_doorbell_video_button_is_created_for_video_capability() -> None:
    async def _run() -> None:
        api = _FakeMemoApi()
        entry = _FakeEntry(
            data={CONF_VIDEO_ENABLED: True},
            runtime_data=_FakeRuntimeData(
                capabilities={"doorbell_video": {"supported": True}},
                api=api,
            ),
        )
        entities: list[Any] = []

        await async_setup_entry(
            _FakeHass(),  # type: ignore[arg-type]
            entry,  # type: ignore[arg-type]
            entities.extend,
        )

        stop_button = next(
            entity
            for entity in entities
            if isinstance(entity, C300XStopDoorbellVideoButton)
        )
        assert stop_button.available is True

        await stop_button.async_press()

        assert api.stop_video_calls == 1

    asyncio.run(_run())


def test_stop_doorbell_video_button_translates_agent_errors() -> None:
    async def _run() -> None:
        for error in (
            C300XAgentApiUnsupportedError("unsupported"),
            C300XAgentApiError("failed"),
        ):
            entry = _FakeEntry(
                runtime_data=_FakeRuntimeData(
                    api=_FailingMemoApi("stop_doorbell_video", error)
                )
            )
            button = C300XStopDoorbellVideoButton(entry)  # type: ignore[arg-type]

            try:
                await button.async_press()
            except exceptions.HomeAssistantError:
                pass
            else:
                raise AssertionError("stop-video agent error was not translated")

    asyncio.run(_run())


def test_stop_doorbell_video_button_requires_enabled_video() -> None:
    async def _run() -> None:
        entry = _FakeEntry(
            data={CONF_VIDEO_ENABLED: False},
            runtime_data=_FakeRuntimeData(
                capabilities={"doorbell_video": {"supported": True}},
                api=_FakeMemoApi(),
            ),
        )
        entities: list[Any] = []

        await async_setup_entry(
            _FakeHass(),  # type: ignore[arg-type]
            entry,  # type: ignore[arg-type]
            entities.extend,
        )

        assert not any(
            isinstance(entity, C300XStopDoorbellVideoButton) for entity in entities
        )

    asyncio.run(_run())


def test_action_buttons_translate_executor_agent_errors(monkeypatch) -> None:  # noqa: ANN001
    async def _run() -> None:
        for button_class, patched_name, expected_call in [
            (C300XStairLightButton, "async_trigger_stair_light", "stair"),
            (C300XDoorUnlockButton, "async_unlock_door", "unlock"),
        ]:
            for error in (
                C300XAgentApiUnsupportedError("unsupported"),
                C300XAgentApiError("failed"),
            ):
                calls: list[str] = []

                def _make_failing(
                    target_calls: list[str],
                    call_name: str,
                    raised_error: Exception,
                ) -> Any:
                    async def _failing(*_args: Any, **_kwargs: Any) -> None:
                        target_calls.append(call_name)
                        raise raised_error

                    return _failing

                monkeypatch.setattr(
                    "custom_components.bticino_c300x.button." + patched_name,
                    _make_failing(calls, expected_call, error),
                )
                entry = _FakeEntry()
                if button_class is C300XDoorUnlockButton:
                    button = button_class(  # type: ignore[call-arg]
                        entry,  # type: ignore[arg-type]
                        "default",
                        "Front door",
                    )
                else:
                    button = button_class(entry)  # type: ignore[call-arg,arg-type]
                button.hass = _FakeHass()

                try:
                    await button.async_press()
                except exceptions.HomeAssistantError:
                    assert calls == [expected_call]
                else:
                    raise AssertionError("executor agent error was not translated")

    asyncio.run(_run())


def test_qml_patch_apply_reports_transient_patching_status() -> None:
    async def _run() -> None:
        api = _FakeMemoApi(
            qml_status={"available": True, "patched": True, "state": "patched"}
        )
        entry = _FakeEntry(
            runtime_data=_FakeRuntimeData(
                api=api,
                qml_patch_status={
                    "available": True,
                    "patched": False,
                    "state": "original",
                    "core_patched": True,
                    "core_state": "patched",
                    "gui_running": True,
                },
            )
        )
        states: list[dict[str, Any]] = []

        await async_apply_qml_patch_and_confirm(
            entry,  # type: ignore[arg-type]
            lambda: states.append(dict(entry.runtime_data.qml_patch_status)),
        )

        assert [state["state"] for state in states] == ["patching", "patched"]
        assert states[0]["patched"] is None
        assert states[0]["core_patched"] is True
        assert states[0]["core_state"] == "patched"
        assert states[0]["gui_running"] is True

    asyncio.run(_run())


def test_qml_patch_restore_reports_transient_restoring_status() -> None:
    async def _run() -> None:
        api = _FakeMemoApi(
            qml_status={"available": True, "patched": False, "state": "original"}
        )
        entry = _FakeEntry(
            runtime_data=_FakeRuntimeData(
                api=api,
                qml_patch_status={
                    "available": True,
                    "patched": True,
                    "state": "patched",
                    "core_patched": True,
                    "core_state": "patched",
                },
            )
        )
        states: list[dict[str, Any]] = []

        await async_restore_qml_patch_and_confirm(
            entry,  # type: ignore[arg-type]
            lambda: states.append(dict(entry.runtime_data.qml_patch_status)),
        )

        assert [state["state"] for state in states] == ["restoring", "original"]
        assert states[0]["patched"] is None
        assert states[0]["core_patched"] is True
        assert states[0]["core_state"] == "patched"

    asyncio.run(_run())


def test_qml_core_patch_apply_reports_transient_core_status() -> None:
    async def _run() -> None:
        entry = _FakeEntry(
            runtime_data=_FakeRuntimeData(
                api=_FakeMemoApi(),
                qml_patch_status={
                    "available": True,
                    "patched": False,
                    "state": "original",
                    "core_patched": False,
                    "core_state": "original",
                },
            )
        )
        states: list[dict[str, Any]] = []

        await async_apply_qml_core_patch_and_confirm(
            entry,  # type: ignore[arg-type]
            lambda: states.append(dict(entry.runtime_data.qml_patch_status)),
        )

        assert [state["core_state"] for state in states] == [
            "core_patching",
            "patched",
        ]
        assert states[0]["patched"] is False
        assert states[0]["state"] == "original"
        assert states[0]["core_patched"] is None

    asyncio.run(_run())


def test_qml_core_patch_restore_reports_transient_core_status() -> None:
    async def _run() -> None:
        entry = _FakeEntry(
            runtime_data=_FakeRuntimeData(
                api=_FakeMemoApi(),
                qml_patch_status={
                    "available": True,
                    "patched": False,
                    "state": "original",
                    "core_patched": True,
                    "core_state": "patched",
                },
            )
        )
        states: list[dict[str, Any]] = []

        await async_restore_qml_core_patch_and_confirm(
            entry,  # type: ignore[arg-type]
            lambda: states.append(dict(entry.runtime_data.qml_patch_status)),
        )

        assert [state["core_state"] for state in states] == [
            "core_restoring",
            "original",
        ]
        assert states[0]["patched"] is False
        assert states[0]["state"] == "original"
        assert states[0]["core_patched"] is None

    asyncio.run(_run())


def test_reload_gui_button_calls_maintenance_api() -> None:
    async def _run() -> None:
        api = _FakeMemoApi()
        entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=api))
        button = C300XReloadGuiButton(entry)  # type: ignore[arg-type]

        await button.async_press()

        assert api.reload_gui_calls == 1

    asyncio.run(_run())


def test_remove_agent_button_calls_maintenance_api() -> None:
    async def _run() -> None:
        api = _FakeMemoApi()
        entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=api))
        button = C300XRemoveAgentButton(entry)  # type: ignore[arg-type]
        button.hass = _FakeHass()

        await button.async_press()

        assert api.remove_agent_calls == 1

    asyncio.run(_run())


def test_restart_agent_button_calls_maintenance_api() -> None:
    async def _run() -> None:
        api = _FakeMemoApi()
        entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=api))
        button = C300XRestartAgentButton(entry)  # type: ignore[arg-type]
        button.hass = _FakeHass()

        await button.async_press()

        assert api.restart_agent_calls == 1

    asyncio.run(_run())


def test_reboot_button_calls_maintenance_api() -> None:
    async def _run() -> None:
        api = _FakeMemoApi()
        entry = _FakeEntry(runtime_data=_FakeRuntimeData(api=api))
        button = C300XRebootButton(entry)  # type: ignore[arg-type]

        await button.async_press()

        assert api.reboot_calls == 1

    asyncio.run(_run())


def test_maintenance_buttons_translate_agent_errors() -> None:
    async def _run() -> None:
        button_cases = [
            (C300XRebootButton, "reboot"),
            (C300XRemoveAgentButton, "remove_agent"),
            (C300XRestartAgentButton, "restart_agent"),
            (C300XReloadGuiButton, "reload_gui"),
        ]
        for button_class, method in button_cases:
            for error in (
                C300XAgentApiUnsupportedError("unsupported"),
                C300XAgentApiError("failed"),
            ):
                entry = _FakeEntry(
                    runtime_data=_FakeRuntimeData(api=_FailingMemoApi(method, error))
                )
                button = button_class(entry)  # type: ignore[call-arg,arg-type]
                button.hass = _FakeHass()

                try:
                    await button.async_press()
                except exceptions.HomeAssistantError:
                    pass
                else:
                    raise AssertionError(f"{method} agent error was not translated")

    asyncio.run(_run())


def test_activation_icon_maps_known_and_unknown_types() -> None:
    assert _activation_icon("light") == "mdi:lightbulb-on"
    assert _activation_icon("stair_light") == "mdi:lightbulb-on"
    assert _activation_icon("scenario") == "mdi:play-box"
    assert _activation_icon("unknown") == "mdi:gesture-tap-button"


def test_memo_delete_support_requires_agent_capability() -> None:
    assert memo_delete_supported({"memos": {"supported": True, "delete": True}})
    assert not memo_delete_supported({"memos": {"supported": True}})
    assert not memo_delete_supported({"memos": False})


def test_video_message_delete_support_requires_agent_capability() -> None:
    assert answering_machine_message_delete_supported(
        {
            "answering_machine": {
                "supported": True,
                "messages": {"supported": True, "delete": True},
            }
        }
    )
    assert not answering_machine_message_delete_supported(
        {
            "answering_machine": {
                "supported": True,
                "messages": {"supported": True},
            }
        }
    )


def test_delete_buttons_require_active_gui_function_patch() -> None:
    async def _run() -> None:
        capabilities = {
            "answering_machine": {
                "supported": True,
                "messages": {"supported": True, "delete": True},
            },
            "memos": {"supported": True, "delete": True},
        }
        unpatched_entry = _FakeEntry(
            options={CONF_DEVICE_UI_ENABLED: True},
            runtime_data=_FakeRuntimeData(
                capabilities=capabilities,
                qml_patch_status={"available": True, "patched": False},
            )
        )
        patched_entry = _FakeEntry(
            options={CONF_DEVICE_UI_ENABLED: True},
            runtime_data=_FakeRuntimeData(
                capabilities=capabilities,
                qml_patch_status={"available": True, "patched": True},
            )
        )
        disabled_entry = _FakeEntry(
            options={CONF_DEVICE_UI_ENABLED: False},
            runtime_data=_FakeRuntimeData(
                capabilities=capabilities,
                qml_patch_status={"available": True, "patched": True},
            ),
        )
        unpatched_entities: list[Any] = []
        patched_entities: list[Any] = []
        disabled_entities: list[Any] = []

        await async_setup_entry(
            _FakeHass(),  # type: ignore[arg-type]
            unpatched_entry,  # type: ignore[arg-type]
            unpatched_entities.extend,
        )
        await async_setup_entry(
            _FakeHass(),  # type: ignore[arg-type]
            patched_entry,  # type: ignore[arg-type]
            patched_entities.extend,
        )
        await async_setup_entry(
            _FakeHass(),  # type: ignore[arg-type]
            disabled_entry,  # type: ignore[arg-type]
            disabled_entities.extend,
        )

        assert any(
            isinstance(entity, C300XDeleteLatestVideoMessageButton)
            for entity in unpatched_entities
        )
        assert any(
            isinstance(entity, C300XDeleteLatestTextMemoButton)
            for entity in unpatched_entities
        )
        assert not next(
            entity
            for entity in unpatched_entities
            if isinstance(entity, C300XDeleteLatestTextMemoButton)
        ).available
        assert not any(
            isinstance(entity, C300XDeleteLatestVideoMessageButton)
            for entity in disabled_entities
        )
        assert not any(
            isinstance(entity, C300XDeleteLatestTextMemoButton)
            for entity in disabled_entities
        )
        assert any(
            isinstance(entity, C300XDeleteLatestVideoMessageButton)
            for entity in patched_entities
        )
        assert any(
            isinstance(entity, C300XDeleteLatestTextMemoButton)
            for entity in patched_entities
        )
        assert any(
            isinstance(entity, C300XDeleteLatestVoiceMemoButton)
            for entity in patched_entities
        )

    asyncio.run(_run())


def test_delete_buttons_require_agent_delete_capabilities() -> None:
    async def _run() -> None:
        entry = _FakeEntry(
            options={CONF_DEVICE_UI_ENABLED: True},
            runtime_data=_FakeRuntimeData(
                capabilities={
                    "answering_machine": {
                        "supported": True,
                        "messages": {"supported": True, "delete": False},
                    },
                    "memos": {"supported": True, "delete": False},
                },
                qml_patch_status={"available": True, "patched": True},
            ),
        )
        entities: list[Any] = []

        await async_setup_entry(
            _FakeHass(),  # type: ignore[arg-type]
            entry,  # type: ignore[arg-type]
            entities.extend,
        )

        assert not any(
            isinstance(entity, C300XDeleteLatestVideoMessageButton)
            for entity in entities
        )
        assert not any(
            isinstance(entity, C300XDeleteLatestTextMemoButton)
            for entity in entities
        )
        assert not any(
            isinstance(entity, C300XDeleteLatestVoiceMemoButton)
            for entity in entities
        )

    asyncio.run(_run())


def test_delete_latest_video_message_button_deletes_and_refreshes() -> None:
    async def _run() -> None:
        refreshed_messages = {
            "available": True,
            "total": 0,
            "unread": 0,
            "read": 0,
            "messages": [],
        }
        api = _FakeMemoApi(refreshed_video_messages=refreshed_messages)
        entry = _FakeEntry(
            options={CONF_DEVICE_UI_ENABLED: True},
            runtime_data=_FakeRuntimeData(
                api=api,
                capabilities={
                    "answering_machine": {
                        "supported": True,
                        "messages": {"supported": True, "delete": True},
                    }
                },
                qml_patch_status={"available": True, "patched": True},
                answering_machine_messages={
                    "available": True,
                    "total": 2,
                    "unread": 1,
                    "messages": [
                        {
                            "id": "message_old",
                            "has_video": True,
                            "unix_time": 1709990000,
                        },
                        {
                            "id": "message_new",
                            "has_video": True,
                            "unix_time": 1710000122,
                            "iso_time": "2024-03-09T16:02:02Z",
                            "read": False,
                            "media_mime_type": "video/x-msvideo",
                            "media_size": 42,
                        },
                    ],
                },
            )
        )
        entity = C300XDeleteLatestVideoMessageButton(entry)  # type: ignore[arg-type]
        entity.hass = _FakeHass()

        assert entity.available is True
        assert entity.extra_state_attributes["latest_message_id"] == "message_new"
        assert entity.extra_state_attributes["has_message"] is True

        await entity.async_press()

        assert api.video_delete_calls == ["message_new"]
        assert api.video_messages_calls == 1
        assert entry.runtime_data.answering_machine_messages == refreshed_messages
        assert entry.runtime_data.answering_machine_messages_updated_at is not None
        assert entity.available is True

    asyncio.run(_run())


def test_delete_latest_text_memo_button_deletes_and_refreshes() -> None:
    async def _run() -> None:
        refreshed_memos = {
            "available": True,
            "total": 1,
            "text_total": 0,
            "voice_total": 1,
            "memos": [{"id": "voice/memo_1", "kind": "voice"}],
        }
        api = _FakeMemoApi(refreshed_memos=refreshed_memos)
        entry = _FakeEntry(
            options={CONF_DEVICE_UI_ENABLED: True},
            runtime_data=_FakeRuntimeData(
                api=api,
                capabilities={"memos": {"supported": True, "delete": True}},
                qml_patch_status={"available": True, "patched": True},
                memos={
                    "available": True,
                    "total": 3,
                    "text_total": 2,
                    "voice_total": 1,
                    "memos": [
                        {
                            "id": "text/older",
                            "kind": "text",
                            "unix_time": 1709990000,
                        },
                        {
                            "id": "text/newer",
                            "kind": "text",
                            "unix_time": 1710000122,
                            "text": "new memo",
                        },
                        {"id": "voice/memo_1", "kind": "voice"},
                    ],
                },
            )
        )
        entity = C300XDeleteLatestTextMemoButton(entry)  # type: ignore[arg-type]
        entity.hass = _FakeHass()

        assert entity.available is True
        assert entity.extra_state_attributes["latest_memo_id"] == "text/newer"
        assert entity.extra_state_attributes["has_memo"] is True

        await entity.async_press()

        assert api.delete_calls == ["text/newer"]
        assert api.memos_calls == 1
        assert entry.runtime_data.memos == refreshed_memos
        assert entry.runtime_data.memos_updated_at is not None
        assert entity.available is True

    asyncio.run(_run())


def test_delete_latest_voice_memo_button_deletes_and_refreshes() -> None:
    async def _run() -> None:
        refreshed_memos = {
            "available": True,
            "total": 1,
            "text_total": 1,
            "voice_total": 0,
            "memos": [{"id": "text/memo_1", "kind": "text"}],
        }
        api = _FakeMemoApi(refreshed_memos=refreshed_memos)
        entry = _FakeEntry(
            options={CONF_DEVICE_UI_ENABLED: True},
            runtime_data=_FakeRuntimeData(
                api=api,
                capabilities={"memos": {"supported": True, "delete": True}},
                qml_patch_status={"available": True, "patched": True},
                memos={
                    "available": True,
                    "total": 3,
                    "text_total": 1,
                    "voice_total": 2,
                    "memos": [
                        {"id": "text/memo_1", "kind": "text"},
                        {
                            "id": "voice/older",
                            "kind": "voice",
                            "unix_time": 1709990000,
                        },
                        {
                            "id": "voice/newer",
                            "kind": "voice",
                            "unix_time": 1710000122,
                            "has_audio": True,
                        },
                    ],
                },
            )
        )
        entity = C300XDeleteLatestVoiceMemoButton(entry)  # type: ignore[arg-type]
        entity.hass = _FakeHass()

        assert entity.available is True
        assert entity.extra_state_attributes["latest_memo_id"] == "voice/newer"
        assert entity.extra_state_attributes["has_memo"] is True

        await entity.async_press()

        assert api.delete_calls == ["voice/newer"]
        assert api.memos_calls == 1
        assert entry.runtime_data.memos == refreshed_memos
        assert entry.runtime_data.memos_updated_at is not None
        assert entity.available is True

    asyncio.run(_run())


def test_delete_latest_text_memo_button_noops_when_missing_memo() -> None:
    async def _run() -> None:
        api = _FakeMemoApi(
            refreshed_memos={
                "available": True,
                "total": 0,
                "text_total": 0,
                "voice_total": 0,
                "memos": [],
            },
        )
        entry = _FakeEntry(
            options={CONF_DEVICE_UI_ENABLED: True},
            runtime_data=_FakeRuntimeData(
                api=api,
                capabilities={"memos": {"supported": True, "delete": True}},
                qml_patch_status={"available": True, "patched": True},
                memos={"available": True, "memos": []},
            )
        )
        entity = C300XDeleteLatestTextMemoButton(entry)  # type: ignore[arg-type]
        entity.hass = _FakeHass()

        assert entity.available is True

        await entity.async_press()

        assert api.delete_calls == []
        assert api.memos_calls == 1
        assert entry.runtime_data.memos_updated_at is not None
        assert entity.available is True

    asyncio.run(_run())


def test_delete_latest_text_memo_button_translates_refresh_failure() -> None:
    async def _run() -> None:
        entry = _FakeEntry(
            options={CONF_DEVICE_UI_ENABLED: True},
            runtime_data=_FakeRuntimeData(
                api=_FailingMemoApi("memos", C300XAgentApiError("failed")),
                capabilities={"memos": {"supported": True, "delete": True}},
                qml_patch_status={"available": True, "patched": True},
                memos={"available": True, "memos": []},
            ),
        )
        entity = C300XDeleteLatestTextMemoButton(entry)  # type: ignore[arg-type]
        entity.hass = _FakeHass()

        try:
            await entity.async_press()
        except exceptions.HomeAssistantError:
            assert entity.available is False
        else:
            raise AssertionError("memo refresh failure was not translated")

    asyncio.run(_run())


def test_delete_latest_buttons_translate_delete_failures() -> None:
    async def _run() -> None:
        cases = [
            (
                C300XDeleteLatestTextMemoButton,
                "delete_memo",
                _FakeRuntimeData(
                    api=_FailingMemoApi("delete_memo", C300XAgentApiError("failed")),
                    capabilities={"memos": {"supported": True, "delete": True}},
                    qml_patch_status={"available": True, "patched": True},
                    memos={
                        "available": True,
                        "text_total": 1,
                        "memos": [{"id": "text/memo_1", "kind": "text"}],
                    },
                ),
            ),
            (
                C300XDeleteLatestVideoMessageButton,
                "delete_answering_machine_message",
                _FakeRuntimeData(
                    api=_FailingMemoApi(
                        "delete_answering_machine_message",
                        C300XAgentApiUnsupportedError("unsupported"),
                    ),
                    capabilities={
                        "answering_machine": {
                            "supported": True,
                            "messages": {"supported": True, "delete": True},
                        }
                    },
                    qml_patch_status={"available": True, "patched": True},
                    answering_machine_messages={
                        "available": True,
                        "total": 1,
                        "messages": [{"id": "message_1", "has_video": True}],
                    },
                ),
            ),
        ]
        for button_class, _method, runtime_data in cases:
            entry = _FakeEntry(
                options={CONF_DEVICE_UI_ENABLED: True},
                runtime_data=runtime_data,
            )
            button = button_class(entry)  # type: ignore[call-arg,arg-type]
            button.hass = _FakeHass()

            try:
                await button.async_press()
            except exceptions.HomeAssistantError:
                pass
            else:
                raise AssertionError("delete failure was not translated")

    asyncio.run(_run())


def test_delete_latest_text_memo_button_ignores_stale_refresh_failure() -> None:
    entry = _FakeEntry(
        options={CONF_DEVICE_UI_ENABLED: True},
        runtime_data=_FakeRuntimeData(
            capabilities={"memos": {"supported": True, "delete": True}},
            qml_patch_status={"available": True, "patched": True},
            memos={"available": True, "memos": []},
        )
    )
    entity = C300XDeleteLatestTextMemoButton(entry)  # type: ignore[arg-type]

    entity._attr_available = False

    assert entity.available is False


def test_delete_latest_text_memo_button_stays_available_before_cache_warmup() -> None:
    entry = _FakeEntry(
        options={CONF_DEVICE_UI_ENABLED: True},
        runtime_data=_FakeRuntimeData(
            capabilities={"memos": {"supported": True, "delete": True}},
            qml_patch_status={"available": True, "patched": True},
            memos={"available": True, "memos": []},
        )
    )
    entity = C300XDeleteLatestTextMemoButton(entry)  # type: ignore[arg-type]

    assert entity.available is True


def test_delete_latest_text_memo_button_stays_available_when_loaded_store_empty() -> None:
    entry = _FakeEntry(
        options={CONF_DEVICE_UI_ENABLED: True},
        runtime_data=_FakeRuntimeData(
            capabilities={"memos": {"supported": True, "delete": True}},
            qml_patch_status={"available": True, "patched": True},
            memos={
                "available": True,
                "total": 0,
                "text_total": 0,
                "voice_total": 0,
                "memos": [],
            },
            memos_updated_at=object(),
        )
    )
    entity = C300XDeleteLatestTextMemoButton(entry)  # type: ignore[arg-type]

    assert entity.available is True


def test_delete_latest_memo_buttons_noop_for_missing_kind() -> None:
    entry = _FakeEntry(
        options={CONF_DEVICE_UI_ENABLED: True},
        runtime_data=_FakeRuntimeData(
            capabilities={"memos": {"supported": True, "delete": True}},
            qml_patch_status={"available": True, "patched": True},
            memos={
                "available": True,
                "total": 1,
                "text_total": 1,
                "voice_total": 0,
                "memos": [{"id": "text/memo_1", "kind": "text"}],
            },
        )
    )

    text_button = C300XDeleteLatestTextMemoButton(entry)  # type: ignore[arg-type]
    voice_button = C300XDeleteLatestVoiceMemoButton(entry)  # type: ignore[arg-type]

    assert text_button.available is True
    assert voice_button.available is True


def test_delete_latest_video_message_button_stays_available_without_message() -> None:
    empty_entry = _FakeEntry(
        options={CONF_DEVICE_UI_ENABLED: True},
        runtime_data=_FakeRuntimeData(
            capabilities={
                "answering_machine": {
                    "supported": True,
                    "messages": {"supported": True, "delete": True},
                }
            },
            qml_patch_status={"available": True, "patched": True},
            answering_machine_messages={
                "available": True,
                "total": 0,
                "unread": 0,
                "messages": [],
            },
        )
    )
    message_entry = _FakeEntry(
        options={CONF_DEVICE_UI_ENABLED: True},
        runtime_data=_FakeRuntimeData(
            capabilities=empty_entry.runtime_data.capabilities,
            qml_patch_status={"available": True, "patched": True},
            answering_machine_messages={
                "available": True,
                "total": 1,
                "unread": 1,
                "messages": [{"id": "message_1", "has_video": True}],
            },
        )
    )

    empty_button = C300XDeleteLatestVideoMessageButton(empty_entry)  # type: ignore[arg-type]
    message_button = C300XDeleteLatestVideoMessageButton(message_entry)  # type: ignore[arg-type]

    assert empty_button.available is True
    assert message_button.available is True


def test_delete_latest_video_button_stays_available_before_cache_warmup() -> None:
    entry = _FakeEntry(
        options={CONF_DEVICE_UI_ENABLED: True},
        runtime_data=_FakeRuntimeData(
            capabilities={
                "answering_machine": {
                    "supported": True,
                    "messages": {"supported": True, "delete": True},
                }
            },
            qml_patch_status={"available": True, "patched": True},
            answering_machine_messages={},
        )
    )
    entity = C300XDeleteLatestVideoMessageButton(entry)  # type: ignore[arg-type]

    assert entity.available is True


def test_delete_latest_video_button_update_sets_availability() -> None:
    async def _run() -> None:
        entry = _FakeEntry(
            runtime_data=_FakeRuntimeData(
                api=_FakeMemoApi(
                    refreshed_video_messages={
                        "available": False,
                        "messages": [],
                    }
                ),
            ),
        )
        entity = C300XDeleteLatestVideoMessageButton(entry)  # type: ignore[arg-type]

        await entity.async_update()

        assert entity.available is False

    asyncio.run(_run())


def test_delete_latest_video_button_update_handles_refresh_failure() -> None:
    async def _run() -> None:
        entry = _FakeEntry(
            runtime_data=_FakeRuntimeData(
                api=_FailingMemoApi(
                    "answering_machine_messages",
                    C300XAgentApiError("failed"),
                ),
            ),
        )
        entity = C300XDeleteLatestVideoMessageButton(entry)  # type: ignore[arg-type]

        await entity.async_update()

        assert entity.available is False

    asyncio.run(_run())


def test_delete_latest_memo_button_refreshes_from_agent_event_without_sensor() -> None:
    async def _run() -> None:
        api = _FakeMemoApi(
            refreshed_memos={
                "available": True,
                "total": 1,
                "text_total": 1,
                "voice_total": 0,
                "memos": [{"id": "text/memo_1", "kind": "text"}],
            }
        )
        entry = _FakeEntry(
            options={CONF_DEVICE_UI_ENABLED: True},
            runtime_data=_FakeRuntimeData(
                api=api,
                capabilities={"memos": {"supported": True, "delete": True}},
                qml_patch_status={"available": True, "patched": True},
                memos={"available": True, "memos": []},
            ),
        )
        entity = C300XDeleteLatestTextMemoButton(entry)  # type: ignore[arg-type]
        entity.hass = _FakeHass()

        entity._handle_agent_event(
            types.SimpleNamespace(
                data={"entry_id": entry.entry_id, "event_key": "memos_changed"}
            )
        )
        task = entry.runtime_data.memos_refresh_task
        assert task is not None
        await task

        assert api.memos_calls == 1
        assert entity.available is True

    asyncio.run(_run())


def test_delete_latest_video_button_refreshes_from_agent_event_without_sensor() -> None:
    async def _run() -> None:
        api = _FakeMemoApi(
            refreshed_video_messages={
                "available": True,
                "total": 1,
                "unread": 1,
                "messages": [{"id": "message_1", "has_video": True}],
            }
        )
        entry = _FakeEntry(
            options={CONF_DEVICE_UI_ENABLED: True},
            runtime_data=_FakeRuntimeData(
                api=api,
                capabilities={
                    "answering_machine": {
                        "supported": True,
                        "messages": {"supported": True, "delete": True},
                    }
                },
                qml_patch_status={"available": True, "patched": True},
                answering_machine_messages={"available": True, "messages": []},
            ),
        )
        entity = C300XDeleteLatestVideoMessageButton(entry)  # type: ignore[arg-type]
        entity.hass = _FakeHass()

        entity._handle_agent_event(
            types.SimpleNamespace(
                data={
                    "entry_id": entry.entry_id,
                    "event_key": "answering_machine_messages_changed",
                }
            )
        )
        task = entry.runtime_data.answering_machine_messages_refresh_task
        assert task is not None
        await task

        assert api.video_messages_calls == 1
        assert entity.available is True

    asyncio.run(_run())


def test_delete_latest_text_memo_button_is_unavailable_when_store_unavailable() -> None:
    entry = _FakeEntry(
        options={CONF_DEVICE_UI_ENABLED: True},
        runtime_data=_FakeRuntimeData(
            capabilities={"memos": {"supported": True, "delete": True}},
            qml_patch_status={"available": True, "patched": True},
            memos={"available": False, "memos": []},
        )
    )
    entity = C300XDeleteLatestTextMemoButton(entry)  # type: ignore[arg-type]

    assert entity.available is False


def test_delete_latest_memo_attributes_handle_non_dict_store() -> None:
    entry = _FakeEntry(
        options={CONF_DEVICE_UI_ENABLED: True},
        runtime_data=_FakeRuntimeData(
            capabilities={"memos": {"supported": True, "delete": True}},
            qml_patch_status={"available": True, "patched": True},
        ),
    )
    entry.runtime_data.memos = []  # type: ignore[assignment]
    entity = C300XDeleteLatestTextMemoButton(entry)  # type: ignore[arg-type]

    assert entity.extra_state_attributes == {
        "kind": "text",
        "has_memo": False,
        "total": None,
        "latest_memo_id": None,
    }


def test_delete_latest_video_attributes_handle_non_dict_store() -> None:
    entry = _FakeEntry(
        options={CONF_DEVICE_UI_ENABLED: True},
        runtime_data=_FakeRuntimeData(
            capabilities={
                "answering_machine": {
                    "supported": True,
                    "messages": {"supported": True, "delete": True},
                }
            },
            qml_patch_status={"available": True, "patched": True},
        ),
    )
    entry.runtime_data.answering_machine_messages = []  # type: ignore[assignment]
    entity = C300XDeleteLatestVideoMessageButton(entry)  # type: ignore[arg-type]

    assert entity.extra_state_attributes == {
        "has_message": False,
        "total": None,
        "unread": None,
        "latest_message_id": None,
    }


def test_gui_required_delete_button_unavailable_when_agent_connection_is_down() -> None:
    entry = _FakeEntry(
        options={CONF_DEVICE_UI_ENABLED: True},
        runtime_data=_FakeRuntimeData(
            capabilities={"memos": {"supported": True, "delete": True}},
            connection_state=_FakeConnectionState(available=False),
            qml_patch_status={"available": True, "patched": True},
            memos={"available": True, "memos": []},
        ),
    )
    entity = C300XDeleteLatestTextMemoButton(entry)  # type: ignore[arg-type]

    assert entity.available is False


def test_delete_latest_text_memo_button_respects_connection_state() -> None:
    entry = _FakeEntry(
        options={CONF_DEVICE_UI_ENABLED: True},
        runtime_data=_FakeRuntimeData(
            capabilities={"memos": {"supported": True, "delete": True}},
            connection_state=_FakeConnectionState(available=False),
            qml_patch_status={"available": True, "patched": True},
            memos={"available": True, "memos": []},
        )
    )
    entity = C300XDeleteLatestTextMemoButton(entry)  # type: ignore[arg-type]

    assert entity.available is False
