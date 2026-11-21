"""Direct probe sessions using an already-connected, host-owned Bleak client.

No scanner, adapter selection, connection, reconnection, or disconnection is performed here.
All methods and client callbacks must run on the same event loop. A session is single-use;
create a new session and client after a disconnect or an uncertain command outcome.
"""

from __future__ import annotations

import asyncio
import math
from typing import Any

from combustion_ble.ble_data.prediction_mode import PredictionMode
from combustion_ble.ble_data.probe_status import ProbeStatus
from combustion_ble.const import (
    DEVICE_STATUS_CHARACTERISTIC,
    UART_RX_CHARACTERISTIC,
    UART_TX_CHARACTERISTIC,
)
from combustion_ble.exceptions import PredictionCommandRejectedError
from combustion_ble.host_session import GattClient, HostSession, NotificationCallback
from combustion_ble.logger import LOGGER
from combustion_ble.meatnet import MeatNet
from combustion_ble.uart.message_type import MessageType
from combustion_ble.uart.set_prediction import SetPredictionRequest
from combustion_ble.utilities.crc16ccitt import crc16ccitt

__all__ = ["PredictionCommandRejectedError", "ProbeSession"]


class ProbeSession(HostSession):
    """Subscribe to a direct probe and control predictions through a host-owned client.

    Discover the probe in ``meatnet`` first. The caller must supply a client connected to that
    probe; use :class:`NodeSession` for a MeatNet repeater. Only one session per probe is allowed. The caller owns the client's
    disconnect callback and must call :meth:`disconnected` from it, then :meth:`stop` for cleanup.
    Stopping a session never disconnects its client or cancels a cook on the probe.
    """

    _already_owned_message = "This probe already has a prediction session"

    def __init__(
        self,
        meatnet: MeatNet,
        serial_number: int,
        client: GattClient,
        *,
        command_timeout: float = 10.0,
    ) -> None:
        if not math.isfinite(command_timeout) or command_timeout <= 0:
            raise ValueError("Command timeout must be finite and positive")
        self._probe = meatnet.probes[serial_number]
        super().__init__(meatnet, self._probe, client)
        self._command_timeout = command_timeout
        self._command_lock = asyncio.Lock()
        self._pending: asyncio.Future[bool] | None = None
        self._uart_buffer = bytearray()

    def disconnected(self) -> None:
        """Invalidate predictions and fail pending work immediately, without Bluetooth I/O.

        Call this from the host's Bleak disconnect callback. It also closes the session after
        a timed-out, cancelled, or failed command: direct probe responses have no request IDs,
        so a late acknowledgement cannot safely be assigned to another command.
        """
        super().disconnected()

    def _notifications(self) -> tuple[tuple[str, NotificationCallback], ...]:
        return (
            (UART_TX_CHARACTERISTIC, self._handle_uart),
            (DEVICE_STATUS_CHARACTERISTIC, self._handle_status),
        )

    def _get_owner(self) -> object | None:
        return self._probe._prediction_session

    def _set_owner(self, owner: object | None) -> None:
        self._probe._prediction_session = owner

    def _on_close(self) -> None:
        self._uart_buffer.clear()
        if self._pending is not None and not self._pending.done():
            self._pending.set_exception(ConnectionError("Probe session closed"))

    def _clear_predictions(self) -> None:
        self._meatnet.clear_prediction(self._probe.serial_number, source=self)

    async def set_removal_temperature(self, celsius: float) -> None:
        """Set a removal target (0–102.3 Celsius, rounded to 0.1) and await acknowledgement.

        An acknowledgement does not mean a prediction is ready; status notifications remain
        authoritative. Raises ``PredictionCommandRejectedError`` for a device rejection,
        ``TimeoutError`` for a timeout, or ``ConnectionError`` when the session is closed.
        """
        await self._send_prediction(celsius, PredictionMode.TIME_TO_REMOVAL)

    async def cancel_prediction(self) -> None:
        """Disable prediction mode on the probe and await acknowledgement."""
        await self._send_prediction(0.0, PredictionMode.NONE)

    async def _send_prediction(self, celsius: float, mode: PredictionMode) -> None:
        request = SetPredictionRequest(celsius, mode)
        async with self._command_lock:
            if not self._ready or not self._client.is_connected:
                raise ConnectionError("Probe session is not running")
            future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
            self._pending = future
            # Closing the session fails ``future``, so racing the write against it lets a close
            # interrupt a stalled write, and release the lock for commands queued behind it.
            write = asyncio.ensure_future(
                self._client.write_gatt_char(UART_RX_CHARACTERISTIC, request.data, response=True)
            )
            try:
                async with asyncio.timeout(self._command_timeout):
                    await asyncio.wait((write, future), return_when=asyncio.FIRST_COMPLETED)
                    if not future.done():
                        write.result()  # Raise a write failure.
                    success = await future
            except BaseException:
                self.disconnected()
                raise
            finally:
                self._pending = None
                if not write.done():
                    write.cancel()
                elif not write.cancelled():
                    write.exception()  # Consume a write failure after the session closed.
                if not future.done():
                    future.cancel()
                elif not future.cancelled():
                    future.exception()  # Consume disconnect errors even if the write failed first.
            if not success:
                raise PredictionCommandRejectedError("Probe rejected the prediction command")

    def _handle_status(self, _sender: Any, data: bytearray) -> None:
        if not self._active:
            return
        try:
            status = ProbeStatus.from_data(bytes(data))
            if status is not None:
                self._meatnet.handle_prediction_status(
                    self._probe.serial_number,
                    status.prediction_status,
                    food_safe=status.food_safe,
                    source=self,
                )
        except ValueError, IndexError:
            LOGGER.debug("Ignoring malformed connected probe status")

    def _handle_uart(self, _sender: Any, data: bytearray) -> None:
        if not self._active:
            return
        self._uart_buffer.extend(data)
        # Notifications may split frames or contain multiple frames. Resynchronize after noise
        # and CRC failures, and ignore valid responses for unrelated command types.
        while len(self._uart_buffer) >= 7:
            if self._uart_buffer[:2] != b"\xca\xfe":
                del self._uart_buffer[0]
                continue
            length = 7 + self._uart_buffer[6]
            if len(self._uart_buffer) < length:
                return
            frame = self._uart_buffer[:length]
            if crc16ccitt(frame[4:]) != int.from_bytes(frame[2:4], "little"):
                del self._uart_buffer[0]
                continue
            del self._uart_buffer[:length]
            if (
                frame[4] == MessageType.SET_PREDICTION
                and frame[5] in (0, 1)
                and frame[6] == 0
                and self._pending is not None
                and not self._pending.done()
            ):
                self._pending.set_result(bool(frame[5]))
