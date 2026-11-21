# Example `combustion_ble` usage

This folder contains examples of how you can use the `combustion_ble` library.

| Example | What it shows |
| --- | --- |
| `passive_meatnet.py` | Every probe, gauge, and node in range, from advertisements only, using `MeatNet`. |
| `repeater_predictions.py` | Connects to the best MeatNet repeater and checks that it relays cooking predictions, using `NodeSession`. Exits non-zero if none arrive. |

Run an example from the repository root, for example `python -m examples.passive_meatnet`. The examples use [rich](https://github.com/Textualize/rich) for output.
