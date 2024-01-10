import struct

from combustion_ble.uart.meatnet.node_response import NodeResponse
from combustion_ble.uart.session_info import SessionInformation


class NodeReadSessionInfoResponse(NodeResponse):
    MINIMUM_PAYLOAD_LENGTH = 10
    SERIAL_RANGE = slice(NodeResponse.HEADER_LENGTH, NodeResponse.HEADER_LENGTH + 4)
    SESSION_ID_RANGE = slice(NodeResponse.HEADER_LENGTH + 4, NodeResponse.HEADER_LENGTH + 8)
    SAMPLE_PERIOD_RANGE = slice(NodeResponse.HEADER_LENGTH + 8, NodeResponse.HEADER_LENGTH + 10)

    def __init__(self, data, success, request_id, response_id, payload_length):
        # Extracting the serial number
        serial_raw = data[self.SERIAL_RANGE]
        self.probe_serial_number = struct.unpack("<I", serial_raw)[0]

        # Extracting the session ID
        session_id_raw = data[self.SESSION_ID_RANGE]
        session_id = struct.unpack("<I", session_id_raw)[0]

        # Extracting the sample period
        sample_period_raw = data[self.SAMPLE_PERIOD_RANGE]
        sample_period = struct.unpack("<H", sample_period_raw)[0]

        self.info = SessionInformation(session_id=session_id, sample_period=sample_period)

        super().__init__(success, request_id, response_id, payload_length)

    @classmethod
    def from_raw(cls, data, success, request_id, response_id, payload_length):
        if payload_length < cls.MINIMUM_PAYLOAD_LENGTH:
            return None
        return cls(data, success, request_id, response_id, payload_length)
