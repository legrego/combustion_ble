"""Parse Combustion BLE advertisements.

This module performs no I/O and has no Bluetooth dependencies. Feed :func:`parse_advertisement`
the manufacturer-specific payload for Combustion's company ID (:data:`COMBUSTION_MANUFACTURER_ID`)
exactly as Home Assistant (``BluetoothServiceInfoBleak.manufacturer_data``) or bleak
(``AdvertisementData.manufacturer_data``) provide it, i.e. *without* the two company ID bytes.

Field layouts follow the `Combustion BLE specifications
<https://github.com/combustion-inc/combustion-documentation>`_. Where the specifications and
Combustion's own SDKs disagree, this module follows the SDKs, because they reflect what devices
actually send.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from combustion_ble.ble_data.advertising_data import CombustionProductType
from combustion_ble.ble_data.battery_status_virtual_sensors import BatteryStatus
from combustion_ble.ble_data.hop_count import HopCount
from combustion_ble.ble_data.mode_id import ModeId, ProbeColor, ProbeID, ProbeMode
from combustion_ble.ble_data.probe_temperatures import ProbeTemperatures
from combustion_ble.ble_data.virtual_sensors import (
    VirtualAmbientSensor,
    VirtualCoreSensor,
    VirtualSurfaceSensor,
)

COMBUSTION_MANUFACTURER_ID = 0x09C7
"""Bluetooth SIG company identifier for Combustion Inc. (2503)."""

PROBE_OVERHEATING_THRESHOLDS: tuple[float, ...] = (
    105.0,
    105.0,
    115.0,
    125.0,
    315.56,
    315.56,
    315.56,
    315.56,
)
"""Per-thermistor (T1-T8) overheating thresholds in Celsius, matching Combustion's SDKs."""

_PROBE_MIN_LENGTH = 18  # product type (1) + serial number (4) + raw temperatures (13)
_GAUGE_MIN_LENGTH = (
    19  # product type (1) + serial (10) + temp (2) + flags (1) + battery (1) + alarms (4)
)
_NODE_MIN_LENGTH = 11  # product type (1) + serial (10)

_RAW_13_BIT_MASK = 0x1FFF


class PowerMode(Enum):
    """Probe power mode, from the thermometer preferences byte."""

    NORMAL = 0
    """The probe turns off when it is placed in its charger."""

    ALWAYS_ON = 1
    """The probe stays on while it is in its charger."""


@dataclass(frozen=True, slots=True)
class ThermometerPreferences:
    """Probe preferences, advertised by newer probe firmware."""

    power_mode: PowerMode
    high_radio_power: bool
    """Whether the probe transmits at +8 dBm (``True``) or +0 dBm (``False``)."""

    @classmethod
    def from_byte(cls, byte: int) -> ThermometerPreferences:
        """Decode the thermometer preferences byte."""
        # Power mode values 2-3 are reserved; treat them as normal, like Combustion's SDKs.
        power_mode = PowerMode.ALWAYS_ON if byte & 0x03 == 0x01 else PowerMode.NORMAL
        return cls(power_mode=power_mode, high_radio_power=bool(byte & 0x04))


