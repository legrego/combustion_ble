"""Firmware and hardware revisions: parsing, device state, and Device Information reads."""

import asyncio

import pytest

from combustion_ble import FirmwareVersion, MeatNet, NodeSession, ProbeSession
from combustion_ble.const import FW_VERSION_CHARACTERISTIC, HW_VERSION_CHARACTERISTIC
from tests.payloads import gauge_payload, probe_payload
from tests.test_probe_session import FakeClient

SERIAL = 0x12345678
PROBE_ADDRESS = "AA:BB:CC:DD:EE:FF"
NODE_ADDRESS = "11:22:33:44:55:66"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("v1.2.3", (1, 2, 3, None, None)),
        ("v0.12.40-15-gabc123", (0, 12, 40, 15, "gabc123")),
        ("v2.0.1_debug", (2, 0, 1, None, None)),
        ("v2.0.1-3-abc_release", (2, 0, 1, 3, "abc")),
        (" v1.2.3\n", (1, 2, 3, None, None)),
    ],
)
def test_parse_versions(raw, expected):
    version = FirmwareVersion.parse(raw)
    assert (version.major, version.minor, version.patch, version.commit, version.sha) == expected
    assert version.is_valid
    assert str(version) == raw.strip()


@pytest.mark.parametrize("raw", ["", "1.2.3", "v1.2", "v1.2.3.4", "vX.2.3", "v1.-2.3", "garbage"])
def test_unparseable_versions_keep_raw_string(raw):
    version = FirmwareVersion.parse(raw)
    assert not version.is_valid
    assert version.raw == raw
    with pytest.raises(TypeError):
        _ = version < FirmwareVersion.parse("v1.0.0")


def test_ordering():
    ordered = [
        FirmwareVersion.parse(raw)
        for raw in ("v0.9.9", "v1.2.3", "v1.2.3-1-a", "v1.2.3-10-b", "v1.2.10", "v1.10.0", "v2.0.0")
    ]
    assert ordered == sorted(reversed(ordered))
    assert FirmwareVersion.parse("v1.2.3") == FirmwareVersion.parse("v1.2.3")
    assert FirmwareVersion.parse("v1.2.3") >= FirmwareVersion.parse("v1.2.3")
    assert len({FirmwareVersion.parse("v1.2.3"), FirmwareVersion.parse("v1.2.3")}) == 1


def test_handle_device_information_notifies_and_keeps_values():
    meatnet = MeatNet()
    meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload())
    probe = meatnet.probes[SERIAL]
    updates = []
    probe.add_listener(lambda: updates.append(probe.firmware_version))
    assert probe.firmware_version is None
    assert probe.hardware_revision is None

    assert meatnet.handle_device_information(probe, firmware_version="v1.2.3") == [probe]
    assert probe.firmware_version == FirmwareVersion.parse("v1.2.3")
    assert updates == [probe.firmware_version]
    assert meatnet.handle_device_information(probe, firmware_version="v1.2.3") == []
    assert meatnet.handle_device_information(probe, hardware_revision="v2") == [probe]
    assert str(probe.firmware_version) == "v1.2.3"  # None leaves the other value unchanged.
    assert probe.hardware_revision == "v2"
    meatnet.handle_device_information(probe, firmware_version=FirmwareVersion.parse("v1.3.0"))
    assert probe.firmware_version == FirmwareVersion.parse("v1.3.0")
    assert len(updates) == 3


def test_gauge_information_applies_to_its_node():
    meatnet = MeatNet()
    assert meatnet.handle_advertisement(NODE_ADDRESS, gauge_payload())
    gauge = meatnet.gauges["AB12CD34EF"]
    node = meatnet.nodes[NODE_ADDRESS]
    changed = meatnet.handle_device_information(node, firmware_version="v1.0.0")
    assert set(changed) == {node, gauge}
    assert gauge.firmware_version == node.firmware_version
    meatnet.handle_device_information(gauge, hardware_revision="hw")
    assert node.hardware_revision == "hw"


def setup_meatnet():
    meatnet = MeatNet()
    meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload())
    meatnet.handle_advertisement(NODE_ADDRESS, probe_payload(hop=0))
    return meatnet


@pytest.mark.parametrize("kind", ["probe", "node"])
def test_sessions_read_device_information(kind):
    async def run():
        meatnet = setup_meatnet()
        client = FakeClient()
        client.gatt = {
            FW_VERSION_CHARACTERISTIC: b"v1.4.2\x00\x00\x00",
            HW_VERSION_CHARACTERISTIC: b"v3",
        }
        if kind == "probe":
            device = meatnet.probes[SERIAL]
            session: ProbeSession | NodeSession = ProbeSession(meatnet, SERIAL, client)
        else:
            device = meatnet.nodes[NODE_ADDRESS]
            session = NodeSession(meatnet, NODE_ADDRESS, client)
        with pytest.raises(ConnectionError):
            await session.read_device_information()  # Not started.
        await session.start()
        await session.read_device_information()
        assert client.reads == [FW_VERSION_CHARACTERISTIC, HW_VERSION_CHARACTERISTIC]
        assert device.firmware_version == FirmwareVersion("v1.4.2", major=1, minor=4, patch=2)
        assert device.hardware_revision == "v3"
        assert not client.writes
        await session.stop()
        # Revisions survive the session.
        assert device.firmware_version.raw == "v1.4.2"
        with pytest.raises(ConnectionError):
            await session.read_device_information()

    asyncio.run(run())


def test_failed_read_keeps_session_and_earlier_values():
    async def run():
        meatnet = setup_meatnet()
        client = FakeClient()
        client.gatt = {FW_VERSION_CHARACTERISTIC: b"v1.0.0"}  # No hardware revision.
        session = ProbeSession(meatnet, SERIAL, client)
        await session.start()
        with pytest.raises(KeyError):
            await session.read_device_information()
        assert meatnet.probes[SERIAL].firmware_version.raw == "v1.0.0"
        assert meatnet.probes[SERIAL].hardware_revision is None
        await session.set_removal_temperature(60)  # Still running.
        await session.stop()

    asyncio.run(run())
