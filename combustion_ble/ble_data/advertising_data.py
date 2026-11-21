"""Combustion product types found in Bluetooth advertising data."""

from enum import Enum


class CombustionProductType(Enum):
    """Product type byte found at the start of Combustion manufacturer data.

    Values that are not recognized map to ``UNKNOWN`` rather than raising, so that newer products
    do not break parsing.
    """

    UNKNOWN = 0x00
    PROBE = 0x01
    MEAT_NET_NODE = 0x02
    """Probe data repeated by a MeatNet node (Display, Booster, Gauge, Engine, ...)."""
    GAUGE = 0x03
    DISPLAY = 0x04
    BOOSTER = 0x05
    ENGINE = 0x06

    @classmethod
    def _missing_(cls, value: object) -> "CombustionProductType":
        return cls.UNKNOWN
