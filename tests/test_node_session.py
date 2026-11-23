"""Relayed predictions through a MeatNet node session, and choosing between prediction sources."""

import asyncio

import pytest

from combustion_ble import MeatNet, NodeSession, PredictionStatus, ProbeSession
from combustion_ble.const import DEVICE_STATUS_CHARACTERISTIC, UART_TX_CHARACTERISTIC
from combustion_ble.meatnet import PREDICTION_FAILOVER_TIMEOUT, PREDICTION_STALE_TIMEOUT
from combustion_ble.utilities.crc16ccitt import crc16ccitt
from tests.payloads import probe_payload
from tests.test_probe_session import FakeClient, status_payload

SERIAL = 0x12345678
OTHER_SERIAL = 0x0BADCAFE
PROBE_ADDRESS = "AA:BB:CC:DD:EE:FF"
NODE_ADDRESS = "11:22:33:44:55:66"
OTHER_NODE_ADDRESS = "11:22:33:44:55:77"


def node_status_frame(
    serial_number: int = SERIAL,
    *,
    hop: int = 0,
    legacy: bool = False,
    food_safe: bytes = bytes(18),
    **status,
) -> bytes:
    """Build a Probe Status (0x45) request frame, packed independently from the parser."""
    payload = serial_number.to_bytes(4, "little") + status_payload(**status)
    network_info = bytes([hop << 6])
    if legacy:
        payload += network_info
    else:
        # Food safe data and status, network info, overheating, preferences, high and low alarm
        # arrays, session ID, and sample period.
        payload += food_safe + network_info + bytes(1 + 1 + 22 + 22 + 4 + 2)
        assert len(payload) == 105
    body = b"\x45" + (0xDEADBEEF).to_bytes(4, "little") + bytes([len(payload)]) + payload
    return b"\xca\xfe" + crc16ccitt(body).to_bytes(2, "little") + body


def node_response_frame(type_: int = 0x05, payload: bytes = b"") -> bytes:
    body = (
        bytes([type_ | 0x80])
        + (1).to_bytes(4, "little")
        + (2).to_bytes(4, "little")
        + bytes([1, len(payload)])
        + payload
    )
    return b"\xca\xfe" + crc16ccitt(body).to_bytes(2, "little") + body


def setup_meatnet():
    clock = [1000.0]
    meatnet = MeatNet(clock=lambda: clock[0])
    for serial_number in (SERIAL, OTHER_SERIAL):
        meatnet.handle_advertisement(
            NODE_ADDRESS, probe_payload(serial_number=serial_number, hop=0)
        )
    return meatnet, clock


def setup_session():
    meatnet, clock = setup_meatnet()
    client = FakeClient()
    return meatnet, client, NodeSession(meatnet, NODE_ADDRESS, client), clock


def emit(client: FakeClient, data: bytes) -> None:
    client.emit(UART_TX_CHARACTERISTIC, data)


def test_relayed_predictions_for_every_probe():
    async def run():
        meatnet, client, session, clock = setup_session()
        probe = meatnet.probes[SERIAL]
        updates = []
        probe.add_listener(lambda: updates.append(probe.prediction))
        temperatures = probe.temperatures
        await session.start()
        assert list(client.callbacks) == [UART_TX_CHARACTERISTIC]
        assert not session._is_reporting(SERIAL)
        emit(client, node_status_frame(seconds=600))
        assert session._is_reporting(SERIAL)
        assert not session._is_reporting(OTHER_SERIAL)
        assert not session._is_reporting(0x01020304)  # Undiscovered probe.
        emit(client, node_status_frame(OTHER_SERIAL, seconds=120))
        assert probe.prediction.seconds_remaining == 600
        assert probe.prediction.percent_through_cook == 50
        assert meatnet.probes[OTHER_SERIAL].prediction.seconds_remaining == 120
        assert probe.temperatures == temperatures  # Relayed data doesn't replace passive data.
        assert len(updates) == 1
        clock[0] += 1
        emit(client, node_status_frame(seconds=600))
        assert len(updates) == 1
        assert probe.prediction_updated_at == clock[0]
        clock[0] += 2
        meatnet.expire()
        assert probe.prediction.seconds_remaining == 598
        clock[0] += PREDICTION_STALE_TIMEOUT
        meatnet.expire()
        assert probe.prediction is None
        assert not session._is_reporting(SERIAL)
        emit(client, node_status_frame(seconds=600))
        assert session._is_reporting(SERIAL)
        await session.stop()
        assert not session._is_reporting(SERIAL)
        assert probe.prediction is None
        assert meatnet.probes[OTHER_SERIAL].prediction is None
        assert client.is_connected
        assert not client.callbacks
        assert not client.writes  # Receiving predictions sends nothing to the node.

    asyncio.run(run())


