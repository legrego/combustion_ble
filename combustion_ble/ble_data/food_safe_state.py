"""Food Safe State"""

from enum import Enum, unique


@unique
class FoodSafeState(Enum):
    NOT_SAFE = 0
    SAFE = 1
    SAFETY_IMPOSSIBLE = 2
