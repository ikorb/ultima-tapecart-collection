"""Original bytes the build relies on, pinned without being quoted.

A patch checks that the bytes it replaces are the ones it was written
against.  Up to 15 bytes are quoted as they are; a longer run of the game's
own bytes is pinned by its length and SHA-256 (the first 16 hex digits), so
the repository holds none of it:

    KEY_QUEUE = Pin("#65:0123456789abcdef")
    assert image[o:o + len(KEY_QUEUE)] == KEY_QUEUE

`want("...")` reads either form: "#n:hash", or plain hex.
"""
import hashlib


def digest(data):
    return hashlib.sha256(bytes(data)).hexdigest()[:16]


class Pin:
    """Equal to the one byte string of its length whose hash it holds."""

    def __init__(self, spec):
        n, h = spec.lstrip("#").split(":")
        self.n, self.h = int(n), h

    @classmethod
    def of(cls, data):
        return cls(f"#{len(data)}:{digest(data)}")

    def __len__(self):
        return self.n

    def __eq__(self, other):
        if isinstance(other, Pin):
            return (self.n, self.h) == (other.n, other.h)
        if isinstance(other, (bytes, bytearray, memoryview)):
            return len(other) == self.n and digest(other) == self.h
        return NotImplemented

    def __ne__(self, other):
        eq = self.__eq__(other)
        return eq if eq is NotImplemented else not eq

    def __hash__(self):
        return hash((self.n, self.h))

    def __repr__(self):
        return f'Pin("#{self.n}:{self.h}")'

    def hex(self, *_args):
        return f"<{self.n} bytes, sha256 {self.h}>"

    def find(self, data, start=0):
        """The one place in data where the pinned bytes are (-1: none)."""
        data = bytes(data)
        at = [i for i in range(start, len(data) - self.n + 1) if digest(data[i:i + self.n]) == self.h]
        assert len(at) <= 1, f"{self!r} is in {len(at)} places"
        return at[0] if at else -1


def want(spec):
    """'#n:hash' as a Pin, else hex (spaces allowed) as bytes."""
    return Pin(spec) if spec.startswith("#") else bytes.fromhex(spec)
