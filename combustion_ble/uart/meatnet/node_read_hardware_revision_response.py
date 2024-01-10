import struct

from combustion_ble.uart.meatnet.node_response import NodeResponse


class NodeReadHardwareRevisionResponse(NodeResponse):
    MINIMUM_PAYLOAD_LENGTH = 20
    SERIAL_RANGE = slice(NodeResponse.HEADER_LENGTH, NodeResponse.HEADER_LENGTH + 4)
    HW_REVISION_RANGE = slice(NodeResponse.HEADER_LENGTH + 4, NodeResponse.HEADER_LENGTH + 20)

    def __init__(self, data, success, request_id, response_id, payload_length):
        # Extracting the serial number
        serial_raw = data[self.SERIAL_RANGE]
        self.probe_serial_number = struct.unpack("<I", serial_raw)[0]

        # Extracting the hardware revision
        hw_revision_raw = data[self.HW_REVISION_RANGE]
        self.hw_revision = hw_revision_raw.decode("utf-8").rstrip("\x00")

        super().__init__(success, request_id, response_id, payload_length)

    @classmethod
    def from_raw(cls, data, success, request_id, response_id, payload_length):
        if payload_length < cls.MINIMUM_PAYLOAD_LENGTH:
            return None
        return cls(data, success, request_id, response_id, payload_length)
