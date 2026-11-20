"""Tests for combustion_ble.advertising.

Probe and gauge vectors are ported from the Combustion Android SDK's ProbeAdvertisingDataTest and
GaugeAdvertisingDataTest (MIT licensed), so both libraries decode the same bytes the same way.
"""

import pytest

from combustion_ble import (
    BatteryStatus,
    CombustionProductType,
    GaugeAdvertisement,
    HopCount,
    NodeAdvertisement,
    PowerMode,
    ProbeAdvertisement,
    ProbeColor,
    ProbeID,
    ProbeMode,
    VirtualAmbientSensor,
    VirtualCoreSensor,
    VirtualSurfaceSensor,
    parse_advertisement,
)
from tests.payloads import (
    encode_alarm,
    encode_probe_temperatures,
    gauge_payload,
    node_payload,
    probe_payload,
)

COLD_RAW_TEMPERATURES = bytes(13)

# Decodes to values where T3 (258.4C) and T4 (160.55C) exceed their overheating thresholds.
HOT_RAW_TEMPERATURES = bytes(
    [0x89, 0x00, 0xDA, 0x00, 0xD7, 0x0D, 0x07, 0x33, 0x05, 0xD5, 0x18, 0x74, 0x1A]
)

# Android test defaults: COLOR7 / ID6 / INSTANT_READ, and LOW_BATTERY / T6 core / T7 surface /
# T7 ambient.
ANDROID_MODE_COLOR_ID = 0b101_110_01
ANDROID_DEVICE_STATUS = 0b10_11_101_1


def android_probe_payload(
    *,
    product_type: int = 0x01,
    serial: bytes = bytes([0x78, 0x56, 0x34, 0x12]),
    raw_temperatures: bytes = COLD_RAW_TEMPERATURES,
    mode_color_id: int = ANDROID_MODE_COLOR_ID,
    device_status: int = ANDROID_DEVICE_STATUS,
    network_info: int = 0b1000_0000,  # HOP3
    overheating_byte: int = 0,
    preferences: int = 0b0000_0100,  # normal power mode, high radio power
    size: int = 23,
) -> bytes:
    data = bytes([product_type]) + serial + raw_temperatures
    data += bytes([mode_color_id, device_status, network_info, overheating_byte, preferences])
    return data[:size]


def parse_probe(data: bytes) -> ProbeAdvertisement:
    advertisement = parse_advertisement(data)
    assert isinstance(advertisement, ProbeAdvertisement)
    return advertisement


def parse_gauge(data: bytes) -> GaugeAdvertisement:
    advertisement = parse_advertisement(data)
    assert isinstance(advertisement, GaugeAdvertisement)
    return advertisement


