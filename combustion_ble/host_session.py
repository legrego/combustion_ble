"""Notification lifecycle shared by sessions that use an already-connected, host-owned client.

No scanner, adapter selection, connection, reconnection, or disconnection is performed here.
All methods and client callbacks must run on the same event loop. A session is single-use;
create a new session and client after a disconnect.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol

from combustion_ble.const import FW_VERSION_CHARACTERISTIC, HW_VERSION_CHARACTERISTIC
from combustion_ble.logger import LOGGER

if TYPE_CHECKING:
    from combustion_ble.meatnet import Device, MeatNet

NotificationCallback = Callable[[Any, bytearray], None]


class GattClient(Protocol):
    """The subset of a connected ``bleak.BleakClient`` used by a session."""

    @property
    def is_connected(self) -> bool: ...

    async def start_notify(self, char_specifier: str, callback: NotificationCallback) -> None: ...

    async def stop_notify(self, char_specifier: str) -> None: ...

    async def read_gatt_char(self, char_specifier: str) -> bytearray: ...

    async def write_gatt_char(
        self, char_specifier: str, data: bytes | bytearray, response: bool = True
    ) -> None: ...


class HostSession:
    """Subscribe to notifications on a host-owned client, with exclusive ownership of a device.

    Subclasses name their subscriptions and the device slot that records ownership, and clear the
    predictions they supplied when the session closes. Stopping a session never disconnects its
    client.
    """

    _already_owned_message = "This device already has a session"

    def __init__(self, meatnet: MeatNet, device: Device, client: GattClient) -> None:
        self._meatnet = meatnet
        self._device = device
        self._client = client
        self._lifecycle_lock = asyncio.Lock()
        self._subscribed: list[str] = []
        self._active = False
        self._ready = False
        self._closed = False

    # Subclass hooks

    def _notifications(self) -> tuple[tuple[str, NotificationCallback], ...]:
        raise NotImplementedError

    def _get_owner(self) -> object | None:
        raise NotImplementedError

    def _set_owner(self, owner: object | None) -> None:
        raise NotImplementedError

    def _on_close(self) -> None:
        """Release in-flight state when the session closes. Must not perform Bluetooth I/O."""

    def _clear_predictions(self) -> None:
        """Invalidate predictions this session supplied. Called only while it owns its device."""
        raise NotImplementedError

    # Lifecycle

    async def start(self) -> None:
        """Subscribe to notifications on an already-connected client.

        Prediction data arrives with the next status notification. A failed start attempts
        subscription cleanup and closes the session. Cancellation closes it immediately without
        awaiting cleanup, preserving the host's deadline. Always call :meth:`stop` in the host's
        ``finally`` block, with its own deadline, and disconnect the client if cleanup stalls.
        """
        async with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError("Create a new session after stopping or disconnecting")
            if self._ready:
                return
            if not self._client.is_connected:
                raise ConnectionError("Client is not connected")
            if self._get_owner() is not None:
                raise RuntimeError(self._already_owned_message)
            self._set_owner(self)
            self._active = True
            try:
                for characteristic, callback in self._notifications():
                    self._subscribed.append(characteristic)
                    await self._client.start_notify(characteristic, callback)
                    if not self._active or not self._client.is_connected:
                        raise ConnectionError("Client disconnected while subscribing")
                self._ready = True
            except asyncio.CancelledError:
                # An expired host timeout has already delivered its cancellation. Awaiting GATT
                # cleanup here could stall indefinitely without another cancellation to stop it.
                # Keep ownership until the host calls stop(), so old subscriptions cannot race
                # with a replacement session.
                self.disconnected()
                raise
            except Exception:
                self.disconnected()
                try:
                    await self._stop_notifications()
                except Exception:
                    LOGGER.exception("Failed cleaning up subscriptions after start failure")
                else:
                    self._set_owner(None)
                raise

    def disconnected(self) -> None:
        """Invalidate predictions and fail pending work immediately, without Bluetooth I/O.

        Call this from the host's Bleak disconnect callback.
        """
        self._active = False
        self._ready = False
        self._closed = True
        self._on_close()
        if self._get_owner() is self:
            # Retain ownership until stop() removes old subscriptions, so another session cannot
            # start on this device while cleanup could still unsubscribe its notifications.
            self._clear_predictions()

    async def stop(self) -> None:
        """Fail pending work, clear predictions, and remove every subscription.

        Safe to call repeatedly, including after disconnect. The host should bound cleanup with
        its own timeout. If cleanup fails or is cancelled, disconnect the client and call stop()
        again to release ownership without Bluetooth I/O before creating a replacement session.
        """
        async with self._lifecycle_lock:
            self.disconnected()
            await self._stop_notifications()
            if self._get_owner() is self:
                self._set_owner(None)

    async def read_device_information(self) -> None:
        """Read the connected device's firmware and hardware revisions into ``meatnet``.

        Reads the standard Device Information characteristics and updates
        :attr:`~combustion_ble.meatnet.Device.firmware_version` and
        :attr:`~combustion_ble.meatnet.Device.hardware_revision` on the device this session is
        connected to, notifying its listeners. Each value is applied as soon as it is read.

        Call it after :meth:`start`, as often as you like; the revisions only change after a
        firmware update. The host should bound it with its own timeout. A failed or cancelled read
        raises without affecting the session or its predictions.
        """
        firmware = await self._read_string(FW_VERSION_CHARACTERISTIC)
        self._meatnet.handle_device_information(self._device, firmware_version=firmware)
        hardware = await self._read_string(HW_VERSION_CHARACTERISTIC)
        self._meatnet.handle_device_information(self._device, hardware_revision=hardware)

    async def _read_string(self, characteristic: str) -> str:
        if not self._ready or not self._client.is_connected:
            raise ConnectionError("Session is not running")
        data = await self._client.read_gatt_char(characteristic)
        return decode_string(data)

    async def _stop_notifications(self) -> None:
        failed: list[str] = []
        error: Exception | None = None
        for characteristic in reversed(self._subscribed):
            if not self._client.is_connected:
                break
            try:
                await self._client.stop_notify(characteristic)
            except Exception as exc:
                failed.append(characteristic)
                error = exc
        self._subscribed = failed
        if error is not None:
            raise error


def decode_string(data: bytes | bytearray) -> str:
    """Decode a fixed-length, NUL-padded UTF-8 string field."""
    return bytes(data).split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()
