"""Ultima 6's write log, from the host side: what the game's driver writes
(u6core.s) and what the init segment reads and compacts (asm/init_u6.s).

Used by tests/test_u6_boot.py and u6_compact_check.py to lay down a log the
way a long game would, without playing one.
"""
KEYLEN, DATALEN = 12, 8
E = KEYLEN + DATALEN
F_LINKS = 0x02
RESERVE = 128                   # init_u6.s: compact below this many free pages


def a24(a):
    return bytes([a & 0xFF, (a >> 8) & 0xFF, a >> 16])


class Log:
    """Writes one half of the log as the game's driver does: pages up from
    the base, 20-byte entries down from the top, newest lowest."""

    def __init__(self, flash, base, top, logdir=None, logdata=None):
        self.flash, self.base, self.top = flash, base, top
        self.dir = top if logdir is None else logdir
        self.data = base if logdata is None else logdata

    def free(self):
        return (self.dir >> 8) - (self.data >> 8)

    def entry(self, e):
        self.dir -= E
        assert self.flash[self.dir:self.dir + E] == b"\xff" * E
        self.flash[self.dir:self.dir + E] = e

    def append(self, key, pages, links):
        addr = self.data
        for pg in pages:
            assert self.flash[self.data:self.data + 256] == b"\xff" * 256
            self.flash[self.data:self.data + 256] = pg
            self.data += 256
        n = len(pages) if links else 0
        self.entry(key.ljust(KEYLEN, b"\x00") + a24(addr) +
                   bytes([n & 0xFF, n >> 8, F_LINKS if links else 0, 0, 0]))

    def header(self, gen):
        self.entry(b"\xfeLOG".ljust(KEYLEN, b"\x00") +
                   bytes([gen & 0xFF, gen >> 8, ~gen & 0xFF, ~gen >> 8 & 0xFF]) + bytes(4))


def play(log, rng, want, until_free, files=12, per_save=4, size=(1, 4)):
    """Saves, as the game makes them, until fewer than `until_free` pages
    are left: a few chunk files and the save area (the BAM write is
    dropped, see M_BAM).  `want` tracks the
    newest version of every key."""
    names = [b"/S" + bytes([65 + i // 26, 65 + i % 26]) for i in range(files)]
    while log.free() >= until_free:
        for name in rng.sample(names, per_save):
            pages = [rng.randbytes(256) for _ in range(rng.randint(*size))]
            log.append(name, pages, True)
            want[name.ljust(KEYLEN, b"\x00")] = b"".join(pages)
        for key in [bytes([1, 0, 6, s]) for s in range(9, 21)]:
            pg = rng.randbytes(256)
            log.append(key, [pg], False)
            want[key.ljust(KEYLEN, b"\x00")] = pg


def view(flash, logdir, count):
    """What the log says, read the way DIR_LOOKUP reads it: `count` entries
    from `logdir` up, the first match for a key wins."""
    out = {}
    for i in range(count):
        e = flash[logdir + i * E:logdir + (i + 1) * E]
        k = bytes(e[:KEYLEN])
        if k[0] == 0xFE or k in out:
            continue
        addr = e[12] | e[13] << 8 | e[14] << 16
        pages = (e[15] | e[16] << 8) if e[17] & F_LINKS else 1
        out[k] = bytes(flash[addr:addr + 256 * pages])
    return out
