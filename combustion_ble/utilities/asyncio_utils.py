"""Utilities for consistently working with asyncio."""

import asyncio
from typing import Any, Callable, Coroutine

from combustion_ble.logger import LOGGER

DoneCallback = Callable[[asyncio.Task], None]


def _done_callback(task: asyncio.Task[Any]):
    try:
        task.result()
    except asyncio.CancelledError:
        pass  # Task cancellation should not be logged as an error.
    except Exception:
        LOGGER.exception("Exception raised by task = %r", task)
    if task.cancelled():
        return


def ensure_future(callable: Coroutine[Any, Any, Any], name: str = "async operation"):
    future = asyncio.ensure_future(callable)
    future.set_name(name)
    future.add_done_callback(_done_callback)
