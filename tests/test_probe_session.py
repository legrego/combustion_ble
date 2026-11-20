"""Host-managed sessions, wire data, prediction freshness, and command lifecycle."""

import asyncio
import math
from collections.abc import Callable
from typing import Any

import pytest

from combustion_ble import (
    MeatNet,
    PredictionCommandRejectedError,
    PredictionMode,
    PredictionState,
    PredictionStatus,
    ProbeSession,
)
from combustion_ble.const import (
    DEVICE_STATUS_CHARACTERISTIC,
    UART_RX_CHARACTERISTIC,
    UART_TX_CHARACTERISTIC,
)
from combustion_ble.meatnet import PREDICTION_STALE_TIMEOUT
from combustion_ble.uart.set_prediction import SetPredictionRequest
from combustion_ble.utilities.crc16ccitt import crc16ccitt
from tests.payloads import encode_probe_temperatures, probe_payload

SERIAL = 0x12345678
ADDRESS = "AA:BB:CC:DD:EE:FF"


def status_payload(
    *, state: int = 3, mode: int = 1, type_: int = 1, seconds: int = 600, core: float = 40.0
) -> bytes:
    # Protocol field positions, independently packed from the production parser.
    prediction = (
        state
        | mode << 4
        | type_ << 6
        | 600 << 8  # 60 Celsius target
        | 200 << 18  # 20 Celsius heat start
        | seconds << 28
        | round((core + 20) * 10) << 45
    )
    return (
        bytes(8)
        + encode_probe_temperatures([25.0] * 8)
        + bytes(2)
        + prediction.to_bytes(7, "little")
    )


def response_frame(success: bool = True, type_: int = 5, payload: bytes = b"") -> bytes:
    body = bytes([type_, int(success), len(payload)]) + payload
    return b"\xca\xfe" + crc16ccitt(body).to_bytes(2, "little") + body


class FakeClient:
    """Intentionally has no scanner, connect, or disconnect methods."""

    def __init__(self) -> None:
        self.is_connected = True
        self.callbacks: dict[str, Callable[[Any, bytearray], None]] = {}
        self.writes: list[bytes] = []
        self.stopped: list[str] = []
        self.reply: bytes | None = response_frame()
        self.fail_start: str | None = None
        self.fail_stop: str | None = None
        self.fail_write = False

    async def start_notify(self, char_specifier, callback):
        self.callbacks[char_specifier] = callback
        if char_specifier == self.fail_start:
            raise RuntimeError("subscription failed")

    async def stop_notify(self, char_specifier):
        self.stopped.append(char_specifier)
        if char_specifier == self.fail_stop:
            raise RuntimeError("unsubscribe failed")
        self.callbacks.pop(char_specifier, None)

    async def write_gatt_char(self, char_specifier, data, response=True):
        assert char_specifier == UART_RX_CHARACTERISTIC
        assert response is True
        self.writes.append(bytes(data))
        if self.fail_write:
            raise OSError("write failed")
        if self.reply is not None:
            self.emit(UART_TX_CHARACTERISTIC, self.reply)

    def emit(self, characteristic: str, data: bytes) -> None:
        self.callbacks[characteristic](None, bytearray(data))


def setup_session(*, timeout: float = 1.0):
    clock = [1000.0]
    meatnet = MeatNet(clock=lambda: clock[0])
    meatnet.handle_advertisement(ADDRESS, probe_payload())
    client = FakeClient()
    session = ProbeSession(meatnet, SERIAL, client, command_timeout=timeout)
    return meatnet, client, session, clock


