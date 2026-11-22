"""Python library for Combustion Inc. Bluetooth devices.

The entry point is :class:`MeatNet`, which builds device state from advertisements
that the caller supplies. It performs no Bluetooth I/O of its own, so it works inside hosts that
own the Bluetooth stack, such as Home Assistant.
"""

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
from combustion_ble.ble_data.food_safe_data import (
    FoodSafeMode,
    IntegratedProduct,
    Serving,
    SimplifiedProduct,
)
from combustion_ble.ble_data.food_safe_state import FoodSafeState
from combustion_ble.ble_data.hop_count import HopCount
from combustion_ble.ble_data.virtual_sensors import (
    VirtualAmbientSensor,
    VirtualCoreSensor,
    VirtualSurfaceSensor,
)
from combustion_ble.connection_plan import ConnectionPlan, plan_connections
from combustion_ble.exceptions import (
    CombustionError,
    PredictionCommandRejectedError,
    RequestRejectedError,
)
from combustion_ble.firmware_version import FirmwareVersion
from combustion_ble.food_safe import FoodSafe, FoodSafeProgram
from combustion_ble.meatnet import Device, Gauge, MeatNet, Node, Probe, ProbeRoute
from combustion_ble.node_session import NodeSession
from combustion_ble.prediction.cooking_prediction import CookingPrediction
from combustion_ble.probe_session import ProbeSession
from combustion_ble.version import VERSION, VERSION_SHORT

__all__ = [
    "COMBUSTION_MANUFACTURER_ID",
    "VERSION",
    "VERSION_SHORT",
    "Advertisement",
    "AlarmStatus",
    "BatteryStatus",
    "CombustionError",
    "CombustionProductType",
    "ConnectionPlan",
    "CookingPrediction",
    "Device",
    "FirmwareVersion",
    "FoodSafe",
    "FoodSafeProgram",
    "FoodSafeMode",
    "FoodSafeState",
    "Gauge",
    "GaugeAdvertisement",
    "HopCount",
    "IntegratedProduct",
    "MeatNet",
    "Node",
    "NodeAdvertisement",
    "NodeSession",
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
    "RequestRejectedError",
    "Serving",
    "SimplifiedProduct",
    "ThermometerPreferences",
    "VirtualAmbientSensor",
    "VirtualCoreSensor",
    "VirtualSurfaceSensor",
    "parse_advertisement",
    "plan_connections",
]
