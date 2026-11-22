"""Relayed cooking predictions through a MeatNet node, using a host-owned Bleak client.

No scanner, adapter selection, connection, reconnection, or disconnection is performed here.
All methods and client callbacks must run on the same event loop. A session is single-use;
create a new session and client after a disconnect.
"""

from __future__ import annotations

import asyncio
import math
import secrets
from dataclasses import dataclass
from typing import Any

from combustion_ble.ble_data.hop_count import HopCount
from combustion_ble.ble_data.prediction_mode import PredictionMode
from combustion_ble.ble_data.probe_status import ProbeStatus
from combustion_ble.const import UART_RX_CHARACTERISTIC, UART_TX_CHARACTERISTIC
from combustion_ble.exceptions import (
    PredictionCommandRejectedError,
    RequestRejectedError,
)
from combustion_ble.food_safe import FoodSafeProgram
from combustion_ble.host_session import (
    GattClient,
    HostSession,
    NotificationCallback,
    decode_string,
)
from combustion_ble.logger import LOGGER
from combustion_ble.meatnet import MeatNet
from combustion_ble.uart.meatnet.node_message_type import NodeMessageType
from combustion_ble.uart.set_prediction import encode_set_prediction
from combustion_ble.utilities.crc16ccitt import crc16ccitt

_SYNC = b"\xca\xfe"
_REQUEST_HEADER_LENGTH = 10
_RESPONSE_HEADER_LENGTH = 15
_RESPONSE_FLAG = 0x80
_REQUEST_ID = slice(5, 9)
_SUCCESS_INDEX = 13

DEFAULT_COMMAND_TIMEOUT = 30.0
"""Seconds to wait for a node's response. Requests can cross several MeatNet hops, so this
matches the timeout Combustion's Android SDK uses for MeatNet messages."""

# Probe Status (0x45) payload layout. Every node firmware starts with the probe's serial number and
# the original 30-byte probe status. Firmware that predates food safe data follows that with the
# network information byte; current firmware puts food safe data (18 bytes) in between.
_SERIAL = slice(0, 4)
_LEGACY_PROBE_STATUS = slice(4, 34)
_PROBE_STATUS = slice(4, 52)
_LEGACY_PAYLOAD_LENGTH = 35
_LEGACY_NETWORK_INFO_INDEX = 34
_NETWORK_INFO_INDEX = 52

# Probe Firmware Revision (0x46) and Probe Hardware Revision (0x47) responses: the probe's serial
# number, then a fixed-length string.
_SERIAL_LENGTH = 4


@dataclass(frozen=True, slots=True)
class _Response:
    success: bool
    payload: bytes


def encode_node_request(message_type: NodeMessageType, request_id: int, payload: bytes) -> bytes:
    """Frame a node UART request: sync bytes, CRC, type, request ID, length, and payload."""
    body = (
        bytes([message_type.value])
        + request_id.to_bytes(4, "little")
        + bytes([len(payload)])
        + payload
    )
    return _SYNC + crc16ccitt(body).to_bytes(2, "little") + body


