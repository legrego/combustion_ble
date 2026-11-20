# 🔥 **combustion_ble**

A Python library for [Combustion Inc.](https://combustion.inc) Bluetooth devices: Predictive Thermometers, Giant Grill Gauges, and MeatNet repeaters (Display, Booster, Engine).

The library is built around `MeatNet`, which turns Bluetooth advertisements into device state. It performs no Bluetooth I/O itself. You own the scanner and feed it advertisements. That makes it safe to use inside hosts that manage Bluetooth themselves, like [Home Assistant](https://www.home-assistant.io/).

From advertisements alone you get, for every probe in range or relayed by a MeatNet node:

- Temperatures for all 8 thermistors, plus virtual core, surface, and ambient
- Instant read temperature, smoothed the same way Combustion's apps show it
- Probe ID, color, mode, battery status, and overheating sensors
- Which nodes are relaying each probe, and how many hops away

Giant Grill Gauges report their temperature, alarms, and battery status. Displays, Boosters, and Engines report their product type and serial number.

Prediction and cook data need a Bluetooth connection, which is not part of the passive core yet.

## Usage

```python
from combustion_ble import MeatNet

meatnet = MeatNet()

def on_new_device(device):
    print("Discovered", device)
    device.add_listener(lambda: print("Updated", device))

meatnet.add_device_listener(on_new_device)

# For every advertisement your scanner receives. manufacturer_data can be the full
# {company_id: bytes} mapping that bleak and Home Assistant provide.
meatnet.handle_advertisement(address, manufacturer_data, rssi, connectable=connectable)

# About once per second, to mark devices unavailable and clear stale instant read readings.
meatnet.expire()

for probe in meatnet.probes.values():
    print(probe.serial_number_string, probe.core_temperature, probe.available)
```

Listeners only fire when something observable changes, so repeated identical advertisements are cheap.

### Home Assistant

Register a Bluetooth callback for manufacturer ID `2503` with `connectable=False` (so advertisements relayed by passive proxies are included), and hand each `BluetoothServiceInfoBleak` to the `MeatNet`:

```python
from datetime import timedelta

from homeassistant.components import bluetooth
from homeassistant.helpers.event import async_track_time_interval

meatnet = MeatNet()

entry.async_on_unload(
    bluetooth.async_register_callback(
        hass,
        lambda service_info, change: meatnet.handle_service_info(service_info),
        bluetooth.BluetoothCallbackMatcher(manufacturer_id=2503, connectable=False),
        bluetooth.BluetoothScanningMode.PASSIVE,
    )
)
entry.async_on_unload(
    async_track_time_interval(hass, lambda _now: meatnet.expire(), timedelta(seconds=1))
)
```

### Standalone

See [`examples/passive_meatnet.py`](examples/passive_meatnet.py) for a live table of every device in range, using a bleak scanner.

### Legacy `DeviceManager`

The original `DeviceManager` API is still available. It runs its own scanner and maintains its own connections, so it is not suitable for Home Assistant. It will be replaced by an optional connection layer built on `MeatNet`.

## Documentation

Docs are at https://combustion-ble.readthedocs.io/. The [Combustion BLE specifications](https://github.com/combustion-inc/combustion-documentation) describe the underlying protocol.

## Credits

Combustion Inc. for their [documentation](https://github.com/combustion-inc/combustion-documentation) and SDKs for [iOS](https://github.com/combustion-inc/combustion-ios-ble) and [Android](https://github.com/combustion-inc/combustion-android-ble). Parsing and arbitration rules follow those SDKs, and the tests reuse their test vectors.
