"""This example illustrates how you can read prediction data."""
import asyncio
from signal import SIGINT, SIGTERM

from rich.live import Live
from rich.table import Table

from combustion_ble.device_manager import DeviceManager
from examples.example_utils import configure_logging, format_device_name


async def main():
    dm = DeviceManager()
    dm.enable_meatnet()
    await dm.init_bluetooth()

    def generate_table():
        table = Table()
        table.add_column("Device")
        table.add_column("Last update time")
        table.add_column("State")
        table.add_column("Prediction")
        table.add_column("Food Safety")

        probes = dm.get_probes()
        for probe in probes:
            name = format_device_name(probe)
            state = "N/A"
            prediction = "N/A"
            if probe.prediction_info:
                state = probe.prediction_info.prediction_state.to_string()
                prediction = str(probe._prediction_info)
            table.add_row(name, str(probe.last_update_time), state, prediction)

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
