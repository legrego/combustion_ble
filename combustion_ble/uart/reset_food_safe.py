"""Reset SafeCook progress without changing its parameters (probe command 0x08)."""

from combustion_ble.uart.message_type import MessageType
from combustion_ble.uart.request import Request
from combustion_ble.uart.response import Response


class ResetFoodSafeRequest(Request):
    def __init__(self):
        super().__init__(b"", MessageType.RESET_FOOD_SAFE)


class ResetFoodSafeResponse(Response):
    pass
