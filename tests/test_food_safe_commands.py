"""SafeCook command encoding, acknowledgement matching, and failure lifecycle."""

import asyncio
from dataclasses import asdict, replace
from decimal import Decimal

import pytest

from combustion_ble import (
    FoodSafeMode,
    FoodSafeProgram,
    IntegratedProduct,
    RequestRejectedError,
    Serving,
    SimplifiedProduct,
)
from combustion_ble.ble_data.food_safe_data import FoodSafeData
from combustion_ble.const import DEVICE_STATUS_CHARACTERISTIC, UART_TX_CHARACTERISTIC
from combustion_ble.uart import ConfigureFoodSafeResponse, ResetFoodSafeResponse
from combustion_ble.uart.response_from_data import response_from_data
from combustion_ble.utilities.crc16ccitt import crc16ccitt
from tests.payloads import encode_food_safe_data, encode_food_safe_status
from tests.test_node_requests import acknowledge
from tests.test_node_requests import response_frame as node_response
from tests.test_node_requests import start
from tests.test_node_session import node_status_frame
from tests.test_probe_session import (
    response_frame,
    settle,
    setup_session,
    status_payload,
)

SERIAL = 0x12345678
PROGRAM = FoodSafeProgram(
    mode=FoodSafeMode.INTEGRATED,
    product=IntegratedProduct.MEATS,
    serving=Serving.SERVED_IMMEDIATELY,
    threshold_temperature=54.4,
    z_value=5.6,
    reference_temperature=60,
    d_value=3.5,
    target_log_reduction=6.5,
)
PAYLOAD = encode_food_safe_data()


def test_encoding_and_rounding():
    assert PROGRAM.to_bytes() == PAYLOAD
    decoded = FoodSafeData.from_bytes(PROGRAM.to_bytes())
    assert decoded.d_value == 3.5
    assert decoded.target_log_reduction == 6.5
    limits = replace(
        PROGRAM,
        product=IntegratedProduct.CUSTOM,
        serving=Serving.COOKED_AND_CHILLED,
        threshold_temperature=409.55,
        z_value=409.55,
        reference_temperature=409.55,
        d_value=409.55,
        target_log_reduction=25.5,
    )
    # All four decimals and the log target fill their bits; the top nibble is reserved.
    assert limits.to_bytes() == b"\xf9\x3f" + b"\xff" * 7 + b"\x0f"
    rounded = FoodSafeData.from_bytes(
        replace(PROGRAM, z_value=5.63, target_log_reduction=6.56).to_bytes()
    )
    assert rounded.z_value == 5.65
    assert rounded.target_log_reduction == 6.6
    simplified = replace(
        PROGRAM, mode=FoodSafeMode.SIMPLIFIED, product=SimplifiedProduct.FISH_AND_SHELLFISH
    )
    assert (
        FoodSafeData.from_bytes(simplified.to_bytes()).product
        is SimplifiedProduct.FISH_AND_SHELLFISH
    )


@pytest.mark.parametrize(
    "field",
    [
        "threshold_temperature",
        "z_value",
        "reference_temperature",
        "d_value",
        "target_log_reduction",
    ],
)
@pytest.mark.parametrize(
    "value",
    [
        -0.01,
        409.56,
        float("nan"),
        float("inf"),
        -float("inf"),
        None,
        "3.5",
        [],
        {},
        complex(1, 2),
        True,
    ],
)
def test_invalid_numbers(field, value):
    with pytest.raises(ValueError):
        replace(PROGRAM, **{field: value}).to_bytes()


@pytest.mark.parametrize(
    "changes",
    [
        {"mode": 7},
        {"product": 1024},
        {"product": 23},  # Reserved integrated category.
        {"product": SimplifiedProduct.ANY_POULTRY},  # IntEnums compare equal across types.
        {"mode": FoodSafeMode.SIMPLIFIED},  # Integrated product in simplified mode.
        {"serving": 7},
        {"target_log_reduction": 25.51},
    ],
)
def test_invalid_choices(changes):
    with pytest.raises(ValueError):
        replace(PROGRAM, **changes).to_bytes()


@pytest.mark.parametrize("product", [3, *range(5, 13)])
def test_legacy_program_round_trip_with_changed_serving(product):
    decoded = FoodSafeData.from_bytes(encode_food_safe_data(product=product))
    program = FoodSafeProgram(**asdict(decoded))
    changed = replace(program, serving=Serving.COOKED_AND_CHILLED)
    assert changed.to_bytes() == encode_food_safe_data(product=product, serving=1)


@pytest.mark.parametrize(
    "field", ["threshold_temperature", "z_value", "reference_temperature", "d_value"]
)
@pytest.mark.parametrize(
    ("value", "expected"), [(0.024, 0), (0.025, 0.05), (0.075, 0.1), (5.625, 5.65)]
)
def test_decimal_halfway_rounding(field, value, expected):
    decoded = FoodSafeData.from_bytes(replace(PROGRAM, **{field: value}).to_bytes())
    assert getattr(decoded, field) == expected


