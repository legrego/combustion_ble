"""Utilities for working with rich."""

import logging

from rich.logging import RichHandler
from rich.text import Text

from combustion_ble.ble_data.probe_temperatures import ProbeTemperatures
from combustion_ble.devices.device import Device
from combustion_ble.devices.meat_net_node import MeatNetNode
from combustion_ble.devices.probe import Probe
from combustion_ble.logger import LOGGER


def configure_logging(log_level="DEBUG", bleak_log_level="WARNING"):
    FORMAT = "%(message)s"
    logging.basicConfig(level="NOTSET", format=FORMAT, datefmt="[%X]", handlers=[RichHandler()])
    bleak_logger = logging.getLogger("bleak")
    bleak_logger.setLevel(bleak_log_level)
    LOGGER.setLevel(log_level)


def format_connection_state(connection_state: str = "unknown"):
    connection = Text(connection_state)
    if connection_state == Device.ConnectionState.CONNECTED:
        connection.stylize("green")
    elif connection_state == Device.ConnectionState.DISCONNECTED:
        connection.stylize("grey")
    elif connection_state == Device.ConnectionState.FAILED:
        connection.stylize("red")
    return connection


def format_temperatures(temperature_data: ProbeTemperatures | None):
    return f"Temps: {str([round(t, 1) for t in (temperature_data.values if temperature_data else [])])}"


def format_device_name(device: Device):
    if isinstance(device, Probe):
        device_name = Text(f"Probe {device.serial_number}")
    elif isinstance(device, MeatNetNode):
        ble_address = device.ble_identifier[-5:] if device.ble_identifier else ""
        device_name = Text(f"MeatNet Node {ble_address}")
    return device_name
