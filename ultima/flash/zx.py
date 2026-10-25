#!/usr/bin/env python3
"""zx02 wrapper, and a decoder written the way asm/zx02s.s works.

Plain `zx02 <in> <out>` -- no -b, -1, -e or -s: asm/zx02s.s decodes the
default format only, and nothing but this file and that one agree on it.

Crunching is cached on disk by content (build/zxcache), because Ultima 4
alone is 1579 units and every build and every test that calls parts()
would otherwise crunch them all again.

`decode` mirrors the 6502 decoder step for step -- the Elias gamma reader
with its bit buffer, the offset's high part from the gamma value and its
low seven bits plus one more bit from the next byte -- so a test that
decodes every stream in flash with it is checking the format the driver
actually implements, not just what the zx02 tool agrees with itself on.

See ../CompressorEvaluation.md for how zx02 was measured.
"""
import hashlib
import os
import subprocess
import tempfile

from ultima import paths

TOOL = os.path.join(paths.BUILD, "tools", "zx02")      # built from external/zx02 by the Makefile

CACHE = os.path.join(paths.BUILD, "zxcache")


_mem = {}


MIN_INPUT = 16


def crunch(data):
    """The zx02 stream for `data`, or None when it is too small to bother.

    The tool segfaults on a one-byte input (Ultima 5's DCONFIG is one), and
    nothing under a few bytes can shrink anyway, so callers store those raw.
    """
    key = bytes(data)
    if len(key) < MIN_INPUT:
        return None
    if key in _mem:
        return _mem[key]
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, hashlib.sha1(key).hexdigest() + ".zx")
    if not os.path.exists(path):
        with tempfile.TemporaryDirectory(prefix="zx") as tmp:
            src = os.path.join(tmp, "unit.bin")
            dst = os.path.join(tmp, "unit.zx")
            with open(src, "wb") as fh:
                fh.write(key)
            subprocess.run([TOOL, "-f", src, dst], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with open(dst, "rb") as fh:
                blob = fh.read()
        with open(path + ".tmp", "wb") as fh:
            fh.write(blob)
        os.replace(path + ".tmp", path)
    with open(path, "rb") as fh:
        blob = fh.read()
    if decode(blob) != key:
        raise ValueError("zx02 output does not decode back to its input")
    _mem[key] = blob
    return blob


def decode(stream):
    """Decode a zx02 stream exactly the way zx02s.s does; returns the output.

    Every name below is the 6502 code's.  Counts are 8-bit like X, with 0
    meaning 256 as the dex/bne loops do; only get_elias refills the bit
    buffer, as in the original -- elias_get and the two `asl bitr` tests
    after a copy take whatever bit is there."""
    data = iter(stream)
    out = bytearray()
    st = {"bitr": 0x80}

    def asl_bitr():
        b = st["bitr"] << 1
        st["bitr"] = b & 0xFF
        return b >> 8

    def control_bit():              # get_elias's asl bitr / bne / refill
        c = asl_bitr()
        if st["bitr"] == 0:
            a = next(data) << 1 | c
            st["bitr"] = a & 0xFF
            c = a >> 8
        return c

    def elias_skip1(x, c):          # X = x, carry = c
        while c:                    # bcs elias_get
            x = (x << 1 | asl_bitr()) & 0xFF
            c = control_bit()
        return x

    def get_elias(x):
        return elias_skip1(x, control_bit())

    def copy(n, offset):
        for _ in range(n or 256):
            out.append(out[-offset])

    offset = 1
    state = "literal"
    while True:
        if state == "literal":
            n = get_elias(1)
            for _ in range(n or 256):
                out.append(next(data))
            if asl_bitr():
                state = "new_offset"
                continue
            copy(get_elias(1), offset)
        else:
            v = get_elias(1)
            if v == 0:
                return bytes(out)
            v -= 1
            b = next(data)
            offset = ((v >> 1) << 8 | (v & 1) << 7 | b >> 1) + 1
            copy((elias_skip1(1, b & 1) + 1) & 0xFF, offset)
        state = "new_offset" if asl_bitr() else "literal"


def sized(data):
    """The zx02 stream with its own 16-bit length in front, or None.

    Ultima 1's and Ultima 3's tables have nowhere to put a compressed length
    -- U3's catalog entry is eight bytes with a block *count* in it -- so
    their blobs carry it.  zxd_unpack_sized (asm/zxdecr.s) reads those two
    bytes first.
    """
    blob = crunch(data)
    if blob is None:
        return None
    return bytes([len(blob) & 0xFF, len(blob) >> 8]) + blob


def unsized(blob):
    """The data a sized() blob decodes to (for the tests)."""
    n = blob[0] | blob[1] << 8
    return decode(blob[2:2 + n])


def smaller(data, pack=None):
    """`pack(data)` if that exists and is smaller than `data`, else None."""
    packed = (pack or crunch)(data)
    return packed if packed is not None and len(packed) < len(data) else None


# descriptor segment flag: this segment is stored crunched
SEG_COMP = 0x01


def place_segment(flash, data):
    """Place a boot segment, crunched if that is smaller.

    Returns (offset, length, flags) for the descriptor.  Crunched segments
    carry their own length, like Ultima 1's and Ultima 3's units, so the menu
    can decode them with zxd_unpack_sized and the same blob can serve both a
    descriptor segment and a catalog entry.
    """
    blob = smaller(data, sized)
    if blob is not None:
        return flash.add(blob), len(blob), SEG_COMP
    return flash.add(bytes(data)), len(data), 0
