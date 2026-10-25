"""Verify the Ultima 1 cart image against the original disk.

Every unit the driver can load is pulled back out of the flash image through
the driver's own table and compared byte-for-byte with the file on the D64.
"""
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

from ultima.disks.d64 import D64
from ultima.flash.tcrt import TCRT
from ultima.flash import zx
from ultima.flash import regions
from ultima import paths

TCRT_PATH = os.path.join(paths.BUILD, "ultima1.tcrt")
SYM_PATH = os.path.join(paths.BUILD, "u1drv.sym")
DISK = paths.disk("u1")
DRIVER_ADDR = 0xC000
NAMES = ["TC", "MA", "PL", "FI", "GE", "OU", "DN", "TW", "CA", "SP", "TM",
         "ST", "IN", "MI", "LO", "PR", "DD", "RO", "P0", "P1", "P2", "P3"]
ABSENT = {"PL", "PR"}
SAVE_SLOTS = {"DD", "RO", "P0", "P1", "P2", "P3"}
SAVE_BASE = regions.save_base("u1")   # not a literal: the map is laid out
                                      # from a size table, see regions.py
ERASE_BLOCK = 0x1000
F_COMPRESSED = 0x01
F_SAVESLOT = 0x02


def symbol(name):
    pat = re.compile(r"^\s*" + re.escape(name) + r"\s*=\s*\$([0-9a-fA-F]+)")
    for line in Path(SYM_PATH).read_text().splitlines():
        m = pat.match(line)
        if m:
            return int(m.group(1), 16)
    raise AssertionError(f"symbol {name} missing")


