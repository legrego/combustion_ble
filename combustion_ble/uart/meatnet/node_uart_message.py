from combustion_ble.uart.meatnet.node_request import NodeRequest
from combustion_ble.uart.meatnet.node_request_from_data import node_request_from_data
from combustion_ble.uart.meatnet.node_response import NodeResponse
from combustion_ble.uart.meatnet.node_response_from_data import node_response_from_data


class NodeUARTMessage:
    @staticmethod
    def from_data(data):
        messages = []

        number_bytes_read = 0

        while number_bytes_read < len(data):
            bytes_to_decode = data[number_bytes_read:]

            response = node_response_from_data(bytes_to_decode)
            if response:
                messages.append(response)
                number_bytes_read += response.payload_length + NodeResponse.HEADER_LENGTH

            else:
                request = node_request_from_data(bytes_to_decode)
                if request and request.payload_length:
                    messages.append(request)
                    number_bytes_read += request.payload_length + NodeRequest.HEADER_LENGTH
                else:
                    # Found invalid response or request, break out of while loop
                    break

        return messages
