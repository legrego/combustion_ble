"""Food Safe State"""

from enum import IntEnum, unique


@unique
class FoodSafeState(IntEnum):
    NOT_SAFE = 0
    SAFE = 1
    SAFETY_IMPOSSIBLE = 2