def test_prediction_status_and_freshness():
    async def run():
        meatnet, client, session, clock = setup_session()
        probe = meatnet.probes[SERIAL]
        updates = []
        probe.add_listener(lambda: updates.append(probe.prediction))
        temperatures = probe.temperatures
        await session.start()
        client.emit(DEVICE_STATUS_CHARACTERISTIC, status_payload())
        prediction = probe.prediction
        assert prediction.state is PredictionState.PREDICTING
        assert prediction.set_point_temperature == 60.0
        assert prediction.estimated_core_temperature == 40.0
        assert prediction.seconds_remaining == 600
        assert prediction.percent_through_cook == 50
        assert probe.temperatures == temperatures  # Connected data doesn't replace passive data.
        assert len(updates) == 1
        clock[0] += 1
        client.emit(DEVICE_STATUS_CHARACTERISTIC, status_payload())
        assert len(updates) == 1
        assert probe.prediction_updated_at == clock[0]
        clock[0] += 2
        meatnet.expire()
        assert probe.prediction.seconds_remaining == 598
        clock[0] += PREDICTION_STALE_TIMEOUT
        # Fresh passive advertisements must not refresh prediction freshness.
        meatnet.handle_advertisement(ADDRESS, probe_payload())
        meatnet.expire()
        assert probe.available
        assert probe.prediction is None
        client.emit(DEVICE_STATUS_CHARACTERISTIC, status_payload(seconds=3))
        clock[0] += 5
        meatnet.expire()
        assert probe.prediction is not None
        assert probe.prediction.seconds_remaining == 0
        assert probe.prediction.state is PredictionState.PREDICTING  # Zero isn't a done event.
        await session.stop()
        assert probe.prediction is None
        assert client.is_connected
        assert not client.callbacks

    asyncio.run(run())


@pytest.mark.parametrize(
    ("state", "mode", "type_", "expected"),
    [(2, 1, 1, None), (3, 0, 1, None), (3, 1, 0, None), (3, 1, 1, 131071), (4, 1, 1, 0)],
)
def test_prediction_states(state, mode, type_, expected):
    async def run():
        meatnet, client, session, _ = setup_session()
        await session.start()
        client.emit(
            DEVICE_STATUS_CHARACTERISTIC,
            status_payload(state=state, mode=mode, type_=type_, seconds=131071),
        )
        assert meatnet.probes[SERIAL].prediction.seconds_remaining == expected
        await session.stop()

    asyncio.run(run())


def test_commands_and_rejection():
    async def run():
        meatnet, client, session, _ = setup_session()
        await session.start()
        await session.set_removal_temperature(63.0)
        # Independent complete frame: sync, CRC, command type, length, LE target/mode.
        body = b"\x05\x02\x76\x06"
        assert client.writes[-1] == b"\xca\xfe" + crc16ccitt(body).to_bytes(2, "little") + body
        assert meatnet.probes[SERIAL].prediction is None  # No optimistic prediction updates.
        client.reply = response_frame(False)
        with pytest.raises(PredictionCommandRejectedError):
            await session.set_removal_temperature(60.0)
        client.reply = response_frame()
        await session.cancel_prediction()
        assert client.writes[-1][4:] == b"\x05\x02\x00\x00"
        await session.stop()
        await session.stop()
        with pytest.raises(RuntimeError):
            await session.start()

    asyncio.run(run())


@pytest.mark.parametrize("value", [-0.1, 102.4, math.inf, -math.inf, math.nan])
def test_target_validation(value):
    with pytest.raises(ValueError):
        SetPredictionRequest(value, PredictionMode.TIME_TO_REMOVAL)


def test_target_rounding_and_mode_validation():
    assert SetPredictionRequest(63.3, PredictionMode.TIME_TO_REMOVAL).data[-2:] == b"\x79\x06"
    assert SetPredictionRequest(102.3, PredictionMode.TIME_TO_REMOVAL).data[-2:] == b"\xff\x07"
    with pytest.raises(ValueError):
        SetPredictionRequest(63, PredictionMode.RESERVED)


