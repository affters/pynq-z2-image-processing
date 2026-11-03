"""Offline adversarial transport checks; no serial port or hardware is opened."""
import json
from pathlib import Path
import struct
import sys
import time
import zlib

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "software"))
from uart_image_client import (FIRMWARE_INFO, FrameClient, REQUEST, RESPONSE,
                               RESPONSE_MAGIC, UARTDeviceError, UARTProtocolError)


class FakeSerial:
    def __init__(self, alter=None, chunk=19):
        self.pending = bytearray()
        self.received = bytearray()
        self.closed = False
        self.alter = alter
        self.chunk = chunk
        self.timeout = 0.01
        self.write_timeout = 0.01

    def reset_input_buffer(self):
        self.pending.clear()

    def close(self):
        self.closed = True

    def write(self, data):
        # Deliberately partial writes exercise client-side progress accounting.
        accepted = min(len(data), 701)
        self.received.extend(data[:accepted])
        if len(self.received) >= REQUEST.size:
            request = REQUEST.unpack(self.received[:REQUEST.size])
            _, sequence, command, mode, width, height, size, checksum = request
            if len(self.received) >= REQUEST.size + size:
                payload = bytes(self.received[REQUEST.size:REQUEST.size + size])
                if zlib.crc32(payload) & 0xFFFFFFFF != checksum:
                    raise AssertionError("Client emitted an invalid request CRC")
                if command == 1:
                    body, out_width, out_height, core = FIRMWARE_INFO, 128, 96, 0
                else:
                    if (width, height, size) != (128, 96, 36864):
                        raise AssertionError("Client emitted invalid image metadata")
                    out_width, out_height = (128, 96) if mode in (0, 4) else (126, 94)
                    body = bytes((i % 251 for i in range(out_width * out_height)))
                    core = 2
                header = [RESPONSE_MAGIC, sequence, 0, out_width, out_height, len(body),
                          zlib.crc32(body) & 0xFFFFFFFF, core]
                if self.alter and command == 2:
                    header, body = self.alter(header, body)
                self.pending.extend(RESPONSE.pack(*header) + body)
                del self.received[:REQUEST.size + size]
        return accepted

    def read(self, count):
        size = min(count, self.chunk, len(self.pending))
        result = bytes(self.pending[:size])
        del self.pending[:size]
        if not result:
            time.sleep(min(0.001, self.timeout))
        return result


def changed(index, value):
    def mutate(header, body):
        header[index] = value(header[index]) if callable(value) else value
        return header, body
    return mutate


def main():
    results = []
    image = np.zeros((96, 128, 3), dtype=np.uint8)
    transport = FakeSerial()
    with FrameClient("OFFLINE_FAKE", timeout=1.0, transport=transport) as client:
        actual, details = client.process(image, 1)
        assert actual.shape == (94, 126) and actual.dtype == np.uint8
        assert details["core_status"] == 2 and details["response_payload_bytes"] == 11844
        assert actual[0, 0] == 0 and actual[0, 1] == 1
    assert transport.closed
    results.append(dict(name="partial_reads_and_writes_valid_response", passed=True))

    cases = [
        ("crc_corruption", changed(6, lambda value: value ^ 1), UARTProtocolError),
        ("stale_sequence", changed(1, lambda value: (value + 1) & 0xFFFFFFFF), UARTProtocolError),
        ("oversized_payload", changed(5, 0xFFFFFFFF), UARTProtocolError),
        ("wrong_shape", changed(3, 127), UARTProtocolError),
        ("core_busy_despite_success", changed(7, 3), UARTProtocolError),
        ("explicit_device_error", lambda h, b: (h[:2] + [4, 0, 0, 0, 0, h[7]], b""), UARTDeviceError),
        ("invalid_nonempty_error", changed(2, 4), UARTProtocolError),
        ("truncated_body", lambda h, b: (h, b[:-5]), TimeoutError),
    ]
    for name, alter, expected in cases:
        transport = FakeSerial(alter=alter)
        client = FrameClient("OFFLINE_FAKE", timeout=0.15, transport=transport)
        client.open()
        try:
            client.process(image, 0)
        except expected:
            pass
        else:
            raise AssertionError(name + " was incorrectly accepted")
        assert client.closed and transport.closed
        try:
            client.process(image, 0)
        except UARTProtocolError:
            pass
        else:
            raise AssertionError("Failed client was incorrectly reused: " + name)
        results.append(dict(name=name, passed=True, closed_after_failure=True))
    print(json.dumps(dict(hardware_test=False, camera_test=False, serial_port_opened=False,
                          tests=results, all_passed=True), indent=2))


if __name__ == "__main__":
    main()
