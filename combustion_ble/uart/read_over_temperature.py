from combustion_ble.uart.message_type import MessageType
from combustion_ble.uart.request import Request
from combustion_ble.uart.response import Response


class ReadOverTemperatureRequest(Request):
    def __init__(self):
        super().__init__(payload=bytes(), message_type=MessageType.READ_OVER_TEMPERATURE)


class ReadOverTemperatureResponse(Response):
    PAYLOAD_LENGTH = 1

    def __init__(self, data, success, payload_length):
        sequence_byte_index = Response.HEADER_LENGTH
        flag_set_byte = data[sequence_byte_index : sequence_byte_index + 1]

        self.flag_set = bool(flag_set_byte[0])

        super().__init__(success, payload_length)
