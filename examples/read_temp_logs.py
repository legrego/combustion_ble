"""This example illustrates how you can read temperature logs."""
import asyncio
from datetime import datetime, timedelta
from signal import SIGINT, SIGTERM

from rich.live import Live
from rich.table import Table

from combustion_ble.device_manager import DeviceManager
from combustion_ble.devices.probe import Probe
from examples.example_utils import configure_logging


def generate_data_points(probe: Probe) -> list[list[tuple[datetime, float]]]:
    data_points: list[list[tuple[datetime, float]]] = []

    for log in probe.temperature_logs:
        # Skip log if start time has not been set
        if not (session_start_time := log.start_time):
            print("skipping logs without start time")
            continue

        count = 0
        for dp in reversed(log.data_points):
            if dp.sequence_num and dp.temperatures:
                second_diff = dp.sequence_num * log.session_information.sample_period / 1000
                data_time_stamp = session_start_time + timedelta(seconds=second_diff)
                data_points.append(
                    [(data_time_stamp, round(temp, 1)) for temp in dp.temperatures.values]
                )
                count += 1
                if count > 20:
                    break

    return data_points


async def main():
    dm = DeviceManager()
    dm.enable_meatnet()
    await dm.init_bluetooth()

    def generate_table():
        probes = dm.get_probes()
        table = Table()
        if probes:
            probe = probes[0]
            probe.update_log_percent()
            table = Table(
                caption="Percent synced: " + str(probe.percent_of_logs_synced)
                if probe.percent_of_logs_synced
                else "0"
            )
            table.add_column("Timestamp")
            table.add_column("Temperature")
            points = generate_data_points(probe)
            for point in points:
                # Only show the first temp reading for now...
                (date, temp) = point[0]
                table.add_row(str(date), str(temp))

        return table

    try:
        with Live(generate_table(), refresh_per_second=1) as live:
            live.console.print(":detective:  Scanning for devices", emoji=True)
            while True:
                await asyncio.sleep(1)
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
