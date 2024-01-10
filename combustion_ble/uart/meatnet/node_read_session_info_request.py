import struct

from combustion_ble.uart.meatnet.node_message_type import NodeMessageType
from combustion_ble.uart.meatnet.node_request import NodeRequest


class NodeReadSessionInfoRequest(NodeRequest):
    def __init__(self, serial_number: int):
        serial_number_bytes = struct.pack("<I", serial_number)
        super().__init__(
            outgoing_payload=serial_number_bytes, message_type=NodeMessageType.SESSION_INFO
        )
