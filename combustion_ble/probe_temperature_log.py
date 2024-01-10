import asyncio
from datetime import datetime, timedelta
from typing import Optional

from combustion_ble.logged_probe_data_count import LoggedProbeDataPoint
from combustion_ble.uart.session_info import SessionInformation


class ProbeTemperatureLog:
    ACCUMULATOR_STABILIZATION_TIME = 0.2
    ACCUMULATOR_MAX = 500

    def __init__(self, session_info: SessionInformation):
        self.session_information = session_info
        self.data_points_dict: dict[int, LoggedProbeDataPoint] = {}
        self.data_point_accumulator = set[LoggedProbeDataPoint]()
        self.accumulator_timer: Optional[asyncio.Task] = None
        self.start_time: Optional[datetime] = None

    @property
    def data_points(self) -> list[LoggedProbeDataPoint]:
        """Return a list of data points, sorted by sequence number (oldest -> newest)."""
        return sorted(
            list(self.data_points_dict.values()),
            key=lambda x: x.sequence_num if x.sequence_num else -1,
        )

    def missing_range(self, sequence_range_start: int, sequence_range_end: int):
        lower_bound = None
        for search in range(sequence_range_start, sequence_range_end + 1):
            if search not in self.data_points_dict:
                lower_bound = search
                break

        if lower_bound is not None:
            upper_bound = None
            if lower_bound < sequence_range_end:
                for search in reversed(range(lower_bound + 1, sequence_range_end + 1)):
                    if search not in self.data_points_dict:
                        upper_bound = search
                        break

            if upper_bound is not None:
                return lower_bound, upper_bound
            else:
                return lower_bound, sequence_range_end

        return None

    def logs_in_range(self, sequence_numbers) -> int:
        records = 0
        if not self.data_points_dict:
            return records

        points = list(sorted(self.data_points_dict.keys()))
        min = None
        max = None
        for i in range(len(points)):
            if min is None and points[i] >= sequence_numbers[0]:
                min = i
                break

        if min is not None:
            for i in reversed(range(len(points))):
                if max is None and points[i] <= sequence_numbers[1]:
                    max = i
                    break

        if min is not None and max is not None:
            records = max - min + 1

        return records

    def insert_accumulated_data_points(self):
        added = False
        for dp in self.data_point_accumulator:
            if dp.sequence_num not in self.data_points_dict:
                assert dp.sequence_num is not None
                self.data_points_dict[dp.sequence_num] = dp
                added = True

        if added:
            self.data_points_dict = dict(sorted(self.data_points_dict.items()))

        self.data_point_accumulator.clear()

    def insert_data_point(self, new_data_point: LoggedProbeDataPoint):
        if new_data_point in self.data_point_accumulator:
            return

        self.data_point_accumulator.add(new_data_point)

        if self.accumulator_timer:
            self.accumulator_timer.cancel()

        if len(self.data_point_accumulator) > self.ACCUMULATOR_MAX:
            self.insert_accumulated_data_points()
        else:
            self.accumulator_timer = asyncio.create_task(self.accumulator_timer_task())

    async def accumulator_timer_task(self):
        await asyncio.sleep(self.ACCUMULATOR_STABILIZATION_TIME)
        await self.insert_accumulated_data_points()

    def append_data_point(self, data_point: LoggedProbeDataPoint):
        if (
            not self.data_points_dict
            or data_point.sequence_num == max(self.data_points_dict.keys()) + 1
        ):
            assert data_point.sequence_num is not None
            self.data_points_dict[data_point.sequence_num] = data_point
            if not self.start_time:
                self.set_start_time(data_point)
        else:
            self.insert_data_point(data_point)

    def set_start_time(self, data_point: LoggedProbeDataPoint):
        assert data_point.sequence_num is not None
        current_time = datetime.now()
        second_diff = (
            int(data_point.sequence_num) * int(self.session_information.sample_period) // 1000
        )
        self.start_time = current_time - timedelta(seconds=second_diff)

    @property
    def id(self):
        return self.session_information.session_id
