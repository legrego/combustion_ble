"""Choosing prediction connections from MeatNet state, without any I/O."""

import asyncio

from combustion_ble import ConnectionPlan, MeatNet, NodeSession, plan_connections
from combustion_ble.meatnet import DEFAULT_STALE_TIMEOUT, PREDICTION_STALE_TIMEOUT
from tests.payloads import node_payload, probe_payload
from tests.test_node_session import emit, node_status_frame
from tests.test_probe_session import FakeClient

DIRECT = 0x10000001
RELAYED_ONLY = 0x10000002
STRONG = "00:00:00:00:00:01"
WEAK = "00:00:00:00:00:02"
IDLE = "00:00:00:00:00:03"
PROBE_ADDRESS = "00:00:00:00:00:04"


def setup():
    clock = [1000.0]
    meatnet = MeatNet(clock=lambda: clock[0])
    meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload(serial_number=DIRECT))
    # The idle repeater has the strongest signal but relays no probes.
    meatnet.handle_advertisement(IDLE, node_payload(5), rssi=-40)
    meatnet.handle_advertisement(STRONG, probe_payload(serial_number=DIRECT, hop=0), rssi=-50)
    meatnet.handle_advertisement(WEAK, probe_payload(serial_number=RELAYED_ONLY, hop=1), rssi=-80)
    return meatnet, clock


def test_without_a_repeater():
    meatnet, clock = setup()
    assert plan_connections(meatnet) == ConnectionPlan(
        repeaters=(STRONG, WEAK, IDLE), direct=frozenset({DIRECT}), release=frozenset()
    )
    # A repeater whose last attempt failed is tried after every other one.
    assert plan_connections(meatnet, failed={STRONG}).repeaters == (WEAK, IDLE, STRONG)

    # Unavailable repeaters and probes are left out.
    clock[0] += DEFAULT_STALE_TIMEOUT + 1
    meatnet.handle_advertisement(WEAK, probe_payload(serial_number=RELAYED_ONLY, hop=1))
    meatnet.expire()
    assert plan_connections(meatnet) == ConnectionPlan(
        repeaters=(WEAK,), direct=frozenset(), release=frozenset()
    )


def test_with_a_repeater_session():
    async def run():
        meatnet, clock = setup()
        client = FakeClient()
        session = NodeSession(meatnet, STRONG, client)
        await session.start()
        # Connected, but not reporting the probe yet: keep its direct connection.
        assert plan_connections(meatnet, repeater=session) == ConnectionPlan(
            repeaters=(), direct=frozenset({DIRECT}), release=frozenset()
        )
        emit(client, node_status_frame(DIRECT))
        emit(client, node_status_frame(RELAYED_ONLY, hop=1))
        assert plan_connections(meatnet, repeater=session) == ConnectionPlan(
            repeaters=(),
            direct=frozenset(),
            release=frozenset({DIRECT, RELAYED_ONLY}),
        )
        # Once the repeater's reports go stale, the probe needs its direct connection again.
        clock[0] += PREDICTION_STALE_TIMEOUT + 1
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload(serial_number=DIRECT))
        meatnet.expire()
        assert plan_connections(meatnet, repeater=session).direct == {DIRECT}
        emit(client, node_status_frame(DIRECT))
        await session.stop()
        assert plan_connections(meatnet).release == frozenset()

    asyncio.run(run())
