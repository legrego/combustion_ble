# **combustion_ble**

This package enables communication with [Combustion Inc.](https://combustion.inc) Predictive Thermometers. It uses [`bleak`](https://bleak.readthedocs.io/en/latest/) to provide asychronous, cross-platform support.

`MeatNet` builds probe, gauge, and node state from Bluetooth advertisements that you supply, and performs no Bluetooth I/O of its own, so it works inside hosts that own the Bluetooth stack, such as Home Assistant. For cooking predictions and SafeCook data, `ProbeSession` and `NodeSession` read status over a connection your code has already opened.

This SDH was heavily inspired by [Combustion Inc.'s Swift SDK](https://github.com/combustion-inc/combustion-ios-ble). As such, the API is very similar, and the documentation for that SDK is a good reference for this one. The architecture may not be "pythonic" in every respect, but the primary design goal is to make subsequent updaets to this SDH as easy as possible, by tracking the diffs from the "upstream" Swift SDH.


```{toctree}
:maxdepth: 2
:hidden:
:caption: Getting started

installation
overview
```

```{toctree}
:hidden:
:caption: Development

CHANGELOG
CONTRIBUTING
License <https://raw.githubusercontent.com/legrego/combustion_ble/main/LICENSE>
GitHub Repository <https://github.com/legrego/combustion_ble>
```

Contents:
```{toctree}
:maxdepth: 2

installation
api/index
CHANGELOG
```

## Indices and tables

```{eval-rst}
* :ref:`genindex`
* :ref:`modindex`
```
