"""Configure SafeCook using the packed Food Safe Data payload (probe command 0x07)."""

from combustion_ble.food_safe import FoodSafeProgram
from combustion_ble.uart.message_type import MessageType
from combustion_ble.uart.request import Request
from combustion_ble.uart.response import Response


class ConfigureFoodSafeRequest(Request):
    def __init__(self, program: FoodSafeProgram):
        super().__init__(program.to_bytes(), MessageType.CONFIGURE_FOOD_SAFE)


class ConfigureFoodSafeResponse(Response):
    pass
