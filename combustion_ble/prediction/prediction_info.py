"""Prediction Info."""
from typing import Optional

from combustion_ble.ble_data.prediction_mode import PredictionMode
from combustion_ble.ble_data.prediction_state import PredictionState
from combustion_ble.ble_data.prediction_type import PredictionType


class PredictionInfo:
    """Prediction Info."""

    def __init__(
        self,
        prediction_state: PredictionState,
        prediction_mode: PredictionMode,
        prediction_type: PredictionType,
        prediction_set_point_temperature: float,
        estimated_core_temperature: float,
        seconds_remaining: Optional[int] = None,
        percent_through_cook: int = 0,
    ):
        """Initialize."""
        self.prediction_state = prediction_state
        self.prediction_mode = prediction_mode
        self.prediction_type = prediction_type
        self.prediction_set_point_temperature = prediction_set_point_temperature
        self.estimated_core_temperature = estimated_core_temperature
        self.seconds_remaining = seconds_remaining
        self.percent_through_cook = percent_through_cook

    def __str__(self) -> str:
        return f"Mode[{self.prediction_mode.to_string()}] Type[{self.prediction_type.to_string()}] Set Point [{round(self.prediction_set_point_temperature, 1)}] Percent Complete [{self.percent_through_cook}]"