class TestU1Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, "-m", "ultima.games.u1.build", TCRT_PATH],
                       check=True, stdout=subprocess.DEVNULL)
        cls.flash = TCRT.read(TCRT_PATH).flash
        cls.disk = D64(DISK)
        # the driver is the first boot segment
        desc = cls.flash[0x100:0x200]
        off = desc[3] << 8 | desc[4] << 16
        length = desc[5] | desc[6] << 8
        cls.driver = cls.flash[off:off + length]
        cls.table = symbol("u1_table") - DRIVER_ADDR
        hello = cls.disk.payload("HELLO")[0]
        cls.original = hello[0x400:0x400 + 0x5FC]       # the original driver image

    def entry(self, i):
        e = self.table + i * 8
        t = self.driver
        return (t[e] << 8 | t[e + 1] << 16,          # flash offset
                t[e + 2] | t[e + 3] << 8,            # length
                t[e + 4] | t[e + 5] << 8,            # destination
                t[e + 6])                            # flags

    def unit(self, name):
        """A unit as the cart stores it, decoded."""
        offset, length, _dest, flags = self.entry(NAMES.index(name))
        stored = self.flash[offset:offset + length]
        return zx.decode(stored) if flags & F_COMPRESSED else stored

    def test_every_present_unit_matches_the_disk(self):
        """A crunched unit's length is the compressed one -- U1's table has a
        dedicated flags byte and a 16-bit length, so the blob needs no prefix
        the way U3's does.  OU and ST differ in their hooks (below)."""
        for i, name in enumerate(NAMES):
            if name in ABSENT or name in SAVE_SLOTS or name in ("OU", "ST"):
                continue
            with self.subTest(index=i, name=name):
                offset, length, _dest, flags = self.entry(i)
                want, ok = self.disk.payload(name)
                self.assertTrue(ok, f"{name} crosses a bad sector")
                stored = self.flash[offset:offset + length]
                if flags & F_COMPRESSED:
                    self.assertEqual(zx.decode(stored), want)
                    self.assertLess(length, len(want))
                else:
                    self.assertEqual(stored, want)

    def view_symbol(self, name):
        sym = {m.group(1): int(m.group(2), 16) for m in re.finditer(
            r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path(os.path.join(paths.BUILD, "u1view.bin.sym")).read_text())}
        return sym[name]

    def test_ou_differs_from_the_disk_only_in_the_hooks(self):
        """F7 and B (u1powers.s): OU's two JSRs point into the segment at
        $CE01, and its key wait ($8DD0) is a JMP to u1idle.s there; its start
        ($8C9E, LDA #$30 / STA $01) is JSR h_ou / NOP, in the segment at
        $0334 (u1view.s); nothing else in OU changed."""
        from ultima.games.u1 import build as u1
        disk = self.disk.payload("OU")[0]
        ou = self.unit("OU")
        diff = {i for i in range(len(disk)) if disk[i] != ou[i]}
        want = {at - 0x8C9E + k for at, _orig, _name in u1.POWER_HOOKS for k in (1, 2)}
        want |= {0, 1, 2, 3}
        at, _orig, name = u1.IDLE_HOOK
        want |= {at - 0x8C9E + k for k in (0, 1, 2)}
        self.assertEqual(len(ou), len(disk))
        self.assertEqual(ou[at - 0x8C9E:at - 0x8C9E + 3],
                         bytes([0x4C, symbol(name) & 0xFF, symbol(name) >> 8]))
        self.assertEqual(diff, want)
        for at, _orig, name in u1.POWER_HOOKS:
            with self.subTest(hook=name):
                self.assertEqual(ou[at - 0x8C9E], 0x20)
                self.assertTrue(0xCE01 <= symbol(name) < symbol("u1_ext_end"))
        h = self.view_symbol("h_ou")
        self.assertEqual(ou[0:4], bytes([0x20, h & 0xFF, h >> 8, 0xEA]))
        self.assertTrue(0x0334 <= h < 0x0400)

    def test_st_differs_from_the_disk_only_in_the_view(self):
        """u1view.s: ST's renderer ($1C8A up to its JSR $1700 at $1DB2), the
        jump table's entries that draw in a bitmap (each a JMP to its hook in
        the segment at $0334) and $1A78 (JMP h_char); nothing else, but the
        renderer's helpers after ST's end, up to $1FFD."""
        from ultima.games.u1 import build as u1
        disk = self.disk.payload("ST")[0]
        st = self.unit("ST")
        self.assertEqual(len(disk), 0x1F87 - 0xC00)
        self.assertLessEqual(0xC00 + len(st), 0x1FFE)
        st = st[:len(disk)]
        first, end, _pin = u1.VIEW_RENDERER
        allowed = set(range(first - 0xC00, end - 0xC00)) | {0x1A78 - 0xC00 + k for k in range(3)}
        for at, orig, name in u1.VIEW_JUMPS:
            allowed |= {at - 0xC00 + 1, at - 0xC00 + 2}
            h = self.view_symbol(name)
            with self.subTest(entry=hex(at)):
                self.assertEqual(st[at - 0xC00:at - 0xC00 + 3], bytes([0x4C, h & 0xFF, h >> 8]))
                self.assertTrue(0x0334 <= h < 0x0400)
        diff = {i for i in range(len(disk)) if disk[i] != st[i]}
        self.assertLessEqual(diff, allowed)
        self.assertEqual(st[end - 0xC00:end - 0xC00 + 3], disk[end - 0xC00:end - 0xC00 + 3])

    def test_the_view_draws_what_sts_own_draws(self):
        """ST's own renderer and u1view.s's, side by side in py65 over a
        walk on a random map (monsters, the edges and past them, standing
        still, the party's tile changing), each drawing into the bitmaps
        in turn as the flip swaps them ($1700 stubbed: $5C EOR $5D; no key):
        every draw leaves the view's 18 rows of bitmap and its colours the
        same in both, and the same zero page, with six ticks of CIA 2's timer
        B before each draw but the first (u1view.s steps the animation at
        the draw that follows them, ST after each draw).  With no tick since
        the last draw nothing changes, the monsters' frames neither; after
        five ticks no step, after thirty one, the clock from then on.  Between some draws a
        character is printed into the view ($1667), the view cleared
        ($1661) or a line drawn ($1691), in both."""
        try:
            from py65.devices.mpu6502 import MPU
        except ImportError:
            self.skipTest("py65 is not installed (use the repository's .venv)")
        import random
        rng = random.Random(64)
        original = self.disk.payload("ST")[0]
        world = bytes(rng.randrange(256) for _ in range(4096))
        frames = bytes(rng.randrange(256) for _ in range(256))
        font = bytes(rng.randrange(256) for _ in range(1024))

        def machine(st, hooks):
            mpu = MPU()
            m = mpu.memory
            m[0x0800:0x0C00] = list(font)
            m[0x0C00:0x0C00 + len(st)] = list(st)
            if hooks:
                m[0x0334:0x0334 + len(hooks)] = list(hooks)
                m[0x02A7:0x02A7 + len(anim)] = list(anim)
            m[0x1ED5:0x1EDA] = [0x84, 0x5E, 0xA9, 0x00, 0x60]      # no key ($5E = Y, as ST's)
            m[0x1700:0x1707] = [0xA5, 0x5C, 0x45, 0x5D, 0x85, 0x5C, 0x60]
            m[0x6400:0x7400] = list(world)
            m[0xB700:0xB800] = list(frames)
            m[0x5C] = m[0x5D] = 0x60
            m[0xC000:0xC003] = [0x20, 0x00, 0x00]                  # JSR, then stop
            return mpu

        def call(mpu, at, a=0, x=0, y=0):
            m = mpu.memory
            m[0xC001], m[0xC002] = at & 0xFF, at >> 8
            mpu.pc, mpu.sp, mpu.a, mpu.x, mpu.y = 0xC000, 0xFF, a, x, y
            for _ in range(200000):
                if mpu.pc == 0xC003:
                    return
                mpu.step()
            self.fail(f"${at:04x} did not return")

        anim = self.segment(0x02A7)
        old = machine(original, None)
        new = machine(self.unit("ST"), self.segment(0x0334))
        new.memory[0xDD06] = 0                  # CIA 2's timer B: no tick yet, and
        new.memory[self.view_symbol("a_frame")] = new.memory[0x178E]   # the frames' start ST's
        x, y, party = 20, 30, 0x02
        stepped = original[0x0000:0x0800]       # ST's tiles before any step
        for n in range(26):
            if n in (6, 7, 8):
                pass                                # standing still
            elif n == 12:
                x, y = 70, 2                        # past the edges
            elif n == 18:
                x, y = 2, 66
            else:
                dx, dy = rng.choice([(1, 0), (-1, 0), (0, 1), (0, -1)])
                x, y = x + dx, y + dy
            if n == 10:
                party = 0x12
            what = {14: "char", 20: "clear", 23: "line"}.get(n)
            for mpu in (old, new):
                m = mpu.memory
                m[0x1639] = party
                if what == "char":
                    m[0x2E], m[0x2F], m[0x30], m[0x31], m[0x32], m[0x33] = 1, 38, 1, 19, 7, 5
                    call(mpu, 0x1667, a=0x41)
                elif what == "clear":
                    call(mpu, 0x1661)
                elif what == "line":
                    m[0x26], m[0x27] = 40, 30
                    call(mpu, 0x1691, x=200, y=120)
                m[0x20], m[0x21] = x & 0xFF, y & 0xFF
                if mpu is new and n:
                    m[0xDD06] = (m[0xDD06] - 6) & 0xFF  # six ticks: the step ST's
                call(mpu, 0x166A)                       # took after the last draw
            with self.subTest(draw=n, at=(x, y), after=what):
                hidden = old.memory[0x5C] ^ 0x60            # the bitmap just drawn
                self.assertEqual(hidden, new.memory[0x5C] ^ 0x60)
                bm = 0x4000 if hidden else 0x2000
                scr = 0x6000 if hidden else 0x0400
                for r in range(1, 19):
                    a = bm + 320 * r + 8
                    self.assertEqual(new.memory[a:a + 304], old.memory[a:a + 304], f"bitmap row {r}")
                    a = scr + 40 * r + 1
                    self.assertEqual(new.memory[a:a + 38], old.memory[a:a + 38], f"colours, row {r}")
                zp = [0x45, 0x46, 0x47, 0x48, 0x49, 0x4C, 0x4D] + list(range(0x60, 0x79))
                self.assertEqual([new.memory[z] for z in zp], [old.memory[z] for z in zp])
                self.assertEqual(new.memory[0x178E], old.memory[0x178E])
                # ST steps after its draw, u1view.s before the next: one behind
                self.assertEqual(new.memory[0x0C00:0x1400], list(stepped))
                stepped = bytes(old.memory[0x0C00:0x1400])
        # no tick since: no step, the monsters' frames as at the last draw;
        # once both bitmaps have been drawn so, two more draws change nothing
        m = new.memory
        m[0x20], m[0x21] = 30, 30               # (the walk ends off the map)
        m[0xDD06] = (m[0xDD06] - 6) & 0xFF
        call(new, 0x166A)
        frame, tiles = m[0x178E], m[0x0C00:0x1400]
        for _ in range(2):
            call(new, 0x166A)
            self.assertEqual(m[0x178E], frame)
        before = [m[0x2000:0x6400], m[0x0400:0x0800], m[0x6000:0x6400], m[0x0C00:0x1400]]
        self.assertEqual(before[3], tiles)
        for _ in range(2):
            call(new, 0x166A)
        self.assertEqual([m[0x2000:0x6400], m[0x0400:0x0800], m[0x6000:0x6400], m[0x0C00:0x1400]], before)
        # five ticks: none yet; thirty (the view away): one step, from now on
        last = m[self.view_symbol("a_last")]
        m[0xDD06] = (m[0xDD06] - 5) & 0xFF
        call(new, 0x166A)
        self.assertEqual(m[0x0C00:0x1400], before[3])
        m[0xDD06] = (m[0xDD06] - 25) & 0xFF
        call(new, 0x166A)
        self.assertNotEqual(m[0x0C00:0x1400], before[3])
        self.assertEqual(m[self.view_symbol("a_last")], m[0xDD06])
        self.assertNotEqual(m[self.view_symbol("a_last")], last)

    def test_the_scroll_does_what_sts_own_does(self):
        """The text window's scroll (ST $1649): u1view.s's pass for the
        usual window (columns 0-29 of rows 20-23, both bitmaps in use) and
        ST's own code for any other, side by side with ST's in py65 on
        random bitmaps: the same bitmaps, screens, zero page and X and Y
        after, but for the view's record, dropped by a window in the view's
        rows."""
        try:
            from py65.devices.mpu6502 import MPU
        except ImportError:
            self.skipTest("py65 is not installed (use the repository's .venv)")
        import random
        rng = random.Random(23)
        original = self.disk.payload("ST")[0]
        for window, d5, c5, fill in (((0, 30, 20, 24), 0x60, 0x60, 0x00), ((0, 30, 20, 24), 0x60, 0x00, 0xFF),
                                     ((0, 30, 20, 24), 0x00, 0x00, 0x00), ((1, 38, 1, 19), 0x60, 0x60, 0x00),
                                     ((31, 10, 20, 24), 0x60, 0x00, 0x00), ((0, 40, 0, 24), 0x60, 0x60, 0x00)):
            ram = [rng.randrange(256) for _ in range(0x10000)]
            out = []
            for st, hooks in ((original, None), (self.unit("ST"), self.segment(0x0334))):
                mpu = MPU()
                m = mpu.memory
                m[:] = ram
                m[0x0C00:0x0C00 + len(st)] = list(st)
                if hooks:
                    m[0x0334:0x0334 + len(hooks)] = list(hooks)
                m[0x1ED5:0x1EDA] = [0x84, 0x5E, 0xA9, 0x00, 0x60]
                m[0x2E], m[0x2F], m[0x30], m[0x31] = window
                m[0x5D], m[0x5C], m[0x1F] = d5, c5, fill
                m[0xC000:0xC003] = [0x20, 0x49, 0x16]
                mpu.pc, mpu.sp = 0xC000, 0xFF
                for _ in range(400000):
                    if mpu.pc == 0xC003:
                        break
                    mpu.step()
                else:
                    self.fail("the scroll did not return")
                out.append((m[0x0000:0x0100], m[0x0400:0x0800], m[0x2000:0x6400], mpu.x, mpu.y))
            with self.subTest(window=window, d5=d5, c5=c5):
                o, n = out
                self.assertEqual(n[1], o[1], "screen 0")
                flags = (0x3FEB - 0x2000, 0x5FEB - 0x2000)     # the view's record: dropped for a
                for f in flags:                                 # window or a cursor in its rows
                    self.assertEqual(n[2][f], o[2][f] >> 1 if min(window[2], ram[0x33]) < 19 else o[2][f])
                    n[2][f] = o[2][f]
                self.assertEqual(n[2], o[2], "bitmaps, screen 1")
                self.assertEqual((n[3], n[4]), (o[3], o[4]), "X, Y")
                self.assertEqual(n[0][0x02:0x80], o[0][0x02:0x80], "zero page")

    def test_the_idle_turn_goes_by_the_clock(self):
        """u1idle.s, from OU's $8DD0, in py65: ST's poll stubbed (no key,
        CIA 2's seconds counted up a poll, in RAM here): with P (PASS) off a
        turn passes when the seconds reach $15 -- A, X 0, Z set -- after the
        wait set them to 0; with P on it polls on; a key comes back in A
        and X, Z clear."""
        try:
            from py65.devices.mpu6502 import MPU
        except ImportError:
            self.skipTest("py65 is not installed (use the repository's .venv)")
        from ultima.launcher import patches
        ou, ext = self.unit("OU"), self.segment(0xCE01)

        def run(opts, key=0, steps=20000):
            mpu = MPU()
            m = mpu.memory
            m[0x8C9E:0x8C9E + len(ou)] = list(ou)
            m[0xCE01:0xCE01 + len(ext)] = list(ext)
            m[symbol("pt_opts")] = opts
            m[0xDD09] = 0x42
            # $167C: one poll -- INC $DD09 / LDA #key / RTS
            m[0x167C:0x1682] = [0xEE, 0x09, 0xDD, 0xA9, key, 0x60]
            m[0xC000:0xC003] = [0x20, 0xD0, 0x8D]
            mpu.pc, mpu.sp = 0xC000, 0xFF
            for _ in range(steps):
                if mpu.pc == 0xC003:
                    return mpu, m[0xDD09]
                mpu.step()
            return None, m[0xDD09]
        mpu, secs = run(0)
        self.assertIsNotNone(mpu)
        self.assertEqual((mpu.a, mpu.x, bool(mpu.p & mpu.ZERO), secs), (0, 0, True, 0x15))
        mpu, secs = run(patches.PASS)
        self.assertIsNone(mpu)
        self.assertGreater(secs, 0x15)
        mpu, secs = run(0, key=0x3B)
        self.assertEqual((mpu.a, mpu.x, bool(mpu.p & mpu.ZERO), secs), (0x3B, 0x3B, False, 1))

    def segment(self, dest):
        desc = self.flash[regions.desc_offset("u1"):regions.desc_offset("u1") + 64]
        for n in range(desc[2]):
            e = desc[3 + 7 * n:3 + 7 * (n + 1)]
            if e[4] | e[5] << 8 == dest:
                off = e[0] << 8 | e[1] << 16
                return self.flash[off:off + (e[2] | e[3] << 8)]
        self.fail(f"no segment at {dest:#06x}")

    def test_f7_teleports_and_b_brings_a_transport(self):
        """u1powers.s (the page's X), run in py65 on the built OU at $8C9E
        and the segment at $CE01, the game's own routines stubbed: with
        pw_on, F1 tells where the party is and goes back to the loop's top
        (no turn), F7 asks a land (0-3) and X and Y (two digits each, up to 63)
        and the party is there, through $983D; B where there is nothing to
        board offers a horse, a cart, a raft, a frigate or an aircar, and
        goes on to Board's end ($90B2) with it.  Without pw_on the
        original's way: the key to MI's $85FD, "nothing to Board!"."""
        try:
            from py65.devices.mpu6502 import MPU
        except ImportError:
            self.skipTest("py65 is not installed (use the repository's .venv)")
        ou = self.unit("OU")
        ext = self.segment(0xCE01)
        on_at = symbol("pw_on")

        def run(at, on, keys, a=0, x=5, y=6):
            mpu = MPU()
            m = mpu.memory
            m[0x8C9E:0x8C9E + len(ou)] = list(ou)
            m[0xCE01:0xCE01 + len(ext)] = list(ext)
            m[on_at] = 0x80 if on else 0
            m[0x20], m[0x21], m[0x81E4], m[0x81F1] = x, y, 1, 0
            m[0x85BE] = 0x2E                        # the number printer's fill
            queue, out, calls = list(keys), [], []
            # the main loop's JSR $8D42 (the command) has pushed $8D44
            mpu.sp = 0xF0
            m[0x1F1], m[0x1F2] = 0x44, 0x8D
            mpu.pc, mpu.a = at, a

            def ret():
                sp = mpu.sp
                mpu.pc = (m[0x101 + sp] | m[0x102 + sp] << 8) + 1
                mpu.sp = (sp + 2) & 0xFF
            for _ in range(20000):
                pc = mpu.pc
                if pc in (0x8D34, 0x8D45, 0x85FD, 0x9085, 0x90B2, 0x8CFB):
                    return pc, mpu, m, "".join(out), calls
                if pc == 0x848E:                    # the inline string
                    sp = mpu.sp
                    p = (m[0x101 + sp] | m[0x102 + sp] << 8) + 1
                    while m[p]:
                        out.append("|" if m[p] == 0x7E else chr(m[p]))
                        p += 1
                    m[0x101 + sp], m[0x102 + sp] = p & 0xFF, p >> 8
                    ret()
                elif pc == 0x83D7:
                    out.append(chr(mpu.a))
                    ret()
                elif pc == 0x8582:                  # A in decimal, no leading zeros
                    self.assertEqual(m[0x85BE], 0, "the fill: none")
                    out.append(str(mpu.a))
                    ret()
                elif pc == 0x83F3:
                    out.append("|")
                    ret()
                elif pc == 0x83F6:                  # column 1: the original's way on
                    ret()
                elif pc == 0x1676:                  # a key
                    mpu.a = queue.pop(0) if queue else 0x0D
                    ret()
                elif pc in (0x8772, 0x983D, 0x9E0B, 0x166A):
                    calls.append((pc, m[0x81E4], m[0x20], m[0x21], m[0x81F1]))
                    ret()
                else:
                    mpu.step()
            self.fail(f"${at:04x}: no end (${mpu.pc:04x})")

        # the command loop, $8D31 JSR $85FD with A = the key ($88 & $7F for F7)
        pc, mpu, m, text, calls = run(0x8D31, False, b"", a=0x08)
        self.assertEqual(pc, 0x85FD, "F7 without the option: to MI, Huh?")
        pc, mpu, m, text, calls = run(0x8D31, True, b"", a=0x42)
        self.assertEqual((pc, mpu.a), (0x85FD, 0x42), "B with the option: the command")
        pc, mpu, m, text, calls = run(0x8D31, False, b"", a=0x05)
        self.assertEqual(pc, 0x85FD, "F1 without the option: to MI, Huh?")
        pc, mpu, m, text, calls = run(0x8D31, True, b"", a=0x05)
        self.assertEqual((pc, text, calls, m[0x85BE]), (0x8CFB, "Position land-1 X-5 Y-6", [], 0x2E))
        # the party's square, as a land's edge leaves it: -10 to 73
        for x, y, said in ((0, 63, "X-0 Y-63"), (0xF6, 73, "X--10 Y-73"), (73, 0xFF, "X-73 Y--1")):
            with self.subTest(x=x, y=y):
                pc, mpu, m, text, calls = run(0x8D31, True, b"", a=0x05, x=x, y=y)
                self.assertEqual((pc, text), (0x8CFB, "Position land-1 " + said))
        pc, mpu, m, text, calls = run(0x8D31, True, b"31020", a=0x08)
        self.assertEqual(pc, 0x8D34)
        self.assertTrue(mpu.p & 1, "C set: the turn ends")
        self.assertEqual(text, "Teleport land-3 X-10 Y-20")
        self.assertEqual(calls, [(0x983D, 3, 10, 20, 0)])
        pc, mpu, m, text, calls = run(0x8D31, True, b"06300", a=0x08)
        self.assertEqual(calls, [(0x983D, 0, 63, 0, 0)])
        for keys, why in ((b"4", "land 4"), (b"164", "X 64"), (b"10199", "Y 99"), (b"1\r", "RETURN")):
            with self.subTest(why):
                pc, mpu, m, text, calls = run(0x8D31, True, keys, a=0x08)
                self.assertEqual((pc, m[0x81E4], m[0x20], m[0x21]), (0x8D34, 1, 5, 6))
                self.assertTrue(text.endswith("|Huh?"), text)
                self.assertEqual([c[0] for c in calls], [0x8772])
        # Board with nothing to board: $9082 JSR $83F6, then "nothing to Board!"
        pc, mpu, m, text, calls = run(0x9082, False, b"")
        self.assertEqual((pc, m[0x81F1]), (0x9085, 0), "without the option: the message")
        for key, vehicle, said in ((b"H", 1, ""), (b"C", 2, ""), (b"R", 3, "Board "),
                                   (b"F", 4, "Board "), (b"A", 5, "Board ")):
            with self.subTest(key=key):
                pc, mpu, m, text, calls = run(0x9082, True, key)
                self.assertEqual((pc, m[0x81F1]), (0x90B2, vehicle))
                self.assertEqual(m[0x101 + mpu.sp], vehicle, "Board's end pulls the vehicle")
                self.assertEqual(m[0x102 + mpu.sp:0x104 + mpu.sp], [0x44, 0x8D], "and returns to the loop")
                self.assertEqual(text, "|(H)orse,(C)art,(R)aft,|(F)rigate,(A)ircar-|" + said)
                self.assertEqual([c[0] for c in calls], [0x9E0B, 0x166A])
        for key in (b"S", b"T", b"\r"):
            with self.subTest(key=key):
                pc, mpu, m, text, calls = run(0x9082, True, key)
                self.assertEqual((pc, m[0x81F1]), (0x8D45, 0), "none: the buzz, back to the loop")
                self.assertEqual([c[0] for c in calls], [0x8772])

    def test_crunching_only_ever_shrinks_a_unit(self):
        for i, name in enumerate(NAMES):
            if name in ABSENT:
                continue
            offset, length, _dest, flags = self.entry(i)
            if name in SAVE_SLOTS:
                self.assertFalse(flags & F_COMPRESSED, f"{name} is a save slot")
                continue
            want, _ok = self.disk.payload(name)
            if name in ("OU", "ST"):
                want = self.unit(name)          # with their hooks
            with self.subTest(index=i, name=name):
                self.assertEqual(bool(flags & F_COMPRESSED),
                                 zx.smaller(want) is not None)

    def test_absent_units_have_zero_length(self):
        # PL is not on the disk; PR sits on the unformatted track 6.  Zero
        # length makes the driver return C set, which is what the original
        # does -- and for PR the game relies on the load failing.
        for i, name in enumerate(NAMES):
            if name in ABSENT:
                with self.subTest(name=name):
                    self.assertEqual(self.entry(i)[1], 0)

    def test_destinations_match_the_drivers_own_table(self):
        for i, name in enumerate(NAMES):
            if name in SAVE_SLOTS:
                continue   # these come from the save tables, checked separately
            with self.subTest(index=i, name=name):
                # the original's table ($C5C3), from the disk: in the image
                # the launcher's options are over it now
                o = 0xC5C3 - DRIVER_ADDR + 2 * i
                self.assertEqual(self.entry(i)[2],
                                 self.original[o] | self.original[o + 1] << 8)

    def test_units_are_page_aligned(self):
        for i, name in enumerate(NAMES):
            if name not in ABSENT:
                self.assertEqual(self.entry(i)[0] % 256, 0, name)

    def test_save_slots_get_their_own_erase_block(self):
        """One 4 KiB block each, so a save never needs read-modify-write and
        cannot corrupt a neighbouring slot."""
        seen = set()
        for i, name in enumerate(NAMES):
            if name not in SAVE_SLOTS:
                continue
            with self.subTest(name=name):
                offset, length, dest, flags = self.entry(i)
                self.assertTrue(flags & F_SAVESLOT)
                self.assertEqual(offset % ERASE_BLOCK, 0)
                self.assertGreaterEqual(offset, SAVE_BASE)
                self.assertNotIn(offset, seen)
                seen.add(offset)
                # length and address must match the game's $C5E3/$C5EF tables
                j = i - 16
                o = 0xC5E3 - DRIVER_ADDR + 2 * j
                start = self.driver[o] | self.driver[o + 1] << 8
                o = 0xC5EF - DRIVER_ADDR + 2 * j
                end = self.driver[o] | self.driver[o + 1] << 8
                self.assertEqual(length, end - start)
                self.assertEqual(dest, start)

    def test_image_covers_the_whole_save_region(self):
        """Unwritten tail is only "assumed erased" on a virgin cart.  Cover
        every save block explicitly so the flash tool erases them, otherwise
        stale bytes could pass the validity check on a reused cart."""
        self.assertGreaterEqual(len(self.flash),
                                SAVE_BASE + len(SAVE_SLOTS) * ERASE_BLOCK)

    def test_seeded_slots_match_the_disk(self):
        """DD and RO ship on the disk, so a fresh cart must present them just
        as a fresh disk does.  P0-P3 were scratched from this image, so they
        must read back as empty."""
        for i, name in enumerate(NAMES):
            if name not in SAVE_SLOTS:
                continue
            offset, length, _dest, _flags = self.entry(i)
            header = self.flash[offset:offset + 4]
            with self.subTest(name=name):
                try:
                    data, readable = self.disk.payload(name)
                except KeyError:
                    data, readable = b"", False
                if readable and data:
                    self.assertEqual(header[:2], b"\xa5\x5a", "should be seeded")
                    self.assertEqual(header[2] | header[3] << 8, length)
                    self.assertEqual(self.flash[offset + 0x100:offset + 0x100 + length],
                                     data[:length])
                else:
                    self.assertEqual(header, b"\xff" * 4, "should read as empty")

    def test_entry_points_are_where_the_game_expects(self):
        at = lambda a: self.driver[a - DRIVER_ADDR]
        self.assertEqual(at(0xC480), 0x4C)   # JMP load-with-OU
        self.assertEqual(at(0xC483), 0x4C)   # JMP save
        self.assertEqual(at(0xC486), 0x4C)   # JMP plain load
        self.assertEqual(at(0xC489), 0xAE)   # LDX $C4F8 ("save next")

    def test_original_code_we_reuse_survives(self):
        """The OU memcpy and the save tables must come through untouched.
        (The name and address tables at $C597-$C5E2 were read only by the
        original KERNAL load routine before them, $C52C: both dead, and the
        launcher's options live there now.)"""
        hello, _ = self.disk.payload("HELLO")
        original = hello[0x400:]
        for lo, hi, what in ((0xC4FD, 0xC52C, "OU memcpy"),
                             (0xC4F8, 0xC4F9, "save-next counter"),
                             (0xC5E3, 0xC5FC, "save start/end tables")):
            with self.subTest(region=what):
                a = lo - DRIVER_ADDR
                b = hi - DRIVER_ADDR
                self.assertEqual(self.driver[a:b], original[a:b])

    def test_boot_descriptor(self):
        from ultima.flash import regions
        desc = self.flash[regions.desc_offset("u1"):regions.desc_offset("u1") + 64]
        # the entry is the init stub, which does HELLO's machine setup and
        # then jumps to LO; that keeps the menu completely game-agnostic.
        # It is at $C700 (where MA goes later), carrying tc_init
        # (TC_INIT_ELSEWHERE): too long for page 2 now.
        self.assertEqual(desc[0] | desc[1] << 8, 0xC700)
        self.assertEqual(desc[2], 7)          # driver + LO + decruncher + init + $CE01 + $0334 + $02A7
        dests = [desc[3 + 7 * n + 4] | desc[3 + 7 * n + 5] << 8 for n in range(desc[2])]
        # the decoder in the old fastload buffer: $CB00 is the settlement map;
        # the view's hooks (u1view.s) in the tape buffer, its animation's
        # timing in the KERNAL's unused $02A7-$02FF
        self.assertEqual(sorted(dests), [0x02A7, 0x0334, 0x0800, 0xC000, 0xC600, 0xC700, 0xCE01])

    def test_LO_is_crunched_and_carries_its_own_length(self):
        """The menu decodes segments through zxd_unpack_sized, which reads
        the length out of the blob -- so a crunched segment is zx.sized(), not
        zx.crunch(), even though the descriptor has a length field."""
        from ultima.flash import regions
        desc = self.flash[regions.desc_offset("u1"):regions.desc_offset("u1") + 64]
        for n in range(desc[2]):
            o = 3 + 7 * n
            if (desc[o + 4] | desc[o + 5] << 8) != 0x0800:
                continue
            offset = desc[o] << 8 | desc[o + 1] << 16
            length = desc[o + 2] | desc[o + 3] << 8
            want, _ok = self.disk.payload("LO")
            stored = self.flash[offset:offset + length]
            self.assertTrue(desc[o + 6] & zx.SEG_COMP, "LO is not crunched")
            self.assertEqual(length, 2 + (stored[0] | stored[1] << 8))
            self.assertEqual(zx.unsized(stored), want)
            return
        self.fail("no segment loads to $0800")

    def test_init_stub_ends_by_jumping_to_LO(self):
        from ultima.flash import regions
        desc = self.flash[regions.desc_offset("u1"):regions.desc_offset("u1") + 64]
        for n in range(desc[2]):
            o = 3 + 7 * n
            if (desc[o + 4] | desc[o + 5] << 8) == 0xC700:
                off = desc[o] << 8 | desc[o + 1] << 16
                length = desc[o + 2] | desc[o + 3] << 8
                stub = self.flash[off:off + length]
                # its code ends JSR tc_init / JMP $0C00, and tc_init follows
                import re
                sym = {m.group(1): int(m.group(2), 16) for m in re.finditer(
                    r"(\w+)\s*=\s*\$([0-9a-fA-F]+)",
                    Path(os.path.join(paths.BUILD, "init_u1.sym")).read_text())}
                at = sym["tc_init"] - 0xC700
                self.assertEqual(stub[at - 6:at], bytes([0x20, sym["tc_init"] & 0xFF, sym["tc_init"] >> 8,
                                                         0x4C, 0x00, 0x0C]),
                                 "init stub must end with JSR tc_init / JMP $0C00")
                return
        self.fail("no init stub segment")


