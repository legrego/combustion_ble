"""SafeCook (food safe) decoding and how it reaches MeatNet probes through sessions."""

import asyncio
from dataclasses import replace

import pytest

from combustion_ble import (
    FoodSafe,
    FoodSafeMode,
    FoodSafeState,
    IntegratedProduct,
    MeatNet,
    NodeSession,
    ProbeSession,
    Serving,
    SimplifiedProduct,
)
from combustion_ble.ble_data.food_safe_data import FoodSafeData
from combustion_ble.ble_data.food_safe_status import FoodSafeStatus
from combustion_ble.ble_data.probe_status import ProbeStatus
from combustion_ble.const import DEVICE_STATUS_CHARACTERISTIC, UART_TX_CHARACTERISTIC
from combustion_ble.meatnet import PREDICTION_STALE_TIMEOUT
from tests.payloads import encode_food_safe_data, encode_food_safe_status, probe_payload
from tests.test_node_session import node_status_frame
from tests.test_probe_session import FakeClient, status_payload

SERIAL = 0x12345678
PROBE_ADDRESS = "AA:BB:CC:DD:EE:FF"
NODE_ADDRESS = "11:22:33:44:55:66"

FOOD_SAFE = encode_food_safe_data() + encode_food_safe_status()
SAFE = encode_food_safe_data() + encode_food_safe_status(state=1, log_reduction=6.6)

EXPECTED = FoodSafe(
    state=FoodSafeState.NOT_SAFE,
    log_reduction=2.3,
    seconds_above_threshold=754,
    mode=FoodSafeMode.INTEGRATED,
    product=IntegratedProduct.MEATS,
    serving=Serving.SERVED_IMMEDIATELY,
    threshold_temperature=54.4,
    z_value=5.6,
    reference_temperature=60.0,
    d_value=3.5,
    target_log_reduction=6.5,
)
EXPECTED_SAFE = replace(EXPECTED, state=FoodSafeState.SAFE, log_reduction=6.6)


def test_food_safe_data_fields():
    data = FoodSafeData.from_bytes(
        encode_food_safe_data(
            mode=0,
            product=12,
            serving=1,
            threshold=409.55,
            z_value=0.05,
            reference=0.0,
            d_value=409.55,
            target_log_reduction=25.5,
        )
    )
    assert data == FoodSafeData(
        mode=FoodSafeMode.SIMPLIFIED,
        product=SimplifiedProduct.CASSEROLES,
        serving=Serving.COOKED_AND_CHILLED,
        threshold_temperature=409.55,
        z_value=0.05,
        reference_temperature=0.0,
        d_value=409.55,
        target_log_reduction=25.5,
    )
    assert FoodSafeData.from_bytes(encode_food_safe_data(product=1023)).product is (
        IntegratedProduct.CUSTOM
    )


def test_unknown_values_stay_raw():
    # Deprecated integrated product, reserved serving, and reserved mode.
    data = FoodSafeData.from_bytes(encode_food_safe_data(product=7, serving=5))
    assert data.product == 7 and not isinstance(data.product, IntegratedProduct)
    assert data.serving == 5 and not isinstance(data.serving, Serving)
    reserved = FoodSafeData.from_bytes(encode_food_safe_data(mode=3, product=2))
    assert reserved.mode == 3 and reserved.product == 2
    status = FoodSafeStatus.from_bytes(encode_food_safe_status(state=6))
    assert status.state == 6 and not isinstance(status.state, FoodSafeState)


def test_food_safe_status_fields():
    status = FoodSafeStatus.from_bytes(
        encode_food_safe_status(
            state=2, log_reduction=25.5, seconds_above_threshold=0xFFFF, sequence_number=0xFFFFFFFF
        )
    )
    assert status == FoodSafeStatus(
        state=FoodSafeState.SAFETY_IMPOSSIBLE,
        log_reduction=25.5,
        seconds_above_threshold=0xFFFF,
        sequence_number=0xFFFFFFFF,
    )


