class CombustionError(Exception):
    """Base Combustion Error."""


class CharacteristicMissingError(CombustionError):
    """Raised when a characteristic is missing."""


class DFUNotImplementedError(NotImplementedError, CombustionError):
    """Raised when a DFU Operation is attempted."""

    def __init__(self) -> None:
        super().__init__("DFU Operations are not supported by this SDK")