class TestProbeAdvertisement:
    def test_parses_serial_number(self):
        advertisement = parse_probe(android_probe_payload())
        assert advertisement.serial_number == 0x12345678
        assert advertisement.serial_number_string == "12345678"
        assert advertisement.has_probe

    def test_zero_serial_number_means_no_probe(self):
        advertisement = parse_probe(android_probe_payload(product_type=0x02, serial=bytes(4)))
        assert advertisement.serial_number == 0
        assert not advertisement.has_probe

    def test_parses_temperatures(self):
        advertisement = parse_probe(android_probe_payload(raw_temperatures=HOT_RAW_TEMPERATURES))
        assert advertisement.temperatures[2] == pytest.approx(258.4, abs=0.05)
        assert advertisement.temperatures[3] == pytest.approx(160.55, abs=0.05)

    def test_cold_temperatures_decode_to_minimum(self):
        advertisement = parse_probe(android_probe_payload())
        assert advertisement.temperatures == (-20.0,) * 8

    def test_test_encoder_matches_firmware_vector(self):
        decoded = parse_probe(android_probe_payload(raw_temperatures=HOT_RAW_TEMPERATURES))
        assert encode_probe_temperatures(decoded.temperatures) == HOT_RAW_TEMPERATURES

    def test_parses_mode_color_and_id(self):
        advertisement = parse_probe(android_probe_payload())
        assert advertisement.mode == ProbeMode.INSTANT_READ
        assert advertisement.color == ProbeColor.color7
        assert advertisement.probe_id == ProbeID.ID6

    def test_defaults_mode_color_and_id_when_byte_is_missing(self):
        advertisement = parse_probe(android_probe_payload(size=18))
        assert advertisement.mode == ProbeMode.NORMAL
        assert advertisement.color == ProbeColor.color1
        assert advertisement.probe_id == ProbeID.ID1

    def test_parses_battery_status_and_virtual_sensors(self):
        advertisement = parse_probe(android_probe_payload())
        assert advertisement.battery_status == BatteryStatus.LOW
        assert advertisement.core_sensor == VirtualCoreSensor.T6
        assert advertisement.surface_sensor == VirtualSurfaceSensor.T7
        assert advertisement.ambient_sensor == VirtualAmbientSensor.T7

    def test_defaults_battery_status_and_virtual_sensors_when_byte_is_missing(self):
        advertisement = parse_probe(android_probe_payload(size=19))
        assert advertisement.battery_status == BatteryStatus.OK
        assert advertisement.core_sensor == VirtualCoreSensor.T1
        assert advertisement.surface_sensor == VirtualSurfaceSensor.T4
        assert advertisement.ambient_sensor == VirtualAmbientSensor.T5

    def test_undefined_core_sensor_falls_back_to_t1(self):
        advertisement = parse_probe(probe_payload(core=7))
        assert advertisement.core_sensor == VirtualCoreSensor.T1

    def test_parses_hop_count_for_a_repeater(self):
        advertisement = parse_probe(android_probe_payload(product_type=0x02))
        assert advertisement.is_repeated
        assert advertisement.hop_count == HopCount.HOP3

    def test_ignores_hop_count_for_a_probe(self):
        advertisement = parse_probe(android_probe_payload())
        assert not advertisement.is_repeated
        assert advertisement.hop_count is None

    def test_ignores_overheating_byte_when_it_disagrees_with_hot_temperatures(self):
        advertisement = parse_probe(
            android_probe_payload(
                raw_temperatures=HOT_RAW_TEMPERATURES,
                mode_color_id=0,  # normal mode
                overheating_byte=0b0000_0101,
            )
        )
        assert advertisement.overheating_sensors == (2, 3)

    def test_ignores_overheating_byte_when_no_temperature_exceeds_threshold(self):
        advertisement = parse_probe(android_probe_payload(mode_color_id=0, overheating_byte=0xFF))
        assert advertisement.overheating_sensors == ()

    def test_reports_no_overheating_in_instant_read_mode(self):
        advertisement = parse_probe(android_probe_payload(raw_temperatures=HOT_RAW_TEMPERATURES))
        assert advertisement.overheating_sensors == ()

    def test_parses_thermometer_preferences(self):
        advertisement = parse_probe(android_probe_payload(preferences=0b0000_0101))
        assert advertisement.preferences is not None
        assert advertisement.preferences.power_mode == PowerMode.ALWAYS_ON
        assert advertisement.preferences.high_radio_power is True

    def test_reserved_power_mode_is_normal(self):
        advertisement = parse_probe(android_probe_payload(preferences=0b0000_0011))
        assert advertisement.preferences is not None
        assert advertisement.preferences.power_mode == PowerMode.NORMAL

    def test_preferences_are_none_when_byte_is_missing(self):
        advertisement = parse_probe(android_probe_payload(size=22))
        assert advertisement.preferences is None

    def test_virtual_temperatures_in_normal_mode(self):
        advertisement = parse_probe(probe_payload(core=1, surface=2, ambient=3))
        assert advertisement.core_temperature == 21.5  # T2
        assert advertisement.surface_temperature == 23.5  # T6
        assert advertisement.ambient_temperature == 24.5  # T8
        assert advertisement.instant_read_temperature is None

    def test_instant_read_temperature(self):
        advertisement = parse_probe(probe_payload(mode=1, temperatures=(63.2,) + (-20.0,) * 7))
        assert advertisement.instant_read_temperature == 63.2
        assert advertisement.core_temperature is None

    def test_too_short_returns_none(self):
        assert parse_advertisement(probe_payload(size=17)) is None


