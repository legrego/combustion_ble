"""Tests for combustion_ble.meatnet."""

from types import SimpleNamespace

import pytest

from combustion_ble import (
    COMBUSTION_MANUFACTURER_ID,
    BatteryStatus,
    CombustionProductType,
    Device,
    Gauge,
    MeatNet,
    Node,
    PowerMode,
    Probe,
    ProbeMode,
    plan_connections,
)
from combustion_ble.meatnet import (
    DEFAULT_STALE_TIMEOUT,
    INSTANT_READ_LOCK_TIMEOUT,
    INSTANT_READ_STALE_TIMEOUT,
    NORMAL_MODE_IDLE_TIMEOUT,
)
from tests.payloads import (
    ROOM_TEMPERATURES,
    gauge_payload,
    instant_read_payload,
    node_payload,
    probe_payload,
)

PROBE_ADDRESS = "AA:AA:AA:AA:AA:01"
NODE_A = "BB:BB:BB:BB:BB:01"
NODE_B = "BB:BB:BB:BB:BB:02"
SERIAL = 0x12345678
DIRECT_TEMPS = ROOM_TEMPERATURES
NODE_TEMPS = tuple(t + 10 for t in ROOM_TEMPERATURES)
OTHER_NODE_TEMPS = tuple(t + 20 for t in ROOM_TEMPERATURES)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def meatnet(clock: FakeClock) -> MeatNet:
    return MeatNet(clock=clock)


def probe_of(meatnet: MeatNet) -> Probe:
    return meatnet.probes[SERIAL]


class TestDiscovery:
    def test_direct_advertisement_creates_probe(self, meatnet: MeatNet):
        discovered: list[Device] = []
        meatnet.add_device_listener(discovered.append)

        changed = meatnet.handle_advertisement(
            PROBE_ADDRESS, probe_payload(core=2), rssi=-60, connectable=True
        )

        probe = probe_of(meatnet)
        assert changed == [probe]
        assert discovered == [probe]
        assert probe.serial_number_string == "12345678"
        assert probe.temperatures == DIRECT_TEMPS
        assert probe.core_temperature == 22.0  # T3
        assert probe.address == PROBE_ADDRESS
        assert probe.rssi == -60
        assert probe.connectable is True
        assert probe.source == PROBE_ADDRESS
        assert probe.source_hop_count is None
        assert probe.available
        assert meatnet.nodes == {}

    def test_device_listener_sees_initial_state(self, meatnet: MeatNet):
        seen = []
        meatnet.add_device_listener(
            lambda device: seen.append(device.temperatures if isinstance(device, Probe) else None)
        )
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload())
        assert seen == [DIRECT_TEMPS]

    def test_repeated_advertisement_creates_node_and_probe(self, meatnet: MeatNet):
        discovered: list[Device] = []
        meatnet.add_device_listener(discovered.append)

        meatnet.handle_advertisement(
            NODE_A, probe_payload(hop=1, temperatures=NODE_TEMPS), rssi=-70
        )

        probe = probe_of(meatnet)
        node = meatnet.nodes[NODE_A]
        assert {type(device) for device in discovered} == {Probe, Node}
        assert probe.temperatures == NODE_TEMPS
        assert probe.address is None
        assert probe.rssi is None
        assert probe.source == NODE_A
        assert probe.source_hop_count == 2
        assert probe.routes[NODE_A].hop_count == 2
        assert node.product_type == CombustionProductType.MEAT_NET_NODE
        assert node.rssi == -70
        assert node.relayed_probes[SERIAL].hop_count == 2

    def test_node_without_probes_creates_only_node(self, meatnet: MeatNet):
        meatnet.handle_advertisement(NODE_A, probe_payload(hop=0, serial_number=0))
        assert NODE_A in meatnet.nodes
        assert meatnet.nodes[NODE_A].relayed_probes == {}
        assert meatnet.probes == {}

    def test_display_device_information_identifies_node(self, meatnet: MeatNet):
        meatnet.handle_advertisement(NODE_A, probe_payload(hop=0))
        meatnet.handle_advertisement(NODE_A, node_payload(0x04, "DISPLAY123"))
        meatnet.handle_advertisement(NODE_A, probe_payload(hop=0))

        node = meatnet.nodes[NODE_A]
        assert node.product_type == CombustionProductType.DISPLAY
        assert node.serial_number == "DISPLAY123"

    def test_gauge_advertisement_creates_gauge_and_node(self, meatnet: MeatNet):
        meatnet.handle_advertisement(NODE_A, gauge_payload(temperature=180.5, gauge_id=2), rssi=-55)

        gauge = meatnet.gauges["AB12CD34EF"]
        node = meatnet.nodes[NODE_A]
        assert isinstance(gauge, Gauge)
        assert gauge.address == NODE_A
        assert gauge.temperature == 180.5
        assert gauge.gauge_id == 2
        assert gauge.rssi == -55
        assert node.product_type == CombustionProductType.GAUGE
        assert node.serial_number == gauge.serial_number

    def test_accepts_full_manufacturer_data_mapping(self, meatnet: MeatNet):
        meatnet.handle_advertisement(
            PROBE_ADDRESS, {0x004C: b"\x02\x15", COMBUSTION_MANUFACTURER_ID: probe_payload()}
        )
        assert SERIAL in meatnet.probes

    def test_handle_service_info(self, meatnet: MeatNet):
        service_info = SimpleNamespace(
            address=PROBE_ADDRESS,
            rssi=-42,
            manufacturer_data={COMBUSTION_MANUFACTURER_ID: probe_payload()},
            connectable=False,
        )
        meatnet.handle_service_info(service_info)
        assert probe_of(meatnet).rssi == -42
        assert probe_of(meatnet).connectable is False

    @pytest.mark.parametrize(
        "manufacturer_data",
        [
            {},
            {0x004C: b"\x02\x15"},
            b"",
            bytes([0x01, 0x02]),
            bytes([0x09]) + bytes(22),
        ],
    )
    def test_ignores_irrelevant_or_malformed_data(self, meatnet: MeatNet, manufacturer_data):
        assert meatnet.handle_advertisement(PROBE_ADDRESS, manufacturer_data) == []
        assert meatnet.devices == []

    def test_instances_are_independent(self, clock: FakeClock):
        first, second = MeatNet(clock=clock), MeatNet(clock=clock)
        first.handle_advertisement(PROBE_ADDRESS, probe_payload())
        assert SERIAL in first.probes
        assert second.probes == {}


