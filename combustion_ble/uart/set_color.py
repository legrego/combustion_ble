from combustion_ble.ble_data.mode_id import ProbeColor
from combustion_ble.uart.message_type import MessageType
from combustion_ble.uart.request import Request
from combustion_ble.uart.response import Response


class SetColorRequest(Request):
    def __init__(self, color: ProbeColor):
        payload = color.value.to_bytes(1)
        super().__init__(payload, message_type=MessageType.SET_COLOR)


class SetColorResponse(Response):
    pass
