from combustion_ble.ble_data.prediction_log import PredictionLog
from combustion_ble.ble_data.probe_temperatures import ProbeTemperatures
from combustion_ble.uart.meatnet.node_response import NodeResponse


class NodeReadLogsResponse(NodeResponse):
    MINIMUM_PAYLOAD_LENGTH = 28
    HEADER_LENGTH = NodeResponse.HEADER_LENGTH
    SERIAL_RANGE = slice(HEADER_LENGTH, HEADER_LENGTH + 4)
    SEQUENCE_RANGE = slice(HEADER_LENGTH + 4, HEADER_LENGTH + 8)
    TEMPERATURE_RANGE = slice(HEADER_LENGTH + 8, HEADER_LENGTH + 21)
    PREDICTION_LOG_RANGE = slice(HEADER_LENGTH + 21, HEADER_LENGTH + 28)

    def __init__(self, data, success, request_id, response_id, payload_length):
        serial_raw = data[self.SERIAL_RANGE]
        self.probe_serial_number = int.from_bytes(serial_raw, byteorder="little")

        sequence_raw = data[self.SEQUENCE_RANGE]
        self.sequence_number = int.from_bytes(sequence_raw, byteorder="little")

        temp_data = data[self.TEMPERATURE_RANGE]
        self.temperatures = ProbeTemperatures.from_raw_data(temp_data)

        prediction_log_data = data[self.PREDICTION_LOG_RANGE]
        self.prediction_log = PredictionLog.from_raw(prediction_log_data)

        super().__init__(success, request_id, response_id, payload_length)

    @classmethod
    def from_raw(cls, data, success, request_id, response_id, payload_length):
        if payload_length < cls.MINIMUM_PAYLOAD_LENGTH:
            return None

        return cls(data, success, request_id, response_id, payload_length)