class TestChangeNotification:
    def test_repeated_identical_advertisement_is_not_a_change(self, meatnet: MeatNet):
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload())
        calls = []
        probe_of(meatnet).add_listener(lambda: calls.append(1))

        assert meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload()) == []
        assert calls == []

    def test_rssi_change_alone_is_not_a_change(self, meatnet: MeatNet):
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload(), rssi=-60)
        calls = []
        probe_of(meatnet).add_listener(lambda: calls.append(1))

        assert meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload(), rssi=-75) == []
        assert calls == []
        assert probe_of(meatnet).rssi == -75

    def test_temperature_change_notifies_once(self, meatnet: MeatNet):
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload())
        probe = probe_of(meatnet)
        calls = []
        probe.add_listener(lambda: calls.append(probe.temperatures))

        changed = meatnet.handle_advertisement(
            PROBE_ADDRESS, probe_payload(temperatures=NODE_TEMPS)
        )

        assert changed == [probe]
        assert calls == [NODE_TEMPS]

    def test_removed_listener_is_not_called(self, meatnet: MeatNet):
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload())
        calls = []
        remove = probe_of(meatnet).add_listener(lambda: calls.append(1))
        remove()
        remove()  # idempotent

        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload(temperatures=NODE_TEMPS))
        assert calls == []

    def test_removed_device_listener_is_not_called(self, meatnet: MeatNet):
        discovered: list[Device] = []
        remove = meatnet.add_device_listener(discovered.append)
        remove()
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload())
        assert discovered == []

    def test_failing_listeners_do_not_break_handling(self, meatnet: MeatNet):
        def broken(*_args):
            raise RuntimeError("boom")

        discovered: list[Device] = []
        meatnet.add_device_listener(broken)
        meatnet.add_device_listener(discovered.append)
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload())
        assert discovered == [probe_of(meatnet)]

        calls = []
        probe_of(meatnet).add_listener(broken)
        probe_of(meatnet).add_listener(lambda: calls.append(1))
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload(temperatures=NODE_TEMPS))
        assert calls == [1]

    def test_battery_and_preferences_are_tracked(self, meatnet: MeatNet):
        meatnet.handle_advertisement(
            PROBE_ADDRESS, probe_payload(low_battery=True, preferences=0b101)
        )
        probe = probe_of(meatnet)
        assert probe.battery_status == BatteryStatus.LOW
        assert probe.power_mode == PowerMode.ALWAYS_ON
        assert probe.high_radio_power is True

    def test_relayed_data_does_not_overwrite_preferences(self, meatnet: MeatNet, clock: FakeClock):
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload(preferences=0b101))
        clock.advance(NORMAL_MODE_IDLE_TIMEOUT + 1)
        # Nodes pad the missing preferences field with zero.
        meatnet.handle_advertisement(NODE_A, probe_payload(hop=0, preferences=0))

        probe = probe_of(meatnet)
        assert probe.source == NODE_A
        assert probe.power_mode == PowerMode.ALWAYS_ON
        assert probe.high_radio_power is True

    def test_preferences_are_unknown_until_heard_directly(self, meatnet: MeatNet):
        meatnet.handle_advertisement(NODE_A, probe_payload(hop=0, preferences=0))
        probe = probe_of(meatnet)
        assert probe.power_mode is None
        assert probe.high_radio_power is None

    def test_overheating_is_computed_from_temperatures(self, meatnet: MeatNet):
        hot = (110.0, 20.0, 20.0, 130.0, 20.0, 20.0, 20.0, 20.0)
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload(temperatures=hot))
        assert probe_of(meatnet).overheating_sensors == (0, 3)


