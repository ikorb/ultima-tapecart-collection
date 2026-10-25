#!/usr/bin/env python3
"""Minimal D64 reader shared by every game's build script.

Deliberately a library rather than a CLI, unlike the per-game `tools/d64.py`
scripts in 1/..6/ which this is derived from.

Handles the 683-byte error map that Ultima 1, 2, 4 and 5's program disks carry
(175531 bytes rather than 174848).  That map is load bearing for the copy
protection in U1, U2 and U4, so it is exposed rather than silently dropped.
"""

SECTORS_PER_TRACK = [0] + [21] * 17 + [19] * 7 + [18] * 6 + [17] * 5
TOTAL_SECTORS = sum(SECTORS_PER_TRACK)
DATA_LENGTH = TOTAL_SECTORS * 256

# error-map codes worth naming; anything but 1 means the sector does not read
ERROR_OK = 0x01
ERRORS = {
    0x02: "20 header block not found",
    0x03: "21 no sync",
    0x04: "22 data block not found",
    0x05: "23 data checksum",
    0x0B: "29 disk id mismatch",
}


class D64:
    def __init__(self, path):
        with open(path, "rb") as fh:
            blob = fh.read()
        self.path = path
        self.data = blob[:DATA_LENGTH]
        self.errmap = blob[DATA_LENGTH:DATA_LENGTH + TOTAL_SECTORS]
        if len(self.data) != DATA_LENGTH:
            raise ValueError(f"{path}: {len(blob)} bytes, not a 35-track D64")

    @classmethod
    def from_bytes(cls, data, errmap=b"", path="<memory>"):
        """An image held in memory (ultima/disks/images.py: a .g64 decoded, a
        member of a zip): 683 sectors, and an error map or none."""
        d = cls.__new__(cls)
        if len(data) != DATA_LENGTH:
            raise ValueError(f"{path}: {len(data)} bytes, not a 35-track D64")
        d.path, d.data, d.errmap = path, bytes(data), bytes(errmap)
        return d

    # -- geometry --------------------------------------------------------

    @staticmethod
    def offset(track, sector):
        if not 1 <= track <= 35:
            raise ValueError(f"track {track} out of range")
        if not 0 <= sector < SECTORS_PER_TRACK[track]:
            raise ValueError(f"sector {sector} out of range on track {track}")
        return sum(SECTORS_PER_TRACK[t] for t in range(1, track)) * 256 + sector * 256

    @staticmethod
    def linear(track, sector):
        """Linear block number, 0-based from T1/S0 -- U3 and U4 address this way."""
        return sum(SECTORS_PER_TRACK[t] for t in range(1, track)) + sector

    @staticmethod
    def from_linear(block):
        for track in range(1, 36):
            n = SECTORS_PER_TRACK[track]
            if block < n:
                return track, block
            block -= n
        raise ValueError("block past the end of the disk")

    def sector(self, track, sector):
        o = self.offset(track, sector)
        return self.data[o:o + 256]

    def error(self, track, sector):
        if not self.errmap:
            return ERROR_OK
        return self.errmap[self.linear(track, sector)]

    def bad_sectors(self):
        """[(track, sector, code)] for every sector the original could not read."""
        if not self.errmap:
            return []
        out = []
        for t in range(1, 36):
            for s in range(SECTORS_PER_TRACK[t]):
                code = self.error(t, s)
                if code != ERROR_OK:
                    out.append((t, s, code))
        return out

    # -- filesystem ------------------------------------------------------

    def directory(self):
        """[(name, type, track, sector, blocks)] for every live entry."""
        entries = []
        t, s = 18, 1
        seen = set()
        while t and (t, s) not in seen and 1 <= t <= 35:
            seen.add((t, s))
            blk = self.sector(t, s)
            for e in range(8):
                ent = blk[e * 32:(e + 1) * 32]
                if not ent[2] & 0x80:
                    continue
                name = ent[5:21].replace(b"\xa0", b"").decode("latin1")
                entries.append((name, ent[2] & 0x0F, ent[3], ent[4],
                                ent[30] | ent[31] << 8))
            t, s = blk[0], blk[1]
        return entries

    def chain(self, track, sector):
        """Follow a sector chain.  Returns (bytes, ok) -- ok is False if any
        sector in the chain is flagged bad in the error map."""
        out = bytearray()
        ok = True
        seen = set()
        while track and (track, sector) not in seen and 1 <= track <= 35:
            seen.add((track, sector))
            if self.error(track, sector) != ERROR_OK:
                ok = False
            blk = self.sector(track, sector)
            nt, ns = blk[0], blk[1]
            out += blk[2:256] if nt else blk[2:2 + max(0, ns - 1)]
            track, sector = nt, ns
        return bytes(out), ok

    def file(self, name):
        """Raw file contents including the 2-byte PRG header.  Returns
        (bytes, ok); ok is False when the file crosses unreadable sectors."""
        for ename, _type, t, s, _blocks in self.directory():
            if ename.upper() == name.upper():
                return self.chain(t, s)
        raise KeyError(f"{name!r} not found in {self.path}")

    def payload(self, name):
        """File contents with the PRG load-address header stripped.  Every
        Ultima loader here uses SETLFS with secondary address 0, so the
        stored header is discarded and the caller supplies the address."""
        data, ok = self.file(name)
        return data[2:], ok
