"""Bounded full-body reads for aiohttp responses and requests.

aiohttp's ``StreamReader.read(n)`` returns as soon as one chunk is buffered, so
it is NOT a whole-body read -- a multi-segment body comes back truncated. This
reads the entire body via ``iter_chunked`` while capping the total size, so a
runaway/hostile body still cannot be pulled fully into memory.
"""

from __future__ import annotations

from typing import Any

_CHUNK = 64 * 1024


async def read_capped_body(
    content: Any,
    content_length: int | None,
    limit: int,
) -> bytes | None:
    """Return the full body bytes, or None if it exceeds ``limit``."""

    if content_length is not None and content_length > limit:
        return None
    buffer = bytearray()
    async for chunk in content.iter_chunked(_CHUNK):
        buffer += chunk
        if len(buffer) > limit:
            return None
    return bytes(buffer)
