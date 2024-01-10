import struct

from combustion_ble.uart.meatnet.node_response import NodeResponse


class NodeReadModelInfoResponse(NodeResponse):
    MINIMUM_PAYLOAD_LENGTH = 54
    SERIAL_RANGE = slice(NodeResponse.HEADER_LENGTH, NodeResponse.HEADER_LENGTH + 4)
    MODEL_INFO_RANGE = slice(NodeResponse.HEADER_LENGTH + 4, NodeResponse.HEADER_LENGTH + 54)

    def __init__(self, data, success, request_id, response_id, payload_length):
        # Extracting the serial number
        serial_raw = data[self.SERIAL_RANGE]
        self.probe_serial_number = struct.unpack("<I", serial_raw)[0]

        # Extracting the model info
        model_info_raw = data[self.MODEL_INFO_RANGE]
        self.model_info = model_info_raw.decode("utf-8").rstrip("\x00")

        super().__init__(success, request_id, response_id, payload_length)

    @classmethod
    def from_raw(cls, data, success, request_id, response_id, payload_length):
        if payload_length < cls.MINIMUM_PAYLOAD_LENGTH:
            return None
        return cls(data, success, request_id, response_id, payload_length)
