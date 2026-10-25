#!/usr/bin/env python3
"""Played world data put back from what the same disk records.

A game that keeps its world on a disk writes into it as it is played.  Where
the disk itself records what each write covered, the scanner
(ultima/disks/scan.py) puts it back and offers the result as a source for
the world's sectors.  The sectors must still match the reference's hashes,
so a rule here can only make a disk acceptable, never change what the cart
gets.

Ultima III's Sosaria (disk B: SOSA, blocks 296-311; SOSM, block 312).  What
ULT3 writes into SOSA and where the tile underneath is kept
(docs/reversing-notes/u3.md, "The pristine state"):

  a monster        SOSM entry n (tile +n, x +$40+n, y +$60+n): the tile under
                   it at +$20+n
  a chest          where a monster dies on land ($525D): $24 + ((under >> 2)
                   & 3), so $25-$27 hold grass, brush and forest; $24
                   (mountains, a floor ...) is ambiguous and stays
  a parked craft   X-it ($6951) parks on a square below $05: a frigate sails
                   only on water and the whirlpool, so it stands on water; a
                   horse cannot stand on water, so it stands on grass
  the whirlpool    moves only onto water (or a frigate) and writes water
                   behind it ($74C3)
  the moon gate    $6EBA writes grass on all eight gate squares, then the gate
                   on the phase's; an unplayed map has it at (15, 29)

Monsters go first: one may stand on a chest, a craft or a gate.
"""

U3B = "u3b"
SOSA_FIRST, SOSA_BLOCKS, SOSM_BLOCK = 296, 16, 312

CHESTS = {0x25: 0x04, 0x26: 0x08, 0x27: 0x0C}
HORSE, FRIGATE, WHIRLPOOL, MOON_GATE = 0x28, 0x2C, 0x30, 0x88
GRASS, WATER = 0x04, 0x00
GATE_UNPLAYED = (15, 29)


def u3_sosa(sosa, sosm):
    """SOSA (4096 bytes) with what play wrote into it put back, from SOSM."""
    out = bytearray(sosa)
    for n in range(32):
        if sosm[n]:
            out[(sosm[0x60 + n] & 63) * 64 + (sosm[0x40 + n] & 63)] = sosm[0x20 + n]
    for i, v in enumerate(out):
        if v in CHESTS:
            out[i] = CHESTS[v]
        elif v in (HORSE, MOON_GATE):
            out[i] = GRASS
        elif v in (FRIGATE, WHIRLPOOL):
            out[i] = WATER
    x, y = GATE_UNPLAYED
    out[y * 64 + x] = MOON_GATE
    return bytes(out)


WHY = {U3B: "a played Player Master: Sosaria's monsters, chests, craft, whirlpool and "
            "moon gate put back from what the disk records"}


def put_back(disk, data):
    """{block: rule} for the world blocks of image bytes `data` that the
    disk's rules change, a rule as scan.reset() takes it ({"set": {offset:
    byte}, "why": ...}); {} for a disk without rules or an image too short."""
    if disk != U3B or len(data) < (SOSM_BLOCK + 1) * 256:
        return {}
    sosa = data[SOSA_FIRST * 256:(SOSA_FIRST + SOSA_BLOCKS) * 256]
    new = u3_sosa(sosa, data[SOSM_BLOCK * 256:(SOSM_BLOCK + 1) * 256])
    rules = {}
    for b in range(SOSA_BLOCKS):
        sets = {o: new[b * 256 + o] for o in range(256) if new[b * 256 + o] != sosa[b * 256 + o]}
        if sets:
            rules[SOSA_FIRST + b] = {"set": sets, "why": WHY[disk]}
    return rules
