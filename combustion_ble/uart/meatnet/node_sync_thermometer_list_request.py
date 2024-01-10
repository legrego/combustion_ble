from typing import Optional

from combustion_ble.uart.meatnet.node_request import NodeRequest


class Thermometer:
    """Individual Thermometer entry."""

    def __init__(self, position: int, present: bool, serial_number: int) -> None:
        self.position = position
        self.present = present
        self.serial_number = serial_number
        self.serial_number_string = f"{self.serial_number:08X}"

    def __str__(self) -> str:
        return f"Position [{self.position}]; Present [{self.present}]; Serial: [{self.serial_number_string}]"

    @classmethod
    def from_raw(cls, position: int, data: bytes):
        present = bool(data[0])
        serial_number = int.from_bytes(data[1:5], byteorder="little")

        return cls(position, present, serial_number)


class NodeSyncThermometerListRequest(NodeRequest):
    PAYLOAD_LENGTH = 26

    def __init__(self, data: Optional[bytes], request_id, payload_length):
        if not data:
            return
        mac_address_index = NodeRequest.HEADER_LENGTH

        # Extracting mac address
        mac_raw = int.from_bytes(data[mac_address_index : mac_address_index + 6])
        self.mac_address = f"{mac_raw:08X}"

        self.thermometers: list[Thermometer] = []
        for i in range(1, 5):
            index_start = mac_address_index + (6 * i)
            index_end = index_start + 5
            self.thermometers.append(Thermometer.from_raw(i, data[index_start:index_end]))

        super().__init__(request_id=request_id, payload_length=payload_length)

    @classmethod
    def from_raw(cls, data, request_id, payload_length):
        if payload_length < cls.PAYLOAD_LENGTH:
            return None
        return cls(data, request_id, payload_length)
