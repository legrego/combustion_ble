"""Requests sent through a MeatNet node: framing, response matching, and failure handling."""

import asyncio
from collections.abc import Callable

import pytest

from combustion_ble import (
    FirmwareVersion,
    NodeSession,
    PredictionCommandRejectedError,
    RequestRejectedError,
)
from combustion_ble.const import UART_RX_CHARACTERISTIC, UART_TX_CHARACTERISTIC
from combustion_ble.utilities.crc16ccitt import crc16ccitt
from tests.test_node_session import (
    NODE_ADDRESS,
    OTHER_SERIAL,
    SERIAL,
    node_status_frame,
    setup_meatnet,
)
from tests.test_probe_session import FakeClient


def response_frame(
    type_: int, request_id: bytes, *, success: bool = True, payload: bytes = b""
) -> bytes:
    """Build a node response frame, packed independently from the session."""
    body = (
        bytes([type_ | 0x80])
        + request_id
        + (0x0BADF00D).to_bytes(4, "little")
        + bytes([int(success), len(payload)])
        + payload
    )
    return b"\xca\xfe" + crc16ccitt(body).to_bytes(2, "little") + body


Responder = Callable[[int, bytes, bytes], bytes | None]


def acknowledge(type_: int, request_id: bytes, payload: bytes) -> bytes | None:
    return response_frame(type_, request_id)


class NodeClient(FakeClient):
    """Replies to each request written to the node using ``responder``."""

    def __init__(self, responder: Responder | None = acknowledge) -> None:
        super().__init__()
        self.responder = responder
        self.requests: list[tuple[int, bytes, bytes]] = []

    async def write_gatt_char(self, char_specifier, data, response=True):
        assert char_specifier == UART_RX_CHARACTERISTIC
        assert response is True
        data = bytes(data)
        self.writes.append(data)
        if self.fail_write:
            raise OSError("write failed")
        # Validate the request frame independently of the session's encoder.
        assert data[:2] == b"\xca\xfe"
        assert int.from_bytes(data[2:4], "little") == crc16ccitt(data[4:])
        assert data[9] == len(data) - 10
        request = (data[4], data[5:9], data[10:])
        self.requests.append(request)
        if self.responder is not None:
            reply = self.responder(*request)
            if reply is not None:
                self.emit(UART_TX_CHARACTERISTIC, reply)


async def settle() -> None:
    """Let queued request and write tasks run until they block."""
    for _ in range(5):
        await asyncio.sleep(0)


async def start(responder: Responder | None = acknowledge, *, timeout: float = 1.0):
    meatnet, _ = setup_meatnet()
    client = NodeClient(responder)
    session = NodeSession(meatnet, NODE_ADDRESS, client, command_timeout=timeout)
    await session.start()
    return meatnet, client, session


def test_set_and_cancel_prediction():
    async def run():
        meatnet, client, session = await start()
        await session.set_removal_temperature(SERIAL, 63.0)
        type_, request_id, payload = client.requests[-1]
        assert type_ == 0x05
        assert request_id != bytes(4)
        assert payload == SERIAL.to_bytes(4, "little") + b"\x76\x06"
        await session.cancel_prediction(OTHER_SERIAL)
        assert client.requests[-1][2] == OTHER_SERIAL.to_bytes(4, "little") + b"\x00\x00"
        assert client.requests[-1][1] != request_id
        assert meatnet.probes[SERIAL].prediction is None  # No optimistic prediction updates.
        await session.stop()

    asyncio.run(run())


def test_rejection_and_validation():
    async def run():
        _, client, session = await start(
            lambda type_, request_id, _: response_frame(type_, request_id, success=False)
        )
        with pytest.raises(PredictionCommandRejectedError):
            await session.set_removal_temperature(SERIAL, 60)
        assert isinstance(PredictionCommandRejectedError(), RequestRejectedError)
        writes = len(client.writes)
        for serial, celsius in ((SERIAL, 102.4), (SERIAL, -1), (-1, 60), (1 << 32, 60)):
            with pytest.raises(ValueError):
                await session.set_removal_temperature(serial, celsius)
        assert len(client.writes) == writes
        with pytest.raises(ValueError):
            NodeSession(session._meatnet, NODE_ADDRESS, client, command_timeout=0)
        await session.stop()

    asyncio.run(run())


def test_responses_match_by_request_id_and_type():
    async def run():
        meatnet, client, session = await start(None)
        first = asyncio.create_task(session.set_removal_temperature(SERIAL, 60))
        second = asyncio.create_task(session.cancel_prediction(OTHER_SERIAL))
        await settle()
        assert len(client.requests) == 2
        first_id, second_id = client.requests[0][1], client.requests[1][1]
        # Another app's response, the wrong type for our ID, and a corrupt frame are ignored.
        bad = bytearray(response_frame(0x05, first_id))
        bad[2] ^= 0xFF
        client.emit(
            UART_TX_CHARACTERISTIC,
            response_frame(0x05, b"\x01\x02\x03\x04") + response_frame(0x46, first_id) + bad,
        )
        await settle()
        assert not first.done() and not second.done()
        # Responses arrive out of order, split across notifications and mixed with status.
        frame = response_frame(0x05, second_id, success=False) + node_status_frame(seconds=60)
        client.emit(UART_TX_CHARACTERISTIC, frame[:12])
        client.emit(UART_TX_CHARACTERISTIC, frame[12:])
        with pytest.raises(PredictionCommandRejectedError):
            await second
        assert meatnet.probes[SERIAL].prediction.seconds_remaining == 60
        assert not first.done()
        client.emit(UART_TX_CHARACTERISTIC, response_frame(0x05, first_id))
        await first
        assert not session._pending
        await session.stop()

    asyncio.run(run())


