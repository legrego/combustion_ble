import math

from combustion_ble.ble_data.prediction_mode import PredictionMode
from combustion_ble.uart.message_type import MessageType
from combustion_ble.uart.request import Request
from combustion_ble.uart.response import Response


class SetPredictionRequest(Request):
    def __init__(self, set_point_celsius: float, prediction_mode: PredictionMode):
        if not math.isfinite(set_point_celsius) or not 0 <= set_point_celsius <= 102.3:
            raise ValueError("Prediction temperature must be between 0 and 102.3 Celsius")
        if prediction_mode not in (
            PredictionMode.NONE,
            PredictionMode.TIME_TO_REMOVAL,
            PredictionMode.REMOVAL_AND_RESTING,
        ):
            raise ValueError("Unsupported prediction mode")
        raw_set_point = round(set_point_celsius * 10)
        raw_payload = (prediction_mode.value << 10) | (raw_set_point & 0x3FF)
        super().__init__(
            payload=raw_payload.to_bytes(2, "little"), message_type=MessageType.SET_PREDICTION
        )


class SetPredictionResponse(Response):
    pass
