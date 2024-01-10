from typing import Optional

from combustion_ble.logger import LOGGER
from combustion_ble.uart.log_response import LogResponse
from combustion_ble.uart.message_type import MessageType
from combustion_ble.uart.read_over_temperature import ReadOverTemperatureResponse
from combustion_ble.uart.response import Response
from combustion_ble.uart.session_info import SessionInfoResponse
from combustion_ble.uart.set_color import SetColorResponse
from combustion_ble.uart.set_id import SetIDResponse
from combustion_ble.uart.set_prediction import SetPredictionResponse
from combustion_ble.utilities.crc16ccitt import crc16ccitt

HEADER_LENGTH = 7


def responses_from_data(data) -> list[Response]:
    responses = []
    number_bytes_read = 0

    while number_bytes_read < len(data):
        bytes_to_decode = data[number_bytes_read:]
        response = response_from_data(bytes_to_decode)
        if response:
            responses.append(response)
            number_bytes_read += response.payload_length + HEADER_LENGTH
        else:
            break

    return responses


def response_from_data(data) -> Optional[Response]:
    # Sync bytes
    sync_bytes = data[:2]
    sync_string = "".join(format(byte, "02x") for byte in sync_bytes)
    if sync_string != "cafe":
        LOGGER.debug("Response::from_data(): Missing sync bytes in response")
        return None

    # Message type
    # type_byte = data[4]
    message_type = int(data[4])

    # Success/Fail
    success = bool(data[5])

    # Payload Length
    payload_length = data[6]

    # CRC - Implement your own CRC16-CCITT calculation
    crc = int.from_bytes(data[2:4], byteorder="little")
    crc_data_length = 3 + payload_length
    crc_data = data[4 : 4 + crc_data_length]
    calculated_crc = crc16ccitt(crc_data)

    if crc != calculated_crc:
        LOGGER.debug("Response::from_data(): Invalid CRC")
        return None

    response_length = payload_length + Response.HEADER_LENGTH
    if len(data) < response_length:
        return None

    # Process based on message_type
    if message_type == MessageType.LOG:
        return LogResponse.from_raw(data, success, int(payload_length))
    elif message_type == MessageType.SET_ID:
        return SetIDResponse(success, int(payload_length))
    elif message_type == MessageType.SET_COLOR:
        return SetColorResponse(success, int(payload_length))
    elif message_type == MessageType.SESSION_INFO:
        return SessionInfoResponse.from_raw(data, success, int(payload_length))
    elif message_type == MessageType.SET_PREDICTION:
        return SetPredictionResponse(success, int(payload_length))
    elif message_type == MessageType.READ_OVER_TEMPERATURE:
        return ReadOverTemperatureResponse(data, success, int(payload_length))
    else:
        LOGGER.debug("Ignoring response of type", message_type)

    return None
