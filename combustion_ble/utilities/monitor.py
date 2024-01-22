from datetime import datetime
from typing import Callable, Generic, TypeVar

T = TypeVar("T")
UpdateListener = Callable[[T], None]

RemoveListener = Callable[[], None]


class Monitorable(Generic[T]):
    def __init__(self, initial_value: T) -> None:
        self._listeners = set[UpdateListener]()
        self._value = initial_value
        self._last_update_time = datetime.now()

    @property
    def value(self):
        return self._value

    @property
    def last_updated(self):
        return self._last_update_time

    def add_update_listener(self, listener: UpdateListener[T]) -> RemoveListener:
        self._listeners.add(listener)

        # Notify new listener of current value
        if self.value:
            listener(self.value)

        def remove():
            """Remove the listener"""
            self._listeners.remove(listener)

        return remove

    def update(self, next_value: T) -> None:
        self._value = next_value
        self._last_update_time = datetime.now()
        for listener in self._listeners:
            listener(next_value)
