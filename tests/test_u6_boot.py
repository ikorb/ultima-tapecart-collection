"""Run Ultima 6's boot side -- the patched $C000 image, the boot driver's
second piece and the init stub -- on the host, against the real flash image.

As in test_u6_driver.py, py65 runs the real code and the tapecart is a model
of its command interpreter behind tc_sendbyte/tc_getbyte (the boot driver's
own, here).  Checked: the init stub's log scan, the resident loader's own
descriptor chains ($C0B6), character creation's save-area writes and the
world reset they trigger, and the hand-off of the log to `game`'s driver.

Skipped without py65 (the repository's .venv has it).
"""
import importlib.util
import os
import unittest

try:
    from ultima.sim.sim6502 import Sim, PowerCut
except ImportError:
    Sim = None
import random
from pathlib import Path

from ultima.launcher.u6log import E, Log, RESERVE, play, view

from ultima.flash.layout import image_from
from ultima.flash import regions

_spec = importlib.util.find_spec("ultima.games.u6.build")
u6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(u6)


def file_bytes(d, name):
    for n, _t, t, s, _b in d.directory():
        if n == name:
            return d.chain(t, s)[0]
    raise KeyError(name)


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestU6Boot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = u6.parts()
        cls.flash = image_from(cls.p["blobs"], regions.FLASH_SIZE)

    @property
    def isym(self):
        import re
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "build", "init_u6.sym")
        return {m.group(1): int(m.group(2), 16)
                for m in re.finditer(r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path(path).read_text())}

    def boot(self, flash=None, cut=None):
        sim = Sim(self.p["boot_image"], 0xC000, self.p["bsym"])
        sim.mem[0xC578:0xC578 + len(self.p["boot_piece2"])] = list(self.p["boot_piece2"])
        sim.mem[u6.INIT_ADDR:u6.INIT_ADDR + len(self.p["init"])] = list(self.p["init"])
        cart = sim.attach_cart(flash if flash is not None else self.flash)
        cart.cut_after = cut
        # the compaction's own 2-bit receive (init_u6.s g_read): the cart's
        # bytes, as for the boot driver's 1-bit one
        sim.traps[self.isym["tc_getbyte_guard"]] = sim.traps[self.p["bsym"]["tc_getbyte"]]
        # the init segment ends in JMP $C00C: stop there
        sim.traps[0xC00C] = lambda s: None
        sim.mem[0x01] = 0x35
        sim.mem[0xD020:0xD022] = [0x0E, 0x06]              # the menu's colours
        sim.mem[0xD800:0xDC00] = [0x0E] * 0x400
        try:
            sim.call(u6.INIT_ADDR)
        finally:
            self._cut_flash = cart.flash      # what a power cut left behind
        return sim, cart

    def u24(self, sim, name):
        a = self.p["bsym"][name]
        return sim.mem[a] | sim.mem[a + 1] << 8 | sim.mem[a + 2] << 16

    def test_init_finds_an_empty_log(self):
        """A fresh cart: both halves erased, so the log starts in half 0."""
        sim, _cart = self.boot()
        lo, hi = self.p["log"]
        self.assertEqual(self.u24(sim, "u6_logdir"), lo + (hi - lo) // 2)
        self.assertEqual(self.u24(sim, "u6_logdata"), lo)
        a = self.p["bsym"]["u6_dircount"]
        self.assertEqual(sim.mem[a] | sim.mem[a + 1] << 8, 0)

    def test_the_game_chain_loads(self):
        """$C054 loads the chain at $C0F1 -- GAME, COLORS, TILEFLAGS, CHARS,
        POINTER -- with the descriptors' own addresses, headers dropped."""
        sim, _cart = self.boot()
        sim.mpu.x, sim.mpu.y = 0xF1, 0xC0
        sim.call(0xC16B)
        self.assertEqual(sim.mpu.p & 1, 0, "carry set: a name was not found")
        d = self.p["disks"]["3B"]
        game = self.p["game"]
        self.assertEqual(bytes(sim.mem[0x0200:0x0200 + len(game)]), game)
        for name, dest in (("COLORS", 0xA000), ("TILEFLAGS", 0xA200), ("CHARS", 0xD000),
                           ("POINTER", 0xFF40)):
            want = file_bytes(d, name)[2:]
            self.assertEqual(bytes(sim.mem[dest:dest + len(want)]), want, name)
        self.assertEqual(sim.mem[0x01], 0x35)

    def test_theme_and_tiles(self):
        sim, _cart = self.boot()
        for ptr, name, dest in ((0xC0B6, "THEME", 0x9000), (0xC124, "TILES", 0x6000)):
            sim.mpu.x, sim.mpu.y = ptr & 0xFF, ptr >> 8
            sim.call(0xC16B)
            want = file_bytes(self.p["disks"]["3B"], name)[2:]
            self.assertEqual(bytes(sim.mem[dest:dest + len(want)]), want, name)

    def test_character_creation_resets_the_world_once(self):
        """create writes the save area with `& 6 9..20` through $C009.  The
        first of those erases the log (a fresh copy of the disks, in cart
        terms); the rest append.  Then a read of the save area returns it."""
        flash = bytearray(self.flash)
        lo, hi = self.p["log"]
        flash[lo:lo + 0x100] = b"\x00" * 0x100            # a stale log page
        sim, cart = self.boot(flash)
        erases = []
        for sec in range(9, 21):
            sim.mem[0x5000:0x5100] = [sec] * 256
            cmd = bytes([0x26, 6, sec, 0, 0, 0x00, 0x50])
            sim.mem[0xC900:0xC900 + len(cmd)] = list(cmd)
            sim.mpu.x, sim.mpu.y = 0x00, 0xC9
            sim.call(0xC16B)
            self.assertEqual(sim.mpu.p & 1, 0)
        erased = [a for kind, a, *_ in cart.log if kind == "erase"]
        self.assertEqual(len(erased), (hi - lo) // 0x1000, "the whole log, once")
        cmd = bytes([0x5E, 6, 12, 0, 0, 0x00, 0x40])
        sim.mem[0xC900:0xC900 + len(cmd)] = list(cmd)
        sim.mpu.x, sim.mpu.y = 0x00, 0xC9
        sim.call(0xC16B)
        self.assertEqual(bytes(sim.mem[0x4000:0x4100]), bytes([12] * 256))
        # and a reboot finds those twelve entries
        sim2, _ = self.boot(cart.flash)
        a = self.p["bsym"]["u6_dircount"]
        self.assertEqual(sim2.mem[a] | sim2.mem[a + 1] << 8, 12)
        self.assertEqual(self.u24(sim2, "u6_logdata"), lo + 12 * 0x100)

    # -- the two halves and compaction -----------------------------------
    def halves(self):
        lo, hi = self.p["log"]
        return lo, lo + (hi - lo) // 2, hi

    def view(self, sim, flash):
        a = self.p["bsym"]["u6_dircount"]
        return view(flash, self.u24(sim, "u6_logdir"), sim.mem[a] | sim.mem[a + 1] << 8)

    def check_appendable(self, sim, flash):
        """Between the next free page and the directory: all erased."""
        data, d = self.u24(sim, "u6_logdata"), self.u24(sim, "u6_logdir")
        self.assertLess(data, d)
        self.assertEqual(data & 0xFF, 0)
        self.assertEqual(flash[data:d], b"\xff" * (d - data))

    def full_log(self, seed=6):
        flash = bytearray(self.flash)
        lo, mid, _hi = self.halves()
        want = {}
        play(Log(flash, lo, mid), random.Random(seed), want, RESERVE)
        return flash, want

    def test_a_log_with_room_is_left_alone(self):
        flash = bytearray(self.flash)
        lo, mid, _hi = self.halves()
        want = {}
        log = Log(flash, lo, mid)
        play(log, random.Random(1), want, 400)
        sim, cart = self.boot(flash)
        self.assertEqual([c for c in cart.log if c[0] in ("erase", "write")], [])
        self.assertEqual(self.u24(sim, "u6_logdir"), log.dir)
        self.assertEqual(self.u24(sim, "u6_logdata"), log.data)
        self.assertEqual(self.view(sim, cart.flash), want)

    def test_a_full_log_is_compacted_into_the_other_half(self):
        flash, want = self.full_log()
        lo, mid, hi = self.halves()
        sim, cart = self.boot(flash)
        f = cart.flash
        self.assertEqual(self.view(sim, f), want)
        self.assertTrue(mid <= self.u24(sim, "u6_logdir") < hi, "not in half 1")
        self.assertEqual(f[lo:mid], b"\xff" * (mid - lo), "the old half was not erased")
        self.assertEqual(f[hi - E:hi - E + 16], b"\xfeLOG" + bytes(8) + bytes([1, 0, 0xFE, 0xFF]))
        a = self.p["bsym"]["u6_dircount"]
        self.assertEqual(sim.mem[a] | sim.mem[a + 1] << 8, len(want) + 1)
        self.assertEqual(self.u24(sim, "u6_logdata"), mid + sum(len(v) for v in want.values()))
        self.check_appendable(sim, f)
        bar = 0x0400 + 40 * 14 + 5
        self.assertEqual(bytes(sim.mem[bar:bar + 30]), b"\xa0" * 30, "the bar did not fill")
        # a second boot finds it as it is
        sim2, cart2 = self.boot(f)
        self.assertEqual([c for c in cart2.log if c[0] in ("erase", "write")], [])
        self.assertEqual(self.view(sim2, cart2.flash), want)

    def test_and_back_into_half_0(self):
        flash, want = self.full_log()
        lo, mid, hi = self.halves()
        sim, cart = self.boot(flash)
        f = bytearray(cart.flash)
        play(Log(f, mid, hi, self.u24(sim, "u6_logdir"), self.u24(sim, "u6_logdata")),
             random.Random(7), want, RESERVE)
        sim2, cart2 = self.boot(f)
        self.assertEqual(self.view(sim2, cart2.flash), want)
        self.assertTrue(lo <= self.u24(sim2, "u6_logdir") < mid, "not in half 0")
        self.assertEqual(cart2.flash[mid - E + 12:mid - E + 16], bytes([2, 0, 0xFD, 0xFF]))
        self.assertEqual(cart2.flash[mid:hi], b"\xff" * (hi - mid))
        self.check_appendable(sim2, cart2.flash)

    def test_the_worst_case_every_chunk_file_live(self):
        """All 84 chunk files saved (208 blocks on the disks), plus the save
        area: 96 live keys, about 225 pages.  (Logs written before M_BAM
        also carry the two BAMs: 98 at most, well under LIVEMAX.)"""
        flash = bytearray(self.flash)
        lo, mid, hi = self.halves()
        want = {}
        log = Log(flash, lo, mid)
        play(log, random.Random(3), want, 400, files=84, per_save=84, size=(2, 3))
        play(log, random.Random(4), want, RESERVE, files=84, per_save=8, size=(2, 3))
        self.assertEqual(len(want), 84 + 12)
        sim, cart = self.boot(flash)
        self.assertTrue(mid <= self.u24(sim, "u6_logdir") < hi)
        self.assertEqual(self.view(sim, cart.flash), want)
        self.check_appendable(sim, cart.flash)
        pages = sum(len(v) for v in want.values()) // 256
        free = (self.u24(sim, "u6_logdir") >> 8) - (self.u24(sim, "u6_logdata") >> 8)
        self.assertGreater(free, RESERVE, "a compacted log would compact again")
        print(f"\n  worst case: {pages} live pages, {free} free after compaction", end=" ")

    def test_the_higher_generation_wins_and_a_torn_header_loses(self):
        lo, mid, hi = self.halves()
        for g0, g1, torn, active in ((5, 4, False, 0), (4, 5, False, 1), (4, 5, True, 0)):
            flash = bytearray(self.flash)
            l0, l1 = Log(flash, lo, mid), Log(flash, mid, hi)
            l0.header(g0)
            l1.header(g1)
            l0.append(b"/A", [b"\x00" * 256], True)
            l1.append(b"/A", [b"\x11" * 256], True)
            if torn:                        # its complement's low byte never came
                flash[hi - E + 14] = 0xFF
            sim, _ = self.boot(flash)
            d = self.u24(sim, "u6_logdir")
            self.assertEqual(d, (l0, l1)[active].dir, (g0, g1, torn))

    def test_a_power_cut_anywhere_in_a_compaction_loses_nothing(self):
        """Cut the power after N changes to the flash -- a byte written or a
        block erased -- for N across every stage: the target's erase, the
        copy, the header byte by byte, the old half's erase.  The next boot
        must find everything, and a log it can append to."""
        flash, want = self.full_log()
        _sim, cart = self.boot(flash)
        total = cart.changes
        blocks = (self.halves()[1] - self.halves()[0]) // 0x1000
        self.assertEqual(total, 2 * blocks + sum(len(v) for v in want.values())
                         + (len(want) + 1) * E, "not exactly one compaction")
        before_header = total - blocks - E
        cuts = [0, 1, blocks - 1, blocks, blocks + 300, before_header - 1000,
                before_header - 1, before_header, before_header + 1,
                before_header + 12, before_header + 14, before_header + 15,
                before_header + 16, before_header + E - 1, total - blocks,
                total - blocks + 1, total - 1]
        for n in cuts:
            with self.subTest(cut=n):
                with self.assertRaises(PowerCut):
                    self.boot(flash, cut=n)
                sim, cart = self.boot(self._cut_flash)
                self.assertEqual(self.view(sim, cart.flash), want)
                self.check_appendable(sim, cart.flash)

    def test_a_torn_entry_does_not_move_the_next_free_page(self):
        """The newest entry's address half written: its pages would end far
        past the directory.  The next free page comes from the entry before."""
        flash = bytearray(self.flash)
        lo, mid, _hi = self.halves()
        log = Log(flash, lo, mid)
        log.append(b"/SAA", [b"\x01" * 256] * 3, True)
        good = log.data
        log.append(b"/SAB", [b"\x02" * 256], True)
        flash[log.dir + 14] = 0x1F          # its address: $1Fxx00, not in the half
        flash[good:good + 256] = b"\xff" * 256   # (and its page never landed)
        sim, _ = self.boot(flash)
        self.assertEqual(self.u24(sim, "u6_logdata"), good)
        self.assertEqual(self.u24(sim, "u6_logdir"), log.dir)

    def test_the_screen_is_black_until_the_opening(self):
        """Border, background and all of colour RAM black at $C00C, so
        nothing the boot loads into the text screen shows -- after a
        compaction too, whose message was white."""
        for flash in (None, self.full_log()[0]):
            sim, _ = self.boot(flash)
            self.assertEqual((sim.mem[0xD020], sim.mem[0xD021]), (0, 0))
            self.assertEqual(bytes(sim.mem[0xD800:0xDBE8]), bytes(1000))

    def test_init_skips_pages_a_torn_save_left(self):
        flash = bytearray(self.flash)
        lo, _hi = self.p["log"]
        flash[lo:lo + 0x200] = b"\x12" * 0x200            # two pages, no entry
        sim, _ = self.boot(flash)
        self.assertEqual(self.u24(sim, "u6_logdata"), lo + 0x200)

    def test_the_handoff_tells_game_where_the_log_is(self):
        """Into `game`'s own variables, wherever they are -- and nothing else.
        (The first version copied eight adjacent bytes; in `game` the next
        free page is not adjacent to the directory, and the copy overwrote
        the keyboard scan at $28CE -- the CPU jammed on entering it.)"""
        sim, _cart = self.boot()
        sim.mem[0x0200:0x0200 + len(self.p["game"])] = list(self.p["game"])
        before = bytes(sim.mem[0x0200:0x0200 + len(self.p["game"])])
        sim.traps[0x4400] = lambda s: None                # JMP $4400, the relocated init: stop
        b = self.p["bsym"]
        for i, v in enumerate((0x11, 0x22, 0x33, 0x44, 0x55)):
            sim.mem[b["u6_logdir"] + i] = v
        for i, v in enumerate((0x66, 0x77, 0x88)):
            sim.mem[b["u6_logdata"] + i] = v
        sim.call(b["ub_handoff"])
        r = self.p["rsym"]
        self.assertEqual(list(sim.mem[r["u6_logdir"]:r["u6_logdir"] + 5]), [0x11, 0x22, 0x33, 0x44, 0x55])
        self.assertEqual(list(sim.mem[r["u6_logdata"]:r["u6_logdata"] + 3]), [0x66, 0x77, 0x88])
        after = bytes(sim.mem[0x0200:0x0200 + len(self.p["game"])])
        changed = [0x0200 + i for i, (x, y) in enumerate(zip(before, after)) if x != y]
        allowed = set(range(r["u6_logdir"], r["u6_logdir"] + 5)) | \
            set(range(r["u6_logdata"], r["u6_logdata"] + 3))
        self.assertEqual([hex(a) for a in changed if a not in allowed], [])
        # and the init's copy came from the cart to $4400, whole
        n = len(self.p["init_copy"])
        self.assertEqual(bytes(sim.mem[0x4400:0x4400 + n]), self.p["init_copy"])


if __name__ == "__main__":
    unittest.main()
