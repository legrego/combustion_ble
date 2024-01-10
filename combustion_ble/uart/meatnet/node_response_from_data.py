import struct

from combustion_ble.logger import LOGGER
from combustion_ble.uart.meatnet.node_message_type import NodeMessageType
from combustion_ble.uart.meatnet.node_read_firmware_revision_response import (
    NodeReadFirmwareRevisionResponse,
)
from combustion_ble.uart.meatnet.node_read_hardware_revision_response import (
    NodeReadHardwareRevisionResponse,
)
from combustion_ble.uart.meatnet.node_read_logs_response import NodeReadLogsResponse
from combustion_ble.uart.meatnet.node_read_model_info_response import (
    NodeReadModelInfoResponse,
)
from combustion_ble.uart.meatnet.node_read_session_info_response import (
    NodeReadSessionInfoResponse,
)
from combustion_ble.uart.meatnet.node_response import NodeResponse
from combustion_ble.uart.meatnet.node_set_prediction_request import (
    NodeSetPredictionResponse,
)
from combustion_ble.utilities.crc16ccitt import crc16ccitt


def node_response_from_data(data: bytes):
    # Sync bytes
    sync_bytes = data[0:2]
    sync_string = "".join(format(x, "02x") for x in sync_bytes)
    if sync_string != "cafe":
        LOGGER.debug("NodeResponse::from_data(): Missing sync bytes in response")
        return None

    # Message type
    type_byte = data[4]

    # Verify that this is a Response by checking the response type flag
    if type_byte & NodeResponse.RESPONSE_TYPE_FLAG != NodeResponse.RESPONSE_TYPE_FLAG:
        # If that 'response type' bit isn't set, this is probably a Request.
        return None

    message_type = NodeMessageType(type_byte & ~NodeResponse.RESPONSE_TYPE_FLAG)
    if message_type is None:
        LOGGER.debug("NodeResponse::from_data(): Unknown message type in response")
        return None

    # Request ID
    request_id = struct.unpack(">I", data[5:9])[0]

    # Response ID
    response_id = struct.unpack(">I", data[9:13])[0]

    # Success/Fail
    success = bool(data[13])

    # Payload Length
    payload_length = data[14]

    # CRC
    crc = int.from_bytes(data[2:4], byteorder="little")
    crc_data = data[4 : 15 + payload_length]
    calculated_crc = crc16ccitt(crc_data)

    if crc != calculated_crc:
        LOGGER.debug("NodeResponse::from_data(): Invalid CRC")
        return None

    response_length = payload_length + NodeResponse.HEADER_LENGTH
    if len(data) < response_length:
        LOGGER.debug("Bad number of bytes")
        return None

    if message_type == NodeMessageType.LOG:
        return NodeReadLogsResponse.from_raw(
            data, success, request_id, response_id, int(payload_length)
        )
    # TODO: NodeSetIDResponse (commented out in Swift impl)
    # TODO: NodeSetColorResponse (commented out in Swift impl)
    elif message_type == NodeMessageType.SESSION_INFO:
        return NodeReadSessionInfoResponse.from_raw(
            data, success, request_id, response_id, int(payload_length)
        )
    elif message_type == NodeMessageType.SET_PREDICTION:
        return NodeSetPredictionResponse(success, request_id, response_id, int(payload_length))
    elif message_type == NodeMessageType.PROBE_FIRMWARE_REVISION:
        return NodeReadFirmwareRevisionResponse.from_raw(
            data, success, request_id, response_id, int(payload_length)
        )
    elif message_type == NodeMessageType.PROBE_HARDWARE_REVISION:
        return NodeReadHardwareRevisionResponse.from_raw(
            data, success, request_id, response_id, int(payload_length)
        )
    elif message_type == NodeMessageType.PROBE_MODEL_INFORMATION:
        return NodeReadModelInfoResponse.from_raw(
            data, success, request_id, response_id, int(payload_length)
        )
    # TODO: NodeReadOverTemperatureResponse (commented out in Swift impl)
    else:
        LOGGER.debug("Unhandled node response type: [%s]", message_type)

    return NodeResponse(success, request_id, response_id, payload_length)
