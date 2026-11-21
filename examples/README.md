# Example `combustion_ble` usage

This folder contains examples of how you can use the `combustion_ble` library.

| Example | What it shows |
| --- | --- |
| `passive_meatnet.py` | **Recommended.** Every probe, gauge, and node in range, from advertisements only, using `MeatNet`. |
| `repeater_predictions.py` | Connects to the best MeatNet repeater and checks that it relays cooking predictions, using `NodeSession`. Exits non-zero if none arrive. |
| `passive_scanner.py` | Legacy `DeviceManager` fed by an external `BleakScanner`. |
| `read_devices.py`, `use_device_listeners.py`, `read_prediction.py`, `read_temp_logs.py` | Legacy `DeviceManager`, which owns its own scanner and connections. |

Run an example from the repository root, for example `python -m examples.passive_meatnet`. The examples use [rich](https://github.com/Textualize/rich) for output.
