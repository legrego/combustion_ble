"""Show every Combustion device in range, using advertisements only.

This example owns a bleak scanner and feeds its advertisements to a MeatNet. Inside Home Assistant
you would not create a scanner; register a Bluetooth callback instead and pass each
BluetoothServiceInfoBleak to MeatNet.handle_service_info().

Run with: python -m examples.passive_meatnet
"""

import asyncio
from signal import SIGINT, SIGTERM

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from rich.live import Live
from rich.table import Table

from combustion_ble import COMBUSTION_MANUFACTURER_ID, MeatNet, ProbeMode


def _format(value: float | None, unit: str = "°C") -> str:
    return "-" if value is None else f"{value:.1f}{unit}"


def build_table(meatnet: MeatNet) -> Table:
    table = Table(title="Combustion devices (advertisements only)")
    table.add_column("Device")
    table.add_column("Available")
    table.add_column("Source")
    table.add_column("Readings")

    for probe in meatnet.probes.values():
        if probe.mode == ProbeMode.INSTANT_READ:
            readings = f"Instant read {_format(probe.instant_read_celsius)}"
        else:
            readings = (
                f"Core {_format(probe.core_temperature)} | "
                f"Surface {_format(probe.surface_temperature)} | "
                f"Ambient {_format(probe.ambient_temperature)}"
            )
        probe_id = "-" if probe.probe_id is None else probe.probe_id.value + 1
        battery = "-" if probe.battery_status is None else probe.battery_status.name.lower()
        source = "direct" if probe.source_hop_count is None else f"{probe.source_hop_count} hop(s)"
        table.add_row(
            f"Probe {probe.serial_number_string} (ID {probe_id})",
            str(probe.available),
            source,
            f"{readings} | battery {battery}",
        )

    for gauge in meatnet.gauges.values():
        table.add_row(
            f"Gauge {gauge.serial_number}",
            str(gauge.available),
            "direct",
            f"{_format(gauge.temperature)} | low battery {gauge.low_battery}",
        )

    for node in meatnet.nodes.values():
        name = node.product_type.name.replace("_", " ").title()
        relayed = ", ".join(f"{serial:08X}" for serial in node.relayed_probes) or "none"
        table.add_row(
            f"{name} {node.serial_number or node.address}",
            str(node.available),
            f"RSSI {node.rssi}",
            f"Relaying: {relayed}",
        )

    return table


async def main() -> None:
    meatnet = MeatNet()
    meatnet.add_device_listener(lambda device: print(f"Discovered {device!r}"))

    def detection_callback(device: BLEDevice, advertisement: AdvertisementData) -> None:
        if COMBUSTION_MANUFACTURER_ID in advertisement.manufacturer_data:
            meatnet.handle_advertisement(
                device.address, advertisement.manufacturer_data, advertisement.rssi
            )

    async with BleakScanner(detection_callback=detection_callback):
        with Live(build_table(meatnet), refresh_per_second=4) as live:
            while True:
                await asyncio.sleep(0.5)
                meatnet.expire()
                live.update(build_table(meatnet))


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    main_task = loop.create_task(main())
    for signal in (SIGINT, SIGTERM):
        loop.add_signal_handler(signal, main_task.cancel)
    try:
        loop.run_until_complete(main_task)
    except asyncio.CancelledError:
        pass
    finally:
        loop.close()
