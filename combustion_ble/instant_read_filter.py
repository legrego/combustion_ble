class InstantReadFilter:
    DEADBAND_RANGE_IN_CELSIUS = 0.05

    def __init__(self):
        self.values: tuple[float, float] = (
            InstantReadFilter.DEADBAND_RANGE_IN_CELSIUS,
            InstantReadFilter.celsius_to_fahrenheit_absolute(
                InstantReadFilter.DEADBAND_RANGE_IN_CELSIUS
            ),
        )

    def add_reading(self, temperature_in_celsius: float):
        if temperature_in_celsius is not None:
            self.values = (
                self.calculate_filtered_temperature(
                    temperature_in_celsius, self.values[0] if self.values else None, "celsius"
                ),
                self.calculate_filtered_temperature(
                    temperature_in_celsius, self.values[1] if self.values else None, "fahrenheit"
                ),
            )
        else:
            self.values = None

    def calculate_filtered_temperature(
        self, temperature_in_celsius: float, current_display_temperature: float, units: str
    ) -> float:
        deadband_range = (
            self.DEADBAND_RANGE_IN_CELSIUS
            if units == "celsius"
            else self.celsius_to_fahrenheit_difference(self.DEADBAND_RANGE_IN_CELSIUS)
        )

        temperature = (
            temperature_in_celsius
            if units == "celsius"
            else self.celsius_to_fahrenheit_absolute(temperature_in_celsius)
        )
        display_temperature = (
            round(current_display_temperature)
            if current_display_temperature is not None
            else round(temperature)
        )

        upper_bound = display_temperature + 0.5 + deadband_range
        lower_bound = display_temperature - 0.5 - deadband_range

        if temperature > upper_bound or temperature < lower_bound:
            return round(temperature)

        return float(display_temperature)

    @staticmethod
    def celsius_to_fahrenheit_difference(celsius: float):
        return (celsius * 9.0) / 5.0

    @staticmethod
    def celsius_to_fahrenheit_absolute(celsius: float):
        return InstantReadFilter.celsius_to_fahrenheit_difference(celsius) + 32.0
