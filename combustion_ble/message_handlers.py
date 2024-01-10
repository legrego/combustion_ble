from datetime import datetime
from typing import Callable

from combustion_ble.uart.meatnet.node_set_prediction_request import (
    NodeSetPredictionResponse,
)
from combustion_ble.uart.read_over_temperature import ReadOverTemperatureResponse
from combustion_ble.uart.set_color import SetColorResponse
from combustion_ble.uart.set_id import SetIDResponse
from combustion_ble.uart.set_prediction import SetPredictionResponse

SuccessHandler = Callable[[bool], None]
ReadOverTemperatureHandler = Callable[[bool, bool], None]


# Structs to store when BLE message was sent and the completion handler for message
class MessageSentHandler:
    def __init__(
        self,
        time_sent: datetime,
        success_handler: SuccessHandler | None,
        read_over_temperature_completion_handler: ReadOverTemperatureHandler | None,
    ) -> None:
        self.time_sent = time_sent
        self.success_handler = success_handler
        self.read_over_temperature_completion_handler = read_over_temperature_completion_handler


class MessageHandlers:
    MESSAGE_TIMEOUT_SECONDS = 3

    def __init__(self):
        self.set_id_completion_handlers: dict[str, MessageSentHandler] = {}
        self.set_color_completion_handlers: dict[str, MessageSentHandler] = {}
        self.set_prediction_completion_handlers: dict[str, MessageSentHandler] = {}
        self.read_over_temperature_completion_handlers: dict[str, MessageSentHandler] = {}
        self.set_node_prediction_completion_handlers: dict[str, MessageSentHandler] = {}

    def check_for_timeout(self):
        current_time = datetime.now()
        self._check_for_message_timeout(self.set_id_completion_handlers, current_time)
        self._check_for_message_timeout(self.set_color_completion_handlers, current_time)
        self._check_for_message_timeout(self.set_prediction_completion_handlers, current_time)
        self._check_for_message_timeout(
            self.read_over_temperature_completion_handlers, current_time
        )
        self._check_for_message_timeout(self.set_node_prediction_completion_handlers, current_time)

    def _check_for_message_timeout(
        self, handlers: dict[str, MessageSentHandler], current_time: datetime
    ):
        keys_to_remove = []
        for key, value in handlers.items():
            if (current_time - value.time_sent).total_seconds() > self.MESSAGE_TIMEOUT_SECONDS:
                if value.success_handler:
                    value.success_handler(False)
                if value.read_over_temperature_completion_handler:
                    value.read_over_temperature_completion_handler(False, False)
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del handlers[key]

    def clear_handlers_for_device(self, device_identifier: str):
        if device_identifier in self.set_color_completion_handlers:
            del self.set_color_completion_handlers[device_identifier]

        if device_identifier in self.set_id_completion_handlers:
            del self.set_id_completion_handlers[device_identifier]

        if device_identifier in self.set_prediction_completion_handlers:
            del self.set_prediction_completion_handlers[device_identifier]

        if device_identifier in self.read_over_temperature_completion_handlers:
            del self.read_over_temperature_completion_handlers[device_identifier]

        if device_identifier in self.set_node_prediction_completion_handlers:
            del self.set_node_prediction_completion_handlers[device_identifier]

    def add_set_id_completion_handler(
        self, device_identifier: str, completion_handler: SuccessHandler
    ):
        self.set_id_completion_handlers[device_identifier] = MessageSentHandler(
            datetime.now(), completion_handler, None
        )

    def call_set_id_completion_handler(self, identifier: str, response: SetIDResponse):
        handler = self.set_id_completion_handlers.get(identifier)
        if handler and handler.success_handler:
            handler.success_handler(response.success)
        self.set_id_completion_handlers.pop(identifier, None)

    def add_set_color_completion_handler(
        self, device_identifier: str, completion_handler: SuccessHandler
    ):
        self.set_color_completion_handlers[device_identifier] = MessageSentHandler(
            datetime.now(), completion_handler, None
        )

    def call_set_color_completion_handler(self, identifier: str, response: SetColorResponse):
        handler = self.set_color_completion_handlers.get(identifier)
        if handler and handler.success_handler:
            handler.success_handler(response.success)
        self.set_color_completion_handlers.pop(identifier, None)

    def add_set_prediction_completion_handler(
        self, device_identifier: str, completion_handler: SuccessHandler
    ):
        self.set_prediction_completion_handlers[device_identifier] = MessageSentHandler(
            datetime.now(), completion_handler, None
        )

    def call_set_prediction_completion_handler(
        self, identifier: str, response: SetPredictionResponse
    ):
        handler = self.set_prediction_completion_handlers.get(identifier)
        if handler and handler.success_handler:
            handler.success_handler(response.success)
        self.set_prediction_completion_handlers.pop(identifier, None)

    def add_read_over_temperature_completion_handler(
        self, device_identifier: str, completion_handler: ReadOverTemperatureHandler
    ):
        self.read_over_temperature_completion_handlers[device_identifier] = MessageSentHandler(
            datetime.now(), None, completion_handler
        )

    def call_read_over_temperature_completion_handler(
        self, identifier: str, response: ReadOverTemperatureResponse
    ):
        handler = self.read_over_temperature_completion_handlers.get(identifier)
        if handler and handler.read_over_temperature_completion_handler:
            handler.read_over_temperature_completion_handler(response.success, response.flag_set)
        self.read_over_temperature_completion_handlers.pop(identifier, None)

    def add_node_set_prediction_completion_handler(
        self, device_identifier: str, completion_handler: SuccessHandler
    ):
        self.set_node_prediction_completion_handlers[device_identifier] = MessageSentHandler(
            datetime.now(), completion_handler, None
        )

    def call_node_set_prediction_completion_handler(
        self, identifier: str, response: NodeSetPredictionResponse
    ):
        handler = self.set_node_prediction_completion_handlers.get(identifier)
        if handler and handler.success_handler:
            handler.success_handler(response.success)
        self.set_node_prediction_completion_handlers.pop(identifier, None)