class TestNormalModeArbitration:
    def test_direct_data_is_preferred_over_relayed_data(self, meatnet: MeatNet, clock: FakeClock):
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload(temperatures=DIRECT_TEMPS))
        clock.advance(1)
        meatnet.handle_advertisement(NODE_A, probe_payload(hop=0, temperatures=NODE_TEMPS))

        probe = probe_of(meatnet)
        assert probe.temperatures == DIRECT_TEMPS
        assert probe.source == PROBE_ADDRESS
        # The node is still recorded as a route to the probe.
        assert NODE_A in probe.routes

    def test_relayed_data_takes_over_when_direct_link_goes_quiet(
        self, meatnet: MeatNet, clock: FakeClock
    ):
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload(temperatures=DIRECT_TEMPS))
        clock.advance(NORMAL_MODE_IDLE_TIMEOUT + 0.1)
        meatnet.handle_advertisement(NODE_A, probe_payload(hop=0, temperatures=NODE_TEMPS))

        probe = probe_of(meatnet)
        assert probe.temperatures == NODE_TEMPS
        assert probe.source == NODE_A
        assert probe.source_hop_count == 1

    def test_direct_link_wins_back_immediately(self, meatnet: MeatNet, clock: FakeClock):
        meatnet.handle_advertisement(NODE_A, probe_payload(hop=0, temperatures=NODE_TEMPS))
        clock.advance(0.1)
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload(temperatures=DIRECT_TEMPS))
        assert probe_of(meatnet).temperatures == DIRECT_TEMPS

    def test_lower_hop_count_node_wins(self, meatnet: MeatNet, clock: FakeClock):
        meatnet.handle_advertisement(NODE_A, probe_payload(hop=1, temperatures=NODE_TEMPS))
        clock.advance(0.1)
        meatnet.handle_advertisement(NODE_B, probe_payload(hop=0, temperatures=OTHER_NODE_TEMPS))
        assert probe_of(meatnet).temperatures == OTHER_NODE_TEMPS

        clock.advance(0.1)
        meatnet.handle_advertisement(NODE_A, probe_payload(hop=1, temperatures=NODE_TEMPS))
        assert probe_of(meatnet).temperatures == OTHER_NODE_TEMPS
        assert probe_of(meatnet).source == NODE_B

    def test_equal_hop_count_node_does_not_steal_preferred_link(
        self, meatnet: MeatNet, clock: FakeClock
    ):
        meatnet.handle_advertisement(NODE_A, probe_payload(hop=0, temperatures=NODE_TEMPS))
        clock.advance(0.1)
        meatnet.handle_advertisement(NODE_B, probe_payload(hop=0, temperatures=OTHER_NODE_TEMPS))
        assert probe_of(meatnet).temperatures == NODE_TEMPS

    def test_rejected_data_does_not_update_battery_or_id(self, meatnet: MeatNet, clock: FakeClock):
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload(low_battery=False, probe_id=0))
        clock.advance(0.1)
        meatnet.handle_advertisement(NODE_A, probe_payload(hop=0, low_battery=True, probe_id=3))
        assert probe_of(meatnet).battery_status == BatteryStatus.OK
        assert probe_of(meatnet).probe_id.value == 0


