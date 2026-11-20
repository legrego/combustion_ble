"""Regression tests for the legacy AdvertisingData parser used by DeviceManager."""

import pytest

from combustion_ble.ble_data.advertising_data import (
    AdvertisingData,
    CombustionProductType,
)
from tests.payloads import gauge_payload, node_payload, probe_payload


def test_unknown_product_type_values_do_not_raise():
    assert CombustionProductType(0x63) == CombustionProductType.UNKNOWN


@pytest.mark.parametrize(
    "payload",
    [gauge_payload(), node_payload(0x04), node_payload(0x05), node_payload(0x06)],
    ids=["gauge", "display", "booster", "engine"],
)
def test_non_probe_advertisements_are_ignored(payload):
    # These product types used to raise ValueError from inside the scanner callback.
    assert AdvertisingData.from_bleak_data(payload) is None


def test_probe_advertisements_still_parse():
    advertising = AdvertisingData.from_bleak_data(probe_payload(serial_number=0x10001234))
    assert advertising is not None
    assert advertising.type == CombustionProductType.PROBE
    assert advertising.serial_number == 0x10001234
    assert advertising.bit_string.startswith("0000100111000111")  # vendor ID 0x09C7
