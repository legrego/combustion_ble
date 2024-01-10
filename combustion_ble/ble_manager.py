from typing import Optional

from bleak import BleakClient, BleakError, BleakGATTCharacteristic, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from combustion_ble.ble_data.advertising_data import AdvertisingData
from combustion_ble.ble_data.probe_status import ProbeStatus
from combustion_ble.const import (
    BT_MANUFACTURER_ID,
    DEVICE_STATUS_CHARACTERISTIC,
    FW_VERSION_CHARACTERISTIC,
    HW_VERSION_CHARACTERISTIC,
    MODEL_NUMBER_CHARACTERISTIC,
    SERIAL_NUMBER_CHARACTERISTIC,
    UART_RX_CHARACTERISTIC,
    UART_TX_CHARACTERISTIC,
)
from combustion_ble.exceptions import CombustionError
from combustion_ble.logger import LOGGER
from combustion_ble.uart.meatnet.node_request import NodeRequest
from combustion_ble.uart.request import Request
from combustion_ble.uart.session_info import SessionInfoRequest
from combustion_ble.utilities.asyncio_utils import ensure_future


class BleManagerDelegate:
    def did_connect_to(self, identifier: str):
        pass

    def did_fail_to_connect_to(self, identifier: str):
        pass

    def did_disconnect_from(self, identifier: str):
        pass

    def handle_bootloader_advertising(self, advertising_name: str, rssi: int, identifier: str):
        pass

    def update_device_with_advertising(
        self, advertising: AdvertisingData, is_connectable: bool, rssi: int, identifier: str
    ):
        pass

    def update_device_with_status(self, identifier: str, status: ProbeStatus):
        pass

    def handle_uart_data(self, identifier: str, data: bytes):
        pass

    def update_device_fw_version(self, identifier: str, fw_version: str):
        pass

    def update_device_hw_revision(self, identifier: str, hw_revision: str):
        pass

    def update_device_serial_number(self, identifier: str, serial_number: str):
        pass

    def update_device_model_info(self, identifier: str, model_info: str):
        pass


