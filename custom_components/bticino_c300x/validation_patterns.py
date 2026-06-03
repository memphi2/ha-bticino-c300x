"""Shared compiled validation patterns."""

from __future__ import annotations

import re

from .const import ACTIVATION_ID_PATTERN, LOCK_ID_PATTERN, STAIR_LIGHT_ADDRESS_PATTERN

ACTIVATION_ID_RE = re.compile(ACTIVATION_ID_PATTERN)
ENTITY_OBJECT_ID_RE = re.compile(r"[a-z0-9_]+")
HA_ACTION_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
HA_DOMAIN_RE = re.compile(r"^[a-z0-9_]+$")
HA_ENTITY_ID_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
HA_SERVICE_RE = re.compile(r"^[a-z0-9_]+$")
LOCK_ID_RE = re.compile(LOCK_ID_PATTERN)
MEMO_ID_RE = re.compile(r"^(text|voice)/[A-Za-z0-9_.-]{1,64}$")
STAIR_LIGHT_ADDRESS_RE = re.compile(STAIR_LIGHT_ADDRESS_PATTERN)
VIDEO_MESSAGE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
