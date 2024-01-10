import random
from typing import Optional

from combustion_ble.uart.meatnet.node_message_type import NodeMessageType
from combustion_ble.utilities.crc16ccitt import crc16ccitt


class NodeRequest:
    HEADER_LENGTH = 10

    def __init__(
        self,
        message_type: Optional[NodeMessageType] = None,
        request_id=None,
        outgoing_payload: Optional[bytes] = None,
        payload_length: Optional[int] = None,
    ):
        if not outgoing_payload:
            self.payload_length = payload_length
            self.request_id = request_id
        else:
            assert message_type
            self.data = bytearray()
            self.payload_length = len(outgoing_payload)
            self.request_id = random.randint(1, 0xFFFFFFFF)

            # Sync Bytes { 0xCA, 0xFE }
            self.data += bytearray([0xCA, 0xFE])

            # Prepare data for CRC calculation
            crc_data = bytearray()
            crc_data.append(message_type.value)
            crc_data.extend(self.request_id.to_bytes(length=4, byteorder="little"))
            crc_data.append(self.payload_length)
            crc_data.extend(outgoing_payload)

            # Calculate CRC
            crc_value = crc16ccitt(crc_data)

            self.data.extend(crc_value.to_bytes(length=2, byteorder="little"))

            # Messaeg type, payload length, payload
            self.data.extend(crc_data)
