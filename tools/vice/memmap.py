#!/usr/bin/env python3
"""Read VICE's memmap image.

`mmsave "<file>" 0` writes a 256x256 8-bit BMP whose palette index *is* the
access bitfield for that address (address = y * 256 + x):

    bit 7 I/O write   bit 6 I/O exec-or-read
    bit 5 ROM read    bit 4 ROM write   bit 3 ROM exec
    bit 2 RAM read    bit 1 RAM write   bit 0 RAM exec

So a byte with no RAM bits set was never touched as RAM, however busy the I/O
at the same address was -- which is exactly the question to ask about the RAM
under I/O.
"""
import struct
import sys

RAM_R, RAM_W, RAM_X = 0x04, 0x02, 0x01
RAM_ANY = RAM_R | RAM_W | RAM_X


def read_bmp(path):
    """Return a list of 65536 access bytes, indexed by address."""
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:2] != b"BM":
        raise ValueError(f"{path} is not a BMP")
    offset = struct.unpack_from("<I", data, 10)[0]
    width, height = struct.unpack_from("<ii", data, 18)
    bits = struct.unpack_from("<H", data, 28)[0]
    if bits != 8:
        raise ValueError(f"{path} is {bits}-bit, expected 8")
    stride = (width + 3) & ~3
    out = bytearray(width * abs(height))
    for row in range(abs(height)):
        y = row if height < 0 else abs(height) - 1 - row   # bottom-up by default
        src = offset + row * stride
        out[y * width:(y + 1) * width] = data[src:src + width]
    return out


def ranges(access, lo=0x0000, hi=0xffff, mask=RAM_ANY, touched=True):
    """Merge addresses in [lo, hi] into runs, by whether mask bits are set."""
    out, start, prev = [], None, None
    for a in range(lo, hi + 1):
        hit = bool(access[a] & mask)
        if hit != touched:
            if start is not None:
                out.append((start, prev))
                start = None
            continue
        if start is None:
            start = a
        prev = a
    if start is not None:
        out.append((start, prev))
    return out


def describe(access, lo, hi, mask=RAM_ANY, what="untouched"):
    free = ranges(access, lo, hi, mask, touched=False)
    return [(a, b, b - a + 1) for a, b in free]


if __name__ == "__main__":
    access = read_bmp(sys.argv[1])
    lo = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0
    hi = int(sys.argv[3], 16) if len(sys.argv) > 3 else 0xffff
    print(f"RAM never touched in ${lo:04x}-${hi:04x}:")
    for a, b, n in describe(access, lo, hi):
        if n >= 16:
            print(f"  ${a:04x}-${b:04x}  {n:5d} bytes")
