from combustion_ble.uart.message_type import MessageType
from combustion_ble.uart.request import Request


class LogRequest(Request):
    def __init__(self, min_sequence: int, max_sequence: int):
        # Packing the min and max sequence numbers into binary format
        min_payload = min_sequence.to_bytes(length=4, byteorder="little")
        max_payload = max_sequence.to_bytes(length=4, byteorder="little")

        # Combining the payloads
        combined_payload = min_payload + max_payload

        # Calling the superclass initializer with the combined payload and a type
        super().__init__(payload=combined_payload, message_type=MessageType.LOG)