class TestGaugeAdvertisement:
    def test_parses_serial_number(self):
        assert parse_gauge(gauge_payload(serial_number="AB12CD34EF")).serial_number == "AB12CD34EF"

    def test_parses_temperature(self):
        advertisement = parse_gauge(gauge_payload(temperature=200.0))
        assert advertisement.temperature == 200.0
        assert advertisement.product_type == CombustionProductType.GAUGE

    def test_temperature_is_none_without_sensor(self):
        advertisement = parse_gauge(gauge_payload(sensor_present=False))
        assert advertisement.sensor_present is False
        assert advertisement.temperature is None

    def test_parses_status_flags(self):
        advertisement = parse_gauge(
            gauge_payload(sensor_present=False, sensor_overheating=True, low_battery=True)
        )
        assert advertisement.sensor_present is False
        assert advertisement.sensor_overheating is True
        assert advertisement.low_battery is True

    def test_parses_high_low_alarm_status(self):
        advertisement = parse_gauge(
            gauge_payload(
                high_alarm=encode_alarm(True, True, False, 210.0),
                low_alarm=encode_alarm(True, False, False, 40.0),
            )
        )
        assert advertisement.high_alarm.set is True
        assert advertisement.high_alarm.tripped is True
        assert advertisement.high_alarm.alarming is False
        assert advertisement.high_alarm.temperature == 210.0
        assert advertisement.low_alarm.set is True
        assert advertisement.low_alarm.tripped is False
        assert advertisement.low_alarm.temperature == 40.0

    def test_parses_preferences(self):
        assert parse_gauge(gauge_payload(preferences=0x01)).high_radio_power is True
        assert parse_gauge(gauge_payload(preferences=0x00)).high_radio_power is False

    def test_preferences_are_none_when_byte_is_missing(self):
        assert parse_gauge(gauge_payload(preferences=None)).high_radio_power is None

    def test_parses_gauge_id_when_present(self):
        assert parse_gauge(gauge_payload(gauge_id=4)).gauge_id == 4

    def test_gauge_id_is_none_when_missing(self):
        assert parse_gauge(gauge_payload()).gauge_id is None

    def test_too_short_returns_none(self):
        assert parse_advertisement(gauge_payload(preferences=None)[:18]) is None


class TestNodeAdvertisement:
    @pytest.mark.parametrize(
        ("product_type", "expected"),
        [
            (0x04, CombustionProductType.DISPLAY),
            (0x05, CombustionProductType.BOOSTER),
            (0x06, CombustionProductType.ENGINE),
        ],
    )
    def test_parses_device_information(self, product_type, expected):
        advertisement = parse_advertisement(node_payload(product_type, "1234ABCD99"))
        assert advertisement == NodeAdvertisement(product_type=expected, serial_number="1234ABCD99")

    def test_strips_null_padding_from_serial_number(self):
        advertisement = parse_advertisement(node_payload(0x04, "ABC"))
        assert isinstance(advertisement, NodeAdvertisement)
        assert advertisement.serial_number == "ABC"