@pytest.mark.parametrize(
    ("value", "expected"), [(6.249, 6.2), (6.25, 6.3), (6.251, 6.3), (Decimal("6.25"), 6.3)]
)
def test_log_target_halfway_rounding(value, expected):
    assert (
        FoodSafeData.from_bytes(
            replace(PROGRAM, target_log_reduction=value).to_bytes()
        ).target_log_reduction
        == expected
    )


@pytest.mark.parametrize("node", [False, True])
@pytest.mark.parametrize("value", [0, 0.001, 0.024])
def test_configuration_cannot_encode_off(node, value):
    async def run():
        if node:
            _, client, session = await start()
        else:
            _, client, session, _ = setup_session()
            await session.start()
        program = FoodSafeProgram(
            FoodSafeMode.SIMPLIFIED,
            SimplifiedProduct.DEFAULT,
            Serving.SERVED_IMMEDIATELY,
            value,
            value,
            value,
            value,
            value,
        )
        args = (SERIAL,) if node else ()
        with pytest.raises(ValueError, match="clear_food_safe"):
            await session.configure_food_safe(*args, program)
        assert not client.writes
        if not node:
            client.reply = response_frame(type_=7)
        await session.clear_food_safe(*args)
        assert client.writes[-1][10 if node else 6 :] == (
            SERIAL.to_bytes(4, "little") if node else b""
        ) + bytes(10)
        await session.stop()

    asyncio.run(run())


@pytest.mark.parametrize("type_", [5, 7, 8])
@pytest.mark.parametrize("malformed", ["success", "payload"])
def test_malformed_node_acknowledgement_fails_promptly(type_, malformed, caplog):
    async def run():
        _, client, session = await start(None, timeout=30)
        request = {
            5: lambda: session.set_removal_temperature(SERIAL, 60),
            7: lambda: session.configure_food_safe(SERIAL, PROGRAM),
            8: lambda: session.reset_food_safe(SERIAL),
        }[type_]
        command = asyncio.create_task(request())
        await settle()
        frame = bytearray(
            node_response(
                type_, client.requests[-1][1], payload=b"bad" if malformed == "payload" else b""
            )
        )
        if malformed == "success":
            frame[13] = 2
            frame[2:4] = crc16ccitt(frame[4:]).to_bytes(2, "little")
        client.emit(UART_TX_CHARACTERISTIC, frame)
        with pytest.raises(ValueError, match="Malformed node response"):
            await asyncio.wait_for(command, 0.2)
        assert "Malformed node response" in caplog.text
        assert not session._pending
        client.responder = acknowledge
        await session.reset_food_safe(SERIAL)
        await session.stop()

    asyncio.run(run())


@pytest.mark.parametrize("node", [False, True])
def test_configuration_clear_reset_and_reported_state(node):
    async def run():
        if node:
            meatnet, client, session = await start()
        else:
            meatnet, client, session, _ = setup_session()
            await session.start()
        probe = meatnet.probes[SERIAL]
        args = (SERIAL,) if node else ()
        reported = encode_food_safe_data() + encode_food_safe_status()
        if node:
            client.emit(UART_TX_CHARACTERISTIC, node_status_frame(food_safe=reported))
        else:
            client.emit(DEVICE_STATUS_CHARACTERISTIC, status_payload(food_safe=reported))
        before = probe.food_safe
        for method, type_, payload in (
            (lambda: session.configure_food_safe(*args, PROGRAM), 7, PAYLOAD),
            (lambda: session.clear_food_safe(*args), 7, bytes(10)),
            (lambda: session.reset_food_safe(*args), 8, b""),
        ):
            if not node:
                client.reply = response_frame(type_=type_)
            await method()
            frame = client.writes[-1]
            assert frame[:2] == b"\xca\xfe"
            assert int.from_bytes(frame[2:4], "little") == crc16ccitt(frame[4:])
            expected = SERIAL.to_bytes(4, "little") + payload if node else payload
            assert frame[4] == type_
            assert frame[10 if node else 6 :] == expected
            assert frame[9 if node else 5] == len(expected)
            assert probe.food_safe is before  # Commands cannot invent reported state.
        writes = len(client.writes)
        with pytest.raises(ValueError):
            await session.configure_food_safe(*args, replace(PROGRAM, d_value=-1))
        with pytest.raises(ValueError, match="d_value must be numeric"):
            await session.configure_food_safe(*args, replace(PROGRAM, d_value=None))
        assert len(client.writes) == writes
        if node:
            for serial in (-1, 1 << 32):
                with pytest.raises(ValueError):
                    await session.configure_food_safe(serial, PROGRAM)
            client.responder = lambda t, r, _: node_response(t, r, success=False)
        else:
            client.reply = response_frame(False, type_=7)
        with pytest.raises(RequestRejectedError):
            await session.clear_food_safe(*args)
        if node:
            client.responder = acknowledge
        else:
            client.reply = response_frame(type_=8)
        await session.reset_food_safe(*args)  # Rejection leaves the session usable.
        await session.stop()
        with pytest.raises(ConnectionError):
            await session.configure_food_safe(*args, PROGRAM)

    asyncio.run(run())


