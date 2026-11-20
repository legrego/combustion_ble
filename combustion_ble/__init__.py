"""Python library for Combustion Inc. Bluetooth devices.

The recommended entry point is :class:`MeatNet`, which builds device state from advertisements
that the caller supplies. It performs no Bluetooth I/O of its own, so it works inside hosts that
own the Bluetooth stack, such as Home Assistant.
"""

import importlib
from typing import Any

from combustion_ble.advertising import (
    COMBUSTION_MANUFACTURER_ID,
    Advertisement,
    AlarmStatus,
    GaugeAdvertisement,
    NodeAdvertisement,
    PowerMode,
    ProbeAdvertisement,
    ThermometerPreferences,
    parse_advertisement,
)
from combustion_ble.ble_data import (
    AdvertisingData,
    BatteryStatus,
    CombustionProductType,
    PredictionMode,
    PredictionState,
    PredictionStatus,
    PredictionType,
    ProbeColor,
    ProbeID,
    ProbeMode,
    ProbeTemperatures,
)
from combustion_ble.ble_data.hop_count import HopCount
from combustion_ble.ble_data.virtual_sensors import (
    VirtualAmbientSensor,
    VirtualCoreSensor,
    VirtualSurfaceSensor,
)
from combustion_ble.meatnet import Device, Gauge, MeatNet, Node, Probe, ProbeRoute
from combustion_ble.prediction.cooking_prediction import CookingPrediction
from combustion_ble.probe_session import PredictionCommandRejectedError, ProbeSession
from combustion_ble.version import VERSION, VERSION_SHORT

# The original DeviceManager stack owns its own Bluetooth scanner and connections, and creates a
# module-level singleton when imported. Load it only when one of its names is requested.
_LEGACY_EXPORTS = {
    "BluetoothMode": "combustion_ble.ble_manager",
    "DeviceManager": "combustion_ble.device_manager",
    "VirtualTemperatures": "combustion_ble.devices.probe",
}


def __getattr__(name: str) -> Any:
    if module := _LEGACY_EXPORTS.get(name):
        return getattr(importlib.import_module(module), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "COMBUSTION_MANUFACTURER_ID",
    "VERSION",
    "VERSION_SHORT",
    "Advertisement",
    # Shared data types
    "AdvertisingData",
    "AlarmStatus",
    "BatteryStatus",
    # Legacy DeviceManager stack (loaded lazily)
    "BluetoothMode",
    "CombustionProductType",
    "CookingPrediction",
    "Device",
    "DeviceManager",
    "Gauge",
    "GaugeAdvertisement",
    "HopCount",
    "MeatNet",
    "Node",
    "NodeAdvertisement",
    "PowerMode",
    "PredictionMode",
    "PredictionCommandRejectedError",
    "PredictionState",
    "PredictionStatus",
    "PredictionType",
    "Probe",
    "ProbeAdvertisement",
    "ProbeColor",
    "ProbeID",
    "ProbeMode",
    "ProbeRoute",
    "ProbeSession",
    "ProbeTemperatures",
    "ThermometerPreferences",
    "VirtualAmbientSensor",
    "VirtualCoreSensor",
    "VirtualSurfaceSensor",
    "VirtualTemperatures",
    "parse_advertisement",
]
