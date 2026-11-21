class CombustionError(Exception):
    """Base Combustion Error."""


class RequestRejectedError(CombustionError):
    """A device acknowledged a request but reported that it failed."""


class PredictionCommandRejectedError(RequestRejectedError):
    """A probe or MeatNet node acknowledged a prediction command but rejected it."""


class CharacteristicMissingError(CombustionError):
    """Raised when a characteristic is missing."""


class DFUNotImplementedError(NotImplementedError, CombustionError):
    """Raised when a DFU Operation is attempted."""

    def __init__(self) -> None:
        super().__init__("DFU Operations are not supported by this SDK")
