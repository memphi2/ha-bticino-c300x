"""Shared RTSP probing helpers for C300X media paths."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Literal
from urllib.parse import urlsplit

from homeassistant.exceptions import HomeAssistantError

from .rtsp_url import agent_host_for_socket

RtspProbeMethod = Literal["DESCRIBE", "OPTIONS"]


async def async_probe_rtsp_url(
    rtsp_url: str,
    *,
    method: RtspProbeMethod,
    socket_host: str | None = None,
    socket_port: int | None = None,
    timeout_seconds: float = 1.0,
    read_size: int = 128,
    user_agent: str = "HomeAssistant-BTicino-C300X",
    accept_sdp: bool = False,
    reject_status_from: int = 300,
) -> None:
    """Open a short RTSP control connection and validate the response status."""

    parsed = urlsplit(rtsp_url)
    if parsed.scheme != "rtsp" or not parsed.hostname or not parsed.port:
        raise HomeAssistantError("Invalid C300X RTSP URL")
    target_host = socket_host or agent_host_for_socket(parsed.hostname)
    target_port = socket_port or parsed.port
    reader: asyncio.StreamReader | None = None
    writer: asyncio.StreamWriter | None = None
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(target_host, target_port),
            timeout=timeout_seconds,
        )
        request = _rtsp_probe_request(
            rtsp_url,
            method=method,
            user_agent=user_agent,
            accept_sdp=accept_sdp,
        )
        writer.write(request.encode("ascii"))
        await asyncio.wait_for(writer.drain(), timeout=timeout_seconds)
        response = await asyncio.wait_for(reader.read(read_size), timeout=timeout_seconds)
        _raise_for_rtsp_probe_response(response, reject_status_from=reject_status_from)
    finally:
        if writer is not None:
            writer.close()
            with suppress(Exception):
                await writer.wait_closed()


def _rtsp_probe_request(
    rtsp_url: str,
    *,
    method: RtspProbeMethod,
    user_agent: str,
    accept_sdp: bool,
) -> str:
    headers = [
        f"{method} {rtsp_url} RTSP/1.0",
        "CSeq: 1",
    ]
    if accept_sdp:
        headers.append("Accept: application/sdp")
    headers.append(f"User-Agent: {user_agent}")
    return "\r\n".join(headers) + "\r\n\r\n"


def _raise_for_rtsp_probe_response(
    response: bytes,
    *,
    reject_status_from: int,
) -> None:
    if not response.startswith(b"RTSP/1.0 "):
        raise HomeAssistantError("RTSP bridge returned a non-RTSP response")
    status_line = response.split(b"\r\n", 1)[0]
    try:
        status_code = int(status_line.split(maxsplit=2)[1])
    except (IndexError, ValueError) as err:
        raise HomeAssistantError("RTSP bridge returned an invalid status line") from err
    if status_code < 200 or status_code >= reject_status_from:
        raise HomeAssistantError(f"RTSP bridge returned status {status_code}")