def test_payload_layouts_framing_and_unknown_probes():
    async def run():
        meatnet, client, session, _ = setup_session()
        await session.start()
        bad = bytearray(node_status_frame())
        bad[2] ^= 0xFF
        short = bytearray(node_status_frame())
        # A 40-byte payload is neither layout: rewrite its length and CRC.
        short = short[:4] + short[4:9] + bytes([40]) + short[10:50]
        short[2:4] = crc16ccitt(bytes(short[4:])).to_bytes(2, "little")
        unknown = node_status_frame(0x01020304)
        emit(client, b"noise" + bytes(bad) + node_response_frame() + bytes(short) + unknown)
        assert meatnet.probes[SERIAL].prediction is None
        assert 0x01020304 not in meatnet.probes
        # Split across notifications, combined with an unrelated response.
        frame = node_status_frame(seconds=300)
        emit(client, frame[:7])
        emit(client, frame[7:60])
        assert meatnet.probes[SERIAL].prediction is None
        emit(client, frame[60:] + node_response_frame(0x03, bytes(10)))
        assert meatnet.probes[SERIAL].prediction.seconds_remaining == 300
        # Node firmware that predates food safe data sends a 35-byte payload.
        emit(client, node_status_frame(OTHER_SERIAL, legacy=True, seconds=42))
        assert meatnet.probes[OTHER_SERIAL].prediction.seconds_remaining == 42
        await session.stop()

    asyncio.run(run())


def test_disconnect_exclusivity_and_late_callbacks():
    async def run():
        meatnet, client, session, _ = setup_session()
        with pytest.raises(KeyError):
            NodeSession(meatnet, OTHER_NODE_ADDRESS, client)
        await session.start()
        other = NodeSession(meatnet, NODE_ADDRESS, FakeClient())
        with pytest.raises(RuntimeError, match="already has"):
            await other.start()
        await other.stop()  # A competing session cannot clear the owner's predictions.
        emit(client, node_status_frame())
        callback = client.callbacks[UART_TX_CHARACTERISTIC]
        assert meatnet.probes[SERIAL].prediction is not None
        client.is_connected = False
        session.disconnected()
        assert meatnet.probes[SERIAL].prediction is None
        callback(None, bytearray(node_status_frame()))
        assert meatnet.probes[SERIAL].prediction is None
        await session.stop()
        assert meatnet.nodes[NODE_ADDRESS]._prediction_session is None
        with pytest.raises(RuntimeError, match="new session"):
            await session.start()
        replacement = NodeSession(meatnet, NODE_ADDRESS, FakeClient())
        await replacement.start()
        await replacement.stop()

    asyncio.run(run())


def prediction_status(seconds: int) -> PredictionStatus:
    return PredictionStatus.from_bytes(status_payload(seconds=seconds)[23:30])


