import struct

from combustion_ble.uart.meatnet.node_message_type import NodeMessageType
from combustion_ble.uart.meatnet.node_request import NodeRequest


class NodeReadHardwareRevisionRequest(NodeRequest):
    def __init__(self, serial_number):
        # Packing the serial number into bytes
        serial_number_bytes = struct.pack("<I", serial_number)

        # Initialize the base class with the payload and type
        super().__init__(
            outgoing_payload=serial_number_bytes,
            message_type=NodeMessageType.PROBE_HARDWARE_REVISION,
        )
