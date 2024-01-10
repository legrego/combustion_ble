from combustion_ble.uart.meatnet.node_message_type import NodeMessageType
from combustion_ble.uart.meatnet.node_request import NodeRequest


class NodeReadModelInfoRequest(NodeRequest):
    def __init__(self, serial_number: int):
        # Packing the serial number into bytes
        serial_number_bytes = serial_number.to_bytes(length=4, byteorder="little")

        # Initialize the base class with the payload and type
        super().__init__(
            outgoing_payload=serial_number_bytes,
            message_type=NodeMessageType.PROBE_MODEL_INFORMATION,
        )
