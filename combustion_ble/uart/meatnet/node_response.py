class NodeResponse:
    HEADER_LENGTH = 15
    RESPONSE_TYPE_FLAG = 0x80

    def __init__(self, success, request_id, response_id, payload_length):
        self.success = success
        self.request_id = request_id
        self.response_id = response_id
        self.payload_length = payload_length