@dataclass(frozen=True, slots=True)
class ProbeAdvertisement:
    """Probe data, advertised either by the probe itself or repeated by a MeatNet node."""

    product_type: CombustionProductType
    """``PROBE`` when sent by the probe, ``MEAT_NET_NODE`` when repeated by a node."""

    serial_number: int
    """Probe serial number. ``0`` when a node is advertising without any connected probes."""

    temperatures: tuple[float, ...]
    """Raw readings for T1-T8 in Celsius. In instant read mode only T1 is meaningful."""

    mode: ProbeMode
    probe_id: ProbeID
    color: ProbeColor
    battery_status: BatteryStatus
    core_sensor: VirtualCoreSensor
    surface_sensor: VirtualSurfaceSensor
    ambient_sensor: VirtualAmbientSensor

    hop_count: HopCount | None
    """Number of MeatNet hops between the node and the probe. ``None`` when sent by the probe."""

    preferences: ThermometerPreferences | None
    """``None`` for repeated data, which doesn't include preferences, or when the advertisement
    predates the preferences byte."""

    @property
    def is_repeated(self) -> bool:
        """Whether this data was repeated by a MeatNet node rather than sent by the probe."""
        return self.product_type == CombustionProductType.MEAT_NET_NODE

    @property
    def has_probe(self) -> bool:
        """Whether this advertisement describes a probe.

        Nodes without any connected probes still advertise, using serial number ``0``.
        """
        return self.serial_number != 0

    @property
    def serial_number_string(self) -> str:
        """Serial number as printed on the probe (8 hex digits)."""
        return f"{self.serial_number:08X}"

    @property
    def instant_read_temperature(self) -> float | None:
        """Instant read temperature in Celsius, or ``None`` when not in instant read mode."""
        if self.mode != ProbeMode.INSTANT_READ:
            return None
        return self.temperatures[0]

    @property
    def core_temperature(self) -> float | None:
        """Virtual core temperature in Celsius, or ``None`` when not in normal mode."""
        if self.mode != ProbeMode.NORMAL:
            return None
        return self.temperatures[self.core_sensor.value]

    @property
    def surface_temperature(self) -> float | None:
        """Virtual surface temperature in Celsius, or ``None`` when not in normal mode."""
        if self.mode != ProbeMode.NORMAL:
            return None
        return self.temperatures[self.surface_sensor.value + 3]

    @property
    def ambient_temperature(self) -> float | None:
        """Virtual ambient temperature in Celsius, or ``None`` when not in normal mode."""
        if self.mode != ProbeMode.NORMAL:
            return None
        return self.temperatures[self.ambient_sensor.value + 4]

    @property
    def overheating_sensors(self) -> tuple[int, ...]:
        """Zero-based indexes of overheating thermistors (normal mode only).

        Computed from the temperatures rather than read from the advertised overheating byte,
        which some repeater firmware is known to set incorrectly.
        """
        if self.mode != ProbeMode.NORMAL:
            return ()
        return overheating_sensors(self.temperatures)


@dataclass(frozen=True, slots=True)
class AlarmStatus:
    """Configuration and state of a single high or low temperature alarm."""

    set: bool
    tripped: bool
    alarming: bool
    temperature: float
    """Alarm set point in Celsius."""

    @classmethod
    def from_bytes(cls, data: bytes) -> AlarmStatus:
        """Decode a 2-byte alarm status field."""
        raw = int.from_bytes(data[0:2], "little")
        return cls(
            set=bool(raw & 0x01),
            tripped=bool(raw & 0x02),
            alarming=bool(raw & 0x04),
            temperature=_gauge_temperature((raw >> 3) & _RAW_13_BIT_MASK),
        )


@dataclass(frozen=True, slots=True)
class GaugeAdvertisement:
    """Giant Grill Gauge data, advertised by the gauge itself."""

    serial_number: str
    temperature: float | None
    """Gauge temperature in Celsius, or ``None`` when the sensor is not connected."""

    sensor_present: bool
    sensor_overheating: bool
    low_battery: bool
    high_alarm: AlarmStatus
    low_alarm: AlarmStatus

    high_radio_power: bool | None
    """``None`` when the advertisement predates the preferences byte."""

    gauge_id: int | None
    """Zero-based, user-assigned gauge ID. ``None`` when the advertisement predates the field.

    Older gauge firmware advertises ``0`` regardless of the configured ID.
    """

    @property
    def product_type(self) -> CombustionProductType:
        """Always ``GAUGE``."""
        return CombustionProductType.GAUGE


@dataclass(frozen=True, slots=True)
class NodeAdvertisement:
    """Device information advertised by a Display, Booster, or Engine about itself."""

    product_type: CombustionProductType
    """``DISPLAY``, ``BOOSTER``, or ``ENGINE``."""

    serial_number: str


Advertisement = ProbeAdvertisement | GaugeAdvertisement | NodeAdvertisement
"""Any advertisement that :func:`parse_advertisement` can return."""


def parse_advertisement(data: bytes) -> Advertisement | None:
    """Parse Combustion manufacturer data (without the company ID bytes).

    Returns ``None`` for payloads that are too short, or for product types this library does not
    understand. Never raises for malformed input.
    """
    if not data:
        return None

    product_type = CombustionProductType(data[0])
    if product_type in (CombustionProductType.PROBE, CombustionProductType.MEAT_NET_NODE):
        return _parse_probe(product_type, data)
    if product_type == CombustionProductType.GAUGE:
        return _parse_gauge(data)
    if product_type in (
        CombustionProductType.DISPLAY,
        CombustionProductType.BOOSTER,
        CombustionProductType.ENGINE,
    ):
        return _parse_node(product_type, data)
    return None


