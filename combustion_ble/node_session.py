"""Relayed cooking predictions through a MeatNet node, using a host-owned Bleak client.

No scanner, adapter selection, connection, reconnection, or disconnection is performed here.
All methods and client callbacks must run on the same event loop. A session is single-use;
create a new session and client after a disconnect.
"""

from __future__ import annotations

from typing import Any

from combustion_ble.ble_data.hop_count import HopCount
from combustion_ble.ble_data.probe_status import ProbeStatus
from combustion_ble.const import UART_TX_CHARACTERISTIC
from combustion_ble.host_session import GattClient, HostSession, NotificationCallback
from combustion_ble.logger import LOGGER
from combustion_ble.meatnet import MeatNet
from combustion_ble.uart.meatnet.node_message_type import NodeMessageType
from combustion_ble.utilities.crc16ccitt import crc16ccitt

_SYNC = b"\xca\xfe"
_REQUEST_HEADER_LENGTH = 10
_RESPONSE_HEADER_LENGTH = 15
_RESPONSE_FLAG = 0x80

# Probe Status (0x45) payload layout. Every node firmware starts with the probe's serial number and
# the original 30-byte probe status. Firmware that predates food safe data follows that with the
# network information byte; current firmware puts food safe data (18 bytes) in between.
_SERIAL = slice(0, 4)
_PROBE_STATUS = slice(4, 34)
_LEGACY_PAYLOAD_LENGTH = 35
_LEGACY_NETWORK_INFO_INDEX = 34
_NETWORK_INFO_INDEX = 52


class NodeSession(HostSession):
    """Receive cooking predictions for every probe a MeatNet node relays, via a host-owned client.

    Discover the node in ``meatnet`` first, then supply a client connected to that node (a Display,
    Booster, Giant Grill Gauge, or Engine). One connection reports predictions for every probe on
    the node's MeatNet network. Only one session per node is allowed. Predictions are applied
    only to probes already discovered through advertisements.

    The caller owns the client's disconnect callback and must call :meth:`disconnected` from it,
    then :meth:`stop` for cleanup. Stopping a session never disconnects its client.
    """

    _already_owned_message = "This node already has a session"

    def __init__(self, meatnet: MeatNet, address: str, client: GattClient) -> None:
        super().__init__(client)
        self._meatnet = meatnet
        self._node = meatnet.nodes[address]
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
            if message_type == NodeMessageType.PROBE_STATUS.value:
                self._handle_probe_status(frame[_REQUEST_HEADER_LENGTH:])

    def _handle_probe_status(self, payload: bytes) -> None:
        if len(payload) == _LEGACY_PAYLOAD_LENGTH:
            network_info = payload[_LEGACY_NETWORK_INFO_INDEX]
        elif len(payload) > _NETWORK_INFO_INDEX:
            network_info = payload[_NETWORK_INFO_INDEX]
        else:
            LOGGER.debug("Ignoring relayed probe status with %d byte payload", len(payload))
            return

        serial_number = int.from_bytes(payload[_SERIAL], "little")
        if serial_number not in self._meatnet.probes:
            # The node's own advertisements will announce the probe shortly.
            LOGGER.debug("Ignoring relayed status for undiscovered probe %08X", serial_number)
            return
        try:
            status = ProbeStatus.from_data(payload[_PROBE_STATUS])
        except ValueError, IndexError:
            LOGGER.debug("Ignoring malformed relayed probe status")
            return
        if status is None:
            return
        self._reported.add(serial_number)
        self._meatnet.handle_prediction_status(
            serial_number,
            status.prediction_status,
            source=self,
            hop_count=HopCount.from_network_info_byte(network_info).value + 1,
        )
