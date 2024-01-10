from combustion_ble.ble_data.advertising_data import CombustionProductType
from combustion_ble.ble_data.hop_count import HopCount
from combustion_ble.logger import LOGGER
from combustion_ble.uart.meatnet.node_request import NodeRequest


class NodeHeartbeatRequest(NodeRequest):
    class ConnectionDetail:
        PAYLOAD_LENGTH = 13
        PROBE_SERIAL_RANGE = slice(0, 4)
        NODE_SERIAL_RANGE = slice(0, 10)
        PRODUCT_TYPE_INDEX = 10
        ATTRIBUTES_INDEX = 11
        RSSI_INDEX = 12

        def __init__(
            self, present: bool, serial_number: str, product_type: CombustionProductType, rssi: int
        ):
            self.present = present
            self.serial_number = serial_number
            self.product_type = product_type
            self.rssi = rssi

        @classmethod
        def from_raw(cls, data: bytes):
            if len(data) < cls.PAYLOAD_LENGTH:
                return cls.not_present()

            attributes = data[cls.ATTRIBUTES_INDEX]
            if (attributes & 0x01) != 0x01:
                return cls.not_present()

            product_type = CombustionProductType(data[cls.PRODUCT_TYPE_INDEX])
            serial_number = ""
            if product_type == CombustionProductType.PROBE:
                serial_raw = int.from_bytes(data[cls.PROBE_SERIAL_RANGE], byteorder="little")
                serial_number = f"{serial_raw:08X}"
            elif product_type == CombustionProductType.MEAT_NET_NODE:
                try:
                    serial_number = data[cls.NODE_SERIAL_RANGE].decode("utf-8")
                except Exception:
                    serial_number = ""

            rssi = int.from_bytes(
                data[cls.RSSI_INDEX : cls.RSSI_INDEX + 1], byteorder="big", signed=True
            )

            return cls(True, serial_number, product_type, rssi)

        @classmethod
        def not_present(cls):
            return cls(False, "", CombustionProductType.UNKNOWN, 0)

    def __init__(self, data: bytes, request_id: int, payload_length: int):
        self.request_id = request_id
        self.payload_length = payload_length

        # Extract serial number
        self.serial_number = data[self.HEADER_LENGTH : self.HEADER_LENGTH + 10].decode("utf-8")

        # Extract MAC address
        mac_raw = data[self.HEADER_LENGTH + 10 : self.HEADER_LENGTH + 16]
        self.mac_address = ":".join("{:02x}".format(byte) for byte in mac_raw).upper()

        # Extract product type, hop count, and inbound
        self.product_type = CombustionProductType(data[self.HEADER_LENGTH + 16])
        self.hop_count = HopCount.from_network_info_byte(data[self.HEADER_LENGTH + 17])
        self.inbound = data[self.HEADER_LENGTH + 18] != 0x00

        # Extract connection details
        try:
            self.connection_details = []
            for i in range(4):
                start = self.HEADER_LENGTH + 19 + (i * self.ConnectionDetail.PAYLOAD_LENGTH)
                end = start + self.ConnectionDetail.PAYLOAD_LENGTH
                self.connection_details.append(self.ConnectionDetail.from_raw(data[start:end]))
        except Exception as ex:
            LOGGER.warn("Error getting connection info:", ex)

        super().__init__(request_id=request_id, payload_length=payload_length)

    @classmethod
    def from_raw(cls, data: bytes, request_id: int, payload_length: int):
        if payload_length < 71:
            return None
        return cls(data, request_id, payload_length)
