#!/usr/bin/env python3
"""Page-aligned flash allocator with content dedup.

Every unit starts on a 256-byte page so a flash address fits in 16 bits of
page number, which keeps the per-game lookup tables small.  Identical content
is stored once -- across the whole collection this matters a lot (U5's disks
share 148 unique files out of 236, U4's music chunks are identical on all four
disks), and it costs nothing to do from the start.
"""
PAGE = 256


class Layout:
    def __init__(self, base=0):
        if base % PAGE:
            raise ValueError(f"base {base:#x} is not page aligned")
        self.base = base
        self.cursor = base
        self.blobs = []            # (offset, bytes)
        self._by_hash = {}

    def add(self, data):
        """Place `data`, returning its flash offset.  Identical content is
        shared rather than stored twice."""
        if not data:
            raise ValueError("refusing to place an empty unit")
        key = bytes(data)
        if key in self._by_hash:
            return self._by_hash[key]
        offset = self.cursor
        self.blobs.append((offset, key))
        self._by_hash[key] = offset
        self.cursor += (len(key) + PAGE - 1) // PAGE * PAGE
        return offset

    def reserve(self, size):
        """Set space aside now, to fill with place_at later.

        Breaks a placement cycle: Ultima 5's directory needs every file's
        offset, including the driver file's, and the driver needs to know
        where the directory landed before it is placed.  The directory's
        *size* depends on neither, so reserve it first.
        """
        offset = self.cursor
        self.cursor += (size + PAGE - 1) // PAGE * PAGE
        return offset

    def place_at(self, offset, data):
        """Place `data` at a fixed offset (descriptors, tables)."""
        if offset % PAGE:
            raise ValueError(f"offset {offset:#x} is not page aligned")
        self.blobs.append((offset, bytes(data)))
        return offset

    def image(self, size=None):
        end = max((o + len(b) for o, b in self.blobs), default=0)
        out = bytearray(b"\xff" * (size or end))
        for offset, blob in self.blobs:
            if offset + len(blob) > len(out):
                raise ValueError(f"unit at {offset:#x} runs past the image end")
            region = out[offset:offset + len(blob)]
            if region != b"\xff" * len(blob):
                raise ValueError(f"overlapping allocation at {offset:#x}")
            out[offset:offset + len(blob)] = blob
        return bytes(out)

    @property
    def used(self):
        return sum(len(b) for _, b in self.blobs)


def image_from(blobs, size):
    """Build a flash image out of (offset, bytes) pairs, checking for overlap.

    Used when several games' layouts are merged into one cartridge image.
    """
    out = bytearray(b"\xff" * size)
    for offset, blob in sorted(blobs):
        end = offset + len(blob)
        if end > size:
            raise ValueError(f"blob at {offset:#08x}+{len(blob)} runs past {size:#08x}")
        if out[offset:end] != b"\xff" * len(blob):
            raise ValueError(f"overlapping allocation at {offset:#08x}")
        out[offset:end] = blob
    return bytes(out)
