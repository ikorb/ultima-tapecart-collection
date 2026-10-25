"""Ultima 6's write cache with an REU (ultima/games/u6/u6wc.s): the real driver --
the resident, the init's REU tail, parts A and B -- in py65 over the real
flash image, with the REU model (reumodel.py: its verify too) and the cart's.

A save that writes what the log already has writes nothing; one that
changes something writes that, and the log reads back as with no REU at
all.  Checked against the driver without an REU, save by save:

  * the same save twice: nothing written the second time;
  * one sector changed: that page and its entry; a page that differs only
    in its last byte, or in a chunk file's padding, is written;
  * a chunk file changed in its middle: the pages before it come from the
    REU's copy, the game's buffer is the game's afterwards; files that grow
    and shrink;
  * a new launch trusts no copy (the REU keeps its contents over a reset);
  * both halves of the sprite buffer, loads by name and reads of the save
    area between the writes (parts A and B swapping), and a randomised run
    against the driver without an REU;
  * a compaction where the held-back pages must be written, and a power cut
    among them, which leaves the log as it was before the command;
  * a file the game stops writing short, all of it so far the log's: the
    old file stays whole, as on a drive.

Skipped without py65.
"""
import importlib.util
import os
import random
import unittest

try:
    from ultima.sim.sim6502 import Sim, PowerCut
    from tests.reumodel import REU
except ImportError:
    Sim = None

from ultima.flash.layout import image_from
from ultima.launcher.u6log import E, KEYLEN, Log, view
from ultima.flash import regions
from ultima import paths

_spec = importlib.util.find_spec("ultima.games.u6.build")
u6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(u6)

CMD, BUF, DEST = 0xC000, 0x5000, 0x4000
FILES = {"SCC": 6, "SBB": 8, "SAE": 7, "SBA": 4}    # chunk files on 1A, their pages


def key(k):
    return k.ljust(KEYLEN, b"\x00")


def file_pages(data, chain, pad):
    """The sectors the game writes for a file: link bytes, then 254 bytes of
    data; the last one's link is 0 and the count, the rest of it `pad`."""
    pages = []
    for i, ts in enumerate(chain):
        part = data[254 * i:254 * (i + 1)]
        if i + 1 < len(chain):
            pages.append(bytes(chain[i + 1]) + part)
        else:
            pages.append((bytes([0, len(part) + 1]) + part + pad)[:256].ljust(256, b"\x00"))
    return pages


