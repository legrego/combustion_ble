# 🔥 **combustion_ble**

A Python library for [Combustion Inc.](https://combustion.inc) Bluetooth devices: Predictive Thermometers, Giant Grill Gauges, and MeatNet repeaters (Display, Booster, Engine).

Requires **Python 3.14.2 or newer**, matching the Python requirement of Home Assistant 2026.11.2. Version 0.4.0 drops support for Python 3.11–3.13.

The library is built around `MeatNet`, which turns Bluetooth advertisements into device state. It performs no Bluetooth I/O itself. You own the scanner and feed it advertisements. That makes it safe to use inside hosts that manage Bluetooth themselves, like [Home Assistant](https://www.home-assistant.io/).

From advertisements alone you get, for every probe in range or relayed by a MeatNet node:

- Temperatures for all 8 thermistors, plus virtual core, surface, and ambient
- Instant read temperature, smoothed the same way Combustion's apps show it
- Probe ID, color, mode, battery status, and overheating sensors
- Which nodes are relaying each probe, and how many hops away

Giant Grill Gauges report their temperature, alarms, and battery status. Displays, Boosters, and Engines report their product type and serial number.

Cooking predictions, target-temperature controls, and firmware and hardware revisions are
available through optional sessions that use an already-connected Bluetooth client supplied by your
application: `ProbeSession` for a direct probe connection, and `NodeSession` for every probe on a
MeatNet network through one connection to a repeater. The passive core still performs no Bluetooth
I/O.

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

### Cooking predictions with a host-managed connection

First discover the probe through advertisements, then pass a connected `bleak.BleakClient`
for that **direct probe** to `ProbeSession`. The session subscribes to status notifications
and command responses. It never scans, connects, reconnects, or disconnects the client.
To read predictions through a MeatNet repeater instead, see
[Predictions through a MeatNet repeater](#predictions-through-a-meatnet-repeater).

```python
from combustion_ble import ProbeSession

session = ProbeSession(meatnet, serial_number, connected_client)
try:
    await session.start()
    await session.set_removal_temperature(63.0)  # Celsius; waits for the probe's acknowledgement.
    # Your application keeps the session alive while monitoring the cook.
    # Probe listeners fire when prediction values change:
    # meatnet.probes[serial_number].prediction
    # To disable predictions on the probe: await session.cancel_prediction()
finally:
    await session.stop()
    # The application releases/disconnects connected_client itself.
```

`probe.prediction` is an immutable `CookingPrediction` containing `state`, `mode`, `type`,
`set_point_temperature`, `estimated_core_temperature`, `seconds_remaining`, and
`percent_through_cook`. A remaining time of `None` means the probe is not providing a usable
estimate. Progress measures temperature change from heat start to the target, not elapsed time.
Status notifications remain authoritative; a successful command does not invent a prediction.

Continue calling `meatnet.expire()` about once per second to advance the countdown and clear
predictions after 15 seconds without connected status. Temperature advertisements do not extend
prediction freshness. A countdown reaching zero does not change the probe's reported cook state.
`prediction_updated_at` records the latest status receipt using MeatNet's monotonic clock.

The host's Bleak disconnect callback must call `session.disconnected()` immediately, then arrange
for `await session.stop()` during cleanup. Stop before releasing the client; use `try/finally` so
the host still disconnects it if subscription cleanup fails. Put separate timeouts around setup,
cleanup, and disconnect operations. Cancelling `start()` closes the session immediately and
leaves notification cleanup to the host's `finally` block. If `stop()` fails or times out,
disconnect the client and call `stop()` again to release session ownership without Bluetooth I/O.
Stopping clears local predictions
but does not cancel the cook. Sessions are single-use, with one session allowed per probe.
The session exclusively owns these two notification subscriptions; do not share them with another
consumer on the same client.

Commands are serialized. Device rejection raises `PredictionCommandRejectedError` and leaves
the session usable. Timeout, cancellation during a command, and write failure close the session:
the probe protocol has no request IDs, so late replies cannot safely be matched to new commands.
After such an error, stop the session, disconnect the client, and establish a fresh connection
and session before retrying. The command might already have reached the probe.

#### Home Assistant connection setup

Home Assistant owns discovery, adapter/proxy selection, and reconnect scheduling. In your
integration, resolve the direct probe's address through HA and establish a fresh client with
`bleak-retry-connector`. Keep that dependency in the integration; this library does not require
Home Assistant or a connection helper.

```python
import asyncio

from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth

from combustion_ble import ProbeSession


async def monitor_predictions(hass, meatnet, serial_number, stop_event):
    """Monitor until the integration requests shutdown or the client disconnects."""
    probe = meatnet.probes[serial_number]
    if probe.address is None:
        raise ConnectionError("Probe has only been heard through a MeatNet repeater")
    device = bluetooth.async_ble_device_from_address(hass, probe.address, connectable=True)
    if device is None:
        raise ConnectionError("No connection-capable adapter can reach the probe")

    session = None
    disconnected = asyncio.Event()

    def on_disconnect(_client):
        if session is not None:
            session.disconnected()
        disconnected.set()

    client = await establish_connection(
        BleakClientWithServiceCache,
        device,
        probe.serial_number_string,
        disconnected_callback=on_disconnect,
        timeout=20.0,
    )
    waiters = []
    try:
        session = ProbeSession(meatnet, serial_number, client)
        async with asyncio.timeout(30):
            await session.start()
        waiters = [
            asyncio.create_task(stop_event.wait()),
            asyncio.create_task(disconnected.wait()),
        ]
        await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for waiter in waiters:
            waiter.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)
        try:
            if session is not None:
                async with asyncio.timeout(10):
                    await session.stop()
        finally:
            try:
                async with asyncio.timeout(10):
                    await client.disconnect()
            finally:
                if session is not None and not client.is_connected:
                    await session.stop()
```

The integration should stop/cancel this monitoring task on config-entry unload. On reconnect,
call this function again to resolve the device through HA's current adapter/proxy selection.
Keep the passive advertisement callback registered with `connectable=False` so temperatures
remain available from listening-only adapters. Prediction connections require a connection-capable
adapter or proxy and occupy a connection slot while subscribed.

See [HA's Bluetooth guidance](https://contributors.home-assistant.io/core/integrations/bluetooth/)
and [Combustion's probe protocol](https://github.com/combustion-inc/combustion-documentation/blob/main/probe_ble_specification.rst).

### Predictions through a MeatNet repeater

A Display, Booster, Giant Grill Gauge, or Engine relays the status of every probe on its MeatNet
network, including predictions, as UART notifications. `NodeSession` subscribes to them through
one connection to the repeater, so a single connection slot covers every probe, including probes
out of the host's direct range. The session can also set and cancel targets on any of those
probes through the repeater.

```python
from combustion_ble import NodeSession

session = NodeSession(meatnet, node.address, connected_client)  # node from meatnet.nodes
try:
    await session.start()
    # meatnet.probes[serial_number].prediction now updates for every relayed probe.
    await session.set_removal_temperature(serial_number, 63.0)  # Waits for the acknowledgement.
    # To disable predictions on that probe: await session.cancel_prediction(serial_number)
finally:
    await session.stop()
```

Unlike a direct probe connection, requests through a repeater carry request IDs, so they can run
concurrently, and a request that times out (30 seconds by default, set with `command_timeout`),
fails, or is cancelled leaves the session running. Rejection raises
`PredictionCommandRejectedError`. As with `ProbeSession`, an acknowledgement doesn't invent a
prediction; relayed status remains authoritative.

The lifecycle matches `ProbeSession`: call `session.disconnected()` from the client's disconnect
callback, bound `start()` and `stop()` with your own timeouts, and release the client yourself.
The HA setup above applies with `node.address` in place of the probe's address. Only one session
per repeater is allowed, and predictions are applied only to probes already discovered through
advertisements.

When several sessions report the same probe, `probe.prediction` follows the direct
`ProbeSession`, then the repeater with the fewest hops to the probe, like Combustion's apps. If
that source disconnects, the next best one takes over immediately; if it goes quiet for 12
seconds, another source that is still reporting replaces it. Repeaters relay each probe's status
about every 5 seconds, while a direct connection reports about once a second.

#### Choosing connections

`plan_connections()` applies Combustion's rules for which connections are worth holding, so the
host doesn't have to. It performs no I/O; call it from the same tick that calls `meatnet.expire()`,
then act on the result with your own connection code:

```python
from combustion_ble import plan_connections

plan = plan_connections(meatnet, repeater=running_node_session, failed=failed_addresses)
plan.repeaters  # With no repeater session running: addresses to try, best first.
plan.direct     # Probes heard directly that the repeater isn't reporting.
plan.release    # Probes the repeater reports: close their direct connections.
```

Repeaters are ranked like Combustion's apps: ones relaying probes first, then the strongest
signal. Pass the addresses of repeaters whose last attempt failed as `failed` to try them last.
Try `plan.repeaters` in order and stop at the first one a connection-capable adapter can reach.
A probe can briefly have both connections, until the repeater relays its first status.

### Firmware and hardware revisions

Advertisements don't carry firmware versions, so they are read through a session and stored on the
device: `device.firmware_version` (a `FirmwareVersion`) and `device.hardware_revision` (a string).
Both are `None` until read, notify the device's listeners when they change, and keep their last
value after the session closes.

```python
await probe_session.read_device_information()  # The directly connected probe.
await node_session.read_device_information()  # The repeater itself (and its Gauge, if it is one).
await node_session.read_probe_information(serial_number)  # A probe, through the repeater.

probe = meatnet.probes[serial_number]
str(probe.firmware_version)  # The reported string, such as "v1.4.2"; use it for HA's sw_version.
probe.firmware_version >= FirmwareVersion.parse("v1.4.0")  # Compare parsed versions.
```

Call these after `start()` and bound them with your own timeouts. A failed read raises without
affecting the session. Repeaters other than the one you're connected to don't report their
revisions.

See [Combustion's MeatNet node protocol](https://github.com/combustion-inc/combustion-documentation/blob/main/meatnet_node_ble_specification.rst).

## Documentation

Docs are at https://combustion-ble.readthedocs.io/. The [Combustion BLE specifications](https://github.com/combustion-inc/combustion-documentation) describe the underlying protocol.

## Credits

Combustion Inc. for their [documentation](https://github.com/combustion-inc/combustion-documentation) and SDKs for [iOS](https://github.com/combustion-inc/combustion-ios-ble) and [Android](https://github.com/combustion-inc/combustion-android-ble). Parsing and arbitration rules follow those SDKs, and the tests reuse their test vectors.
