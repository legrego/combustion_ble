from combustion_ble.uart.meatnet.node_message_type import NodeMessageType
from combustion_ble.uart.meatnet.node_request import NodeRequest


class NodeReadLogsRequest(NodeRequest):
    def __init__(self, serial_number: int, min_sequence: int = 0, max_sequence: int = 0):
        # Create payload

        serial = serial_number.to_bytes(length=4, byteorder="little")
        min = min_sequence.to_bytes(length=4, byteorder="little")
        max = max_sequence.to_bytes(length=4, byteorder="little")

        super().__init__(outgoing_payload=serial + min + max, message_type=NodeMessageType.LOG)
