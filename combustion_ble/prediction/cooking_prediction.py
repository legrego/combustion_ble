"""Immutable cooking prediction snapshots for the host-managed API."""

from dataclasses import dataclass

from combustion_ble.ble_data.prediction_mode import PredictionMode
from combustion_ble.ble_data.prediction_state import PredictionState
from combustion_ble.ble_data.prediction_status import PredictionStatus
from combustion_ble.ble_data.prediction_type import PredictionType


@dataclass(frozen=True, slots=True)
class CookingPrediction:
    """A probe's prediction; temperatures are Celsius and time is seconds.

    ``percent_through_cook`` measures temperature progress, not elapsed cooking time.
    ``seconds_remaining`` is absent until the probe provides a usable prediction.
    """

    state: PredictionState
    mode: PredictionMode
    type: PredictionType
    set_point_temperature: float
    estimated_core_temperature: float
    seconds_remaining: int | None
    percent_through_cook: int | None

    @classmethod
    def from_status(cls, status: PredictionStatus) -> "CookingPrediction":
        """Copy a decoded status without retaining mutable legacy objects."""
        active = status.prediction_mode in (
            PredictionMode.TIME_TO_REMOVAL,
            PredictionMode.REMOVAL_AND_RESTING,
        )
        seconds = None
        if active and status.prediction_type in (PredictionType.REMOVAL, PredictionType.RESTING):
            if status.prediction_state == PredictionState.PREDICTING:
                seconds = int(status.prediction_value_seconds)
            elif status.prediction_state == PredictionState.REMOVAL_PREDICTION_DONE:
                seconds = 0

        start = status.heat_start_temperature
        end = status.prediction_set_point_temperature
        progress = None
        if active and end > start:
            progress = max(
                0, min(100, int(100 * (status.estimated_core_temperature - start) / (end - start)))
            )

        return cls(
            state=status.prediction_state,
            mode=status.prediction_mode,
            type=status.prediction_type,
            set_point_temperature=end,
            estimated_core_temperature=status.estimated_core_temperature,
            seconds_remaining=seconds,
            percent_through_cook=progress,
        )