@pytest.mark.parametrize("node", [False, True])
def test_matching_and_malformed_acknowledgements(node):
    async def run():
        if node:
            _, client, session = await start(None)
        else:
            _, client, session, _ = setup_session()
            await session.start()
            client.reply = None
        command = asyncio.create_task(
            session.configure_food_safe(SERIAL, PROGRAM)
            if node
            else session.configure_food_safe(PROGRAM)
        )
        await settle()

        def reply(type_, payload=b"", request_id=None):
            return (
                node_response(type_, request_id or client.writes[-1][5:9], payload=payload)
                if node
                else response_frame(type_=type_, payload=payload)
            )

        client.emit(UART_TX_CHARACTERISTIC, reply(5) + reply(8))
        if node:
            client.emit(UART_TX_CHARACTERISTIC, reply(7, request_id=bytes(4)))
        else:
            client.emit(UART_TX_CHARACTERISTIC, reply(7, b"unexpected"))
            bad_success = bytearray(reply(7))
            bad_success[5] = 2
            bad_success[2:4] = crc16ccitt(bad_success[4:]).to_bytes(2, "little")
            client.emit(UART_TX_CHARACTERISTIC, bad_success)
        await settle()
        assert not command.done()
        good = reply(7)
        bad_crc = bytearray(good)
        bad_crc[2] ^= 0xFF
        client.emit(UART_TX_CHARACTERISTIC, b"noise" + bad_crc + good[:4])
        assert not command.done()
        client.emit(UART_TX_CHARACTERISTIC, good[4:])
        await command
        await session.stop()

    asyncio.run(run())


@pytest.mark.parametrize("node", [False, True])
@pytest.mark.parametrize("failure", ["timeout", "cancel", "disconnect", "write"])
def test_command_failure_lifecycle(node, failure):
    async def run():
        timeout = 0.01 if failure == "timeout" else 1
        if node:
            _, client, session = await start(None, timeout=timeout)
        else:
            _, client, session, _ = setup_session(timeout=timeout)
            await session.start()
            client.reply = None
        client.fail_write = failure == "write"
        command = asyncio.create_task(
            session.configure_food_safe(SERIAL, PROGRAM)
            if node
            else session.configure_food_safe(PROGRAM)
        )
        await settle()
        error = {
            "timeout": TimeoutError,
            "cancel": asyncio.CancelledError,
            "disconnect": ConnectionError,
            "write": OSError,
        }[failure]
        if failure == "cancel":
            command.cancel()
        elif failure == "disconnect":
            session.disconnected()
        with pytest.raises(error):
            await command
        if node and failure != "disconnect":
            client.fail_write = False
            client.responder = acknowledge
            await session.reset_food_safe(SERIAL)
        else:
            with pytest.raises(ConnectionError):
                await (session.reset_food_safe(SERIAL) if node else session.reset_food_safe())
        await session.stop()

    asyncio.run(run())


def test_uart_response_dispatch():
    assert isinstance(response_from_data(response_frame(type_=7)), ConfigureFoodSafeResponse)
    assert isinstance(response_from_data(response_frame(type_=8)), ResetFoodSafeResponse)


@pytest.mark.parametrize("node", [False, True])
def test_prediction_and_food_safe_commands_together(node):
    async def run():
        if node:
            _, client, session = await start(None)
        else:
            _, client, session, _ = setup_session()
            await session.start()
            client.reply = None
        args = (SERIAL,) if node else ()
        prediction = asyncio.create_task(session.set_removal_temperature(*args, 60))
        configure = asyncio.create_task(session.configure_food_safe(*args, PROGRAM))
        reset = asyncio.create_task(session.reset_food_safe(*args))
        await settle()
        if node:
            assert len(client.requests) == 3
            # Reply out of order; each response must complete only its own request.
            for type_, request_id, _ in reversed(client.requests):
                client.emit(UART_TX_CHARACTERISTIC, node_response(type_, request_id))
            await asyncio.gather(prediction, configure, reset)
        else:
            assert len(client.writes) == 1
            client.emit(UART_TX_CHARACTERISTIC, response_frame(type_=7))
            await settle()
            assert not prediction.done()
            for task, type_ in ((prediction, 5), (configure, 7), (reset, 8)):
                assert client.writes[-1][4] == type_
                client.emit(UART_TX_CHARACTERISTIC, response_frame(type_=type_))
                await task
                await settle()
            assert len(client.writes) == 3
        await session.stop()

    asyncio.run(run())
