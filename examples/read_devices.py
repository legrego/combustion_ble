"""This example illustrates how you can enumerate all discovered devices."""
import asyncio
import logging
from signal import SIGINT, SIGTERM

from rich.live import Live
from rich.logging import RichHandler
from rich.table import Table

from combustion_ble.device_manager import DeviceManager
from combustion_ble.devices.probe import Probe
from combustion_ble.logger import LOGGER
from examples.example_utils import (
    configure_logging,
    format_connection_state,
    format_device_name,
    format_temperatures,
)


async def main():
    dm = DeviceManager()
    dm.enable_meatnet()
    await dm.init_bluetooth()

    def generate_table():
        table = Table()
        table.add_column("Device")
        table.add_column("State")
        table.add_column("Last update time")
        table.add_column("Details")

        devices = dm.get_devices()
        for device in devices:
            name = format_device_name(device)
            connection = format_connection_state(device.connection_state)
            if isinstance(device, Probe):
                temperatures = format_temperatures(device.current_temperatures)
                table.add_row(name, connection, str(device.last_update_time), temperatures)
            else:
                details = f"fw: {device.firmware_version} hw: {device.hardware_revision}"
                table.add_row(name, connection, str(device.last_update_time), details)

        return table

    try:
        with Live(generate_table(), refresh_per_second=4) as live:
            live.console.print(":detective:  Scanning for devices", emoji=True)
            while True:
                await asyncio.sleep(0.25)
                live.update(generate_table())
    except asyncio.CancelledError:
        await dm.async_stop()


if __name__ == "__main__":
    configure_logging()
    loop = asyncio.get_event_loop()
    main_task = asyncio.ensure_future(main())
    for signal in [SIGINT, SIGTERM]:
        loop.add_signal_handler(signal, main_task.cancel)
    try:
        loop.run_until_complete(main_task)
    finally:
        loop.close()