class BleManager:
    shared: "BleManager" = None  # type: ignore

    def __init__(self):
        self.clients: dict[str, BleakClient] = {}
        self.peripherals: dict[str, BLEDevice] = {}
        self.scanner: Optional[BleakScanner] = None
        self.delegate: Optional[BleManagerDelegate] = None
        self.device_status_characteristics: dict[str, BleakGATTCharacteristic] = {}
        self.uart_characteristics: dict[str, BleakGATTCharacteristic] = {}
        self.fw_revision_characteristics: dict[str, BleakGATTCharacteristic] = {}
        self.hw_revision_characteristics: dict[str, BleakGATTCharacteristic] = {}
        self.serial_number_characteristics: dict[str, BleakGATTCharacteristic] = {}
        self.model_number_characteristics: dict[str, BleakGATTCharacteristic] = {}

    async def init_bluetooth(self, scanner: Optional[BleakScanner] = None):
        if self.scanner:
            raise CombustionError("Bluetooth has already been initialized.")

        if scanner:
            LOGGER.debug("Initializing bluetooth with provided BleakScanner.")
            self.scanner = scanner
            scanner.register_detection_callback(self.detection_callback)
        else:
            LOGGER.debug("Initializing bluetooth with our own BleakScanner.")
            self.scanner = BleakScanner(detection_callback=self.detection_callback)
            await self.scanner.start()

    def detection_callback(self, device: BLEDevice, advertisement_data: AdvertisementData):
        if BT_MANUFACTURER_ID not in advertisement_data.manufacturer_data:
            return

        advertising_data = AdvertisingData.from_bleak_data(
            advertisement_data.manufacturer_data[BT_MANUFACTURER_ID]
        )
        if advertising_data and self.delegate:
            self.delegate.update_device_with_advertising(
                advertising=advertising_data,
                is_connectable=True,  # TODO: support non-connectable devices
                rssi=advertisement_data.rssi,
                identifier=device.address,
            )

    async def connect(self, identifier: str):
        if not self.delegate:
            return
        LOGGER.debug("Connecting to [%s]", identifier)
        client = BleakClient(
            identifier, disconnected_callback=self.disconnected_callback(identifier)
        )
        successful = False
        try:
            await client.connect()
            LOGGER.debug("Connection to [%s] successful", identifier)
            self.clients[identifier] = client
            successful = True
        except Exception as ex:
            LOGGER.debug("Failed connecting to [%s]: %s", identifier, ex)
            self.delegate.did_fail_to_connect_to(identifier)

        if successful:
            self.delegate.did_connect_to(identifier)
            self.handle_discovered_services(identifier, client)

    def disconnected_callback(self, identifier: str):
        def cb(client: BleakClient):
            if self.delegate:
                self.delegate.did_disconnect_from(identifier)
            if identifier in self.clients:
                del self.clients[identifier]
            if identifier in self.uart_characteristics:
                del self.uart_characteristics[identifier]
            if identifier in self.device_status_characteristics:
                del self.device_status_characteristics[identifier]
            if identifier in self.fw_revision_characteristics:
                del self.fw_revision_characteristics[identifier]
            if identifier in self.hw_revision_characteristics:
                del self.hw_revision_characteristics[identifier]
            if identifier in self.serial_number_characteristics:
                del self.serial_number_characteristics[identifier]
            if identifier in self.model_number_characteristics:
                del self.model_number_characteristics[identifier]

        return cb

    async def disconnect(self, identifier: str):
        if identifier in self.clients:
            client = self.clients[identifier]
            if client.is_connected:
                try:
                    await client.disconnect()
                except BleakError as be:
                    LOGGER.error("Error disconnecting from [%s]: %s", identifier, be)
                # Additional cleanup handled by disconnected_callback

    async def send_request(
        self, identifier: str, request: Request | NodeRequest
    ):  # todo this does not need to be async. we can ensure_future instead
        connection_peripheral = self.get_connected_peripheral(identifier)
        if not connection_peripheral:
            return

        uart_char = self.uart_characteristics.get(identifier)
        client = self.clients.get(identifier)
        try:
            if client and client.is_connected and uart_char:
                await client.write_gatt_char(uart_char, request.data, response=False)
        except BleakError as be:
            LOGGER.error("Error sending request to [%s]: %s", identifier, be)

    async def read_firmware_revision(self, identifier: str) -> None:
        connection_peripheral = self.get_connected_peripheral(identifier)
        if connection_peripheral:
            uart_char = self.fw_revision_characteristics.get(identifier)
            client = self.clients.get(identifier)
            try:
                if client and client.is_connected and uart_char and self.delegate:
                    data = await client.read_gatt_char(uart_char)
                    fw_version = data.decode(encoding="utf-8")
                    self.delegate.update_device_fw_version(identifier, fw_version)
            except BleakError as be:
                LOGGER.error("Error reading firmware version from [%s]: %s", identifier, be)

    async def read_hardware_revision(self, identifier: str) -> None:
        connection_peripheral = self.get_connected_peripheral(identifier)
        if connection_peripheral:
            uart_char = self.hw_revision_characteristics.get(identifier)
            client = self.clients.get(identifier)
            try:
                if client and client.is_connected and uart_char and self.delegate:
                    data = await client.read_gatt_char(uart_char)
                    hw_revision = data.decode(encoding="utf-8")
                    self.delegate.update_device_hw_revision(identifier, hw_revision)
            except BleakError as be:
                LOGGER.error("Error reading hardware version from [%s]: %s", identifier, be)

    async def read_serial_number(self, identifier: str) -> None:
        connection_peripheral = self.get_connected_peripheral(identifier)
        if connection_peripheral:
            uart_char = self.serial_number_characteristics.get(identifier)
            client = self.clients.get(identifier)
            try:
                if client and client.is_connected and uart_char and self.delegate:
                    data = await client.read_gatt_char(uart_char)
                    serial_number = data.decode(encoding="utf-8")
                    self.delegate.update_device_serial_number(identifier, serial_number)
            except BleakError as be:
                LOGGER.error("Error reading serial number from [%s]: %s", identifier, be)

    async def read_model_number(self, identifier: str) -> None:
        connection_peripheral = self.get_connected_peripheral(identifier)
        if connection_peripheral:
            uart_char = self.model_number_characteristics.get(identifier)
            client = self.clients.get(identifier)
            try:
                if client and client.is_connected and uart_char and self.delegate:
                    data = await client.read_gatt_char(uart_char)
                    model_number = data.decode(encoding="utf-8")
                    self.delegate.update_device_model_info(identifier, model_number)
            except BleakError as be:
                LOGGER.error("Error reading model number from [%s]: %s", identifier, be)

    def get_connected_peripheral(self, identifier: str) -> BleakClient | None:
        connected_clients = [
            self.clients[c]
            for c in self.clients
            if self.clients[c].address == identifier and self.clients[c].is_connected
        ]
        if not connected_clients:
            return None

        return connected_clients[0]

    def handle_uart_data(self, identifier: str, data: bytes):
        if self.delegate:
            self.delegate.handle_uart_data(identifier, data)

    def handle_discovered_services(self, identifier: str, client: BleakClient):
        def uart_tx_notify_callback(char: BleakGATTCharacteristic, data: bytearray):
            if char.uuid == UART_TX_CHARACTERISTIC:
                self.handle_uart_data(identifier, bytes(data))
            elif char.uuid == DEVICE_STATUS_CHARACTERISTIC:
                probe_status = ProbeStatus.from_data(data)
                if probe_status and self.delegate:
                    self.delegate.update_device_with_status(identifier, probe_status)
            else:
                LOGGER.debug("uart_tx_notify_callback ignoring unknown char [%s]", char.uuid)

        for service in client.services:
            for characteristic in service.characteristics:
                if characteristic.uuid == UART_RX_CHARACTERISTIC:
                    self.uart_characteristics[identifier] = characteristic
                elif characteristic.uuid == DEVICE_STATUS_CHARACTERISTIC:
                    self.device_status_characteristics[identifier] = characteristic
                elif (
                    characteristic.uuid == FW_VERSION_CHARACTERISTIC
                    or characteristic.uuid == HW_VERSION_CHARACTERISTIC
                    or characteristic.uuid == SERIAL_NUMBER_CHARACTERISTIC
                    or characteristic.uuid == MODEL_NUMBER_CHARACTERISTIC
                ):
                    if characteristic.uuid == FW_VERSION_CHARACTERISTIC:
                        self.fw_revision_characteristics[identifier] = characteristic
                        ensure_future(
                            self.read_firmware_revision(identifier),
                            name="ble_manager[read_firmware_revision]",
                        )
                    elif characteristic.uuid == HW_VERSION_CHARACTERISTIC:
                        self.hw_revision_characteristics[identifier] = characteristic
                        ensure_future(
                            self.read_hardware_revision(identifier),
                            name="ble_manager[read_hardware_revision]",
                        )
                    elif characteristic.uuid == SERIAL_NUMBER_CHARACTERISTIC:
                        self.serial_number_characteristics[identifier] = characteristic
                        ensure_future(
                            self.read_serial_number(identifier),
                            name="ble_manager[read_serial_number]",
                        )
                    elif characteristic.uuid == MODEL_NUMBER_CHARACTERISTIC:
                        self.model_number_characteristics[identifier] = characteristic
                        ensure_future(
                            self.read_model_number(identifier),
                            name="ble_manager[read_model_number]",
                        )
                elif characteristic.uuid == UART_TX_CHARACTERISTIC:
                    if characteristic.descriptors:
                        client = self.get_connected_peripheral(identifier)
                        if client:
                            ensure_future(
                                client.start_notify(characteristic, uart_tx_notify_callback),
                                name="ble_manager[start_notify:uart_tx]",
                            )
                            status_char = self.device_status_characteristics.get(identifier)
                            if status_char:
                                ensure_future(
                                    client.start_notify(status_char, uart_tx_notify_callback),
                                    name="ble_manager[start_notify:device_status]",
                                )
                                ensure_future(
                                    self.send_request(identifier, request=SessionInfoRequest()),
                                    name="ble_manager[send_request:session_info]",
                                )


# Instantiate the BleManager singleton
BleManager.shared = BleManager()