def overheating_sensors(temperatures: tuple[float, ...]) -> tuple[int, ...]:
    """Zero-based indexes of thermistors at or above their overheating threshold."""
    return tuple(
        index
        for index, (temperature, threshold) in enumerate(
            zip(temperatures, PROBE_OVERHEATING_THRESHOLDS)
        )
        if temperature >= threshold
    )


def _parse_probe(product_type: CombustionProductType, data: bytes) -> ProbeAdvertisement | None:
    if len(data) < _PROBE_MIN_LENGTH:
        return None

    serial_number = int.from_bytes(data[1:5], "little")
    temperatures = tuple(ProbeTemperatures.from_raw_data(data[5:18]).values)

    mode_id = ModeId.from_byte(data[18]) if len(data) > 18 else ModeId.default_values()

    status = data[19] if len(data) > 19 else 0
    battery_status = BatteryStatus.LOW if status & 0x01 else BatteryStatus.OK
    core_sensor, surface_sensor, ambient_sensor = _virtual_sensors(status >> 1)

    hop_count: HopCount | None = None
    if product_type == CombustionProductType.MEAT_NET_NODE:
        hop_count = HopCount.from_network_info_byte(data[20]) if len(data) > 20 else HopCount.HOP1

    # data[21] is the overheating byte, which is deliberately ignored (see overheating_sensors).

    # Repeated probe data has no preferences field. Nodes pad its place with zero, which would
    # otherwise read as normal power mode.
    preferences = None
    if product_type == CombustionProductType.PROBE and len(data) > 22:
        preferences = ThermometerPreferences.from_byte(data[22])

    return ProbeAdvertisement(
        product_type=product_type,
        serial_number=serial_number,
        temperatures=temperatures,
        mode=mode_id.mode,
        probe_id=mode_id.id,
        color=mode_id.color,
        battery_status=battery_status,
        core_sensor=core_sensor,
        surface_sensor=surface_sensor,
        ambient_sensor=ambient_sensor,
        hop_count=hop_count,
        preferences=preferences,
    )


def _virtual_sensors(
    bits: int,
) -> tuple[VirtualCoreSensor, VirtualSurfaceSensor, VirtualAmbientSensor]:
    raw_core = bits & 0x07
    # Core sensor values 6-7 are undefined. Fall back to T1, like Combustion's SDKs.
    core = VirtualCoreSensor(raw_core) if raw_core <= 5 else VirtualCoreSensor.T1
    surface = VirtualSurfaceSensor((bits >> 3) & 0x03)
    ambient = VirtualAmbientSensor((bits >> 5) & 0x03)
    return core, surface, ambient


def _parse_gauge(data: bytes) -> GaugeAdvertisement | None:
    if len(data) < _GAUGE_MIN_LENGTH:
        return None

    flags = data[13]
    sensor_present = bool(flags & 0x01)
    raw_temperature = int.from_bytes(data[11:13], "little") & _RAW_13_BIT_MASK

    # data[14] is the battery percentage. Current firmware always reports 100, so it is not
    # exposed; use low_battery instead.
    return GaugeAdvertisement(
        serial_number=_decode_serial(data[1:11]),
        temperature=_gauge_temperature(raw_temperature) if sensor_present else None,
        sensor_present=sensor_present,
        sensor_overheating=bool(flags & 0x02),
        low_battery=bool(flags & 0x04),
        high_alarm=AlarmStatus.from_bytes(data[15:17]),
        low_alarm=AlarmStatus.from_bytes(data[17:19]),
        high_radio_power=bool(data[19] & 0x01) if len(data) > 19 else None,
        gauge_id=data[20] if len(data) > 20 else None,
    )


def _parse_node(product_type: CombustionProductType, data: bytes) -> NodeAdvertisement | None:
    if len(data) < _NODE_MIN_LENGTH:
        return None
    return NodeAdvertisement(product_type=product_type, serial_number=_decode_serial(data[1:11]))


def _gauge_temperature(raw: int) -> float:
    return round(raw * 0.1 - 20.0, 1)


def _decode_serial(data: bytes) -> str:
    return data.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()