class TestInstantRead:
    def test_instant_read_is_smoothed(self, meatnet: MeatNet):
        meatnet.handle_advertisement(PROBE_ADDRESS, instant_read_payload(60.2))
        probe = probe_of(meatnet)
        assert probe.mode == ProbeMode.INSTANT_READ
        assert probe.instant_read_raw_celsius == 60.2
        assert probe.instant_read_celsius == 60.0
        assert probe.instant_read_fahrenheit == 140.0
        assert probe.temperatures is None

    def test_raw_instant_read_change_within_deadband_is_not_a_change(self, meatnet: MeatNet):
        meatnet.handle_advertisement(PROBE_ADDRESS, instant_read_payload(60.2))
        calls = []
        probe_of(meatnet).add_listener(lambda: calls.append(1))

        assert meatnet.handle_advertisement(PROBE_ADDRESS, instant_read_payload(60.25)) == []
        assert calls == []
        assert probe_of(meatnet).instant_read_raw_celsius == 60.25

    @pytest.mark.parametrize("reading", [27.6, 27.85, 60.2, 63.4])
    def test_smoothed_instant_read_is_always_a_float(self, meatnet: MeatNet, reading: float):
        # The smoothing filter used to return an int when a reading jumped outside its deadband.
        meatnet.handle_advertisement(PROBE_ADDRESS, instant_read_payload(reading))
        assert isinstance(probe_of(meatnet).instant_read_celsius, float)
        assert isinstance(probe_of(meatnet).instant_read_fahrenheit, float)

    def test_direct_instant_read_locks_out_relayed_data(self, meatnet: MeatNet, clock: FakeClock):
        meatnet.handle_advertisement(PROBE_ADDRESS, instant_read_payload(60.0))
        clock.advance(INSTANT_READ_LOCK_TIMEOUT / 2)
        meatnet.handle_advertisement(NODE_A, instant_read_payload(80.0, hop=0))
        assert probe_of(meatnet).instant_read_celsius == 60.0

    def test_any_link_takes_over_after_lock_timeout(self, meatnet: MeatNet, clock: FakeClock):
        meatnet.handle_advertisement(PROBE_ADDRESS, instant_read_payload(60.0))
        clock.advance(INSTANT_READ_LOCK_TIMEOUT + 0.1)
        meatnet.handle_advertisement(NODE_A, instant_read_payload(80.0, hop=0))
        assert probe_of(meatnet).instant_read_celsius == 80.0
        assert probe_of(meatnet).source == NODE_A

    def test_relayed_links_switch_only_to_strictly_lower_hop_count(
        self, meatnet: MeatNet, clock: FakeClock
    ):
        meatnet.handle_advertisement(NODE_A, instant_read_payload(60.0, hop=1))
        clock.advance(0.1)
        meatnet.handle_advertisement(NODE_B, instant_read_payload(70.0, hop=1))
        assert probe_of(meatnet).instant_read_celsius == 60.0

        clock.advance(0.1)
        meatnet.handle_advertisement(NODE_B, instant_read_payload(70.0, hop=0))
        assert probe_of(meatnet).instant_read_celsius == 70.0

    def test_interleaved_normal_mode_data_keeps_instant_read(
        self, meatnet: MeatNet, clock: FakeClock
    ):
        # Real probes in instant read mode interleave normal mode advertisements.
        meatnet.handle_advertisement(PROBE_ADDRESS, instant_read_payload(60.0))
        clock.advance(0.1)
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload())

        probe = probe_of(meatnet)
        assert probe.mode == ProbeMode.INSTANT_READ
        assert probe.instant_read_celsius == 60.0
        assert probe.temperatures == DIRECT_TEMPS

    def test_interleaved_identical_data_is_not_a_change(self, meatnet: MeatNet, clock: FakeClock):
        meatnet.handle_advertisement(PROBE_ADDRESS, instant_read_payload(60.0))
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload())
        calls = []
        probe_of(meatnet).add_listener(lambda: calls.append(1))

        for _ in range(3):
            clock.advance(0.1)
            meatnet.handle_advertisement(PROBE_ADDRESS, instant_read_payload(60.0))
            clock.advance(0.1)
            meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload())
        assert calls == []


