from combustion_ble.ble_data.prediction_log import PredictionLog
from combustion_ble.ble_data.probe_temperatures import ProbeTemperatures
from combustion_ble.uart.response import Response


class LogResponse(Response):
    MINIMUM_PAYLOAD_LENGTH = 24
    SEQUENCE_RANGE = slice(Response.HEADER_LENGTH, Response.HEADER_LENGTH + 4)
    TEMPERATURE_RANGE = slice(Response.HEADER_LENGTH + 4, Response.HEADER_LENGTH + 17)
    PREDICTION_LOG_RANGE = slice(Response.HEADER_LENGTH + 17, Response.HEADER_LENGTH + 24)

    def __init__(self, data, success, payload_length):
        self.sequence_number = int.from_bytes(data[LogResponse.SEQUENCE_RANGE], byteorder="little")

        temp_data = data[LogResponse.TEMPERATURE_RANGE]
        self.temperatures = ProbeTemperatures.from_raw_data(temp_data)

        prediction_log_data = data[LogResponse.PREDICTION_LOG_RANGE]
        self.prediction_log = PredictionLog.from_raw(prediction_log_data)

        super().__init__(success, payload_length)

    @classmethod
    def from_raw(cls, data, success, payload_length):
        if payload_length < cls.MINIMUM_PAYLOAD_LENGTH:
            return None
        return cls(data, success, payload_length)
