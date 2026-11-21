# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

- Add `NodeSession`, which reads cooking predictions for every probe on a MeatNet network through one host-owned connection to a Display, Booster, Giant Grill Gauge, or Engine. It understands relayed probe status from node firmware with and without food safe data.
- Add `plan_connections()`, which applies Combustion's rules for prediction connections without performing any I/O: which repeaters to try, best first; which probes need a direct connection; and which direct connections a running repeater session makes redundant. Hosts keep owning connections, retries, and cleanup.
- When a direct probe connection and one or more repeaters report the same probe, `Probe.prediction` follows the direct connection, then the repeater with the fewest hops. Losing a source falls back to the next best one without clearing the prediction.
- `MeatNet.handle_prediction_status()` and `MeatNet.clear_prediction()` accept a `source`, and `handle_prediction_status()` a `hop_count`. Clearing a prediction now removes only that source's data.
- Add `examples/repeater_predictions.py`, which connects to the best repeater in range and reports whether relayed predictions arrive.

## [v0.5.0](https://github.com/legrego/combustion_ble/releases/tag/v0.5.0) - 2026-11-20

- Add direct-probe `ProbeSession` support using an already-connected, host-owned Bleak client, compatible with Home Assistant's Bluetooth connection management. Sessions receive cooking predictions and support acknowledged removal-target and cancel commands without scanning or managing connections.
- Expose immutable cooking predictions on `MeatNet.Probe`, with listener updates, countdowns advanced by `expire()`, and freshness independent of temperature advertisements.
- Correct direct set-prediction requests to use a two-byte little-endian payload, validate targets, and round them to tenths of a degree Celsius.
- Preserve host subscription deadlines when `ProbeSession.start()` is cancelled: invalidate predictions immediately and defer notification cleanup to the host, retaining session ownership until cleanup completes.

## [v0.4.1](https://github.com/legrego/combustion_ble/releases/tag/v0.4.1) - 2026-11-20
- Allow bleak 3.0.2, the version Home Assistant 2026.10 and 2026.11 pin. Home Assistant couldn't install 0.4.0, which required bleak 3.1.0 or newer.

## [v0.4.0](https://github.com/legrego/combustion_ble/releases/tag/v0.4.0) - 2026-11-20
- Require Python >= 3.14.2 to match Home Assistant, refresh dependencies and CI actions, and publish to PyPI and GitHub only through a manually triggered workflow.
- Add `MeatNet`, a passive core that builds probe, gauge, and node state from advertisements supplied by the caller. It performs no Bluetooth I/O, creates no background tasks, and has no global state, so it can run inside Home Assistant.
- Add `parse_advertisement()`, which decodes advertisements from every current product type: probes, repeated probe data, Giant Grill Gauge, Display, Booster, and Engine.
- Choose between direct and MeatNet-relayed probe data using the same rules as Combustion's Android SDK.
- Fix `ValueError` raised for every advertisement from a Giant Grill Gauge, Display, Booster, or Engine.
- Fix smoothed instant read temperatures sometimes being returned as `int` instead of `float`.
- Remove the `bitstring` dependency.
- `import combustion_ble` no longer imports bleak or creates the legacy `BleManager` singleton. `DeviceManager`, `BluetoothMode`, and `VirtualTemperatures` are still importable from the package and load on first use.

## [v0.3.3](https://github.com/legrego/combustion_ble/releases/tag/v0.3.3) - 2024-03-11
- Disable Food Safe features

## [v0.3.2](https://github.com/legrego/combustion_ble/releases/tag/v0.3.2) - 2024-03-08
- Bump `black`, reformat (#24)
- Improve teardown logic (#28)

## [v0.3.0](https://github.com/legrego/combustion_ble/releases/tag/v0.3.0) - 2024-01-25
- Allow externally managed `BleakScanner`s to be used via new `BluetoothMode` parameter. (#20)
- Add additional probe attribute listeners (#21)

## [v0.2.1](https://github.com/legrego/combustion_ble/releases/tag/v0.2.1) - 2024-01-22
- Allow BleManager to be stopped and restarted (#14)
- Add device listeners to respond to device changes (#15)
- Prevent concurrent GATT read requests (#18)

## [v0.1.1](https://github.com/legrego/combustion_ble/releases/tag/v0.1.1) - 2024-01-10
- Fix Documentation

## [v0.1.0](https://github.com/legrego/combustion_ble/releases/tag/v0.1.0) - 2024-01-10
- Added readme, and cleaned up linting errors (#11)