def test_fragmented_corrupt_unrelated_and_combined_responses():
    async def run():
        _, client, session, _ = setup_session()
        await session.start()
        client.reply = None
        command = asyncio.create_task(session.set_removal_temperature(60))
        await asyncio.sleep(0)
        # Short headers, bad CRC, unrelated frame, and a split response.
        bad = bytearray(response_frame())
        bad[2] ^= 0xFF
        client.emit(UART_TX_CHARACTERISTIC, b"noise" + bad + response_frame(type_=1))
        frame = response_frame()
        client.emit(UART_TX_CHARACTERISTIC, frame[:4])
        assert not command.done()
        client.emit(UART_TX_CHARACTERISTIC, frame[4:] + response_frame(type_=2))
        await command
        await session.stop()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["timeout", "disconnect", "cancel", "write", "stop"])
def test_interrupted_commands_close_session(failure):
    async def run():
        meatnet, client, session, _ = setup_session(timeout=0.01 if failure == "timeout" else 1)
        await session.start()
        client.emit(DEVICE_STATUS_CHARACTERISTIC, status_payload())
        callback = client.callbacks[DEVICE_STATUS_CHARACTERISTIC]
        client.reply = None
        client.fail_write = failure == "write"
        command = asyncio.create_task(session.set_removal_temperature(60))
        await asyncio.sleep(0)
        error: type[BaseException] = ConnectionError
        if failure == "timeout":
            error = TimeoutError
        elif failure == "write":
            error = OSError
        elif failure == "cancel":
            command.cancel()
            error = asyncio.CancelledError
        elif failure == "disconnect":
            client.is_connected = False
            session.disconnected()
        else:
            await session.stop()
        with pytest.raises(error):
            await command
        assert meatnet.probes[SERIAL].prediction is None
        callback(None, bytearray(status_payload()))  # Late callbacks are ignored.
        assert meatnet.probes[SERIAL].prediction is None
        with pytest.raises(ConnectionError):
            await session.cancel_prediction()
        await session.stop()
        assert not session._subscribed

    asyncio.run(run())


def test_serialized_commands_and_exclusive_sessions():
    async def run():
        meatnet, client, session, _ = setup_session()
        await session.start()
        await session.start()
        other = ProbeSession(meatnet, SERIAL, client)
        with pytest.raises(RuntimeError):
            await other.start()
        await other.stop()  # A competing session cannot clear the owner's prediction.
        client.emit(DEVICE_STATUS_CHARACTERISTIC, status_payload())
        client.reply = None
        first = asyncio.create_task(session.set_removal_temperature(60))
        second = asyncio.create_task(session.cancel_prediction())
        await asyncio.sleep(0)
        assert len(client.writes) == 1
        client.emit(UART_TX_CHARACTERISTIC, response_frame())
        await first
        await asyncio.sleep(0)
        assert len(client.writes) == 2
        client.emit(UART_TX_CHARACTERISTIC, response_frame())
        await second
        await session.stop()
        replacement = ProbeSession(meatnet, SERIAL, FakeClient())
        await replacement.start()
        await replacement.stop()

    asyncio.run(run())


def test_subscription_failure_and_cleanup_failure():
    async def run():
        meatnet, client, session, _ = setup_session()
        client.fail_start = DEVICE_STATUS_CHARACTERISTIC
        with pytest.raises(RuntimeError, match="subscription failed"):
            await session.start()
        assert set(client.stopped) == {UART_TX_CHARACTERISTIC, DEVICE_STATUS_CHARACTERISTIC}
        assert not client.callbacks
        assert meatnet.probes[SERIAL]._prediction_session is None
        replacement = ProbeSession(meatnet, SERIAL, client)
        client.fail_start = None
        await replacement.start()
        client.fail_stop = DEVICE_STATUS_CHARACTERISTIC
        with pytest.raises(RuntimeError, match="unsubscribe failed"):
            await replacement.stop()
        assert UART_TX_CHARACTERISTIC not in client.callbacks
        assert meatnet.probes[SERIAL]._prediction_session is replacement
        client.fail_stop = None
        await replacement.stop()
        assert not client.callbacks
        assert meatnet.probes[SERIAL]._prediction_session is None

    asyncio.run(run())


