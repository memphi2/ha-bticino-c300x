"""Small non-secret fingerprint helpers."""

from __future__ import annotations

_FNV1A64_OFFSET = 1469598103934665603
_FNV1A64_PRIME = 1099511628211
_FNV1A64_MASK = (1 << 64) - 1


def fnv1a64_fingerprint(value: str) -> str:
    """Return the stable FNV-1a 64-bit fingerprint string used by the agent."""

    fingerprint = _FNV1A64_OFFSET
    for byte in value.encode():
        fingerprint ^= byte
        fingerprint = (fingerprint * _FNV1A64_PRIME) & _FNV1A64_MASK
    return f"fnv1a64:{fingerprint:016x}"