if __name__ == "__main__":
    unittest.main()


class TestU1Memory(unittest.TestCase):
    """What the driver may occupy.  Not $CB00-$CDFF: the town and castle
    overlays fill it with the settlement's map as they start (TW $8CF5, CA
    $8CF7: three pages from a table), so code there would be wrecked by the
    first settlement and crash the next load."""

    def test_the_settlements_map_copy_is_where_it_was_found(self):
        disk = D64(DISK)
        for name, at in (("TW", 0x8CF5), ("CA", 0x8CF7)):
            data = disk.payload(name)[0]
            off = at - 0x8C9E
            # LDA abs,X (self-modified) / STA $CB00,X / DEX / BNE: three pages
            self.assertEqual(data[off], 0xBD, name)
            self.assertEqual(bytes(data[off + 3:off + 6]), bytes([0x9D, 0x00, 0xCB]), name)

    def test_no_unit_names_the_segment_at_ce01(self):
        """$CE01-$CFFF (the launcher's X and the options' table): a linear
        disassembly of every unit with code -- not TC, MA and FI, which are
        data -- names no address there, absolute or as an immediate that
        could build a pointer, but for one hit in DN's data (a table of
        three-byte records, each ending in $01, where $AC49 reads as CMP
        $CE01,X)."""
        try:
            from py65.devices.mpu6502 import MPU
        except ImportError:
            self.skipTest("py65 is not installed (use the repository's .venv)")
        from ultima.games.u1 import build as u1
        size = {"abs": 3, "abx": 3, "aby": 3, "ind": 3, "imp": 1, "acc": 1}
        disk = D64(DISK)
        names, loads = u1.read_tables(disk.payload("HELLO")[0][0x400:0x400 + 0x5FC])
        hits, scanned = [], 0
        for i, name in enumerate(names[:16]):
            if name in ("TC", "MA", "FI") or name in ABSENT:
                continue
            data = disk.payload(name)[0]
            base = 0x8C9E if name == "OU" else loads[i]
            o = 0
            while o < len(data):
                mnemonic, mode = MPU.disassemble[data[o]]
                n = 1 if mnemonic == "???" else size.get(mode, 2)
                operand = data[o + 1:o + n]
                if n == 3 and len(operand) == 2 and 0xCE01 <= (operand[0] | operand[1] << 8) <= 0xCFFF:
                    hits.append((name, base + o))
                if mode == "imm" and len(operand) == 1 and operand[0] in (0xCE, 0xCF):
                    hits.append((name, base + o))
                o += n
            scanned += len(data)
        self.assertGreater(scanned, 50000)
        self.assertEqual(hits, [("DN", 0xAC49)])

    def test_no_unit_names_the_views_memory(self):
        """What u1view.s uses: $02A7-$02FF (the KERNAL's unused bytes),
        $0334-$03FF (the tape buffer and its spare bytes), $1F87-$1FFD
        (after ST) and the bitmaps' tails ($3F40-$3FFF, $5F40-$5FFF).  A
        linear disassembly of every unit with code names no address there
        but in data: text (OU $A0B4, TW $9D8E, $A0EE, $A141, $AAC2: "~",
        $7F, $03), the people's glyph tables (TW $AD98, CA $A21D), TM's jump
        table at $A4BE (whose $A4C0 reads as AND $3FA5,Y), ST's tiles
        ($0C8E) and IN's graphics ($7C32, $7D07)."""
        try:
            from py65.devices.mpu6502 import MPU
        except ImportError:
            self.skipTest("py65 is not installed (use the repository's .venv)")
        from ultima.games.u1 import build as u1
        ranges = ((0x02A7, 0x02FF), (0x0334, 0x03FF), (0x1F87, 0x1FFD), (0x3F40, 0x3FFF), (0x5F40, 0x5FFF))
        size = {"abs": 3, "abx": 3, "aby": 3, "ind": 3, "imp": 1, "acc": 1}
        disk = D64(DISK)
        names, loads = u1.read_tables(disk.payload("HELLO")[0][0x400:0x400 + 0x5FC])
        hits, scanned = [], 0
        for i, name in enumerate(names[:16]):
            if name in ("TC", "MA", "FI") or name in ABSENT:
                continue
            data = disk.payload(name)[0]
            base = 0x8C9E if name == "OU" else loads[i]
            o = 0
            while o < len(data):
                mnemonic, mode = MPU.disassemble[data[o]]
                n = 1 if mnemonic == "???" else size.get(mode, 2)
                operand = data[o + 1:o + n]
                if n == 3 and len(operand) == 2 and \
                        any(a <= (operand[0] | operand[1] << 8) <= b for a, b in ranges):
                    hits.append((name, base + o))
                o += n
            scanned += len(data)
        self.assertGreater(scanned, 50000)
        self.assertEqual(sorted(hits), sorted([
            ("OU", 0xA0B4), ("TW", 0x9D8E), ("TW", 0xA0EE), ("TW", 0xA141), ("TW", 0xAAC2),
            ("TW", 0xAD98), ("CA", 0xA21D), ("TM", 0xA4C0), ("ST", 0x0C8E), ("IN", 0x7C32), ("IN", 0x7D07)]))

    def test_no_driver_piece_is_in_the_settlements_map(self):
        segs = []
        flash = TCRT.read(TCRT_PATH).flash
        desc = flash[0x100:0x200]
        for n in range(desc[2]):
            e = desc[3 + 7 * n:3 + 7 * (n + 1)]
            segs.append((e[4] | e[5] << 8, e[2] | e[3] << 8))
        for dest, length in segs:
            with self.subTest(dest=hex(dest)):
                self.assertTrue(dest + length <= 0xCB00 or dest >= 0xCE00,
                                f"a segment at {dest:#06x} reaches into $CB00-$CDFF")
