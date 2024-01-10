from typing import TYPE_CHECKING

from combustion_ble.ble_data.advertising_data import AdvertisingData
from combustion_ble.devices.device import Device
from combustion_ble.dfu_manager import DFUDeviceType

if TYPE_CHECKING:
    from ..device_manager import DeviceManager
    from .probe import Probe


class MeatNetNode(Device):
    def __init__(
        self,
        advertising: AdvertisingData,
        device_manager: "DeviceManager",
        is_connectable: bool,
        rssi: int,
        identifier: str,
    ):
        super().__init__(
            unique_identifier=str(identifier),
            device_manager=device_manager,
            ble_identifier=identifier,
            rssi=rssi,
        )
        self.serial_number_string = None
        self.probes: dict[int, Probe] = {}
        self.dfu_type = DFUDeviceType.UNKNOWN
        self.update_with_advertising(advertising, is_connectable, rssi)

    def update_with_advertising(
        self, advertising: AdvertisingData, is_connectable: bool, rssi: int
    ):
        self.rssi = rssi
        self.is_connectable = is_connectable

    def update_networked_probe(self, probe: "Probe"):
        if probe is not None:
            self.probes[probe.serial_number] = probe

    def has_connection_to_probe(self, serial_number: int):
        return serial_number in self.probes or str(serial_number) in self.probes  # todo ... yucky

    def update_with_model_info(self, model_info: str):
        super().update_with_model_info(model_info)
        if "Timer" in model_info:
            self.dfu_type = "display"
        elif "Charger" in model_info:
            self.dfu_type = "charger"

    def __str__(self):
        return f"MeatNetNode: {self.unique_identifier}"