def test_sources_prefer_direct_then_fewest_hops():
    meatnet, clock = setup_meatnet()
    probe = meatnet.probes[SERIAL]
    far, near, direct = object(), object(), object()
    meatnet.handle_prediction_status(SERIAL, prediction_status(300), source=far, hop_count=2)
    assert probe.prediction.seconds_remaining == 300
    meatnet.handle_prediction_status(SERIAL, prediction_status(200), source=near, hop_count=1)
    assert probe.prediction.seconds_remaining == 200
    meatnet.handle_prediction_status(SERIAL, prediction_status(300), source=far, hop_count=2)
    assert probe.prediction.seconds_remaining == 200
    meatnet.handle_prediction_status(SERIAL, prediction_status(100), source=direct)
    assert probe.prediction.seconds_remaining == 100
    meatnet.handle_prediction_status(SERIAL, prediction_status(200), source=near, hop_count=1)
    assert probe.prediction.seconds_remaining == 100

    # Losing the direct source falls back to the best remaining one immediately.
    clock[0] += 2
    meatnet.clear_prediction(SERIAL, source=direct)
    assert probe.prediction.seconds_remaining == 198
    assert probe.prediction_updated_at == clock[0] - 2

    # A quiet preferred source is replaced by a worse one that is still reporting.
    clock[0] += PREDICTION_FAILOVER_TIMEOUT
    meatnet.handle_prediction_status(SERIAL, prediction_status(300), source=far, hop_count=2)
    assert probe.prediction.seconds_remaining == 300
    # ...and takes over again once it resumes, because it has fewer hops.
    meatnet.handle_prediction_status(SERIAL, prediction_status(190), source=near, hop_count=1)
    assert probe.prediction.seconds_remaining == 190

    meatnet.clear_prediction(SERIAL, source=near)
    meatnet.clear_prediction(SERIAL, source=far)
    assert probe.prediction is None
    assert probe.prediction_updated_at is None


def test_repeater_status_gap_does_not_hand_over():
    """Repeaters relay each probe's status about every 5 seconds (measured on a Booster)."""
    meatnet, clock = setup_meatnet()
    probe = meatnet.probes[SERIAL]
    near, far = object(), object()
    meatnet.handle_prediction_status(SERIAL, prediction_status(200), source=near, hop_count=1)
    for _ in range(3):
        clock[0] += 6
        meatnet.handle_prediction_status(SERIAL, prediction_status(300), source=far, hop_count=2)
        assert probe.prediction.seconds_remaining == 194
        meatnet.handle_prediction_status(SERIAL, prediction_status(200), source=near, hop_count=1)
        assert probe.prediction.seconds_remaining == 200


def test_node_with_fewest_hops_wins():
    async def run():
        meatnet, far_client, far_session, _ = setup_session()
        meatnet.handle_advertisement(OTHER_NODE_ADDRESS, probe_payload(hop=1))
        near_client = FakeClient()
        near_session = NodeSession(meatnet, OTHER_NODE_ADDRESS, near_client)
        await far_session.start()
        await near_session.start()
        probe = meatnet.probes[SERIAL]
        emit(far_client, node_status_frame(hop=2, seconds=300))
        assert probe.prediction.seconds_remaining == 300
        emit(near_client, node_status_frame(hop=1, seconds=200))
        emit(far_client, node_status_frame(hop=2, seconds=300))
        assert probe.prediction.seconds_remaining == 200
        await near_session.stop()
        assert probe.prediction.seconds_remaining == 300
        await far_session.stop()

    asyncio.run(run())


def test_direct_and_node_sessions_together():
    async def run():
        meatnet, node_client, node_session, _ = setup_session()
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload())
        probe_client = FakeClient()
        probe_session = ProbeSession(meatnet, SERIAL, probe_client)
        await node_session.start()
        await probe_session.start()
        probe = meatnet.probes[SERIAL]
        emit(node_client, node_status_frame(seconds=500))
        probe_client.emit(DEVICE_STATUS_CHARACTERISTIC, status_payload(seconds=600))
        emit(node_client, node_status_frame(seconds=500))
        assert probe.prediction.seconds_remaining == 600
        await probe_session.stop()
        assert probe.prediction.seconds_remaining == 500
        await node_session.stop()
        assert probe.prediction is None

    asyncio.run(run())


def test_status_for_a_restored_probe_waits_until_it_is_heard():
    async def run():
        meatnet, client, session, _ = setup_session()
        serial_number = 0x01020304
        probe = meatnet.restore_probe(serial_number)
        await session.start()
        emit(client, node_status_frame(serial_number, seconds=600))
        assert probe.prediction is None
        assert not session._is_reporting(serial_number)

        meatnet.handle_advertisement(
            NODE_ADDRESS, probe_payload(serial_number=serial_number, hop=0)
        )
        emit(client, node_status_frame(serial_number, seconds=600))
        assert meatnet.probes[serial_number].prediction.seconds_remaining == 600
        assert session._is_reporting(serial_number)
        await session.stop()

    asyncio.run(run())
