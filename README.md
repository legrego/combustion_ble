# 🔥 **combustion_ble**

This package enables communication with [Combustion Inc.](https://combustion.inc) Predictive Thermometers. It uses [`bleak`](https://bleak.readthedocs.io/en/latest/) to provide asychronous, cross-platform support.

Discovered probes show up as instances of the Probe class in the `DeviceManager.probes` dictionary, and their temperatures and other data are continually updated by incoming BLE advertising messages. Additionally, calling connect() on an individual `Probe` object will cause the framework to maintain a connection to that device, and will automatically download all logged temperature records on the device.

This SDH was heavily inspired by [Combustion Inc.'s Swift SDK](https://github.com/combustion-inc/combustion-ios-ble). As such, the API is very similar, and the documentation for that SDK is a good reference for this one. The architecture may not be "pythonic" in every respect, but the primary design goal is to make subsequent updaets to this SDH as easy as possible, by tracking the diffs from the "upstream" Swift SDH.

## Usage

Docs are still in-progress. In the meantime, see the [examples](./examples/) directory for some sample code.