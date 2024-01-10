from combustion_ble.ble_data.prediction_mode import PredictionMode
from combustion_ble.uart.message_type import MessageType
from combustion_ble.uart.request import Request
from combustion_ble.uart.response import Response


class SetPredictionRequest(Request):
    def __init__(self, set_point_celsius: float, prediction_mode: PredictionMode):
        raw_set_point = int(set_point_celsius / 0.1)
        raw_payload = (prediction_mode.value << 10) | (raw_set_point & 0x3FF)
        super().__init__(payload=raw_payload.to_bytes(), message_type=MessageType.SET_PREDICTION)


class SetPredictionResponse(Response):
    pass