class TestExpiry:
    def test_instant_read_is_cleared_when_stale(self, meatnet: MeatNet, clock: FakeClock):
        meatnet.handle_advertisement(PROBE_ADDRESS, instant_read_payload(60.0))
        probe = probe_of(meatnet)

        clock.advance(INSTANT_READ_STALE_TIMEOUT - 0.1)
        assert meatnet.expire() == []
        assert probe.instant_read_celsius == 60.0

        clock.advance(0.2)
        assert meatnet.expire() == [probe]
        assert probe.instant_read_celsius is None
        assert probe.instant_read_raw_celsius is None
        assert probe.mode == ProbeMode.NORMAL

    def test_normal_mode_data_does_not_delay_instant_read_expiry(
        self, meatnet: MeatNet, clock: FakeClock
    ):
        meatnet.handle_advertisement(PROBE_ADDRESS, instant_read_payload(60.0))
        probe = probe_of(meatnet)
        for _ in range(int(INSTANT_READ_STALE_TIMEOUT) + 1):
            clock.advance(1.0)
            meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload())
            meatnet.expire()

        assert probe.mode == ProbeMode.NORMAL
        assert probe.instant_read_celsius is None
        assert probe.temperatures == DIRECT_TEMPS
        assert probe.available

    def test_device_becomes_unavailable_then_recovers(self, meatnet: MeatNet, clock: FakeClock):
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload())
        probe = probe_of(meatnet)
        availability = []
        probe.add_listener(lambda: availability.append(probe.available))

        clock.advance(DEFAULT_STALE_TIMEOUT + 0.1)
        assert meatnet.expire() == [probe]
        assert probe.available is False
        # Readings are kept so the host can decide how to present them.
        assert probe.temperatures == DIRECT_TEMPS

        assert meatnet.expire() == []  # already unavailable

        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload())
        assert probe.available is True
        assert availability == [False, True]

    def test_custom_stale_timeout(self, clock: FakeClock):
        meatnet = MeatNet(stale_timeout=60, clock=clock)
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload())
        clock.advance(DEFAULT_STALE_TIMEOUT + 1)
        meatnet.expire()
        assert probe_of(meatnet).available is True

    def test_routes_expire_when_node_stops_relaying(self, meatnet: MeatNet, clock: FakeClock):
        meatnet.handle_advertisement(NODE_A, probe_payload(hop=0))
        meatnet.handle_advertisement(NODE_B, probe_payload(hop=1))

        clock.advance(DEFAULT_STALE_TIMEOUT / 2)
        # Node B keeps relaying; node A now advertises no probes.
        meatnet.handle_advertisement(NODE_B, probe_payload(hop=1))
        meatnet.handle_advertisement(NODE_A, probe_payload(hop=0, serial_number=0))

        clock.advance(DEFAULT_STALE_TIMEOUT / 2 + 0.1)
        meatnet.expire()

        probe = probe_of(meatnet)
        assert set(probe.routes) == {NODE_B}
        assert meatnet.nodes[NODE_A].relayed_probes == {}
        assert SERIAL in meatnet.nodes[NODE_B].relayed_probes
        assert meatnet.nodes[NODE_A].available
        assert probe.available

    def test_gauge_and_node_become_unavailable(self, meatnet: MeatNet, clock: FakeClock):
        meatnet.handle_advertisement(NODE_A, gauge_payload())
        clock.advance(DEFAULT_STALE_TIMEOUT + 0.1)
        changed = meatnet.expire()
        assert set(changed) == {meatnet.gauges["AB12CD34EF"], meatnet.nodes[NODE_A]}
        assert not meatnet.gauges["AB12CD34EF"].available
        assert not meatnet.nodes[NODE_A].available

    def test_gauge_sensor_removal_is_a_change(self, meatnet: MeatNet):
        meatnet.handle_advertisement(NODE_A, gauge_payload(temperature=100.0))
        gauge = meatnet.gauges["AB12CD34EF"]
        calls = []
        gauge.add_listener(lambda: calls.append(gauge.temperature))

        meatnet.handle_advertisement(NODE_A, gauge_payload(sensor_present=False))
        assert calls == [None]