def test_malformed_status_and_disconnected_start():
    async def run():
        meatnet, client, session, _ = setup_session()
        client.is_connected = False
        with pytest.raises(ConnectionError):
            await session.start()
        client.is_connected = True
        await session.start()
        for length in range(30):
            client.emit(DEVICE_STATUS_CHARACTERISTIC, bytes(length))
        assert meatnet.probes[SERIAL].prediction is None
        # Current firmware appends fields after the original 30-byte prefix.
        client.emit(DEVICE_STATUS_CHARACTERISTIC, status_payload() + bytes(100))
        assert meatnet.probes[SERIAL].prediction is not None
        await session.stop()

    asyncio.run(run())


@pytest.mark.parametrize("phase", ["first_subscription", "second_subscription", "failure_cleanup"])
@pytest.mark.parametrize("interrupt", ["timeout", "cancel"])
def test_start_cancellation_propagates_when_cleanup_stalls(phase, interrupt):
    """A host deadline/cancellation must not wait for a second, stalled GATT operation."""

    async def run():
        meatnet, _, _, _ = setup_session()
        entered = asyncio.Event()

        class StallingClient(FakeClient):
            async def start_notify(self, char_specifier, callback):
                await super().start_notify(char_specifier, callback)
                stalled_characteristic = (
                    UART_TX_CHARACTERISTIC
                    if phase == "first_subscription"
                    else DEVICE_STATUS_CHARACTERISTIC
                )
                if char_specifier == stalled_characteristic:
                    entered.set()
                    await asyncio.Event().wait()

            async def stop_notify(self, char_specifier):
                self.stopped.append(char_specifier)
                entered.set()
                await asyncio.Event().wait()

        client = StallingClient()
        if phase == "failure_cleanup":
            client.fail_start = DEVICE_STATUS_CHARACTERISTIC
        session = ProbeSession(meatnet, SERIAL, client)
        # Cancellation must also clear an existing prediction.
        meatnet.handle_prediction_status(
            SERIAL, PredictionStatus.from_bytes(status_payload()[23:30])
        )

        async def start():
            if interrupt == "timeout":
                async with asyncio.timeout(0.01):
                    await session.start()
            else:
                await session.start()

        task = asyncio.create_task(start())
        try:
            async with asyncio.timeout(1):
                await entered.wait()
            if interrupt == "cancel":
                task.cancel()
            # asyncio.wait doesn't itself cancel the task: wait_for would mask the regression
            # with a second cancellation, or hang waiting for cancellation cleanup.
            done, _ = await asyncio.wait({task}, timeout=0.2)
            assert task in done, "Host cancellation remained blocked on unsubscribe cleanup"
            expected = TimeoutError if interrupt == "timeout" else asyncio.CancelledError
            with pytest.raises(expected):
                await task
            probe = meatnet.probes[SERIAL]
            assert probe.prediction is None
            if phase != "failure_cleanup":
                assert not client.stopped  # No Bluetooth cleanup is attempted on cancellation.
            assert probe._prediction_session is session
            replacement = ProbeSession(meatnet, SERIAL, FakeClient())
            with pytest.raises(RuntimeError, match="already has"):
                await replacement.start()
            for callback in client.callbacks.values():
                callback(None, bytearray(status_payload()))
            assert probe.prediction is None
            with pytest.raises(ConnectionError):
                await session.cancel_prediction()
            with pytest.raises(RuntimeError, match="new session"):
                await session.start()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            # The host can disconnect even if notification cleanup stalls, then release ownership
            # without issuing any further GATT operations.
            client.is_connected = False
            await session.stop()
        assert meatnet.probes[SERIAL]._prediction_session is None
        assert not session._subscribed
        replacement = ProbeSession(meatnet, SERIAL, FakeClient())
        await replacement.start()
        await replacement.stop()

    asyncio.run(run())
