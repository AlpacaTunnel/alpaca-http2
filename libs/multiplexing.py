"""
Bidirectional multiplexing channel/stream over stream like TCP.

Author: twitter.com/alpacatunnel
"""

from typing import Tuple


BINARY_PADDING = b'abbcccddddeeeee' + b'some-random-data' + b'-never-' * 3 + b'appear-in-other-places'


def byte2int(b: bytes):
    return int.from_bytes(b, byteorder='big')


def int2byte(i: int):
    return i.to_bytes(4, 'big')


class Multiplexing:
    """
    No io involved. Only parse binary data.

    Insert 4 bytes stream ID and data length. Format is:
    4-bytes-stream-id + 4-bytes-data-length + data

    Like HTTP2, client-initiated streams have odd-numbered stream IDs.
    """

    IncompleteReadError = 0

    def __init__(self, role='client'):
        if role == 'client':
            self._max_id = 1
        else:
            self._max_id = 2
        self._alive_ids = set()

    def new_stream(self) -> int:
        # TODO: recycle id when reach max 4 bytes
        new_id = self._max_id
        self._alive_ids.add(new_id)
        self._max_id += 2
        return new_id

    def del_stream(self, stream_id: int):
        self._alive_ids.discard(stream_id)

    def send(self, stream_id: int, data: bytes) -> bytes:
        if not data:
            data = b''

        id_bytes = int2byte(stream_id)
        len_bytes = int2byte(len(data))
        return id_bytes + len_bytes + data

    def receive(self, data: bytes) -> Tuple[int, bytes, bytes]:
        """
        The data may be any size. If size is more than data_len, return the left data.
        The left data can be parsed next time.
        """
        if len(data) < 8:
            return self.IncompleteReadError, None, data

        stream_id, data_len = byte2int(data[0:4]), byte2int(data[4:8])
        if len(data) < 8 + data_len:
            return self.IncompleteReadError, None, data

        return stream_id, data[8:8+data_len], data[8+data_len:]


def _test_main():
    pass


if __name__ == '__main__':
    _test_main()
