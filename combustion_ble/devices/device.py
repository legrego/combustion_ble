from datetime import datetime
from typing import TYPE_CHECKING, Optional

from combustion_ble.exceptions import DFUNotImplementedError
from combustion_ble.utilities.asyncio_utils import ensure_future

if TYPE_CHECKING:
    from combustion_ble.device_manager import DeviceManager


class Device:
    MIN_RSSI = -128
    STALE_TIMEOUT = 15.0

    class ConnectionState:
        DISCONNECTED = "disconnected"
        CONNECTING = "connecting"
        CONNECTED = "connected"
        FAILED = "failed"

    class DFUErrorMessage:
        def __init__(self, error, message):
            self.error = error
            self.message = message

    class DFUUploadProgress:
        def __init__(self, part, total_parts, progress):
            self.part = part
            self.total_parts = total_parts
            self.progress = progress

    def __init__(
        self,
        unique_identifier: str,
        device_manager: "DeviceManager",
        ble_identifier: Optional[str] = None,
        rssi=None,
    ):
        self.unique_identifier: str = unique_identifier
        self.ble_identifier: Optional[str] = ble_identifier if ble_identifier else None
        self.rssi: int = rssi if rssi is not None else self.MIN_RSSI
        self.firmware_version: Optional[str] = "IDK"
        self.hardware_revision: Optional[str] = "IDK"
        self.sku: Optional[str] = None
        self.manufacturing_lot: Optional[str] = None
        self.connection_state: str = Device.ConnectionState.DISCONNECTED
        self.is_connectable: bool = False
        self.maintaining_connection: bool = False
        self.stale: bool = False
        self.dfu_state = None
        self.dfu_error = None
        self.dfu_upload_progress = None
        self.last_update_time: datetime = datetime.now()
        self.dfu_service_controller = None
        self.device_manager: "DeviceManager" = device_manager

    def update_connection_state(self, state: str):
        self.connection_state = state

        if self.connection_state == Device.ConnectionState.DISCONNECTED:
            self.firmware_version = None

        if self.maintaining_connection and (
            self.connection_state == Device.ConnectionState.DISCONNECTED
            or self.connection_state == Device.ConnectionState.FAILED
        ):
            ensure_future(self.connect(), name="device.connect[update_connection_state]")

    def update_device_stale(self):
        self.stale = (datetime.now() - self.last_update_time).total_seconds() > self.STALE_TIMEOUT
        if self.stale:
            self.is_connectable = False

    def is_dfu_running(self) -> bool:
        if not self.dfu_state:
            return False

        raise DFUNotImplementedError()

    def dfu_complete(self):
        raise DFUNotImplementedError()

    def update_with_model_info(self, model_info: str):
        # Parse the SKU and lot number, which are delimited by a ':'
        parts = model_info.split(":")
        if len(parts) == 2:
            self.sku = parts[0]
            self.manufacturing_lot = parts[1]

    async def connect(self):
        self.maintaining_connection = True

        if self.connection_state != Device.ConnectionState.CONNECTED:
            await self.device_manager._connect_to_device(self)

    async def disconnect(self):
        self.maintaining_connection = False
        await self.device_manager._disconnect_from_device(self)

    def run_software_upgrade(self, dfu_file):
        raise DFUNotImplementedError()

    def dfu_state_did_change(self, state):
        raise DFUNotImplementedError()

    def dfu_error_did_occur(self, error, message):
        raise DFUNotImplementedError()

    def dfu_progress_did_change(self, part, total_parts, progress):
        raise DFUNotImplementedError()

    def log_with_level(self, level, message):
        raise DFUNotImplementedError()

    # Hashable implementation
    def __hash__(self):
        return hash(self.unique_identifier)

    def __eq__(self, other: object):
        if not isinstance(other, Device):
            return False
        return self.unique_identifier == other.unique_identifier if other else False
