"""Reject ARM firmware load segments outside its reserved DDR area."""
import json
from pathlib import Path
import struct
import sys

source, destination = map(Path, sys.argv[1:3])
data = source.read_bytes()
h = struct.unpack_from('<16sHHIIIIIHHHHHH', data)
if data[:6] != b'\x7fELF\x01\x01' or h[1:3] != (2, 40):
    raise ValueError('Expected little-endian ARM32 executable')
segments = []
for i in range(h[10]):
    q = struct.unpack_from('<8I', data, h[5] + i * h[9])
    if q[0] == 1 and q[5]:
        if not (0x100000 <= q[2] and q[2] + q[5] <= 0x1e0000
                and q[3] == q[2] and q[1] + q[4] <= len(data)):
            raise ValueError('Firmware segment outside reserved DDR')
        segments.append(dict(virtual_address=q[2], physical_address=q[3],
                             file_bytes=q[4], memory_bytes=q[5], flags=q[6]))
if h[4] != 0x100000 or not any(s['flags'] & 1 and s['virtual_address'] <= h[4]
                              < s['virtual_address'] + s['memory_bytes'] for s in segments):
    raise ValueError('Expected executable ARM entry at 0x00100000')
result = dict(entry=h[4], segments=segments, all_loads_in_reserved_firmware_ddr=True)
with destination.open('x', encoding='utf-8') as stream:
    json.dump(result, stream, indent=2)
print('UART_ELF_LAYOUT_OK')
