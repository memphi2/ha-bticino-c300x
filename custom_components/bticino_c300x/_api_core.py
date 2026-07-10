"""Shared transport core for the C300X device-agent client mixins."""

from __future__ import annotations

import json
from typing import Any, cast

from aiohttp import ClientError, ClientSession

from ._api_normalize import (
    _http_error_text,
)
from .api_errors import (
    C300XAgentApiConnectionError,
    C300XAgentApiResponseError,
    C300XAgentApiUnsupportedError,
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
        try:
            async with self._session.request(
                method,
                f"{self._base_url}{path}",
                headers=self._auth_headers(extra_headers),
                json=json_data,
                timeout=cast(
                    Any,
                    self._timeout if request_timeout is None else request_timeout,
                ),
            ) as response:
                raw = await read_capped_body(
                    response.content,
                    response.content_length,
                    _MAX_JSON_RESPONSE_BYTES,
                )
                if raw is None:
                    raise C300XAgentApiResponseError(
                        "device agent response too large"
                    )
                text = raw.decode(response.charset or "utf-8", errors="replace")
                self._raise_for_agent_status(response.status, text, path)
        except TimeoutError as err:
            raise C300XAgentApiConnectionError("device-agent request timed out") from err
        except ClientError as err:
            raise C300XAgentApiConnectionError(str(err)) from err

        try:
            return json.loads(text) if text else {}
        except json.JSONDecodeError as err:
            raise C300XAgentApiResponseError("device agent returned invalid JSON") from err

    async def _request_bytes(
        self,
        method: str,
        path: str,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[bytes, str]:
        try:
            async with self._session.request(
                method,
                f"{self._base_url}{path}",
                headers=self._auth_headers(extra_headers),
                timeout=cast(Any, self._timeout),
            ) as response:
                if response.status < 200 or response.status >= 300:
                    self._raise_for_agent_status(
                        response.status, await response.text(), path
                    )
                content = await response.read()
                content_type = response.headers.get(
                    "Content-Type",
                    "application/octet-stream",
                )
        except TimeoutError as err:
            raise C300XAgentApiConnectionError("device-agent request timed out") from err
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

        if status == 404:
            raise C300XAgentApiUnsupportedError(
                _http_error_text(
                    status,
                    text,
                    fallback=f"device-agent endpoint is not available: {path}",
                )
            )
        if status < 200 or status >= 300:
            raise C300XAgentApiConnectionError(_http_error_text(status, text))

    def _maintenance_headers(self) -> dict[str, str]:
        """Return maintenance authorization headers when configured."""

        if not self._maintenance_token:
            return {}
        return {HEADER_MAINTENANCE_TOKEN: self._maintenance_token}
