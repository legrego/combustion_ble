"""Builders for Combustion manufacturer data payloads (without the company ID bytes)."""

from __future__ import annotations

from collections.abc import Sequence

ROOM_TEMPERATURES = (21.0, 21.5, 22.0, 22.5, 23.0, 23.5, 24.0, 24.5)


def encode_probe_temperatures(values: Sequence[float]) -> bytes:
    """Pack 8 Celsius readings into the 13-byte raw temperature field."""
    raw = 0
    for index, value in enumerate(values):
        raw |= (round((value + 20.0) / 0.05) & 0x1FFF) << (13 * index)
    return raw.to_bytes(13, "little")


def probe_payload(
    *,
    serial_number: int = 0x12345678,
    temperatures: Sequence[float] = ROOM_TEMPERATURES,
    raw_temperatures: bytes | None = None,
    mode: int = 0,
    color: int = 0,
    probe_id: int = 0,
    low_battery: bool = False,
    core: int = 0,
    surface: int = 0,
    ambient: int = 0,
    hop: int | None = None,
    overheating_byte: int = 0,
    preferences: int | None = None,
    size: int | None = None,
) -> bytes:
    """Build probe advertising data.

    ``hop`` is the raw 2-bit hop count (0 = one hop). Passing it makes this a repeated (node)
    advertisement; leaving it ``None`` makes it a direct probe advertisement.
    """
    data = bytearray([0x01 if hop is None else 0x02])
    data += serial_number.to_bytes(4, "little")
    data += (
        raw_temperatures
        if raw_temperatures is not None
        else encode_probe_temperatures(temperatures)
    )
    data.append((probe_id << 5) | (color << 2) | mode)
    virtual_sensors = core | (surface << 3) | (ambient << 5)
    data.append((virtual_sensors << 1) | int(low_battery))
    data.append((hop or 0) << 6)
    data.append(overheating_byte)
    if preferences is not None:
        data.append(preferences)
    if size is not None:
        data = data[:size]
    return bytes(data)


def instant_read_payload(temperature: float, **kwargs) -> bytes:
    """Build probe advertising data in instant read mode (only T1 is set)."""
    return probe_payload(
        temperatures=(temperature, -20.0, -20.0, -20.0, -20.0, -20.0, -20.0, -20.0),
        mode=1,
        **kwargs,
    )


def encode_alarm(set_: bool, tripped: bool, alarming: bool, temperature: float) -> bytes:
    """Pack a 2-byte gauge alarm status."""
    raw = round((temperature + 20.0) / 0.1) & 0x1FFF
    value = (raw << 3) | int(set_) | (int(tripped) << 1) | (int(alarming) << 2)
    return value.to_bytes(2, "little")


def gauge_payload(
    *,
    serial_number: str = "AB12CD34EF",
    temperature: float = 150.0,
    sensor_present: bool = True,
    sensor_overheating: bool = False,
    low_battery: bool = False,
    high_alarm: bytes = bytes(2),
    low_alarm: bytes = bytes(2),
    preferences: int | None = 0x01,
    gauge_id: int | None = None,
) -> bytes:
    """Build Giant Grill Gauge advertising data."""
    data = bytearray([0x03])
    data += serial_number.encode("ascii").ljust(10, b"\x00")
    raw_temperature = round((temperature + 20.0) / 0.1) if sensor_present else 0
    data += raw_temperature.to_bytes(2, "little")
    data.append(int(sensor_present) | (int(sensor_overheating) << 1) | (int(low_battery) << 2))
    data.append(100)  # battery percentage, always 100 on current firmware
    data += high_alarm + low_alarm
    if preferences is not None:
        data.append(preferences)
        if gauge_id is not None:
            data.append(gauge_id)
    return bytes(data)


def node_payload(product_type: int, serial_number: str = "1234ABCD99") -> bytes:
    """Build Display (4), Booster (5), or Engine (6) device information advertising data."""
    return bytes([product_type]) + serial_number.encode("ascii").ljust(10, b"\x00") + bytes(12)
