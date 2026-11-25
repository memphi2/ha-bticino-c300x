"""Shared transport core for the C300X device-agent client mixins."""

from __future__ import annotations

import json
from typing import Any, cast

from aiohttp import ClientError, ClientSession

from ._api_normalize import (
    _agent_error_field,
    _http_error_text,
)
from .agent_update import (
    MAINTENANCE_BUSY_ACTION_WAIT_SECONDS,
    MAINTENANCE_BUSY_WAIT_SECONDS,
    async_retry_update_maintenance_busy,
)
from .api_errors import (
    C300XAgentApiAuthError,
    C300XAgentApiConnectionError,
    C300XAgentApiResponseError,
    C300XAgentApiUnsupportedError,
    C300XAgentUpdateError,
    C300XDeviceNotRegisteredError,
    C300XDisplayBridgeNotRegisteredError,
    C300XStationBusyError,
)
from .const import (
    HEADER_MAINTENANCE_TOKEN,
)
from .http_body import read_capped_body

_SETUP_TIMEOUT = 2.0
# Defensive cap on agent JSON responses read into memory. Real responses
# (status, diagnostics, memo/voicemail lists) are far smaller; this only guards
# against a runaway or hostile body.
_MAX_JSON_RESPONSE_BYTES = 8 * 1024 * 1024
_MAX_MEDIA_RESPONSE_BYTES = 32 * 1024 * 1024


def _decode_text(raw: bytes, charset: str | None) -> str:
    """Decode an agent response; a charset Python does not know means UTF-8."""

    try:
        return raw.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")

# A request that restarts the device or removes the agent is answered after
# the agent started SSH, which it gives up to 60 s.
_RESTART_WRITE_TIMEOUT = 75.0


