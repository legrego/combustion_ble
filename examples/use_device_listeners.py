"""This example illustrates how you can use the device listener interfaces to respond to changes."""

import asyncio
from signal import SIGINT, SIGTERM

from rich.console import Console

from combustion_ble import VirtualTemperatures
from combustion_ble.device_manager import DeviceManager
from combustion_ble.devices import Probe
from examples._example_utils import (
    configure_logging,
    format_device_name,
    format_virtual_temperatures,
)


async def main():
    console = Console()
    console.log(":detective: Scanning for devices", emoji=True)

    dm = DeviceManager()
    dm.enable_meatnet()
    await dm.init_bluetooth()

    remove_listeners = []

    def create_temperature_listener(probe: Probe):
        def listener(virtual_temps: VirtualTemperatures):
            console.log(
                f"{format_device_name(probe)}; Temperatures: {format_virtual_temperatures(virtual_temps)}"
            )

        return listener

    def listener(added_devices, removed_devices):
        for device in added_devices:
            console.log(f"Discovered device: {format_device_name(device)}")
            if isinstance(device, Probe):
                remove_listeners.append(
                    device.add_virtual_temperatures_listener(create_temperature_listener(device))
                )

    dm.add_device_listener(listener)

    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        try:
            # Unregister event listeners
            for rm in remove_listeners:
                rm()
        finally:
            # Shutdown Device Manager
            await dm.async_stop()


if __name__ == "__main__":
    configure_logging(log_level="INFO")
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    main_task = asyncio.ensure_future(main())
    for signal in [SIGINT, SIGTERM]:
        loop.add_signal_handler(signal, main_task.cancel)
    try:
        loop.run_until_complete(main_task)
    finally:
        loop.close()
