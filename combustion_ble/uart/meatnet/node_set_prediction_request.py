import struct

from combustion_ble.uart.meatnet.node_message_type import NodeMessageType
from combustion_ble.uart.meatnet.node_request import NodeRequest
from combustion_ble.uart.meatnet.node_response import NodeResponse


class NodeSetPredictionRequest(NodeRequest):
    def __init__(self, serial_number, set_point_celsius, mode):
        # Packing serial number into bytes
        serial_number_bytes = struct.pack("<I", serial_number)

        # Calculating raw set point and payload
        raw_set_point = int(set_point_celsius / 0.1)
        raw_payload = (mode.value << 10) | (raw_set_point & 0x3FF)
        raw_payload_bytes = struct.pack("<H", raw_payload)

        # Combining both parts of the payload
        payload = serial_number_bytes + raw_payload_bytes

        super().__init__(outgoing_payload=payload, message_type=NodeMessageType.SET_PREDICTION)


class NodeSetPredictionResponse(NodeResponse):
    pass
