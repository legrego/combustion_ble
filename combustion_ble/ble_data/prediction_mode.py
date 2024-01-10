"""Prediction Mode."""
from enum import Enum


class PredictionMode(Enum):
    """Prediction Mode."""

    NONE = 0x00
    TIME_TO_REMOVAL = 0x01
    REMOVAL_AND_RESTING = 0x02
    RESERVED = 0x03

    MASK = 0x3

    def to_string(self):
        """Human-readable representation of prediction mode."""
        if self == PredictionMode.NONE:
            return "None"
        elif self == PredictionMode.TIME_TO_REMOVAL:
            return "Time to Removal"
        elif self == PredictionMode.REMOVAL_AND_RESTING:
            return "Remove and Resting"
        elif self == PredictionMode.RESERVED:
            return "Reserved"
