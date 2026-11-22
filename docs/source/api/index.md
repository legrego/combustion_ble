MeatNet
-------
```{eval-rst}
.. autoclass:: combustion_ble.MeatNet
    :members:

.. autoclass:: combustion_ble.Probe
    :members:

.. autoclass:: combustion_ble.Gauge
    :members:

.. autoclass:: combustion_ble.Node
    :members:

.. autoclass:: combustion_ble.Device
    :members:

.. autoclass:: combustion_ble.ProbeRoute
    :members:

.. autoclass:: combustion_ble.FirmwareVersion
    :members:
```

Advertisements
--------------
```{eval-rst}
.. autofunction:: combustion_ble.parse_advertisement

.. autoclass:: combustion_ble.ProbeAdvertisement
    :members:

.. autoclass:: combustion_ble.GaugeAdvertisement
    :members:

.. autoclass:: combustion_ble.NodeAdvertisement
    :members:

.. autoclass:: combustion_ble.AlarmStatus
    :members:

.. autoclass:: combustion_ble.ThermometerPreferences
    :members:
```

Host-managed sessions
---------------------
```{eval-rst}
.. autoclass:: combustion_ble.ProbeSession
    :members:
    :inherited-members:

.. autoclass:: combustion_ble.NodeSession
    :members:
    :inherited-members:

.. autofunction:: combustion_ble.plan_connections

.. autoclass:: combustion_ble.ConnectionPlan
    :members:

.. autoclass:: combustion_ble.CookingPrediction
    :members:

.. autoclass:: combustion_ble.FoodSafe
    :members:

.. autoclass:: combustion_ble.FoodSafeProgram
    :members:

.. autoclass:: combustion_ble.FoodSafeState
    :members:

.. autoclass:: combustion_ble.FoodSafeMode
    :members:

.. autoclass:: combustion_ble.SimplifiedProduct
    :members:

.. autoclass:: combustion_ble.IntegratedProduct
    :members:

.. autoclass:: combustion_ble.Serving
    :members:

.. autoexception:: combustion_ble.CombustionError

.. autoexception:: combustion_ble.RequestRejectedError

.. autoexception:: combustion_ble.PredictionCommandRejectedError
```

Sensor readings
---------------
```{eval-rst}
.. autoclass:: combustion_ble.ble_data.PredictionMode
    :members:

.. autoclass:: combustion_ble.ble_data.PredictionState
    :members:

.. autoclass:: combustion_ble.ble_data.PredictionStatus
    :members:

.. autoclass:: combustion_ble.ble_data.PredictionType
    :members:

.. autoclass:: combustion_ble.ble_data.ProbeTemperatures
    :members:
```
