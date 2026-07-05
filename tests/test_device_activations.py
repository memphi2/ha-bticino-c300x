from __future__ import annotations

import pytest

from custom_components.bticino_c300x.const import DEVICE_ACTIVATION_MODE_MANUAL
from custom_components.bticino_c300x.device_activations import (
    DeviceActivationConfigError,
    activation_items_match,
    desired_activation_items,
    normalize_device_activations,
)


def test_normalize_device_activations_uses_manual_address_mode() -> None:
    assert normalize_device_activations(
        [
            {
                "id": "front_lock",
                "name": "Front lock",
                "type": "lock",
                "address": "10",
            }
        ]
    ) == [
        {
            "address": "10",
            "addressMode": "manual",
            "id": "front_lock",
            "name": "Front lock",
            "type": "lock",
        }
    ]


def test_normalize_device_activations_rejects_duplicate_reserved_ids() -> None:
    with pytest.raises(DeviceActivationConfigError):
        normalize_device_activations(
            [
                {
                    "id": "stair_light",
                    "name": "Duplicate stair light",
                    "type": "light",
                    "address": "10",
                }
            ],
            reserved_ids={"stair_light"},
        )


def test_desired_activation_items_includes_generated_stair_light() -> None:
    assert desired_activation_items(
        mode=DEVICE_ACTIVATION_MODE_MANUAL,
        stair_light_address="12",
        device_activations=[],
    ) == [
        {
            "address": "12",
            "addressMode": "manual",
            "id": "stair_light",
            "name": "Stair light",
            "type": "stair_light",
        }
    ]


def test_activation_items_match_ignores_agent_runtime_fields() -> None:
    assert activation_items_match(
        [
            {
                "id": "front_lock",
                "name": "Front lock",
                "type": "lock",
                "addressMode": "manual",
                "address": "10",
            }
        ],
        [
            {
                "id": "front_lock",
                "name": "Front lock",
                "type": "lock",
                "addressMode": "manual",
                "address": "10",
                "source": "config",
                "available": True,
            }
        ],
    )
