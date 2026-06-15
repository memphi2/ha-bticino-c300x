"""Mapping-compatible base class for typed device-agent contracts."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True, slots=True, eq=False)
class AgentContract(Mapping[str, Any]):
    """Base contract preserving dict-style access while exposing attributes."""

    raw: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            raise KeyError(key) from None

    def __iter__(self) -> Iterator[str]:
        return (field.name for field in fields(self))

    def __len__(self) -> int:
        return len(fields(self))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return self.to_dict() == dict(other)
        return NotImplemented

    def to_dict(self) -> dict[str, Any]:
        """Return a shallow dict representation without copying nested payloads."""

        return {field.name: getattr(self, field.name) for field in fields(self)}
