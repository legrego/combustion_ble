"""Utilities for consistently working with asyncio."""

import asyncio
from typing import Any, Callable, Coroutine

from bleak import BleakError

from combustion_ble.logger import LOGGER

DoneCallback = Callable[[asyncio.Task], None]


def _done_callback(task: asyncio.Task[Any]):
    try:
        task.result()
    except asyncio.CancelledError:
        pass  # Task cancellation should not be logged as an error.
    except BleakError as be:
        # This is raised specifically by the `corebluetooth` backend.
        # It remains to be seen if this is a good idea or not. Many bleak operations are retried by us,
        # and a single failure isn't something to be concerned about in most cases.
        # TODO: handle other backend implementations.
        if be.__str__() == "disconnected":
            LOGGER.debug(
                "Exception raised by task as a result of client disconnect = %r",
                task,
                exc_info=True,
            )
        else:
            LOGGER.exception("Exception raised by task = %r", task)
    except Exception:
        LOGGER.exception("Exception raised by task = %r", task)
    if task.cancelled():
        return


def ensure_future(callable: Coroutine[Any, Any, Any], name: str = "async operation"):
    future = asyncio.ensure_future(callable)
    future.set_name(name)
    future.add_done_callback(_done_callback)
