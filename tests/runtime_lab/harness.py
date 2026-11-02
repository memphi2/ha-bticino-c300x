"""Real HA runtime with loopback HTTP and no frontend/go2rtc processes."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

from aiohttp import ThreadedResolver
from aiohttp.test_utils import TestServer
from fake_agent import EVENT_TOKEN, TOKEN, FakeAgent
from homeassistant import auth, bootstrap, config_entries, core, loader
from homeassistant.components import webhook
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.bticino_c300x import const, events
from custom_components.bticino_c300x.media import async_setup_media_view
from custom_components.bticino_c300x.runtime_manager import BASE_PLATFORMS

try:
    from homeassistant.components.http.server import HomeAssistantHTTP
except ModuleNotFoundError as err:
    if err.name != "homeassistant.components.http.server":
        raise
    from homeassistant.components.http import HomeAssistantHTTP

ROOT = Path(__file__).resolve().parents[2]


class LoopbackResolver(ThreadedResolver):
    """Match HA resolver ownership without starting mDNS in the test lab."""

    async def close(self):
        pass

    async def real_close(self):
        await super().close()


class RuntimeLab:
    """Exercise actual config entries, entity platforms, services and webhooks."""

    def __init__(self, config_dir: Path, *, recorder=False, video=False) -> None:
        self.config_dir = config_dir
        self.recorder_enabled = recorder
        self.video_enabled = video
        self.stack = AsyncExitStack()
        self.agent = FakeAgent()
        self.loop_errors = []

    async def __aenter__(self):
        await self.stack.__aenter__()
        try:
            await self.stack.enter_async_context(self.agent)
            self.config_dir.mkdir(parents=True, exist_ok=True)
            (self.config_dir / "custom_components").symlink_to(
                ROOT / "custom_components", target_is_directory=True
            )
            self.hass = core.HomeAssistant(str(self.config_dir))
            hass = self.hass
            loop = asyncio.get_running_loop()
            old_handler = loop.get_exception_handler()
            loop.set_exception_handler(
                lambda _loop, context: self.loop_errors.append(context)
            )
            self.stack.callback(loop.set_exception_handler, old_handler)
            if hasattr(aiohttp_client, "_async_make_resolver"):
                self.stack.enter_context(
                    patch.object(
                        aiohttp_client,
                        "_async_make_resolver",
                        lambda _hass: LoopbackResolver(),
                    )
                )
            else:
                self.stack.enter_context(
                    patch.object(aiohttp_client, "AsyncResolver", LoopbackResolver)
                )
            hass.config.skip_pip = True
            hass.config.time_zone = "UTC"
            loader.async_setup(hass)
            hass.config_entries = config_entries.ConfigEntries(hass, {})
            await bootstrap.async_load_base_functionality(hass)
            self.stack.push_async_callback(hass.async_stop)
            hass.http = HomeAssistantHTTP(
                hass, None, None, None, ["127.0.0.1"], 0, [], "modern"
            )
            hass.auth = await auth.auth_manager_from_config(hass, [], [])
            await hass.http.async_initialize(
                cors_origins=[],
                use_x_forwarded_for=False,
                login_threshold=-1,
                is_ban_enabled=False,
                use_x_frame_options=True,
            )
            # Frontend assets and go2rtc processes are not loaded. Token checks,
            # entity platforms, services, registries and lifecycle are production.
            hass.config.components.update(
                {"http", "frontend", "lovelace", "go2rtc", "websocket_api"}
            )
            assert await async_setup_component(hass, "homeassistant", {})
            assert await async_setup_component(hass, "webhook", {})
            if self.recorder_enabled:
                from homeassistant.helpers.recorder import async_initialize_recorder

                async_initialize_recorder(hass)
                assert await async_setup_component(
                    hass,
                    "recorder",
                    {
                        "recorder": {
                            "db_url": f"sqlite:///{self.config_dir / 'recorder.db'}",
                            "auto_purge": False,
                            "commit_interval": 0,
                        }
                    },
                )
            for platform in BASE_PLATFORMS:
                assert await async_setup_component(hass, platform, {})
            if self.video_enabled:
                assert await async_setup_component(hass, "camera", {})
            self.server = TestServer(hass.http.app, host="127.0.0.1")
            # Routes must be registered before aiohttp freezes the application.
            from custom_components.bticino_c300x import async_setup

            await async_setup(hass, {})
            async_setup_media_view(hass)
            hass.config.components.add(const.DOMAIN)
            await self.server.start_server()
            self.stack.push_async_callback(self.server.close)

            async def callback_url(_hass, _entry, webhook_id):
                return str(
                    self.server.make_url(webhook.async_generate_path(webhook_id))
                )

            self.stack.enter_context(
                patch.object(events, "async_generate_agent_callback_url", callback_url)
            )
            self.stack.enter_context(
                patch.object(events, "_REGISTRATION_RETRY_SECONDS", 0.05)
            )
            self.stack.enter_context(
                patch.object(events, "_ENTITY_REGISTRY_REFRESH_SECONDS", 0.01)
            )
            self.stack.enter_context(
                patch.object(events, "DEFAULT_RECONNECT_GRACE_SECONDS", 0.02)
            )
            await hass.async_start()
            return self
        except BaseException:
            await self.stack.aclose()
            raise

    async def __aexit__(self, *_):
        try:
            for entry in self.hass.config_entries.async_entries(const.DOMAIN):
                await self.hass.config_entries.async_unload(entry.entry_id)
        finally:
            try:
                await self.hass.async_stop()
            finally:
                await self.stack.aclose()
        assert not self.loop_errors, self.loop_errors

    async def add_entry(self, *, enabled_sensors=(), name="synthetic"):
        self.entry = config_entries.ConfigEntry(
            version=1,
            minor_version=2,
            domain=const.DOMAIN,
            title=f"{name.title()} Door",
            source="user",
            unique_id=f"{name}-device",
            discovery_keys=MappingProxyType({}),
            subentries_data=None,
            disabled_by=config_entries.ConfigEntryDisabler.USER
            if enabled_sensors
            else None,
            options={},
            data={
                const.CONF_AGENT_HOST: "127.0.0.1",
                const.CONF_AGENT_PORT: self.agent.server.port,
                const.CONF_AGENT_TOKEN: TOKEN,
                const.CONF_WEBHOOK_ID: f"{name}-display",
                const.CONF_SHARED_SECRET: "synthetic-display-token",
                const.CONF_EVENT_WEBHOOK_ID: f"{name}-events",
                const.CONF_EVENT_WEBHOOK_TOKEN: EVENT_TOKEN,
                const.CONF_VIDEO_ENABLED: self.video_enabled,
                const.CONF_DEVICE_UI_ENABLED: False,
            },
        )
        await self.hass.config_entries.async_add(self.entry)
        for key in enabled_sensors:
            er.async_get(self.hass).async_get_or_create(
                "sensor",
                const.DOMAIN,
                f"{self.entry.entry_id}_{key}",
                config_entry=self.entry,
                suggested_object_id=f"synthetic_{key}",
                disabled_by=None,
            )
        if enabled_sensors:
            await self.hass.config_entries.async_set_disabled_by(
                self.entry.entry_id, None
            )
        await self.settle()
        assert self.entry.state is config_entries.ConfigEntryState.LOADED, (
            self.entry.state
        )
        assert not self.agent.unexpected, self.agent.unexpected
        return self.entry

    async def settle(self):
        await self.hass.async_block_till_done()

    def entity(self, key, domain="sensor"):
        result = er.async_get(self.hass).async_get_entity_id(
            domain, const.DOMAIN, f"{self.entry.entry_id}_{key}"
        )
        assert result, (domain, key)
        return result

    async def wait_for(self, predicate):
        async with asyncio.timeout(5):
            while not predicate():  # noqa: ASYNC110 - bounded observation of production state
                await asyncio.sleep(0.01)

    async def push(self, event_type, data, **kwargs):
        result = await self.agent.push(
            str(self.server.make_url("/api/webhook/synthetic-events")),
            event_type,
            data,
            **kwargs,
        )
        await self.settle()
        return result
