import struct
from typing import Optional

from combustion_ble.ble_data.hop_count import HopCount
from combustion_ble.ble_data.probe_status import ProbeStatus
from combustion_ble.uart.meatnet.node_request import NodeRequest


class NodeProbeStatusRequest(NodeRequest):
    PAYLOAD_LENGTH = 35

    def __init__(self, data: Optional[bytes], request_id, payload_length):
        if not data:
            return
        sequence_byte_index = NodeRequest.HEADER_LENGTH

        # Extracting the serial number
        serial_number_raw = data[sequence_byte_index : sequence_byte_index + 4]
        self.serial_number = struct.unpack("<I", serial_number_raw)[0]

        # Parse Probe Status
        probe_status_raw = data[sequence_byte_index + 4 : sequence_byte_index + 48]
        self.probe_status = ProbeStatus.from_data(probe_status_raw)

        # Extracting Hop Count
        hop_count_raw = data[sequence_byte_index + 34 : sequence_byte_index + 35]
        hop_count_integer = hop_count_raw[0]
        self.hop_count = HopCount.from_network_info_byte(hop_count_integer)

        super().__init__(request_id=request_id, payload_length=payload_length)

    @classmethod
    def from_raw(cls, data, request_id, payload_length):
        if payload_length < cls.PAYLOAD_LENGTH:
            return None
        return cls(data, request_id, payload_length)
