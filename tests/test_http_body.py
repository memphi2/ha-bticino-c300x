from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from custom_components.bticino_c300x.http_body import read_capped_body


class _Content:
    def __init__(self, *chunks: bytes) -> None:
        self._chunks = chunks

    async def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk


def test_reads_the_whole_body_across_multiple_chunks() -> None:
    # The real defect: a multi-segment body must be fully assembled, not
    # truncated to the first chunk.
    content = _Content(b'{"value":', b' "spa', b'nned"}')
    raw = asyncio.run(read_capped_body(content, None, 1_000))
    assert raw == b'{"value": "spanned"}'


def test_rejects_when_content_length_exceeds_limit() -> None:
    content = _Content(b"x" * 20)
    assert asyncio.run(read_capped_body(content, 20, 8)) is None


def test_rejects_when_accumulated_chunks_exceed_limit() -> None:
    # content_length withheld (chunked) -> the running cap must reject it.
    content = _Content(b"aaaa", b"bbbb", b"cccc")
    assert asyncio.run(read_capped_body(content, None, 8)) is None


def test_accepts_body_exactly_at_the_limit() -> None:
    content = _Content(b"a" * 8)
    assert asyncio.run(read_capped_body(content, None, 8)) == b"a" * 8