class World:
    """What a save writes: chunk files (bytes) and the save area's sectors."""

    def __init__(self, rng, files=FILES):
        self.files = {n: rng.randbytes(rng.randint(254 * (k - 2) + 1, 254 * k)) for n, k in files.items()}
        self.pads = {n: bytes(256) for n in files}
        self.sectors = {s: rng.randbytes(256) for s in range(9, 21)}

    def copy(self):
        w = World.__new__(World)
        w.files, w.pads, w.sectors = dict(self.files), dict(self.pads), dict(self.sectors)
        return w


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestU6WriteCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = u6.parts()
        cls.flash = image_from(cls.p["blobs"], regions.FLASH_SIZE)
        lo, hi = cls.p["log"]
        cls.lo, cls.mid, cls.hi = lo, lo + (hi - lo) // 2, hi
        cls.rsym = cls.p["rsym"]
        cls.reusym = u6.symbols(os.path.join(paths.BUILD, "u6reu.sym"))

    # -- harness ---------------------------------------------------------
    def machine(self, flash=None, kind="reu", reu_ram=None, log=None):
        """`game` with the driver, after the init's REU tail; kind "none": no
        REU (the plain u6bulk).  log: a u6log.Log the resident is told of."""
        sim = Sim(self.p["game"], u6.GAME_ADDR, self.rsym)
        cart = sim.attach_cart(bytearray(self.flash) if flash is None else flash)
        reu = REU(sim, kind, 512)
        if reu_ram is not None:
            reu.ram[:] = reu_ram
        sim.mem[0x27] = 0x00
        sim.mem[u6.INIT_AT:u6.INIT_AT + len(self.p["init_copy"])] = list(self.p["init_copy"])
        sim.traps[0x03FC] = lambda s: None
        sim.mem[1] = 0x34
        sim.call(self.reusym["reu_init"])
        self.assertEqual(sim.mem[self.reusym["rc_on"]], 1 if kind == "reu" else 0)
        if log is not None:
            self.tell(sim, log)
        sim.reu = reu
        return sim, cart

    def tell(self, sim, log):
        r = self.rsym
        count = (self.mid - log.dir) // E
        for name, value in (("u6_logdir", log.dir), ("u6_logdata", log.data)):
            sim.mem[r[name]:r[name] + 3] = [value & 0xFF, value >> 8 & 0xFF, value >> 16]
        sim.mem[r["u6_dircount"]:r["u6_dircount"] + 2] = [count & 0xFF, count >> 8]

    def run_cmd(self, sim, cmd, disk=None):
        if disk is not None:
            sim.mpu.x = {"1A": 0, "1B": 2}[disk]
            sim.call(0x2823)
        sim.mem[CMD:CMD + len(cmd)] = list(cmd)
        sim.mpu.x, sim.mpu.y = CMD & 0xFF, CMD >> 8
        sim.call(0x29BE)
        self.assertEqual(sim.mem[1], 0x34, "$01 not put back")
        return sim.mpu.p & 1

    def u24(self, sim, name):
        a = self.rsym[name]
        return sim.mem[a] | sim.mem[a + 1] << 8 | sim.mem[a + 2] << 16

    def log_view(self, sim, cart):
        a = self.rsym["u6_dircount"]
        return view(cart.flash, self.u24(sim, "u6_logdir"), sim.mem[a] | sim.mem[a + 1] << 8)

    def chain(self, name, n):
        t, s = self.p["starts"][name]
        extra = [(16 + i // 3, 17 + i % 3) for i in range(n - 1)]
        return [(t, s)] + extra

    def write_file(self, sim, name, data, pad, stop=None):
        n = -(-len(data) // 254)
        pages = file_pages(data, self.chain(name, n), pad)
        self.assertEqual(self.run_cmd(sim, b"!" + name.encode() + b"\xff\x00\x40", "1A"), 0)
        for i, ((t, s), pg) in enumerate(zip(self.chain(name, n), pages)):
            if stop is not None and i == stop:
                break
            sim.mem[BUF:BUF + 256] = list(pg)
            self.assertEqual(self.run_cmd(sim, bytes([0x26, t, s, 0, 0, BUF & 0xFF, BUF >> 8])), 0)
            self.assertEqual(bytes(sim.mem[BUF:BUF + 256]), pg, f"{name} page {i}: the game's buffer changed")
        return b"".join(pages)

    def save(self, sim, world, want, between=None):
        """A save as the game makes it: chunk files, the BAM, the save area.
        between(sim): run between commands (loads, reads)."""
        for name in sorted(world.files):
            want[key(b"/" + name.encode())] = self.write_file(sim, name, world.files[name], world.pads[name])
            if between:
                between(sim)
        sim.mem[BUF:BUF + 256] = list(range(256))
        self.assertEqual(self.run_cmd(sim, bytes([0x26, 18, 0, 0, 0, BUF & 0xFF, BUF >> 8]), "1A"), 0)
        for s, pg in sorted(world.sectors.items()):
            sim.mem[BUF:BUF + 256] = list(pg)
            self.assertEqual(self.run_cmd(sim, bytes([0x26, 6, s, 0, 0, BUF & 0xFF, BUF >> 8])), 0)
            self.assertEqual(bytes(sim.mem[BUF:BUF + 256]), pg)
            want[key(bytes([1, 0, 6, s]))] = pg
            if between:
                between(sim)

    def writes(self, cart, since=0):
        """Pages written (256 bytes each), entries written (20 bytes each)."""
        w = [e[2] for e in cart.log[since:] if e[0] == "write" and e[2]]
        return w.count(256), w.count(E)

    def read_back(self, sim, world):
        for name, data in world.files.items():
            self.assertEqual(self.run_cmd(sim, b"/" + name.encode() + b"\x80" + bytes([DEST & 0xFF, DEST >> 8])), 0)
            self.assertEqual(bytes(sim.mem[DEST:DEST + len(data)]), data, name)
        for s, pg in world.sectors.items():
            self.assertEqual(self.run_cmd(sim, bytes([0x5E, 6, s, 0, 0, DEST & 0xFF, DEST >> 8]), "1A"), 0)
            self.assertEqual(bytes(sim.mem[DEST:DEST + 256]), pg, f"T6 S{s}")

    # -- tests -------------------------------------------------------------
    def test_the_same_save_twice_writes_nothing_the_second_time(self):
        rng = random.Random(1)
        w = World(rng)
        sim, cart = self.machine()
        want = {}
        self.save(sim, w, want)
        pages = sum(-(-len(d) // 254) for d in w.files.values()) + 12
        self.assertEqual(self.writes(cart), (pages, len(w.files) + 12), "the first save writes everything")
        self.assertEqual(self.log_view(sim, cart), want)
        mark = len(cart.log)
        self.save(sim, w, want)
        self.assertEqual(self.writes(cart, mark), (0, 0), "an unchanged save wrote something")
        self.assertEqual(self.log_view(sim, cart), want)
        self.assertTrue(any(v[3] for v in sim.reu.verifies), "nothing was compared")
        self.read_back(sim, w)

    def test_one_sector_changed_writes_that_page_and_its_entry(self):
        rng = random.Random(2)
        w = World(rng)
        sim, cart = self.machine()
        want = {}
        self.save(sim, w, want)
        for change in (lambda pg: rng.randbytes(256), lambda pg: pg[:255] + bytes([pg[255] ^ 1]),
                       lambda pg: bytes([pg[0] ^ 0x80]) + pg[1:]):
            w.sectors[14] = change(w.sectors[14])
            mark = len(cart.log)
            self.save(sim, w, want)
            self.assertEqual(self.writes(cart, mark), (1, 1))
            self.assertEqual(self.log_view(sim, cart), want)
        self.read_back(sim, w)

    def test_a_chunk_file_changed_in_its_middle(self):
        """Its pages before the change are written from the REU's copy; the
        whole file is in the log, each page right, and the game's buffer is
        its own after every command (write_file checks it)."""
        rng = random.Random(3)
        w = World(rng)
        w.files["SCC"] = rng.randbytes(254 * 3 + 100)              # 4 pages
        sim, cart = self.machine()
        want = {}
        self.save(sim, w, want)
        for at in (254 * 2 + 10, 254 * 3 + 5, 7, 254 + 253):        # page 2, 3, 0, 1
            d = bytearray(w.files["SCC"])
            d[at] ^= 0x55
            w.files["SCC"] = bytes(d)
            mark = len(cart.log)
            self.save(sim, w, want)
            self.assertEqual(self.writes(cart, mark), (4, 1), at)
            self.assertEqual(self.log_view(sim, cart), want, at)
        self.read_back(sim, w)

    def test_the_padding_of_a_last_page_is_written_too(self):
        rng = random.Random(4)
        w = World(rng)
        sim, cart = self.machine()
        want = {}
        self.save(sim, w, want)
        w.pads["SAE"] = bytes([0xEE]) * 256
        mark = len(cart.log)
        self.save(sim, w, want)
        n = -(-len(w.files["SAE"]) // 254)
        self.assertEqual(self.writes(cart, mark), (n, 1))
        self.assertEqual(self.log_view(sim, cart), want)

    def test_files_that_grow_and_shrink(self):
        rng = random.Random(5)
        w = World(rng)
        sim, cart = self.machine()
        want = {}
        source = rng.randbytes(254 * 8)
        for size in (254 * 2 + 3, 254 * 4 + 1, 254 * 6, 254 + 1, 254 + 1, 30, 254 * 3, 254 * 3):
            w.files["SBB"] = source[:size]                           # a prefix of the old, or longer
            mark = len(cart.log)
            self.save(sim, w, want)
            self.assertEqual(self.log_view(sim, cart), want, size)
            self.read_back(sim, w)
        self.assertEqual(self.writes(cart, mark), (0, 0), "the same 3 pages again")

    def test_a_file_longer_than_its_slot_is_written_every_time(self):
        """Its slot (build.py: the file's pages and one) cannot hold it: no copy,
        so no compare -- written every time, and right."""
        rng = random.Random(6)
        w = World(rng)
        cap = self.slot("SBA")[2]
        w.files["SBA"] = rng.randbytes(254 * cap + 10)              # cap + 1 pages
        sim, cart = self.machine()
        want = {}
        self.save(sim, w, want)
        mark = len(cart.log)
        self.save(sim, w, want)
        self.assertEqual(self.writes(cart, mark), (cap + 1, 1))
        self.assertEqual(self.log_view(sim, cart), want)
        self.read_back(sim, w)

    def test_a_long_file_never_counts_past_its_slot(self):
        """A file longer than its slot has no copy: else its pages past the slot
        would be compared with the next slot's copy.  Here that copy (a
        one-page file's) is just what the long file's last page becomes, and
        it must still be written."""
        slots = {n: self.slot(n) for n in self.p["starts"]}
        pair = [(x, y) for x, (page, bank, cap, _i) in slots.items() for y, sl in slots.items()
                if x[0] == y[0] == "S" and sl[1] == bank and sl[0] == page + cap and sl[2] == 2]
        self.assertTrue(pair, "no long file followed by a one-page file's slot")
        x, y = pair[0]
        rng = random.Random(40)
        sim, cart = self.machine()
        want = {}
        ydata = rng.randbytes(150)
        want[key(b"/" + y.encode())] = self.write_file(sim, y, ydata, bytes(256))
        cap = slots[x][2]
        head = rng.randbytes(254 * cap)
        want[key(b"/" + x.encode())] = self.write_file(sim, x, head + rng.randbytes(150), bytes(256))
        mark = len(cart.log)
        want[key(b"/" + x.encode())] = self.write_file(sim, x, head + ydata, bytes(256))   # last page = y's
        self.run_cmd(sim, bytes([0x26, 6, 9, 0, 0, BUF & 0xFF, BUF >> 8]), "1A")
        want[key(bytes([1, 0, 6, 9]))] = bytes(sim.mem[BUF:BUF + 256])
        self.assertEqual(self.writes(cart, mark), (cap + 2, 3))   # (the `!` closes the first x)
        self.assertEqual(self.log_view(sim, cart), want)

    def slot(self, name):
        sdir = self.p["sdir"]
        for i in range(self.p["entries"]):
            e = self.flash[sdir + i * E:sdir + (i + 1) * E]
            if e[:KEYLEN] == key(b"!" + name.encode()):
                return e[13], e[14], e[15], e[16]               # page, bank, pages, index
        raise KeyError(name)

    def test_every_chunk_file_has_a_slot_of_its_own(self):
        used, counts = set(), set()
        for name in self.p["starts"]:
            page, bank, n, ix = self.slot(name)
            self.assertIn(bank, (2, 3), name)
            self.assertLessEqual(page + n, 0x100, name)
            self.assertGreaterEqual(n, 2, name)
            pages = {(bank, page + i) for i in range(n)}
            self.assertFalse(pages & used, name)
            used |= pages
            self.assertNotIn(ix, counts)
            self.assertLess(ix, 0x80)
            counts.add(ix)
            if bank == 2:
                self.assertGreaterEqual(page, self.p["pages"] - 512, f"{name}: the read cache's pages")
                self.assertLess(page + n, 0xC0 + 9, f"{name}: the save area's copies")
            else:
                self.assertGreaterEqual(page, 4, f"{name}: the flags and counts")

    def test_a_new_launch_trusts_no_copy(self):
        """The REU keeps what it holds over a reset; the init forgets it."""
        rng = random.Random(7)
        w = World(rng)
        sim, cart = self.machine()
        want = {}
        self.save(sim, w, want)
        log = Log(cart.flash, self.lo, self.mid, self.u24(sim, "u6_logdir"), self.u24(sim, "u6_logdata"))
        sim2, cart2 = self.machine(cart.flash, reu_ram=sim.reu.ram, log=log)
        mark = len(cart2.log)
        self.save(sim2, w, want)
        pages = sum(-(-len(d) // 254) for d in w.files.values()) + 12
        self.assertEqual(self.writes(cart2, mark), (pages, len(w.files) + 12))
        self.assertEqual(self.log_view(sim2, cart2), want)

    def test_parts_a_and_b_swap_over_loads_reads_and_both_halves(self):
        """Between the save's commands: a load by name (part A's) and a read of
        the save area (part A's too, the session left open); and every other
        save in the other half, as after frames drawn ($2823 drops the half)."""
        rng = random.Random(8)
        w = World(rng)
        sim, cart = self.machine()
        want = {}
        from tests.test_u6_driver import chain_bytes
        talk = chain_bytes(self.p["disks"]["2A"], "T005")

        def between(s):
            self.assertEqual(self.run_cmd(s, b"/T005\x80" + bytes([DEST & 0xFF, DEST >> 8])), 0)
            self.assertEqual(bytes(s.mem[DEST:DEST + len(talk)]), talk)
            self.assertEqual(self.run_cmd(s, bytes([0x5E, 6, 9, 0, 0, DEST & 0xFF, DEST >> 8]), "1A"), 0)

        for k in range(6):
            sim.mem[0x27] = 0x10 * (k & 1)
            if k == 3:
                w.files["SCC"] = rng.randbytes(254 * 2 + 9)
                w.sectors[20] = rng.randbytes(256)
            mark = len(cart.log)
            self.save(sim, w, want, between)
            self.assertEqual(self.log_view(sim, cart), want, k)
            if k in (1, 2, 4, 5):
                self.assertEqual(self.writes(cart, mark), (0, 0), k)
        self.read_back(sim, w)
        self.assertEqual(sim.reu.io_hits, 0, "a DMA reached the chips")

    def test_against_the_driver_without_an_reu(self):
        """Random saves -- files changed, grown, shrunk, padded, sectors
        changed -- the same on both: the log reads the same after each, and
        the REU's never writes more."""
        rng = random.Random(9)
        w = World(rng)
        a, ca = self.machine()
        b, cb = self.machine(kind="none")
        wa, wb = {}, {}
        for k in range(12):
            for name in w.files:
                r = rng.random()
                d = bytearray(w.files[name])
                if r < 0.3:
                    d[rng.randrange(len(d))] ^= 1 << rng.randrange(8)
                elif r < 0.4:
                    d += rng.randbytes(rng.randint(1, 300))
                elif r < 0.5 and len(d) > 300:
                    del d[rng.randint(260, len(d)):]
                elif r < 0.55:
                    w.pads[name] = rng.randbytes(256)
                w.files[name] = bytes(d)
            for s in rng.sample(range(9, 21), rng.randint(0, 6)):
                w.sectors[s] = rng.randbytes(256)
            half = 0x10 * rng.randrange(2)
            a.mem[0x27] = b.mem[0x27] = half
            ma, mb = len(ca.log), len(cb.log)
            self.save(a, w, wa)
            self.save(b, w, wb)
            self.assertEqual(wa, wb)
            self.assertEqual(self.log_view(a, ca), wa, k)
            self.assertEqual(self.log_view(b, cb), wb, k)
            self.assertLessEqual(self.writes(ca, ma)[0], self.writes(cb, mb)[0])
        self.read_back(a, w)
        self.read_back(b, w)

    def fill(self, sim, cart, free):
        """Junk in the log (keys no save uses, four of them, so a compaction
        has room to make) until at most `free` pages are left; the resident
        is told."""
        log = Log(cart.flash, self.lo, self.mid, self.u24(sim, "u6_logdir"), self.u24(sim, "u6_logdata"))
        junk = {}
        n = 0
        while log.free() > free:
            k = b"/ZZ%03d" % (n % 4)
            pg = bytes([n & 0xFF]) * 256
            log.append(k, [pg], True)
            junk[key(k)] = pg
            n += 1
        self.tell(sim, log)
        return junk

    def test_a_compaction_before_the_held_back_pages_are_written(self):
        """A file's first two pages are the log's, its third is not, and the
        log has no room for three: the compaction comes before any of them
        (the command again), then all three are written -- for a few fill
        levels, some of which need no compaction."""
        packed = set()
        for free in (2, 3, 4, 5, 6, 7, 8):
            with self.subTest(free=free):
                rng = random.Random(10 + free)
                w = World(rng)
                w.files["SCC"] = rng.randbytes(254 * 2 + 40)       # 3 pages
                sim, cart = self.machine()
                want = {}
                self.save(sim, w, want)
                want.update(self.fill(sim, cart, free))
                d = bytearray(w.files["SCC"])
                d[254 * 2 + 3] ^= 0xFF
                w.files["SCC"] = bytes(d)
                mark = len(cart.log)
                want[key(b"/SCC")] = self.write_file(sim, "SCC", w.files["SCC"], w.pads["SCC"])
                erases = [c for c in cart.log[mark:] if c[0] == "erase"]
                self.assertIn(len(erases), (0, 64), "more than one compaction")
                if erases:
                    packed.add(free)
                self.run_cmd(sim, bytes([0x26, 6, 9, 0, 0, BUF & 0xFF, BUF >> 8]), "1A")  # closes it
                w.sectors[9] = want[key(bytes([1, 0, 6, 9]))] = bytes(sim.mem[BUF:BUF + 256])
                self.assertEqual(self.log_view(sim, cart), want)
                self.read_back(sim, w)
        self.assertTrue(packed and packed != {2, 3, 4, 5, 6, 7, 8}, packed)

    def test_a_power_cut_among_the_held_back_pages(self):
        """Cut the power at every write of a file whose third page differs
        (its first two written from the REU's copy): the log at the next boot
        is the log before the file, as on a drive."""
        def first():
            rng = random.Random(20)
            w = World(rng)
            w.files["SCC"] = rng.randbytes(254 * 3 + 40)           # 4 pages
            sim, cart = self.machine()
            self.save(sim, w, {})
            d = bytearray(w.files["SCC"])
            d[254 * 2 + 3] ^= 0xFF
            w.files["SCC"] = bytes(d)
            return w, sim, cart

        w, sim, cart = first()
        before = self.log_view(sim, cart)
        start = cart.changes
        self.write_file(sim, "SCC", w.files["SCC"], w.pads["SCC"])
        total = cart.changes - start
        self.assertEqual(total, 4 * 256, "four pages, the entry only at the next command")
        for k in sorted({0, 1, 255, 256, 257, 511, 512, 513, 767, 768, 769, total - 1}
                        | set(range(0, total, total // 7))):
            with self.subTest(cut=k):
                w, s2, c2 = first()
                c2.cut_after = c2.changes + k
                with self.assertRaises(PowerCut):
                    self.write_file(s2, "SCC", w.files["SCC"], w.pads["SCC"])
                bsim, bcart = self.boot(c2.flash)
                b = self.p["bsym"]
                n = bsim.mem[b["u6_dircount"]] | bsim.mem[b["u6_dircount"] + 1] << 8
                dd = sum(bsim.mem[b["u6_logdir"] + i] << 8 * i for i in range(3))
                self.assertEqual(view(bcart.flash, dd, n), before)

    def boot(self, flash):
        sim = Sim(self.p["boot_image"], 0xC000, self.p["bsym"])
        sim.mem[0xC578:0xC578 + len(self.p["boot_piece2"])] = list(self.p["boot_piece2"])
        sim.mem[u6.INIT_ADDR:u6.INIT_ADDR + len(self.p["init"])] = list(self.p["init"])
        cart = sim.attach_cart(flash)
        isym = u6.symbols(os.path.join(paths.BUILD, "init_u6.sym"))
        sim.traps[isym["tc_getbyte_guard"]] = sim.traps[self.p["bsym"]["tc_getbyte"]]
        sim.traps[0xC00C] = lambda s: None
        sim.mem[0x01] = 0x35
        sim.call(u6.INIT_ADDR)
        return sim, cart

    def test_a_file_stopped_short_keeps_the_old_one_whole(self):
        """Two of a file's three pages sent, both the log's, then the next
        command: nothing is written, and the old file reads back whole -- as
        on a drive, where the same sectors keep the same bytes.  (Without an
        REU the cart writes the two pages as the file, cut short.)"""
        rng = random.Random(30)
        w = World(rng)
        w.files["SCC"] = rng.randbytes(254 * 2 + 40)
        sim, cart = self.machine()
        want = {}
        self.save(sim, w, want)
        mark = len(cart.log)
        self.write_file(sim, "SCC", w.files["SCC"], w.pads["SCC"], stop=2)
        self.run_cmd(sim, bytes([0x26, 6, 9, 0, 0, BUF & 0xFF, BUF >> 8]), "1A")
        self.assertEqual(self.writes(cart, mark)[0], 1, "only the sector")
        self.assertEqual(self.log_view(sim, cart)[key(b"/SCC")], want[key(b"/SCC")])
        self.assertEqual(self.run_cmd(sim, b"/SCC\x80" + bytes([DEST & 0xFF, DEST >> 8])), 0)
        self.assertEqual(bytes(sim.mem[DEST:DEST + len(w.files["SCC"])]), w.files["SCC"])


if __name__ == "__main__":
    unittest.main()