class NodeSession(HostSession):
    """Receive cooking predictions for every probe a MeatNet node relays, via a host-owned client.

    Discover the node in ``meatnet`` first, then supply a client connected to that node (a Display,
    Booster, Giant Grill Gauge, or Engine). One connection reports predictions for every probe on
    the node's MeatNet network. Only one session per node is allowed. Predictions are applied
    only to probes already discovered through advertisements.

    The session can also send requests through the node to any probe on its network: setting and
    cancelling prediction targets, and reading a probe's firmware and hardware revisions. Each
    request is matched to its response by request ID, so requests may run concurrently, and a
    request that times out or is cancelled doesn't affect the session or other requests.

    The caller owns the client's disconnect callback and must call :meth:`disconnected` from it,
    then :meth:`stop` for cleanup. Stopping a session never disconnects its client or cancels a
    cook on any probe.
    """

    _already_owned_message = "This node already has a session"

    def __init__(
        self,
        meatnet: MeatNet,
        address: str,
        client: GattClient,
        *,
        command_timeout: float = DEFAULT_COMMAND_TIMEOUT,
    ) -> None:
        if not math.isfinite(command_timeout) or command_timeout <= 0:
            raise ValueError("Command timeout must be finite and positive")
        self._node = meatnet.nodes[address]
        super().__init__(meatnet, self._node, client)
        self._command_timeout = command_timeout
        self._write_lock = asyncio.Lock()
        self._pending: dict[bytes, tuple[int, asyncio.Future[_Response]]] = {}
        self._uart_buffer = bytearray()
        self._reported: set[int] = set()

    def _is_reporting(self, serial_number: int) -> bool:
        """Whether this session is currently supplying predictions for a probe.

        True once the node has relayed a status for the probe, until that status goes stale
        (see :meth:`MeatNet.expire`) or the session closes. Used by
        :func:`~combustion_ble.connection_plan.plan_connections`.
        """
        probe = self._meatnet.probes.get(serial_number)
        return probe is not None and self in probe._prediction_feeds

    def _notifications(self) -> tuple[tuple[str, NotificationCallback], ...]:
        return ((UART_TX_CHARACTERISTIC, self._handle_uart),)

    def _get_owner(self) -> object | None:
        return self._node._prediction_session

    def _set_owner(self, owner: object | None) -> None:
        self._node._prediction_session = owner

    def _on_close(self) -> None:
        self._uart_buffer.clear()
        for _, future in self._pending.values():
            if not future.done():
                future.set_exception(ConnectionError("Node session closed"))

    def _clear_predictions(self) -> None:
        reported, self._reported = self._reported, set()
        for serial_number in reported:
            if serial_number in self._meatnet.probes:
                self._meatnet.clear_prediction(serial_number, source=self)

    def _handle_uart(self, _sender: Any, data: bytearray) -> None:
        if not self._active:
            return
        buffer = self._uart_buffer
        buffer.extend(data)
        # Notifications may split frames or contain multiple frames. Resynchronize after noise and
        # CRC failures, and skip every message other than relayed probe status.
        while len(buffer) >= _REQUEST_HEADER_LENGTH:
            if buffer[:2] != _SYNC:
                del buffer[0]
                continue
            message_type = buffer[4]
            header_length = (
                _RESPONSE_HEADER_LENGTH if message_type & _RESPONSE_FLAG else _REQUEST_HEADER_LENGTH
            )
            if len(buffer) < header_length:
                return
            length = header_length + buffer[header_length - 1]
            if len(buffer) < length:
                return
            frame = bytes(buffer[:length])
            if crc16ccitt(frame[4:]) != int.from_bytes(frame[2:4], "little"):
                del buffer[0]
                continue
            del buffer[:length]
            if message_type & _RESPONSE_FLAG:
                self._handle_response(message_type & ~_RESPONSE_FLAG, frame)
            elif message_type == NodeMessageType.PROBE_STATUS.value:
                self._handle_probe_status(frame[_REQUEST_HEADER_LENGTH:])

    def _handle_response(self, message_type: int, frame: bytes) -> None:
        # Responses to requests from other apps on the network are ignored.
        pending = self._pending.get(frame[_REQUEST_ID])
        if pending is None or pending[0] != message_type or pending[1].done():
            return
        invalid_success = frame[_SUCCESS_INDEX] not in (0, 1)
        unexpected_payload = (
            message_type
            in (
                NodeMessageType.SET_PREDICTION.value,
                NodeMessageType.CONFIGURE_FOOD_SAFE.value,
                NodeMessageType.RESET_FOOD_SAFE.value,
            )
            and len(frame) != _RESPONSE_HEADER_LENGTH
        )
        if invalid_success or unexpected_payload:
            reason = "invalid success flag" if invalid_success else "unexpected payload"
            message = f"Malformed node response for {NodeMessageType(message_type).name}: {reason}"
            LOGGER.warning(message)
            pending[1].set_exception(ValueError(message))
            return
        pending[1].set_result(
            _Response(bool(frame[_SUCCESS_INDEX]), frame[_RESPONSE_HEADER_LENGTH:])
        )

    # Requests

    async def set_removal_temperature(self, serial_number: int, celsius: float) -> None:
        """Set a probe's removal target (0–102.3 Celsius, rounded to 0.1) through the node.

        Awaits the node's acknowledgement. An acknowledgement does not mean a prediction is ready;
        relayed status remains authoritative. Raises ``PredictionCommandRejectedError`` when the
        node reports failure, ``ValueError`` for a malformed response, ``TimeoutError`` after
        ``command_timeout``, or ``ConnectionError``
        when the session isn't running or closes first.
        """
        await self._send_prediction(serial_number, celsius, PredictionMode.TIME_TO_REMOVAL)

    async def cancel_prediction(self, serial_number: int) -> None:
        """Disable prediction mode on a probe through the node and await acknowledgement."""
        await self._send_prediction(serial_number, 0.0, PredictionMode.NONE)

    async def configure_food_safe(self, serial_number: int, program: FoodSafeProgram) -> None:
        """Configure a probe's SafeCook program through the node and await acknowledgement.

        Status remains authoritative. Raises ``ValueError`` for invalid parameters,
        ``RequestRejectedError`` for rejection, ``ValueError`` for a malformed response,
        ``TimeoutError`` for timeout, or
        ``ConnectionError`` when closed. Failed requests leave the node session running.
        """
        await self._send_food_safe(
            serial_number, NodeMessageType.CONFIGURE_FOOD_SAFE, program.to_bytes()
        )

    async def clear_food_safe(self, serial_number: int) -> None:
        """Turn a probe's SafeCook off by writing an all-zero program; await acknowledgement."""
        await self._send_food_safe(serial_number, NodeMessageType.CONFIGURE_FOOD_SAFE, bytes(10))

    async def reset_food_safe(self, serial_number: int) -> None:
        """Reset a probe's SafeCook progress, preserving its parameters; await acknowledgement."""
        await self._send_food_safe(serial_number, NodeMessageType.RESET_FOOD_SAFE, b"")

    async def _send_food_safe(
        self, serial_number: int, message_type: NodeMessageType, payload: bytes
    ) -> None:
        response = await self._request(message_type, _encode_serial(serial_number) + payload)
        if not response.success:
            raise RequestRejectedError("Node rejected the SafeCook command")

    async def read_probe_information(self, serial_number: int) -> None:
        """Read a probe's firmware and hardware revisions through the node into ``meatnet``.

        Updates :attr:`~combustion_ble.meatnet.Device.firmware_version` and
        :attr:`~combustion_ble.meatnet.Device.hardware_revision` on the probe, which must already
        be discovered, notifying its listeners. Each value is applied as soon as it is read.
        Raises ``RequestRejectedError`` when the node can't reach the probe, and otherwise the
        same errors as :meth:`set_removal_temperature`.
        """
        probe = self._meatnet.probes[serial_number]
        firmware = await self._read_probe_string(
            NodeMessageType.PROBE_FIRMWARE_REVISION, serial_number
        )
        self._meatnet.handle_device_information(probe, firmware_version=firmware)
        hardware = await self._read_probe_string(
            NodeMessageType.PROBE_HARDWARE_REVISION, serial_number
        )
        self._meatnet.handle_device_information(probe, hardware_revision=hardware)

    async def _send_prediction(
        self, serial_number: int, celsius: float, mode: PredictionMode
    ) -> None:
        payload = _encode_serial(serial_number) + encode_set_prediction(celsius, mode)
        response = await self._request(NodeMessageType.SET_PREDICTION, payload)
        if not response.success:
            raise PredictionCommandRejectedError("Node rejected the prediction command")

    async def _read_probe_string(self, message_type: NodeMessageType, serial_number: int) -> str:
        serial = _encode_serial(serial_number)
        response = await self._request(message_type, serial)
        if not response.success:
            raise RequestRejectedError(
                f"Node couldn't read {message_type.name} for probe {serial_number:08X}"
            )
        if response.payload[:_SERIAL_LENGTH] != serial:
            raise ValueError(f"Malformed {message_type.name} response")
        return decode_string(response.payload[_SERIAL_LENGTH:])

    async def _request(self, message_type: NodeMessageType, payload: bytes) -> _Response:
        if not self._ready or not self._client.is_connected:
            raise ConnectionError("Node session is not running")
        request_id = secrets.randbits(32).to_bytes(4, "little")
        while request_id in self._pending or request_id == bytes(4):
            request_id = secrets.randbits(32).to_bytes(4, "little")
        frame = encode_node_request(message_type, int.from_bytes(request_id, "little"), payload)
        future: asyncio.Future[_Response] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = (message_type.value, future)
        # Closing the session fails ``future``, so racing the write against it lets a close
        # interrupt a request that is still waiting for the write lock or for a stalled write.
        write = asyncio.ensure_future(self._write(frame))
        try:
            async with asyncio.timeout(self._command_timeout):
                await asyncio.wait((write, future), return_when=asyncio.FIRST_COMPLETED)
                if not future.done():
                    write.result()  # Raise a write failure.
                return await future
        finally:
            del self._pending[request_id]
            if not write.done():
                write.cancel()
            elif not write.cancelled():
                write.exception()  # Consume a write failure after the session closed.
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()  # Consume a close error even if the write failed first.

    async def _write(self, frame: bytes) -> None:
        async with self._write_lock:
            if not self._active:
                raise ConnectionError("Node session closed")
            await self._client.write_gatt_char(UART_RX_CHARACTERISTIC, frame, response=True)

    def _handle_probe_status(self, payload: bytes) -> None:
        if len(payload) == _LEGACY_PAYLOAD_LENGTH:
            network_info = payload[_LEGACY_NETWORK_INFO_INDEX]
            status_bytes = payload[_LEGACY_PROBE_STATUS]
        elif len(payload) > _NETWORK_INFO_INDEX:
            network_info = payload[_NETWORK_INFO_INDEX]
            status_bytes = payload[_PROBE_STATUS]
        else:
            LOGGER.debug("Ignoring relayed probe status with %d byte payload", len(payload))
            return

        serial_number = int.from_bytes(payload[_SERIAL], "little")
        if serial_number not in self._meatnet.probes:
            # The node's own advertisements will announce the probe shortly.
            LOGGER.debug("Ignoring relayed status for undiscovered probe %08X", serial_number)
            return
        try:
            status = ProbeStatus.from_data(status_bytes)
        except ValueError, IndexError:
            LOGGER.debug("Ignoring malformed relayed probe status")
            return
        if status is None:
            return
        self._reported.add(serial_number)
        self._meatnet.handle_prediction_status(
            serial_number,
            status.prediction_status,
            food_safe=status.food_safe,
            source=self,
            hop_count=HopCount.from_network_info_byte(network_info).value + 1,
        )


def _encode_serial(serial_number: int) -> bytes:
    if not 0 <= serial_number <= 0xFFFFFFFF:
        raise ValueError("Probe serial number must fit in 32 bits")
    return serial_number.to_bytes(4, "little")
