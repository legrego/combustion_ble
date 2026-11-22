"""Immutable SafeCook (food safety) snapshots for the host-managed API."""

from __future__ import annotations

import math
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
class FoodSafeProgram:
    """Parameters to send to a probe; no product presets or safety targets are inferred.

    Temperatures and Z-value are Celsius. The four 13-bit decimal fields accept 0–409.55
    and round to 0.05 steps; target log reduction accepts 0–25.5 and rounds to 0.1.
    Validation checks protocol ranges and supported enums, not the suitability of a program
    for a particular food. Reserved and deprecated enum values cannot be written.
    """

    mode: FoodSafeMode
    product: SimplifiedProduct | IntegratedProduct
    serving: Serving
    threshold_temperature: float
    z_value: float
    reference_temperature: float
    d_value: float
    target_log_reduction: float

    def to_bytes(self) -> bytes:
        """Validate and encode the 10-byte Food Safe Data command payload.

        Raises ``ValueError`` before any Bluetooth write for unsupported choices or values.
        """
        if not isinstance(self.mode, FoodSafeMode):
            raise ValueError("Unsupported food safe mode")
        product_type = (
            SimplifiedProduct if self.mode is FoodSafeMode.SIMPLIFIED else IntegratedProduct
        )
        if not isinstance(self.product, product_type):
            raise ValueError("Food safe product must match the selected mode")
        if not isinstance(self.serving, Serving):
            raise ValueError("Unsupported food safe serving")
        raw = int(self.mode) | (int(self.product) << 3) | (int(self.serving) << 13)
        for name, value, shift in (
            ("threshold_temperature", self.threshold_temperature, 16),
            ("z_value", self.z_value, 29),
            ("reference_temperature", self.reference_temperature, 42),
            ("d_value", self.d_value, 55),
        ):
            if not math.isfinite(value) or not 0 <= value <= 409.55:
                raise ValueError(f"{name} must be finite and between 0 and 409.55")
            raw |= round(value * 20) << shift
        target = self.target_log_reduction
        if not math.isfinite(target) or not 0 <= target <= 25.5:
            raise ValueError("target_log_reduction must be finite and between 0 and 25.5")
        raw |= round(target * 10) << 68
        return raw.to_bytes(10, "little")


@dataclass(frozen=True, slots=True)
class FoodSafe:
    """A probe's SafeCook program and its progress. Temperatures are Celsius.

    Probes report SafeCook data even when SafeCook is off; check :attr:`program_set` before
    using the rest. Enum fields are left as raw integers when the firmware reports a value this
    library doesn't know.
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

    @property
    def program_set(self) -> bool:
        """Whether the probe has a SafeCook program.

        Turning SafeCook off in the Combustion app writes an all-zero program, which decodes as
        Simplified mode with the Default product and every temperature and parameter 0. No real
        program has a 0 °C threshold or a 0 log target, so this is ``False`` only for that.
        """
        return any(
            (
                self.mode,
                self.product,
                self.serving,
                self.threshold_temperature,
                self.z_value,
                self.reference_temperature,
                self.d_value,
                self.target_log_reduction,
            )
        )

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
