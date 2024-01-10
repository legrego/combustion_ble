import struct

from combustion_ble.logger import LOGGER
from combustion_ble.uart.meatnet.node_heartbeat_request import NodeHeartbeatRequest
from combustion_ble.uart.meatnet.node_message_type import NodeMessageType
from combustion_ble.uart.meatnet.node_probe_status_request import NodeProbeStatusRequest
from combustion_ble.uart.meatnet.node_request import NodeRequest
from combustion_ble.uart.meatnet.node_sync_thermometer_list_request import (
    NodeSyncThermometerListRequest,
)
from combustion_ble.utilities.crc16ccitt import crc16ccitt


def node_request_from_data(data: bytes) -> NodeRequest | None:
    if data[:2] != b"\xCA\xFE":
        LOGGER.debug("Missing sync bytes in request")
        return None

    message_type_raw = data[4]
    message_type = None
    if message_type_raw in NodeMessageType._value2member_map_:
        message_type = NodeMessageType(message_type_raw)

    if message_type is None:
        LOGGER.debug("Unknown message type in request: [%s]", message_type_raw)
        return None

    # Request ID
    request_id = struct.unpack(">I", data[5:9])[0]

    # Payload Length
    payload_length = data[9]

    # CRC Check
    crc = int.from_bytes(data[2:4], byteorder="little")
    calculated_crc = crc16ccitt(data[4 : 10 + payload_length])

    if crc != calculated_crc:
        LOGGER.debug("Invalid CRC. Expected [%s] but found [%s]", calculated_crc, crc)
        return None

    if message_type == NodeMessageType.PROBE_STATUS:
        return NodeProbeStatusRequest.from_raw(data, request_id, payload_length)
    elif message_type == NodeMessageType.HEARTBEAT:
        return NodeHeartbeatRequest.from_raw(data, request_id, payload_length)
    elif message_type == NodeMessageType.SYNC_THERMOMETER_LIST:
        return NodeSyncThermometerListRequest.from_raw(data, request_id, payload_length)
    elif (
        message_type == NodeMessageType.SESSION_INFO
        or message_type == NodeMessageType.CONNECTED
        or message_type == NodeMessageType.DISCONNECTED
    ):
        # This SDK, as of now, does not need to act on these requests.
        # This also isn't implemented upstream. This if block exists to quiet the debug logger.
        pass

    LOGGER.debug("node_request_from_data:: Unhandled node request type: [%s]", message_type.name)
    return None