def test_program_set():
    assert EXPECTED.program_set
    # Turning SafeCook off in the app writes an all-zero program, as captured from a Booster.
    off = ProbeStatus.from_data(status_payload(food_safe=bytes(18))).food_safe
    assert off is not None
    assert off.mode is FoodSafeMode.SIMPLIFIED and off.product is SimplifiedProduct.DEFAULT
    assert not off.program_set
    # A real Simplified program for the Default product has a threshold.
    default_product = ProbeStatus.from_data(
        status_payload(
            food_safe=encode_food_safe_data(mode=0, product=0, threshold=73.9)
            + encode_food_safe_status()
        )
    ).food_safe
    assert default_product is not None and default_product.program_set


def test_short_fields_raise():
    with pytest.raises(ValueError):
        FoodSafeData.from_bytes(bytes(9))
    with pytest.raises(ValueError):
        FoodSafeStatus.from_bytes(bytes(7))


def test_probe_status_lengths():
    assert ProbeStatus.from_data(status_payload()).food_safe is None
    # Current probe firmware sends 100 bytes; food safe fields sit at 30-47.
    status = ProbeStatus.from_data(status_payload(food_safe=FOOD_SAFE) + bytes(52))
    assert status.food_safe == EXPECTED
    assert status.food_safe_status.sequence_number == 0xFEDCBA98


def test_direct_probe_session():
    async def run():
        clock = [1000.0]
        meatnet = MeatNet(clock=lambda: clock[0])
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload())
        client = FakeClient()
        session = ProbeSession(meatnet, SERIAL, client)
        probe = meatnet.probes[SERIAL]
        updates = []
        probe.add_listener(lambda: updates.append(probe.food_safe))
        await session.start()
        client.emit(DEVICE_STATUS_CHARACTERISTIC, status_payload(food_safe=FOOD_SAFE))
        assert probe.food_safe == EXPECTED
        assert len(updates) == 1
        client.emit(DEVICE_STATUS_CHARACTERISTIC, status_payload(food_safe=SAFE))
        assert probe.food_safe == EXPECTED_SAFE
        assert len(updates) == 2
        # Older firmware has no food safe fields.
        client.emit(DEVICE_STATUS_CHARACTERISTIC, status_payload())
        assert probe.food_safe is None
        assert probe.prediction is not None
        client.emit(DEVICE_STATUS_CHARACTERISTIC, status_payload(food_safe=FOOD_SAFE))
        clock[0] += PREDICTION_STALE_TIMEOUT + 1
        meatnet.expire()
        assert probe.food_safe is None
        client.emit(DEVICE_STATUS_CHARACTERISTIC, status_payload(food_safe=FOOD_SAFE))
        await session.stop()
        assert probe.food_safe is None

    asyncio.run(run())


def test_relayed_through_node_and_direct_preferred():
    async def run():
        meatnet = MeatNet(clock=lambda: 1000.0)
        meatnet.handle_advertisement(NODE_ADDRESS, probe_payload(hop=0))
        probe = meatnet.probes[SERIAL]
        node_client = FakeClient()
        node = NodeSession(meatnet, NODE_ADDRESS, node_client)
        await node.start()
        node_client.emit(UART_TX_CHARACTERISTIC, node_status_frame(food_safe=FOOD_SAFE))
        assert probe.food_safe == EXPECTED
        # Node firmware that predates food safe data.
        node_client.emit(UART_TX_CHARACTERISTIC, node_status_frame(legacy=True))
        assert probe.food_safe is None
        node_client.emit(UART_TX_CHARACTERISTIC, node_status_frame(food_safe=FOOD_SAFE))

        # A direct connection wins over the relay, for food safe data as for predictions.
        meatnet.handle_advertisement(PROBE_ADDRESS, probe_payload())
        probe_client = FakeClient()
        direct = ProbeSession(meatnet, SERIAL, probe_client)
        await direct.start()
        probe_client.emit(DEVICE_STATUS_CHARACTERISTIC, status_payload(food_safe=SAFE))
        node_client.emit(UART_TX_CHARACTERISTIC, node_status_frame(food_safe=FOOD_SAFE))
        assert probe.food_safe == EXPECTED_SAFE
        await direct.stop()
        assert probe.food_safe == EXPECTED
        await node.stop()
        assert probe.food_safe is None

    asyncio.run(run())