@pytest.mark.parametrize("failure", ["timeout", "cancel", "write"])
def test_failed_request_keeps_session_running(failure):
    async def run():
        meatnet, client, session = await start(None, timeout=0.01 if failure == "timeout" else 1)
        client.fail_write = failure == "write"
        command = asyncio.create_task(session.set_removal_temperature(SERIAL, 60))
        await settle()
        error: type[BaseException] = TimeoutError
        if failure == "cancel":
            command.cancel()
            error = asyncio.CancelledError
        elif failure == "write":
            error = OSError
        with pytest.raises(error):
            await command
        assert not session._pending
        # A late response to the failed request is ignored, and the session keeps working.
        client.emit(UART_TX_CHARACTERISTIC, response_frame(0x05, client.writes[-1][5:9]))
        client.emit(UART_TX_CHARACTERISTIC, node_status_frame(seconds=60))
        assert meatnet.probes[SERIAL].prediction.seconds_remaining == 60
        client.fail_write = False
        client.responder = acknowledge
        await session.cancel_prediction(SERIAL)
        await session.stop()

    asyncio.run(run())


@pytest.mark.parametrize("close", ["disconnect", "stop"])
def test_closing_fails_pending_requests(close):
    async def run():
        _, client, session = await start(None)
        commands = [
            asyncio.create_task(session.set_removal_temperature(SERIAL, 60)),
            asyncio.create_task(session.read_probe_information(SERIAL)),
        ]
        await settle()
        if close == "disconnect":
            client.is_connected = False
            session.disconnected()
        else:
            await session.stop()
        for command in commands:
            with pytest.raises(ConnectionError):
                await command
        with pytest.raises(ConnectionError):
            await session.cancel_prediction(SERIAL)
        await session.stop()

    asyncio.run(run())


def revision_responder(firmware: bytes, hardware: bytes, serial: int = SERIAL) -> Responder:
    def respond(type_: int, request_id: bytes, payload: bytes) -> bytes:
        assert payload == SERIAL.to_bytes(4, "little")
        value = {0x46: firmware.ljust(20, b"\x00"), 0x47: hardware.ljust(16, b"\x00")}[type_]
        return response_frame(type_, request_id, payload=serial.to_bytes(4, "little") + value)

    return respond


def test_read_probe_information():
    async def run():
        meatnet, client, session = await start(revision_responder(b"v1.4.2", b"v3"))
        probe = meatnet.probes[SERIAL]
        updates = []
        probe.add_listener(
            lambda: updates.append((probe.firmware_version, probe.hardware_revision))
        )
        await session.read_probe_information(SERIAL)
        assert [request[0] for request in client.requests] == [0x46, 0x47]
        assert probe.firmware_version == FirmwareVersion.parse("v1.4.2")
        assert probe.firmware_version.minor == 4
        assert probe.hardware_revision == "v3"
        assert len(updates) == 2
        assert meatnet.nodes[NODE_ADDRESS].firmware_version is None  # Only the probe changes.
        with pytest.raises(KeyError):
            await session.read_probe_information(0x01020304)  # Undiscovered probe.
        await session.stop()
        assert probe.firmware_version.raw == "v1.4.2"

    asyncio.run(run())


def test_probe_information_failures():
    async def run():
        meatnet, client, session = await start(
            lambda type_, request_id, _: response_frame(type_, request_id, success=False)
        )
        with pytest.raises(RequestRejectedError, match="12345678"):
            await session.read_probe_information(SERIAL)
        client.responder = revision_responder(b"v1.0.0", b"v1", serial=OTHER_SERIAL)
        with pytest.raises(ValueError):
            await session.read_probe_information(SERIAL)
        assert meatnet.probes[SERIAL].firmware_version is None
        await session.stop()

    asyncio.run(run())


@pytest.mark.parametrize("close", ["disconnect", "stop"])
def test_closing_interrupts_requests_blocked_on_writes(close):
    """A stalled write holds the write lock; closing must fail both waiting requests."""

    async def run():
        meatnet, _ = setup_meatnet()

        class StallingClient(NodeClient):
            async def write_gatt_char(self, char_specifier, data, response=True):
                self.writes.append(bytes(data))
                await asyncio.Event().wait()

        client = StallingClient()
        session = NodeSession(meatnet, NODE_ADDRESS, client, command_timeout=5)
        await session.start()
        writing = asyncio.create_task(session.set_removal_temperature(SERIAL, 60))
        queued = asyncio.create_task(session.read_probe_information(SERIAL))
        await settle()
        assert len(client.writes) == 1  # The second request is waiting for the write lock.
        if close == "disconnect":
            client.is_connected = False
            session.disconnected()
        else:
            await session.stop()
        done, _ = await asyncio.wait({writing, queued}, timeout=0.5)
        assert done == {writing, queued}, "Requests stayed blocked after the session closed"
        for request in (writing, queued):
            with pytest.raises(ConnectionError):
                await request
        assert len(client.writes) == 1
        assert not session._pending
        assert not session._write_lock.locked()
        await session.stop()

    asyncio.run(run())
