"""Passive MeatNet state, built only from Bluetooth advertisements.

:class:`MeatNet` turns a stream of advertisements into probe, gauge, and node state. It performs no
I/O, starts no tasks, and owns no Bluetooth resources: the caller owns scanning and feeds every
advertisement to :meth:`MeatNet.handle_advertisement`. This lets Home Assistant (or any other host)
keep full control of the Bluetooth stack.

Typical use::

    meatnet = MeatNet()
    meatnet.add_device_listener(on_new_device)

    # From your scanner's callback, for every advertisement:
    meatnet.handle_advertisement(address, manufacturer_data, rssi, connectable=connectable)

    # About once per second, to time out stale devices and readings:
    meatnet.expire()
"""

from __future__ import annotations

import time
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Protocol

from combustion_ble.advertising import (
    COMBUSTION_MANUFACTURER_ID,
    AlarmStatus,
    GaugeAdvertisement,
    NodeAdvertisement,
    PowerMode,
    ProbeAdvertisement,
    overheating_sensors,
    parse_advertisement,
)
from combustion_ble.ble_data.advertising_data import CombustionProductType
from combustion_ble.ble_data.battery_status_virtual_sensors import BatteryStatus
from combustion_ble.ble_data.mode_id import ProbeColor, ProbeID, ProbeMode
from combustion_ble.ble_data.prediction_status import PredictionStatus
from combustion_ble.ble_data.virtual_sensors import (
    VirtualAmbientSensor,
    VirtualCoreSensor,
    VirtualSurfaceSensor,
)
from combustion_ble.instant_read_filter import InstantReadFilter
from combustion_ble.logger import LOGGER
from combustion_ble.prediction.cooking_prediction import CookingPrediction

_LOGGER = LOGGER.getChild("meatnet")

DEFAULT_STALE_TIMEOUT = 15.0
"""Seconds without any advertisement before a device is marked unavailable."""

PREDICTION_STALE_TIMEOUT = 15.0
"""Seconds without connected status before a prediction is cleared."""

NORMAL_MODE_IDLE_TIMEOUT = 5.0
"""Seconds before normal mode data from a worse link may replace data from the preferred link."""

INSTANT_READ_LOCK_TIMEOUT = 1.0
"""Seconds that instant read data locks out relayed data from other links."""

INSTANT_READ_STALE_TIMEOUT = 5.0
"""Seconds without instant read data before the instant read reading is cleared."""

Listener = Callable[[], None]
"""Called with no arguments when a device's state changes."""

DeviceListener = Callable[["Device"], None]
"""Called with a newly discovered device."""

RemoveListener = Callable[[], None]
"""Call to unregister a listener."""


