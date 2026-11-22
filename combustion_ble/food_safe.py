"""Immutable SafeCook (food safety) snapshots for the host-managed API."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

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
    for a particular food. Reserved enum values cannot be written. Deprecated Integrated
    product IDs (3 and 5–12) may be supplied as integers for backward compatibility.
    Exact halfway values round up. Programs that encode as all zeros are rejected; use
    ``clear_food_safe()`` to turn SafeCook off.
    """

    mode: FoodSafeMode
    product: SimplifiedProduct | IntegratedProduct | int
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
        legacy_product = (
            self.mode is FoodSafeMode.INTEGRATED
            and type(self.product) is int
            and self.product in (3, *range(5, 13))
        )
        if not isinstance(self.product, product_type) and not legacy_product:
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
            raw |= _encode_decimal(name, value, 20, "409.55") << shift
        raw |= _encode_decimal("target_log_reduction", self.target_log_reduction, 10, "25.5") << 68
        if raw == 0:
            raise ValueError("Program encodes as SafeCook off; use clear_food_safe() instead")
        return raw.to_bytes(10, "little")


def _encode_decimal(name: str, value: float, scale: int, maximum: str) -> int:
    # Use the decimal spelling so halfway inputs such as 6.25 and 0.075 round consistently.
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(f"{name} must be numeric")
    decimal = Decimal(str(value))
    if not decimal.is_finite() or not 0 <= decimal <= Decimal(maximum):
        raise ValueError(f"{name} must be finite and between 0 and {maximum}")
    return int((decimal * scale).to_integral_value(rounding=ROUND_HALF_UP))


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
