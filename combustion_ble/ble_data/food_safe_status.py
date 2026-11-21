"""Food Safe Status: progress of a probe's SafeCook program.

Decoded from the 8-byte packed field that follows Food Safe Data in the Probe Status
characteristic and in relayed MeatNet Probe Status (0x45) messages. Fields are packed least
significant bit first.
"""

from __future__ import annotations

from dataclasses import dataclass

from combustion_ble.ble_data.food_safe_state import FoodSafeState

FOOD_SAFE_STATUS_LENGTH = 8


@dataclass(frozen=True, slots=True)
class FoodSafeStatus:
    state: FoodSafeState | int
    """Left as a raw integer when the firmware reports a state this library doesn't know."""
    log_reduction: float
    """Integrated log reduction so far. Always 0 in Simplified mode."""
    seconds_above_threshold: int
    sequence_number: int
    """Log sequence number of the status."""

    @classmethod
    def from_bytes(cls, data: bytes) -> FoodSafeStatus:
        if len(data) < FOOD_SAFE_STATUS_LENGTH:
            raise ValueError(f"Food safe status needs {FOOD_SAFE_STATUS_LENGTH} bytes")
        raw = int.from_bytes(data[:FOOD_SAFE_STATUS_LENGTH], "little")
        raw_state = raw & 0x7
        try:
            state: FoodSafeState | int = FoodSafeState(raw_state)
        except ValueError:
            state = raw_state
        return cls(
            state=state,
            log_reduction=round(((raw >> 3) & 0xFF) * 0.1, 1),
            seconds_above_threshold=(raw >> 11) & 0xFFFF,
            sequence_number=(raw >> 27) & 0xFFFFFFFF,
        )
