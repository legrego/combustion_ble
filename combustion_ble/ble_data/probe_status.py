from combustion_ble.ble_data.battery_status_virtual_sensors import (
    BatteryStatusVirtualSensors,
)
from combustion_ble.ble_data.food_safe_data import FoodSafeData
from combustion_ble.ble_data.food_safe_status import FoodSafeStatus
from combustion_ble.ble_data.mode_id import ModeId
from combustion_ble.ble_data.prediction_status import PredictionStatus
from combustion_ble.ble_data.probe_temperatures import ProbeTemperatures
from combustion_ble.food_safe import FoodSafe


class ProbeStatus:
    def __init__(
        self,
        min_sequence_number: int,
        max_sequence_number: int,
        temperatures: ProbeTemperatures,
        mode_id: ModeId,
        battery_status_virtual_sensors: BatteryStatusVirtualSensors,
        prediction_status: PredictionStatus,
        food_safe_data: FoodSafeData | None = None,
        food_safe_status: FoodSafeStatus | None = None,
    ):
        self.min_sequence_number = min_sequence_number
        self.max_sequence_number = max_sequence_number
        self.temperatures = temperatures
        self.mode_id = mode_id
        self.battery_status_virtual_sensors = battery_status_virtual_sensors
        self.prediction_status = prediction_status
        self.food_safe_data = food_safe_data
        self.food_safe_status = food_safe_status

    @classmethod
    def from_data(cls, data):
        if len(data) < 30:
            return None

        min_sequence_number = int.from_bytes(data[0:4], "little")
        max_sequence_number = int.from_bytes(data[4:8], "little")

        temperatures = ProbeTemperatures.from_raw_data(data[8:21])
        mode_id = ModeId.from_byte(data[21])
        battery_status_virtual_sensors = BatteryStatusVirtualSensors.from_byte(data[22])

        prediction_status_bytes = data[23:30]
        prediction_status = PredictionStatus.from_bytes(prediction_status_bytes)

        # Firmware that supports SafeCook follows the prediction status with food safe data and
        # food safe status. Older firmware ends here.
        food_safe_data = None
        food_safe_status = None
        if len(data) >= 48:
            food_safe_data = FoodSafeData.from_bytes(data[30:40])
            food_safe_status = FoodSafeStatus.from_bytes(data[40:48])

        return cls(
            min_sequence_number,
            max_sequence_number,
            temperatures,
            mode_id,
            battery_status_virtual_sensors,
            prediction_status,
            food_safe_data=food_safe_data,
            food_safe_status=food_safe_status,
        )

    @property
    def food_safe(self) -> FoodSafe | None:
        """SafeCook snapshot, or ``None`` when the firmware doesn't report it."""
        if self.food_safe_data is None or self.food_safe_status is None:
            return None
        return FoodSafe.from_status(self.food_safe_data, self.food_safe_status)
