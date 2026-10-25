#!/usr/bin/env python3
"""Export and import of saved games to and from real disks (asm/page.s).

Each game's build describes, as p["xfer"], what its saved game is on the
original disks and where it is on the cart:

    [Disk(label, bam, slots, check=None), ...]     in the order to use them

A Disk is recognised by its BAM's disk name -- or another edition's
official name (`alt`: Sierra's U2 player disk, U3's 1984 Scenario disk,
U4's 1986 Britannia disk; the Trilogy's are the first) -- and the ID, where
the game itself tells disks apart by it, and optionally one more byte the
game checks (Ultima IV's disk number, T1/S0 byte 0).  A Slot is one save slot:

    Raw(base, hdr, [(t, s), ...])     sectors, block read/written ("U1"/"U2")
    File(base, hdr, name, load, lo, hi, optional)
                                      a PRG file, scratched and saved as the
                                      game does; its length within [lo, hi]

hdr: how the slot holds its data -- NONE (raw pages at the base), BYTES (the
drivers' A5 5A len16 header page, data a page on: U1, U5) or BLOCKS (A5 5A
count 00: U3) -- or LOG | unit: Ultima II's write log (u2log.py), where
the base is the unit's seed and the page looks for a newer version.  Ultima VI is different enough to be code of its own in the
page; its build hands over only the numbers that code needs.
"""
NONE, BYTES, BLOCKS = 0, 1, 2
LOG = 0x80
RAW, FILE = 1, 2


def petscii(text):
    return text.upper().encode("latin1")


class Disk:
    def __init__(self, label, bam, slots, check=None, check_id=False, alt=None):
        self.label, self.slots, self.check = label, slots, check
        self.name = bytes(bam[0x90:0xA0])
        self.alt = alt.upper().encode("latin1").ljust(16, b"\xa0") if alt else bytes(16)
        assert len(self.alt) == 16, alt
        self.id = bytes(bam[0xA2:0xA4])
        self.check_id = check_id

    def describe(self):
        return dict(label=self.label, bam_name=self.name.hex(), alt_name=self.alt.hex() if any(self.alt) else None,
                    id=self.id.hex(), check_id=self.check_id,
                    check=list(self.check) if self.check else None, slots=[sl.__dict__ for sl in self.slots])

    def data(self):
        from ultima.launcher import launcher
        out = bytearray(launcher.display(self.label) + b"\x00")
        out += self.name + self.alt + bytes([1 if self.check_id else 0]) + self.id
        t, s, off, val = self.check or (0, 0, 0, 0)
        out += bytes([t, s, off, val, len(self.slots)])
        for sl in self.slots:
            out += sl.data()
        return bytes(out)


class Raw:
    def __init__(self, base, hdr, sectors):
        self.base, self.hdr, self.sectors = base, hdr, list(sectors)

    def data(self):
        out = bytearray([RAW]) + a24(self.base) + bytes([self.hdr, len(self.sectors)])
        for t, s in self.sectors:
            out += bytes([t, s])
        return bytes(out)


class File:
    def __init__(self, base, hdr, name, load, lo, hi, optional=False):
        self.base, self.hdr, self.name = base, hdr, name
        self.load, self.lo, self.hi, self.optional = load, lo, hi, optional
        assert 0 < lo <= hi <= 0x3000, name

    def data(self):
        return (bytes([FILE]) + a24(self.base) + bytes([self.hdr]) + petscii(self.name) +
                b"\x00" + w16(self.load) + w16(self.lo) + w16(self.hi) +
                bytes([1 if self.optional else 0]))


def a24(a):
    return bytes([a & 0xFF, (a >> 8) & 0xFF, a >> 16])


def w16(v):
    return bytes([v & 0xFF, v >> 8])


def table(disks):
    return bytes([len(disks)]) + b"".join(d.data() for d in disks)
