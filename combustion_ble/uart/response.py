"""Base Response."""


class Response:
    HEADER_LENGTH = 7

    def __init__(self, success, payload_length):
        self.success = success
        self.payload_length = payload_length
