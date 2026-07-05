from __future__ import annotations

import pytest

from custom_components.bticino_c300x.const import DEVICE_ACTIVATION_MODE_MANUAL
from custom_components.bticino_c300x.device_activations import (
    MAX_DEVICE_ACTIVATIONS,
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


def test_normalize_device_activations_rejects_native_max_address() -> None:
    assert normalize_device_activations(
        [
            {
                "id": "front_lock",
                "name": "Front lock",
                "type": "lock",
                "address": "1" * 31,
            }
        ]
    )[0]["address"] == "1" * 31

    with pytest.raises(DeviceActivationConfigError):
        normalize_device_activations(
            [
                {
                    "id": "front_lock",
                    "name": "Front lock",
                    "type": "lock",
                    "address": "1" * 32,
                }
            ]
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


def test_desired_activation_items_rejects_manual_total_over_native_limit() -> None:
    with pytest.raises(DeviceActivationConfigError):
        desired_activation_items(
            mode=DEVICE_ACTIVATION_MODE_MANUAL,
            stair_light_address="12",
            device_activations=[
                {
                    "id": f"extra_{index}",
                    "name": f"Extra {index}",
                    "type": "lock",
                    "address": str(index + 1),
                }
                for index in range(MAX_DEVICE_ACTIVATIONS)
            ],
        )


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
