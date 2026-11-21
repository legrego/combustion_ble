import math

from combustion_ble.ble_data.prediction_mode import PredictionMode
from combustion_ble.uart.message_type import MessageType
from combustion_ble.uart.request import Request
from combustion_ble.uart.response import Response


def encode_set_prediction(set_point_celsius: float, prediction_mode: PredictionMode) -> bytes:
    """Encode Set Prediction Data: a 10-bit set point in 0.1 Celsius, then a 2-bit mode.

    Raises ``ValueError`` for a set point outside 0–102.3 Celsius or an unsupported mode.
    """
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
    return raw_payload.to_bytes(2, "little")


class SetPredictionRequest(Request):
    def __init__(self, set_point_celsius: float, prediction_mode: PredictionMode):
        super().__init__(
            payload=encode_set_prediction(set_point_celsius, prediction_mode),
            message_type=MessageType.SET_PREDICTION,
        )


class SetPredictionResponse(Response):
    pass
