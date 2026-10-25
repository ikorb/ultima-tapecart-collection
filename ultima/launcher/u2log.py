"""Ultima II's save log (ultima/games/u2/u2log.s), on the host.

Two halves of PAGES pages at the save region's base: data pages 0 ..
DATA-1, one unit's version each, and the directory page DATA -- byte k the
unit in page k ($FF free, $FE dead), bytes $FE/$FF the half's generation and
its complement.  Unit 0 is the player record, unit n the driver table's
entry n - 1.  The active half is the valid one; of two, the one whose
generation is the other's plus one.
"""
PAGES = 64
DATA = PAGES - 1
HALF = PAGES * 256
FREE, DEAD = 0xFF, 0xFE


def directory(flash, base, half):
    d = base + half * HALF + DATA * 256
    return bytes(flash[d:d + 256])


def valid(flash, base, half):
    d = directory(flash, base, half)
    return d[0xFE] ^ 0xFF == d[0xFF]


def active(flash, base):
    """(half, generation), or None: no valid half, an empty log."""
    v = [valid(flash, base, h) for h in (0, 1)]
    g = [directory(flash, base, h)[0xFE] for h in (0, 1)]
    if v[0] and v[1]:
        return (1, g[1]) if (g[0] + 1) & 0xFF == g[1] else (0, g[0])
    if v[1]:
        return 1, g[1]
    if v[0]:
        return 0, g[0]
    return None


def units(flash, base):
    """{unit: flash address of its newest version}"""
    a = active(flash, base)
    if a is None:
        return {}
    half = a[0]
    out = {}
    for k, u in enumerate(directory(flash, base, half)[:DATA]):
        if u == FREE:
            break
        if u != DEAD:
            out[u] = base + half * HALF + k * 256
    return out


def find(flash, base, unit, seed):
    """Where unit's current bytes are: the log's newest, else its seed."""
    return units(flash, base).get(unit, seed)


def write(flash, base, versions, half=0, gen=0):
    """A fresh half holding `versions` [(unit, 256 bytes)], in order (for
    seeding tests; it is erased first)."""
    lo = base + half * HALF
    flash[lo:lo + HALF] = b"\xff" * HALF
    d = lo + DATA * 256
    for k, (u, data) in enumerate(versions):
        assert len(data) <= 256
        flash[lo + k * 256:lo + k * 256 + len(data)] = data
        flash[d + k] = u
    flash[d + 0xFE] = gen
    flash[d + 0xFF] = gen ^ 0xFF