GAUGE_SERIAL = "AB12CD34EF"


class TestRestore:
    def test_restored_probe_has_no_readings(self, meatnet: MeatNet):
        probe = meatnet.restore_probe(SERIAL)

        assert meatnet.probes == {SERIAL: probe}
        assert meatnet.devices == [probe]
        assert probe.serial_number_string == "12345678"
        assert not probe.heard
        assert not probe.available
        assert probe.last_seen is None
        assert probe.address is None
        assert probe.temperatures is None
        assert probe.core_temperature is None
        assert probe.instant_read_celsius is None
        assert probe.battery_status is None
        assert probe.probe_id is None
        assert probe.color is None

    def test_restored_gauge_has_no_readings(self, meatnet: MeatNet):
        gauge = meatnet.restore_gauge(GAUGE_SERIAL)

        assert meatnet.gauges == {GAUGE_SERIAL: gauge}
        assert meatnet.nodes == {}
        assert not gauge.heard
        assert not gauge.available
        assert gauge.last_seen is None
        assert gauge.address is None
        assert gauge.temperature is None
        assert gauge.low_battery is None
        assert gauge.sensor_present is None
        assert gauge.sensor_overheating is None

    @pytest.mark.parametrize("serial_number", [0, -1, 0x1_0000_0000])
    def test_invalid_probe_serial_numbers_are_rejected(self, meatnet: MeatNet, serial_number: int):
        with pytest.raises(ValueError):
            meatnet.restore_probe(serial_number)
        assert meatnet.devices == []

    def test_empty_gauge_serial_number_is_rejected(self, meatnet: MeatNet):
        with pytest.raises(ValueError):
            meatnet.restore_gauge("")
        assert meatnet.devices == []

    @pytest.mark.parametrize("hop", [None, 0])
    def test_probe_is_updated_in_place_when_heard(
        self, meatnet: MeatNet, clock: FakeClock, hop: int | None
    ):
        discovered: list[Device] = []
        meatnet.add_device_listener(discovered.append)
        probe = meatnet.restore_probe(SERIAL)
        assert discovered == [probe]
        calls: list[bool] = []
        probe.add_listener(lambda: calls.append(probe.available))

        address = PROBE_ADDRESS if hop is None else NODE_A
        meatnet.handle_advertisement(address, probe_payload(hop=hop))
        assert probe_of(meatnet) is probe
        assert probe not in discovered[1:]
        assert calls == [True]
        assert probe.heard
        assert probe.last_seen == clock.now
        assert probe.temperatures == DIRECT_TEMPS
        assert probe.battery_status == BatteryStatus.OK

        # Going silent again isn't the same as never having been heard.
        clock.advance(DEFAULT_STALE_TIMEOUT + 0.1)
        meatnet.expire()
        assert calls == [True, False]
        assert probe.heard

    def test_gauge_is_updated_in_place_when_heard(self, meatnet: MeatNet):
        discovered: list[Device] = []
        meatnet.add_device_listener(discovered.append)
        gauge = meatnet.restore_gauge(GAUGE_SERIAL)
        assert discovered == [gauge]
        calls: list[bool] = []
        gauge.add_listener(lambda: calls.append(gauge.available))

        meatnet.handle_advertisement(NODE_A, gauge_payload(temperature=180.5))
        assert meatnet.gauges[GAUGE_SERIAL] is gauge
        assert discovered == [gauge, meatnet.nodes[NODE_A]]
        assert calls == [True]
        assert gauge.heard
        assert gauge.address == NODE_A
        assert gauge.temperature == 180.5
        assert gauge.low_battery is False

    def test_unusable_data_is_heard_without_readings(self, meatnet: MeatNet):
        probe = meatnet.restore_probe(SERIAL)
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload(mode=ProbeMode.ERROR.value))
        assert probe.heard
        assert probe.available
        assert probe.battery_status is None
        assert probe.temperatures is None

    def test_expire_leaves_restored_devices_alone(self, meatnet: MeatNet, clock: FakeClock):
        meatnet.restore_probe(SERIAL)
        meatnet.restore_gauge(GAUGE_SERIAL)
        clock.advance(DEFAULT_STALE_TIMEOUT + 0.1)
        assert meatnet.expire() == []

    def test_restoring_a_known_device_returns_it(self, meatnet: MeatNet):
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload())
        meatnet.handle_advertisement(NODE_A, gauge_payload())
        discovered: list[Device] = []
        meatnet.add_device_listener(discovered.append)

        probe = meatnet.restore_probe(SERIAL)
        gauge = meatnet.restore_gauge(GAUGE_SERIAL)
        assert probe.available and probe.temperatures == DIRECT_TEMPS
        assert gauge.available and gauge.heard
        assert meatnet.restore_probe(SERIAL) is probe
        assert discovered == []

    def test_restored_devices_need_no_connection(self, meatnet: MeatNet):
        meatnet.restore_probe(SERIAL)
        meatnet.restore_gauge(GAUGE_SERIAL)
        plan = plan_connections(meatnet)
        assert plan.repeaters == ()
        assert plan.direct == plan.release == frozenset()

    def test_information_for_a_restored_gauge(self, meatnet: MeatNet):
        gauge = meatnet.restore_gauge(GAUGE_SERIAL)
        assert meatnet.handle_device_information(gauge, hardware_revision="v1") == [gauge]
        assert gauge.hardware_revision == "v1"

    def test_forgotten_device_is_discovered_when_heard(self, meatnet: MeatNet):
        probe = meatnet.restore_probe(SERIAL)
        gauge = meatnet.restore_gauge(GAUGE_SERIAL)
        meatnet.forget(probe)
        meatnet.forget(gauge)
        assert meatnet.devices == []

        discovered: list[Device] = []
        meatnet.add_device_listener(discovered.append)
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload())
        meatnet.handle_advertisement(NODE_A, gauge_payload())
        heard = probe_of(meatnet), meatnet.gauges[GAUGE_SERIAL]
        assert probe is not heard[0] and gauge is not heard[1]
        assert all(device in discovered for device in heard)

        # The forgotten objects no longer stand for anything.
        meatnet.forget(probe)
        meatnet.forget(gauge)
        assert (probe_of(meatnet), meatnet.gauges[GAUGE_SERIAL]) == heard

    def test_heard_device_cannot_be_forgotten(self, meatnet: MeatNet, clock: FakeClock):
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload())
        clock.advance(DEFAULT_STALE_TIMEOUT + 0.1)
        meatnet.expire()
        with pytest.raises(ValueError):
            meatnet.forget(probe_of(meatnet))
        assert SERIAL in meatnet.probes
