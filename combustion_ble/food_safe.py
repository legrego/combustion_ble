"""Immutable SafeCook (food safety) snapshots for the host-managed API."""

from __future__ import annotations

from dataclasses import dataclass

from combustion_ble.ble_data.food_safe_data import (
    FoodSafeData,
    FoodSafeMode,
    IntegratedProduct,
    Serving,
    SimplifiedProduct,
)
from combustion_ble.ble_data.food_safe_state import FoodSafeState
from combustion_ble.ble_data.food_safe_status import FoodSafeStatus


@dataclass(frozen=True, slots=True)
class FoodSafe:
    """A probe's SafeCook program and its progress. Temperatures are Celsius.

    Probes report a program even when nobody has set one up in the Combustion app. Enum fields
    are left as raw integers when the firmware reports a value this library doesn't know.
    """

    state: FoodSafeState | int
    log_reduction: float
    """Integrated log reduction so far. Always 0 in Simplified mode."""
    seconds_above_threshold: int
    mode: FoodSafeMode | int
    product: SimplifiedProduct | IntegratedProduct | int
    serving: Serving | int
    threshold_temperature: float
    z_value: float
    reference_temperature: float
    d_value: float
    """D-value at :attr:`reference_temperature`."""
    target_log_reduction: float

    @classmethod
    def from_status(cls, data: FoodSafeData, status: FoodSafeStatus) -> FoodSafe:
        return cls(
            state=status.state,
            log_reduction=status.log_reduction,
            seconds_above_threshold=status.seconds_above_threshold,
            mode=data.mode,
            product=data.product,
            serving=data.serving,
            threshold_temperature=data.threshold_temperature,
            z_value=data.z_value,
            reference_temperature=data.reference_temperature,
            d_value=data.d_value,
            target_log_reduction=data.target_log_reduction,
        )
