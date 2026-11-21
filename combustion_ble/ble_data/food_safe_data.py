"""Food Safe Data: the SafeCook program a probe is running.

Decoded from the 10-byte packed field in the Probe Status characteristic and in relayed MeatNet
Probe Status (0x45) messages. Fields are packed least significant bit first.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum, unique

FOOD_SAFE_DATA_LENGTH = 10


@unique
class FoodSafeMode(IntEnum):
    """How the probe decides when food is safe."""

    SIMPLIFIED = 0
    """Safe once the core reaches the product's USDA threshold temperature."""

    INTEGRATED = 1
    """Safe once the integrated log reduction reaches the target (time at temperature)."""


@unique
class SimplifiedProduct(IntEnum):
    """Product selected for a Simplified mode program."""

    DEFAULT = 0
    ANY_POULTRY = 1
    BEEF_CUTS = 2
    PORK_CUTS = 3
    VEAL_CUTS = 4
    LAMB_CUTS = 5
    GROUND_MEATS = 6
    HAM_FRESH_OR_SMOKED = 7
    HAM_COOKED_AND_REHEATED = 8
    EGGS = 9
    FISH_AND_SHELLFISH = 10
    LEFTOVERS = 11
    CASSEROLES = 12


@unique
class IntegratedProduct(IntEnum):
    """Product selected for an Integrated mode program.

    The probe only stores this so that apps can sync it. Values 3 and 5-12 are deprecated.
    """

    POULTRY = 0
    MEATS = 1
    MEATS_GROUND = 2
    POULTRY_GROUND = 4
    SEAFOOD = 13
    SEAFOOD_GROUND = 14
    DAIRY_MILK = 15
    OTHER = 16
    SEAFOOD_STUFFED = 17
    EGGS = 18
    EGGS_YOLK = 19
    EGGS_WHITE = 20
    DAIRY_CREAMS = 21
    DAIRY_ICE_CREAM_MIX = 22
    CUSTOM = 1023


@unique
class Serving(IntEnum):
    """How the food will be served, which sets the target for safety calculations."""

    SERVED_IMMEDIATELY = 0
    COOKED_AND_CHILLED = 1


def _enum_or_int[E: Enum](enum: type[E], raw: int) -> E | int:
    try:
        return enum(raw)
    except ValueError:
        return raw


@dataclass(frozen=True, slots=True)
class FoodSafeData:
    """A probe's SafeCook program.

    ``mode``, ``product``, and ``serving`` are left as raw integers when the firmware reports a
    value this library doesn't know. Temperatures are Celsius.
    """

    mode: FoodSafeMode | int
    product: SimplifiedProduct | IntegratedProduct | int
    serving: Serving | int
    threshold_temperature: float
    """Selected threshold reference temperature."""
    z_value: float
    reference_temperature: float
    d_value: float
    """D-value at the reference temperature."""
    target_log_reduction: float

    @classmethod
    def from_bytes(cls, data: bytes) -> FoodSafeData:
        if len(data) < FOOD_SAFE_DATA_LENGTH:
            raise ValueError(f"Food safe data needs {FOOD_SAFE_DATA_LENGTH} bytes")
        raw = int.from_bytes(data[:FOOD_SAFE_DATA_LENGTH], "little")

        mode = _enum_or_int(FoodSafeMode, raw & 0x7)
        raw_product = (raw >> 3) & 0x3FF
        product: SimplifiedProduct | IntegratedProduct | int = raw_product
        if mode is FoodSafeMode.SIMPLIFIED:
            product = _enum_or_int(SimplifiedProduct, raw_product)
        elif mode is FoodSafeMode.INTEGRATED:
            product = _enum_or_int(IntegratedProduct, raw_product)

        return cls(
            mode=mode,
            product=product,
            serving=_enum_or_int(Serving, (raw >> 13) & 0x7),
            threshold_temperature=_temperature(raw >> 16),
            z_value=_temperature(raw >> 29),
            reference_temperature=_temperature(raw >> 42),
            d_value=_temperature(raw >> 55),
            target_log_reduction=round(((raw >> 68) & 0xFF) * 0.1, 1),
        )


def _temperature(raw: int) -> float:
    return round((raw & 0x1FFF) * 0.05, 2)
