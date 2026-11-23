"""Check cooking predictions through a MeatNet repeater, using NodeSession.

Scans for Combustion devices, connects to the best repeater (a Display, Booster, Giant Grill
Gauge, or Engine), and shows the predictions it relays for every probe. It keeps scanning while
connected, because NodeSession only reports probes MeatNet has discovered through advertisements.

It also reads firmware and hardware revisions for the repeater and every probe it relays, and can
set or cancel a removal target on every relayed probe, to check requests sent through the repeater.

The raw UART counters help tell connectivity problems apart: no notifications means the
subscription isn't delivering data; notifications without predictions means the data isn't being
parsed as relayed probe status.

Run with: python -m examples.repeater_predictions [--address ADDRESS] [--duration SECONDS]
    [--target CELSIUS | --cancel]

Inside Home Assistant, the host owns scanning and connections; see the README instead.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from signal import SIGINT, SIGTERM
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from rich.console import Console
from rich.live import Live
from rich.table import Table

from combustion_ble import (
    COMBUSTION_MANUFACTURER_ID,
    MeatNet,
    Node,
    NodeSession,
    plan_connections,
)
from combustion_ble.logger import LOGGER

console = Console()


class CountingClient:
    """Wraps a BleakClient to count the raw UART notifications a NodeSession receives."""

    def __init__(self, client: BleakClient) -> None:
        self._client = client
        self.notifications = 0
        self.bytes_received = 0
        self.first_notification_at: float | None = None

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected

    async def start_notify(self, char_specifier: str, callback: Callable[[Any, bytearray], None]):
        def counting_callback(sender: Any, data: bytearray) -> None:
            self.notifications += 1
            self.bytes_received += len(data)
            if self.first_notification_at is None:
                self.first_notification_at = time.monotonic()
            callback(sender, data)

        await self._client.start_notify(char_specifier, counting_callback)

    async def stop_notify(self, char_specifier: str) -> None:
        await self._client.stop_notify(char_specifier)

    async def write_gatt_char(self, char_specifier, data, response=True) -> None:
        await self._client.write_gatt_char(char_specifier, data, response=response)

    async def read_gatt_char(self, char_specifier: str) -> bytearray:
        return await self._client.read_gatt_char(char_specifier)


def _node_name(node: Node) -> str:
    name = node.product_type.name.replace("_", " ").title()
    return f"{name} {node.serial_number or ''} ({node.address})".replace("  ", " ")


def _choose_node(meatnet: MeatNet, address: str | None) -> Node | None:
    if address is not None:
        return next(
            (node for node in meatnet.nodes.values() if node.address.lower() == address.lower()),
            None,
        )
    # The same ranking a host such as Home Assistant uses: best repeater first.
    repeaters = plan_connections(meatnet).repeaters
    return meatnet.nodes[repeaters[0]] if repeaters else None


def _minutes(seconds: int | None) -> str:
    if seconds is None:
        return "-"
    return f"{seconds // 60}:{seconds % 60:02d}"


def build_table(
    meatnet: MeatNet,
    node: Node,
    client: CountingClient,
    status_counts: dict[int, int],
    started: float,
) -> Table:
    now = time.monotonic()
    table = Table(
        title=f"Predictions via {_node_name(node)}",
        caption=(
            f"Connected {client.is_connected} | {now - started:.0f}s | "
            f"UART notifications {client.notifications} ({client.bytes_received} bytes)"
        ),
    )
    for column in (
        "Probe",
        "Firmware",
        "Hops to node",
        "Statuses",
        "Age",
        "State",
        "Mode",
        "Target",
        "Est. core",
        "Remaining",
        "Progress",
    ):
        table.add_column(column)

    for probe in meatnet.probes.values():
        route = node.relayed_probes.get(probe.serial_number)
        prediction = probe.prediction
        age = (
            "-"
            if probe.prediction_updated_at is None
            else f"{now - probe.prediction_updated_at:.0f}s"
        )
        probe_id = "-" if probe.probe_id is None else probe.probe_id.value + 1
        row = [
            f"{probe.serial_number_string} (ID {probe_id})",
            str(probe.firmware_version or "-"),
            "-" if route is None else str(route.hop_count),
            str(status_counts.get(probe.serial_number, 0)),
            age,
        ]
        if prediction is None:
            row += ["no prediction", "", "", "", "", ""]
        else:
            row += [
                prediction.state.name,
                prediction.mode.name,
                f"{prediction.set_point_temperature:.1f}°C",
                f"{prediction.estimated_core_temperature:.1f}°C",
                _minutes(prediction.seconds_remaining),
                (
                    "-"
                    if prediction.percent_through_cook is None
                    else f"{prediction.percent_through_cook}%"
                ),
            ]
        table.add_row(*row)
    if not meatnet.probes:
        table.add_row("no probes discovered yet", *[""] * 10)
    return table


async def _attempt(description: str, request: Awaitable[None], timeout: float = 35) -> bool:
    try:
        async with asyncio.timeout(timeout):
            await request
    except Exception as exc:
        console.print(f"  [red]{description} failed:[/] {exc!r}")
        return False
    console.print(f"  [green]{description}[/]")
    return True


async def exercise_requests(
    meatnet: MeatNet, node: Node, session: NodeSession, args: argparse.Namespace
) -> None:
    """Read revisions for the repeater and its probes, then optionally set or cancel targets."""
    if await _attempt("Read repeater revisions", session.read_device_information()):
        console.print(f"    firmware {node.firmware_version}, hardware {node.hardware_revision}")
    for serial_number in list(node.relayed_probes):
        probe = meatnet.probes[serial_number]
        name = probe.serial_number_string
        if await _attempt(
            f"Read probe {name} revisions", session.read_probe_information(serial_number)
        ):
            console.print(
                f"    firmware {probe.firmware_version}, hardware {probe.hardware_revision}"
            )
        if args.target is not None:
            await _attempt(
                f"Set probe {name} removal target to {args.target}°C",
                session.set_removal_temperature(serial_number, args.target),
            )
        elif args.cancel:
            await _attempt(
                f"Cancel probe {name} prediction", session.cancel_prediction(serial_number)
            )


async def main(args: argparse.Namespace, stop: asyncio.Event) -> bool:
    meatnet = MeatNet()
    devices: dict[str, BLEDevice] = {}

    def detection_callback(device: BLEDevice, advertisement: AdvertisementData) -> None:
        if COMBUSTION_MANUFACTURER_ID in advertisement.manufacturer_data:
            devices[device.address] = device
            meatnet.handle_advertisement(
                device.address, advertisement.manufacturer_data, advertisement.rssi
            )

    async with BleakScanner(detection_callback=detection_callback):
        console.print(f"Scanning for {args.scan_seconds:.0f}s...")
        try:
            async with asyncio.timeout(args.scan_seconds):
                await stop.wait()
            return False
        except TimeoutError:
            pass
        meatnet.expire()
        for found in meatnet.nodes.values():
            relayed = ", ".join(f"{s:08X}" for s in found.relayed_probes) or "none"
            console.print(f"  Found {_node_name(found)}, RSSI {found.rssi}, relaying: {relayed}")
        for probe in meatnet.probes.values():
            console.print(f"  Found probe {probe.serial_number_string}")

        node = _choose_node(meatnet, args.address)
        if node is None:
            console.print("[red]No repeater found.[/] Is a Display, Booster, Gauge, or Engine on?")
            return False
        console.print(f"Connecting to {_node_name(node)}...")

        session: NodeSession | None = None
        disconnected = asyncio.Event()

        def on_disconnect(_client: BleakClient) -> None:
            if session is not None:
                session.disconnected()
            disconnected.set()

        bleak_client = BleakClient(devices[node.address], disconnected_callback=on_disconnect)
        connect_started = time.monotonic()
        try:
            async with asyncio.timeout(30):
                await bleak_client.connect()
        except Exception as exc:
            console.print(f"[red]Connection failed:[/] {exc!r}")
            return False
        console.print(
            f"[green]Connected[/] in {time.monotonic() - connect_started:.1f}s, "
            f"MTU {bleak_client.mtu_size}"
        )

        client = CountingClient(bleak_client)
        status_counts: dict[int, int] = {}
        last_updated: dict[int, float | None] = {}
        first_updated: dict[int, float] = {}
        dropped = False
        started = time.monotonic()
        try:
            session = NodeSession(meatnet, node.address, client)
            async with asyncio.timeout(30):
                await session.start()
            console.print("Subscribed to the repeater's UART notifications.")
            await exercise_requests(meatnet, node, session, args)

            with Live(
                build_table(meatnet, node, client, status_counts, started), console=console
            ) as live:
                while not disconnected.is_set() and not stop.is_set():
                    if args.duration and time.monotonic() - started >= args.duration:
                        break
                    await asyncio.sleep(0.5)
                    meatnet.expire()
                    for probe in meatnet.probes.values():
                        updated = probe.prediction_updated_at
                        if updated is not None and updated != last_updated.get(probe.serial_number):
                            status_counts[probe.serial_number] = (
                                status_counts.get(probe.serial_number, 0) + 1
                            )
                            first_updated.setdefault(probe.serial_number, updated)
                        last_updated[probe.serial_number] = updated
                    live.update(build_table(meatnet, node, client, status_counts, started))
            dropped = disconnected.is_set()
        finally:
            try:
                if session is not None:
                    async with asyncio.timeout(10):
                        await session.stop()
            except Exception as exc:
                console.print(f"[yellow]Session cleanup failed:[/] {exc!r}")
            finally:
                async with asyncio.timeout(10):
                    await bleak_client.disconnect()
                if session is not None and not bleak_client.is_connected:
                    await session.stop()

    elapsed = time.monotonic() - started
    console.print()
    console.print(f"Ran {elapsed:.0f}s, connection dropped while monitoring: {dropped}")
    console.print(f"UART notifications: {client.notifications} ({client.bytes_received} bytes)")
    for probe in meatnet.probes.values():
        count = status_counts.get(probe.serial_number, 0)
        line = f"  Probe {probe.serial_number_string}: {count} relayed statuses"
        last = last_updated.get(probe.serial_number)
        if count > 1 and last is not None:
            gap = (last - first_updated[probe.serial_number]) / (count - 1)
            line += f", one every {gap:.1f}s on average"
        console.print(line)

    if client.notifications == 0:
        console.print("[red]FAIL:[/] connected, but the repeater sent no UART notifications.")
        return False
    if not status_counts:
        console.print(
            "[red]FAIL:[/] notifications arrived, but none were relayed probe statuses for a "
            "discovered probe. Re-run with --verbose to see what was ignored."
        )
        return False
    console.print("[green]PASS:[/] predictions are arriving through the repeater.")
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--address", help="Repeater address (default: best one found)")
    parser.add_argument("--scan-seconds", type=float, default=10.0, help="Initial scan length")
    parser.add_argument(
        "--duration", type=float, default=0, help="Seconds to stay connected (default: until ^C)"
    )
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument(
        "--target", type=float, help="Set this removal target (Celsius) on every relayed probe"
    )
    commands.add_argument(
        "--cancel", action="store_true", help="Cancel the prediction on every relayed probe"
    )
    parser.add_argument("--verbose", action="store_true", help="Show combustion_ble debug logs")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    if args.verbose:
        LOGGER.setLevel(logging.DEBUG)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    stop = asyncio.Event()
    main_task = loop.create_task(main(args, stop))

    def on_signal() -> None:
        # The first ^C ends monitoring and prints the summary; a second one aborts.
        if stop.is_set():
            main_task.cancel()
        stop.set()

    for signal in (SIGINT, SIGTERM):
        loop.add_signal_handler(signal, on_signal)
    passed = False
    try:
        passed = loop.run_until_complete(main_task)
    except asyncio.CancelledError:
        pass
    finally:
        loop.close()
    raise SystemExit(0 if passed else 1)