class _C300XApiCore:
    """HTTP transport + shared helpers for the api mixins."""

    def __init__(
        self,
        session: ClientSession,
        base_url: str,
        token: str,
        maintenance_token: str = "",
        timeout: float = 5.0,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._maintenance_token = maintenance_token
        self._timeout = timeout

    async def _request_json(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        request_timeout: float | None = None,
    ) -> Any:
        """Send a request, waiting out a maintenance job the agent is running.

        The agent runs one maintenance job at a time, also a short status
        read that Home Assistant asked for itself, and refuses every other
        maintenance request meanwhile, before it does anything for it. A
        read waits as long as such a job may take, an action only briefly.
        A caller that waits itself (the update steps) decides the time.
        """

        return await async_retry_update_maintenance_busy(
            lambda: self._request_json_once(
                method, path, json_data, extra_headers, request_timeout
            ),
            MAINTENANCE_BUSY_WAIT_SECONDS if method == "GET"
            else MAINTENANCE_BUSY_ACTION_WAIT_SECONDS,
        )

    async def _request_json_once(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        request_timeout: float | None = None,
    ) -> Any:
        try:
            async with self._session.request(
                method,
                f"{self._base_url}{path}",
                allow_redirects=False,
                headers=self._auth_headers(extra_headers),
                json=json_data,
                timeout=cast(
                    Any,
                    self._timeout if request_timeout is None else request_timeout,
                ),
            ) as response:
                if response.status == 401:
                    raise C300XAgentApiAuthError()
                raw = await read_capped_body(
                    response.content,
                    response.content_length,
                    _MAX_JSON_RESPONSE_BYTES,
                )
                if raw is None:
                    if response.status == 403:
                        self._raise_for_agent_status(403, "", path)
                    raise C300XAgentApiResponseError("device agent response too large")
                text = _decode_text(raw, response.charset)
                self._raise_for_agent_status(response.status, text, path)
        except TimeoutError as err:
            raise C300XAgentApiConnectionError(
                "device-agent request timed out"
            ) from err
        except ClientError as err:
            raise C300XAgentApiConnectionError(str(err)) from err

        try:
            return json.loads(text) if text else {}
        except json.JSONDecodeError as err:
            raise C300XAgentApiResponseError(
                "device agent returned invalid JSON"
            ) from err

    async def _request_bytes(
        self,
        method: str,
        path: str,
        extra_headers: dict[str, str] | None = None,
        *,
        max_bytes: int | None = None,
    ) -> tuple[bytes, str]:
        media_limit = (
            _MAX_MEDIA_RESPONSE_BYTES
            if max_bytes is None else min(max_bytes, _MAX_MEDIA_RESPONSE_BYTES)
        )
        try:
            async with self._session.request(
                method,
                f"{self._base_url}{path}",
                allow_redirects=False,
                headers=self._auth_headers(extra_headers),
                timeout=cast(Any, self._timeout),
            ) as response:
                if response.status == 401:
                    raise C300XAgentApiAuthError()
                content = await read_capped_body(
                    response.content,
                    response.content_length,
                    media_limit
                    if 200 <= response.status < 300
                    else _MAX_JSON_RESPONSE_BYTES,
                )
                if content is None:
                    if response.status == 403:
                        self._raise_for_agent_status(403, "", path)
                    raise C300XAgentApiResponseError("device agent response too large")
                if response.status < 200 or response.status >= 300:
                    self._raise_for_agent_status(
                        response.status,
                        _decode_text(content, response.charset),
                        path,
                    )
                content_type = response.headers.get(
                    "Content-Type",
                    "application/octet-stream",
                )
        except TimeoutError as err:
            raise C300XAgentApiConnectionError(
                "device-agent request timed out"
            ) from err
        except ClientError as err:
            raise C300XAgentApiConnectionError(str(err)) from err
        return content, content_type.split(";", 1)[0]

    def _auth_headers(self, extra_headers: dict[str, str] | None) -> dict[str, str]:
        """Return the bearer auth headers merged with any caller headers."""

        headers = {"Authorization": f"Bearer {self._token}"}
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _raise_for_agent_status(self, status: int, text: str, path: str) -> None:
        """Map a non-success agent HTTP status to the right client exception."""

        if status == 401:
            raise C300XAgentApiAuthError()
        if status == 403:
            try:
                payload = json.loads(text)
            except (ValueError, TypeError):
                payload = {}
            code = payload.get("error") if isinstance(payload, dict) else None
            if code in (
                "loopback_required", "ui_header_required", "gui_header_required",
                "ringer_gui_header_required",
            ):
                raise C300XAgentApiResponseError("device agent denied this operation")
            raise C300XAgentApiAuthError(
                maintenance=code == "maintenance_unauthorized"
                or path.startswith("/api/v1/maintenance/")
            )
        if status in (404, 501):
            # 501 is the agent's answer for an /api/v1 route it does not have.
            if (
                path == "/api/v1/display-bridge/events"
                and _agent_error_field(text, "error") == "display_bridge_disabled"
            ):
                # The route exists, but its runtime bridge registration is gone.
                raise C300XDisplayBridgeNotRegisteredError(_http_error_text(status, text))
            raise C300XAgentApiUnsupportedError(
                _http_error_text(
                    status,
                    text,
                    fallback=f"device-agent endpoint is not available: {path}",
                )
            )
        if status < 200 or status >= 300:
            if path.startswith("/api/v1/maintenance/update/"):
                raise C300XAgentUpdateError(
                    _http_error_text(status, text), status=status,
                    code=_agent_error_field(text, "error"),
                )
            if _agent_error_field(text, "detail") == "device_domain_missing":
                raise C300XDeviceNotRegisteredError(_http_error_text(status, text))
            if status == 409 and _agent_error_field(text, "error") == "station_busy":
                raise C300XStationBusyError(_http_error_text(status, text))
            raise C300XAgentApiConnectionError(_http_error_text(status, text), http_status=status)

    def _maintenance_headers(self) -> dict[str, str]:
        """Return maintenance authorization headers when configured."""

        if not self._maintenance_token:
            return {}
        return {HEADER_MAINTENANCE_TOKEN: self._maintenance_token}