class ServiceInfo(Protocol):
    """The parts of Home Assistant's ``BluetoothServiceInfoBleak`` that :class:`MeatNet` uses."""

    @property
    def address(self) -> str: ...

    @property
    def rssi(self) -> int: ...

    @property
    def manufacturer_data(self) -> Mapping[int, bytes]: ...

    @property
    def connectable(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class ProbeRoute:
    """A MeatNet node that is relaying a probe's data."""

    node_address: str
    hop_count: int
    """Number of hops between the node and the probe (1-4)."""

    last_seen: float


class Device:
    """State common to every Combustion device."""

    def __init__(self, now: float) -> None:
        self.available: bool = True
        """``False`` once nothing has been heard from the device for the stale timeout."""

        self.last_seen: float = now
        """Clock time of the most recent advertisement about this device."""

        self._listeners: list[Listener] = []

    def add_listener(self, listener: Listener) -> RemoveListener:
        """Call ``listener`` whenever this device's state changes.

        Signal strength changes alone do not trigger listeners.
        """
        self._listeners.append(listener)

        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def _notify(self) -> None:
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:  # A broken listener must not break advertisement handling.
                _LOGGER.exception("Error in listener for %s", self)

    def _observable_state(self) -> tuple[Hashable, ...]:
        return (self.available,)

    def _mark_seen(self, now: float) -> None:
        self.last_seen = now
        self.available = True

    def _expire(self, now: float, stale_timeout: float) -> None:
        if self.available and now - self.last_seen > stale_timeout:
            self.available = False


class Probe(Device):
    """A Predictive Thermometer, heard directly or relayed by MeatNet nodes."""

    def __init__(self, serial_number: int, now: float) -> None:
        super().__init__(now)
        self.serial_number: int = serial_number

        self.prediction: CookingPrediction | None = None
        """Latest connected prediction, or ``None`` when unknown, stale, or disconnected."""
        self.prediction_updated_at: float | None = None
        """Monotonic clock time of the latest connected prediction status."""
        self._prediction_seconds: int | None = None
        self._prediction_session: object | None = None

        self.mode: ProbeMode = ProbeMode.NORMAL
        """``INSTANT_READ`` while instant read readings are current, otherwise ``NORMAL``.

        Probes in instant read mode interleave normal mode advertisements with instant read ones,
        so this does not follow the mode of each advertisement.
        """

        self.probe_id: ProbeID = ProbeID.ID1
        self.color: ProbeColor = ProbeColor.color1
        self.battery_status: BatteryStatus = BatteryStatus.OK

        self.temperatures: tuple[float, ...] | None = None
        """Readings for T1-T8 in Celsius from the most recent normal mode data."""

        self.core_sensor: VirtualCoreSensor = VirtualCoreSensor.T1
        self.surface_sensor: VirtualSurfaceSensor = VirtualSurfaceSensor.T4
        self.ambient_sensor: VirtualAmbientSensor = VirtualAmbientSensor.T5

        self.overheating_sensors: tuple[int, ...] = ()
        """Zero-based indexes of thermistors at or above their overheating threshold."""

        self.power_mode: PowerMode | None = None
        """Known once the probe has been heard directly. MeatNet nodes don't relay it."""

        self.high_radio_power: bool | None = None
        """Known once the probe has been heard directly. MeatNet nodes don't relay it."""

        self.instant_read_celsius: float | None = None
        """Instant read temperature in Celsius, smoothed the same way Combustion's apps show it."""

        self.instant_read_fahrenheit: float | None = None
        """Instant read temperature in Fahrenheit, smoothed the same way Combustion's apps show it."""

        self.instant_read_raw_celsius: float | None = None
        """Unsmoothed instant read temperature. Changes to this alone do not trigger listeners."""

        self.address: str | None = None
        """Bluetooth address of the probe, once it has been heard directly."""

        self.rssi: int | None = None
        """Signal strength of the probe's own advertisements, once it has been heard directly."""

        self.connectable: bool | None = None
        """Whether the probe's most recent direct advertisement was connectable."""

        self.routes: dict[str, ProbeRoute] = {}
        """MeatNet nodes currently relaying this probe, by node address."""

        self.source: str | None = None
        """Address of the device that sent the most recently used data (the probe or a node)."""

        self.source_hop_count: int | None = None
        """Hops between :attr:`source` and the probe, or ``None`` when heard directly."""

        self._instant_read_filter = InstantReadFilter()

        # Normal mode arbitration (see _accept_normal_mode)
        self._normal_link: str | None = None
        self._normal_rank: int = 0
        self._normal_last_used: float = 0.0

        # Instant read arbitration (see _accept_instant_read)
        self._instant_read_link: str | None = None
        self._instant_read_hop_count: int | None = None
        self._instant_read_last_used: float | None = None

    @property
    def serial_number_string(self) -> str:
        """Serial number as printed on the probe (8 hex digits)."""
        return f"{self.serial_number:08X}"

    @property
    def core_temperature(self) -> float | None:
        """Virtual core temperature in Celsius."""
        if self.temperatures is None:
            return None
        return self.temperatures[self.core_sensor.value]

    @property
    def surface_temperature(self) -> float | None:
        """Virtual surface temperature in Celsius."""
        if self.temperatures is None:
            return None
        return self.temperatures[self.surface_sensor.value + 3]

    @property
    def ambient_temperature(self) -> float | None:
        """Virtual ambient temperature in Celsius."""
        if self.temperatures is None:
            return None
        return self.temperatures[self.ambient_sensor.value + 4]

    def __repr__(self) -> str:
        return f"Probe({self.serial_number_string})"

    def _observable_state(self) -> tuple[Hashable, ...]:
        return (
            self.available,
            self.mode,
            self.prediction,
            self.probe_id,
            self.color,
            self.battery_status,
            self.temperatures,
            self.core_sensor,
            self.surface_sensor,
            self.ambient_sensor,
            self.overheating_sensors,
            self.power_mode,
            self.high_radio_power,
            self.instant_read_celsius,
            self.instant_read_fahrenheit,
            self.address,
            self.source,
            self.source_hop_count,
            frozenset(self.routes),
        )

    def _handle_advertisement(
        self,
        advertisement: ProbeAdvertisement,
        link: str,
        hop_count: int | None,
        now: float,
    ) -> None:
        """Apply probe data that arrived on ``link`` (``hop_count`` is ``None`` when direct)."""
        self._mark_seen(now)
        if hop_count is not None:
            self.routes[link] = ProbeRoute(node_address=link, hop_count=hop_count, last_seen=now)

        # Error and reserved modes carry no usable data.
        if advertisement.mode == ProbeMode.NORMAL and self._accept_normal_mode(
            link, hop_count or 0, now
        ):
            self._apply_common(advertisement, link, hop_count)
            self._apply_normal_mode(advertisement)
        elif advertisement.mode == ProbeMode.INSTANT_READ and self._accept_instant_read(
            link, hop_count, now
        ):
            self._apply_common(advertisement, link, hop_count)
            self._apply_instant_read(advertisement)

    def _accept_normal_mode(self, link: str, rank: int, now: float) -> bool:
        """Decide whether to use normal mode data from ``link``.

        Port of the Combustion Android SDK's advertising arbitration: stay with the preferred link
        unless another link has a strictly lower hop count (direct links rank 0), or the preferred
        link has been quiet for :data:`NORMAL_MODE_IDLE_TIMEOUT`.
        """
        accept = (
            self._normal_link is None
            or link == self._normal_link
            or rank < self._normal_rank
            or now - self._normal_last_used > NORMAL_MODE_IDLE_TIMEOUT
        )
        if accept:
            self._normal_link = link
            self._normal_rank = rank
            self._normal_last_used = now
        return accept

    def _accept_instant_read(self, link: str, hop_count: int | None, now: float) -> bool:
        """Decide whether to use instant read data from ``link``.

        Port of the Combustion Android SDK's ``InstantReadArbitrator``: direct data always wins and
        locks out relayed data for :data:`INSTANT_READ_LOCK_TIMEOUT`. Once nothing has been used for
        that long, any link takes over. Otherwise relayed data is used only from the current link,
        or from a link with a strictly lower hop count.
        """
        last_used = self._instant_read_last_used
        locked = last_used is not None and now - last_used < INSTANT_READ_LOCK_TIMEOUT
        if hop_count is None or not locked or link == self._instant_read_link:
            accept = True
        elif self._instant_read_hop_count is None:
            accept = False
        else:
            accept = hop_count < self._instant_read_hop_count

        if accept:
            self._instant_read_link = link
            self._instant_read_hop_count = hop_count
            self._instant_read_last_used = now
        return accept

    def _apply_common(
        self, advertisement: ProbeAdvertisement, link: str, hop_count: int | None
    ) -> None:
        self.probe_id = advertisement.probe_id
        self.color = advertisement.color
        self.battery_status = advertisement.battery_status
        if advertisement.preferences is not None:
            self.power_mode = advertisement.preferences.power_mode
            self.high_radio_power = advertisement.preferences.high_radio_power
        self.source = link
        self.source_hop_count = hop_count

    def _apply_normal_mode(self, advertisement: ProbeAdvertisement) -> None:
        self.temperatures = advertisement.temperatures
        self.core_sensor = advertisement.core_sensor
        self.surface_sensor = advertisement.surface_sensor
        self.ambient_sensor = advertisement.ambient_sensor
        self.overheating_sensors = overheating_sensors(advertisement.temperatures)
        # Instant read is left alone: probes in instant read mode send normal mode data too. It is
        # cleared once instant read data goes stale (see _expire).

    def _apply_instant_read(self, advertisement: ProbeAdvertisement) -> None:
        self.mode = ProbeMode.INSTANT_READ
        reading = advertisement.temperatures[0]
        self._instant_read_filter.add_reading(reading)
        celsius, fahrenheit = self._instant_read_filter.values
        self.instant_read_raw_celsius = reading
        self.instant_read_celsius = celsius
        self.instant_read_fahrenheit = fahrenheit

    def _clear_instant_read(self) -> None:
        self.mode = ProbeMode.NORMAL
        self.instant_read_celsius = None
        self.instant_read_fahrenheit = None
        self.instant_read_raw_celsius = None
        self._instant_read_filter = InstantReadFilter()

    def _expire(self, now: float, stale_timeout: float) -> None:
        if self.prediction is not None and self.prediction_updated_at is not None:
            elapsed = max(0.0, now - self.prediction_updated_at)
            if elapsed > PREDICTION_STALE_TIMEOUT:
                self.prediction = None
            elif self._prediction_seconds is not None:
                self.prediction = replace(
                    self.prediction,
                    seconds_remaining=max(0, self._prediction_seconds - int(elapsed)),
                )
        last_used = self._instant_read_last_used
        if (
            self.instant_read_celsius is not None
            and last_used is not None
            and now - last_used > INSTANT_READ_STALE_TIMEOUT
        ):
            self._clear_instant_read()

        for address, route in list(self.routes.items()):
            if now - route.last_seen > stale_timeout:
                del self.routes[address]

        super()._expire(now, stale_timeout)


class Gauge(Device):
    """A Giant Grill Gauge.

    A gauge is also a MeatNet repeater, so it appears in :attr:`MeatNet.nodes` as well, with the
    same serial number.
    """

    def __init__(self, serial_number: str, address: str, now: float) -> None:
        super().__init__(now)
        self.serial_number: str = serial_number
        self.address: str = address
        self.temperature: float | None = None
        """Gauge temperature in Celsius, or ``None`` when the sensor is not connected."""

        self.sensor_present: bool = False
        self.sensor_overheating: bool = False
        self.low_battery: bool = False
        self.high_alarm: AlarmStatus | None = None
        self.low_alarm: AlarmStatus | None = None
        self.high_radio_power: bool | None = None
        self.gauge_id: int | None = None
        self.rssi: int | None = None
        self.connectable: bool | None = None

    def __repr__(self) -> str:
        return f"Gauge({self.serial_number})"

    def _observable_state(self) -> tuple[Hashable, ...]:
        return (
            self.available,
            self.address,
            self.temperature,
            self.sensor_present,
            self.sensor_overheating,
            self.low_battery,
            self.high_alarm,
            self.low_alarm,
            self.high_radio_power,
            self.gauge_id,
        )

    def _handle_advertisement(
        self,
        advertisement: GaugeAdvertisement,
        address: str,
        rssi: int | None,
        connectable: bool | None,
        now: float,
    ) -> None:
        self._mark_seen(now)
        self.address = address
        self.rssi = rssi
        self.connectable = connectable
        self.temperature = advertisement.temperature
        self.sensor_present = advertisement.sensor_present
        self.sensor_overheating = advertisement.sensor_overheating
        self.low_battery = advertisement.low_battery
        self.high_alarm = advertisement.high_alarm
        self.low_alarm = advertisement.low_alarm
        if advertisement.high_radio_power is not None:
            self.high_radio_power = advertisement.high_radio_power
        if advertisement.gauge_id is not None:
            self.gauge_id = advertisement.gauge_id


class Node(Device):
    """A MeatNet repeater: Display, Booster, Giant Grill Gauge, or Engine."""

    def __init__(self, address: str, now: float) -> None:
        super().__init__(now)
        self.address: str = address

        self.product_type: CombustionProductType = CombustionProductType.MEAT_NET_NODE
        """Specific product type, once the node has advertised its own device information.

        ``MEAT_NET_NODE`` until then.
        """

        self.serial_number: str | None = None
        """Serial number, once the node has advertised its own device information."""

        self.rssi: int | None = None
        self.connectable: bool | None = None

        self.relayed_probes: dict[int, ProbeRoute] = {}
        """Probes this node is currently relaying, by probe serial number."""

    def __repr__(self) -> str:
        return f"Node({self.address})"

    def _observable_state(self) -> tuple[Hashable, ...]:
        return (
            self.available,
            self.product_type,
            self.serial_number,
            frozenset(self.relayed_probes),
        )

    def _mark_heard(self, rssi: int | None, connectable: bool | None, now: float) -> None:
        self._mark_seen(now)
        self.rssi = rssi
        self.connectable = connectable

    def _expire(self, now: float, stale_timeout: float) -> None:
        for serial_number, route in list(self.relayed_probes.items()):
            if now - route.last_seen > stale_timeout:
                del self.relayed_probes[serial_number]
        super()._expire(now, stale_timeout)


class MeatNet:
    """Passive state for every Combustion device heard via advertisements.

    Create one per Bluetooth environment (for Home Assistant, one per config entry). Instances are
    independent; there is no global state. All methods are synchronous and must be called from a
    single thread (for example, the event loop).
    """

    def __init__(
        self,
        *,
        stale_timeout: float = DEFAULT_STALE_TIMEOUT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize.

        :param stale_timeout: Seconds without any advertisement before a device is unavailable.
        :param clock: Monotonic clock in seconds. Override in tests.
        """
        self._stale_timeout = stale_timeout
        self._clock = clock
        self._probes: dict[int, Probe] = {}
        self._gauges: dict[str, Gauge] = {}
        self._nodes: dict[str, Node] = {}
        self._device_listeners: list[DeviceListener] = []

    @property
    def probes(self) -> Mapping[int, Probe]:
        """Known probes, by serial number."""
        return MappingProxyType(self._probes)

    @property
    def gauges(self) -> Mapping[str, Gauge]:
        """Known Giant Grill Gauges, by serial number."""
        return MappingProxyType(self._gauges)

    @property
    def nodes(self) -> Mapping[str, Node]:
        """Known MeatNet repeaters, by Bluetooth address."""
        return MappingProxyType(self._nodes)

    @property
    def devices(self) -> list[Device]:
        """Every known device."""
        return [*self._probes.values(), *self._gauges.values(), *self._nodes.values()]

    def add_device_listener(self, listener: DeviceListener) -> RemoveListener:
        """Call ``listener`` once for each newly discovered device.

        The device's initial state has already been applied when ``listener`` is called. Use
        :meth:`Device.add_listener` to follow later changes.
        """
        self._device_listeners.append(listener)

        def remove() -> None:
            if listener in self._device_listeners:
                self._device_listeners.remove(listener)

        return remove

    def handle_service_info(self, service_info: ServiceInfo) -> list[Device]:
        """Handle a Home Assistant ``BluetoothServiceInfoBleak``.

        Equivalent to calling :meth:`handle_advertisement` with its fields.
        """
        return self.handle_advertisement(
            service_info.address,
            service_info.manufacturer_data,
            service_info.rssi,
            connectable=service_info.connectable,
        )

    def handle_advertisement(
        self,
        address: str,
        manufacturer_data: Mapping[int, bytes] | bytes,
        rssi: int | None = None,
        *,
        connectable: bool | None = None,
    ) -> list[Device]:
        """Update state from one advertisement.

        :param address: Bluetooth address of the device that sent the advertisement.
        :param manufacturer_data: Either the full manufacturer data mapping (company ID to payload),
            or just the Combustion payload, without the company ID bytes.
        :param rssi: Signal strength of the advertisement.
        :param connectable: Whether the advertisement was connectable, if known.
        :return: Devices whose state changed, including newly discovered devices. Never raises for
            malformed advertisements.
        """
        if isinstance(manufacturer_data, Mapping):
            payload = manufacturer_data.get(COMBUSTION_MANUFACTURER_ID)
        else:
            payload = manufacturer_data
        if not payload:
            return []

        try:
            advertisement = parse_advertisement(bytes(payload))
        except Exception:  # noqa: BLE001 - never let a malformed advertisement escape
            _LOGGER.debug("Ignoring malformed advertisement from %s: %s", address, payload.hex())
            return []
        if advertisement is None:
            return []

        now = self._clock()
        tracker = _ChangeTracker()

        if isinstance(advertisement, ProbeAdvertisement):
            self._handle_probe_advertisement(
                advertisement, address, rssi, connectable, now, tracker
            )
        elif isinstance(advertisement, GaugeAdvertisement):
            self._handle_gauge_advertisement(
                advertisement, address, rssi, connectable, now, tracker
            )
        elif isinstance(advertisement, NodeAdvertisement):
            node = self._get_node(address, now, tracker)
            tracker.watch(node)
            node._mark_heard(rssi, connectable, now)
            node.product_type = advertisement.product_type
            node.serial_number = advertisement.serial_number

        return self._publish(tracker)

    def expire(self) -> list[Device]:
        """Time out stale data and advance connected prediction countdowns.

        Call this periodically (about once per second). Returns the devices whose state changed.
        """
        now = self._clock()
        tracker = _ChangeTracker()
        for device in self.devices:
            tracker.watch(device)
            device._expire(now, self._stale_timeout)
        return self._publish(tracker)

    def handle_prediction_status(
        self, serial_number: int, status: PredictionStatus
    ) -> list[Device]:
        """Apply connected prediction data to an already discovered probe.

        This does not refresh advertisement availability or overwrite passive temperature data.
        Identical statuses refresh prediction freshness without notifying listeners.
        """
        probe = self._probes[serial_number]
        tracker = _ChangeTracker()
        tracker.watch(probe)
        probe.prediction = CookingPrediction.from_status(status)
        probe.prediction_updated_at = self._clock()
        probe._prediction_seconds = probe.prediction.seconds_remaining
        return self._publish(tracker)

    def clear_prediction(self, serial_number: int) -> list[Device]:
        """Invalidate a probe's prediction when its status connection is lost."""
        probe = self._probes[serial_number]
        tracker = _ChangeTracker()
        tracker.watch(probe)
        probe.prediction = None
        probe.prediction_updated_at = None
        probe._prediction_seconds = None
        return self._publish(tracker)

    def _handle_probe_advertisement(
        self,
        advertisement: ProbeAdvertisement,
        address: str,
        rssi: int | None,
        connectable: bool | None,
        now: float,
        tracker: _ChangeTracker,
    ) -> None:
        if advertisement.is_repeated:
            hop_count = advertisement.hop_count.value + 1 if advertisement.hop_count else 1
            node = self._get_node(address, now, tracker)
            tracker.watch(node)
            node._mark_heard(rssi, connectable, now)
            if not advertisement.has_probe:
                return
            node.relayed_probes[advertisement.serial_number] = ProbeRoute(
                node_address=address, hop_count=hop_count, last_seen=now
            )
            probe = self._get_probe(advertisement.serial_number, now, tracker)
            tracker.watch(probe)
            probe._handle_advertisement(advertisement, address, hop_count, now)
        else:
            if not advertisement.has_probe:
                return
            probe = self._get_probe(advertisement.serial_number, now, tracker)
            tracker.watch(probe)
            probe.address = address
            probe.rssi = rssi
            probe.connectable = connectable
            probe._handle_advertisement(advertisement, address, None, now)

    def _handle_gauge_advertisement(
        self,
        advertisement: GaugeAdvertisement,
        address: str,
        rssi: int | None,
        connectable: bool | None,
        now: float,
        tracker: _ChangeTracker,
    ) -> None:
        node = self._get_node(address, now, tracker)
        tracker.watch(node)
        node._mark_heard(rssi, connectable, now)
        node.product_type = CombustionProductType.GAUGE
        node.serial_number = advertisement.serial_number

        if not advertisement.serial_number:
            return
        gauge = self._gauges.get(advertisement.serial_number)
        if gauge is None:
            gauge = Gauge(advertisement.serial_number, address, now)
            self._gauges[advertisement.serial_number] = gauge
            tracker.discovered(gauge)
        tracker.watch(gauge)
        gauge._handle_advertisement(advertisement, address, rssi, connectable, now)

    def _get_probe(self, serial_number: int, now: float, tracker: _ChangeTracker) -> Probe:
        probe = self._probes.get(serial_number)
        if probe is None:
            probe = Probe(serial_number, now)
            self._probes[serial_number] = probe
            tracker.discovered(probe)
        return probe

    def _get_node(self, address: str, now: float, tracker: _ChangeTracker) -> Node:
        node = self._nodes.get(address)
        if node is None:
            node = Node(address, now)
            self._nodes[address] = node
            tracker.discovered(node)
        return node

    def _publish(self, tracker: _ChangeTracker) -> list[Device]:
        changed = tracker.changed()
        for device in tracker.new_devices:
            for listener in list(self._device_listeners):
                try:
                    listener(device)
                except Exception:  # A broken listener must not break advertisement handling.
                    _LOGGER.exception("Error in device listener for %s", device)
        for device in changed:
            if device not in tracker.new_devices:
                device._notify()
        return changed


class _ChangeTracker:
    """Records device state before an update so that only real changes are published."""

    def __init__(self) -> None:
        self.new_devices: list[Device] = []
        self._before: dict[int, tuple[Device, tuple[Hashable, ...]]] = {}

    def discovered(self, device: Device) -> None:
        self.new_devices.append(device)

    def watch(self, device: Device) -> None:
        self._before.setdefault(id(device), (device, device._observable_state()))

    def changed(self) -> list[Device]:
        changed = [
            device
            for device, before in self._before.values()
            if device._observable_state() != before
        ]
        for device in self.new_devices:
            if device not in changed:
                changed.append(device)
        return changed