class TestCapturedProbeAdvertisements:
    """Advertisements captured from real probes (serial numbers replaced with 0x10000001)."""

    def test_normal_mode_low_battery_always_on(self):
        advertisement = parse_probe(
            bytes.fromhex("01" "01000010" "6ac36dc80db51136b6c6d6f01a" "20e1000001")
        )
        assert advertisement.serial_number_string == "10000001"
        assert advertisement.mode == ProbeMode.NORMAL
        assert advertisement.probe_id == ProbeID.ID2
        assert advertisement.color == ProbeColor.color1
        assert advertisement.battery_status == BatteryStatus.LOW
        assert advertisement.temperatures == (23.7, 23.9, 24.1, 23.7, 23.25, 22.95, 22.95, 23.1)
        assert advertisement.core_sensor == VirtualCoreSensor.T1
        assert advertisement.surface_sensor == VirtualSurfaceSensor.T6
        assert advertisement.ambient_sensor == VirtualAmbientSensor.T8
        assert advertisement.preferences is not None
        assert advertisement.preferences.power_mode == PowerMode.ALWAYS_ON
        assert advertisement.preferences.high_radio_power is False

    def test_normal_mode(self):
        advertisement = parse_probe(
            bytes.fromhex("01" "01000010" "5ac36a588daaa135ac46d6d81a" "00c0000000")
        )
        assert advertisement.mode == ProbeMode.NORMAL
        assert advertisement.probe_id == ProbeID.ID1
        assert advertisement.battery_status == BatteryStatus.OK
        assert advertisement.temperatures == (22.9, 22.7, 22.7, 22.65, 22.9, 22.7, 22.85, 22.95)
        assert advertisement.core_temperature == 22.9
        assert advertisement.surface_temperature == 22.65
        assert advertisement.ambient_temperature == 22.95
        assert advertisement.preferences is not None
        assert advertisement.preferences.power_mode == PowerMode.NORMAL

    def test_instant_read(self):
        advertisement = parse_probe(
            bytes.fromhex("01" "01000010" "cb030000000000000000000000" "21c1000001")
        )
        assert advertisement.mode == ProbeMode.INSTANT_READ
        assert advertisement.instant_read_temperature == 28.55
        assert advertisement.temperatures[1:] == (-20.0,) * 7

    def test_repeated_by_booster(self):
        advertisement = parse_probe(
            bytes.fromhex("02" "01000010" "b4c375b08ed7c1391a07e4f81c" "20c1000000")
        )
        assert advertisement.is_repeated
        assert advertisement.serial_number_string == "10000001"
        assert advertisement.hop_count == HopCount.HOP1
        assert advertisement.mode == ProbeMode.NORMAL
        assert advertisement.probe_id == ProbeID.ID2
        assert advertisement.battery_status == BatteryStatus.LOW
        assert advertisement.temperatures == (27.4, 27.1, 27.0, 27.15, 26.2, 25.45, 25.6, 26.35)
        assert advertisement.core_sensor == VirtualCoreSensor.T1
        assert advertisement.surface_sensor == VirtualSurfaceSensor.T4
        assert advertisement.ambient_sensor == VirtualAmbientSensor.T8
        # Repeated data has no preferences field. The trailing zero is padding.
        assert advertisement.preferences is None

    def test_instant_read_repeated_by_booster(self):
        advertisement = parse_probe(
            bytes.fromhex("02" "01000010" "b1030000000000000000000000" "21c1000000")
        )
        assert advertisement.is_repeated
        assert advertisement.mode == ProbeMode.INSTANT_READ
        assert advertisement.instant_read_temperature == 27.25

    def test_booster_without_probes(self):
        advertisement = parse_probe(bytes.fromhex("02" + "00" * 22))
        assert advertisement.is_repeated
        assert not advertisement.has_probe


def test_captured_booster_device_information():
    """Booster advertisement captured from a real device (serial number replaced)."""
    data = bytes([0x05]) + b"CR10000001" + bytes.fromhex("01" + "00" * 11)
    assert parse_advertisement(data) == NodeAdvertisement(
        product_type=CombustionProductType.BOOSTER, serial_number="CR10000001"
    )


@pytest.mark.parametrize(
    "data",
    [
        b"",
        bytes([0x00]) + bytes(22),  # unknown product type
        bytes([0x07]) + bytes(22),  # product type from the future
        bytes([0xFF]) + bytes(22),
        bytes([0x01]),
        bytes([0x04, 0x41]),
    ],
)
def test_unsupported_or_malformed_data_returns_none(data):
    assert parse_advertisement(data) is None
