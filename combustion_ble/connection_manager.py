import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from combustion_ble.devices.device import Device
from combustion_ble.utilities.asyncio_utils import ensure_future

if TYPE_CHECKING:
    from combustion_ble.device_manager import DeviceManager
    from combustion_ble.devices.meat_net_node import MeatNetNode
    from combustion_ble.devices.probe import Probe


class ConnectionManager:
    def __init__(self, device_manager: "DeviceManager"):
        self.meat_net_enabled = False
        self.dfu_mode_enabled = False
        self.connection_timers: dict[str, asyncio.Task] = {}
        self.last_status_update: dict[str, datetime] = {}
        self.PROBE_STATUS_STALE_TIMEOUT = 10.0
        self.device_manager = device_manager

    def received_probe_advertising(self, probe: Optional["Probe"]):
        if probe is None:
            return

        probe_status_stale = True

        if probe.serial_number_string in self.last_status_update:
            last_update_time = self.last_status_update[probe.serial_number_string]
            probe_status_stale = (
                datetime.now() - last_update_time
            ).total_seconds() > self.PROBE_STATUS_STALE_TIMEOUT

        if self.dfu_mode_enabled:
            ensure_future(probe.connect(), "probe.connect[dfu]")
        elif (
            self.meat_net_enabled
            and probe_status_stale
            and probe.connection_state != "connected"
            and probe.serial_number_string not in self.connection_timers
        ):
            self.connection_timers[probe.serial_number_string] = asyncio.create_task(
                self.connect_probe_after_delay(probe)
            )

    async def connect_probe_after_delay(self, probe: "Probe"):
        await asyncio.sleep(3)
        updated_probe = self.get_probe_with_serial(probe.serial_number_string)
        if updated_probe:
            await updated_probe.connect()
        del self.connection_timers[probe.serial_number_string]

    def received_probe_advertising_from_node(self, probe: Optional["Probe"], node: "MeatNetNode"):
        if self.meat_net_enabled:
            ensure_future(node.connect(), "probe.connect[meatnet]")

    def received_status_for(self, probe: "Probe", direct_connection: bool):
        self.last_status_update[probe.serial_number_string] = datetime.now()

        if not direct_connection and self.meat_net_enabled and not self.dfu_mode_enabled:
            updated_probe = self.get_probe_with_serial(probe.serial_number_string)
            if updated_probe and updated_probe.connection_state == Device.ConnectionState.CONNECTED:
                ensure_future(updated_probe.disconnect(), "probe.disconnect[prefer_meatnet]")

    def get_probe_with_serial(self, serial: str) -> Optional["Probe"]:
        probes = self.device_manager.get_probes()
        return next((probe for probe in probes if probe.serial_number_string == serial), None)
