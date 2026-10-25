"""Verify the Ultima 2 cart image against the original disks.

Ultima 2 reaches the drive only through four SUBS jump-table vectors and
addresses everything by name, so the checks here follow the name table: every
directory entry must resolve to the bytes the original disk holds, the twelve
names that exist on both disks must stay distinguishable, and the writable
files are seeded raw from the player disk, with the save log (u2log.s)
empty on a fresh cart.
"""
import os
import subprocess
import sys
import unittest

from ultima.disks.d64 import D64
from ultima.flash.tcrt import TCRT
from ultima.flash import regions
from ultima.flash import zx

import importlib.util as _il
from ultima import paths


def _load_game(name):
    """Load games/<name>/build.py under a unique module name.

    Importing it as plain `build` makes the per-game test modules collide in
    sys.modules -- whichever runs first wins and the other silently tests the
    wrong game."""
    spec = _il.find_spec(f"ultima.games.{name}.build")
    mod = _il.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


u2 = _load_game("u2")

TCRT_PATH = os.path.join(paths.BUILD, "ultima2.tcrt")


class TestU2Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, "-m", "ultima.games.u2.build"],
                       check=True, stdout=subprocess.DEVNULL)
        cls.flash = TCRT.read(TCRT_PATH).flash
        cls.parts = u2.parts()
        cls.disks = {n: D64(f) for n, f in u2.DISKS.items()}
        cls.sym = u2.symbols(os.path.join(paths.BUILD, "u2drv.sym"))
        cls.sym.update(u2.symbols(os.path.join(paths.BUILD, "u2powers.sym")))
        with open(os.path.join(paths.BUILD, "u2powers.bin"), "rb") as fh:
            cls.powers = fh.read()
        desc = cls.flash[regions.desc_offset("u2"):regions.desc_offset("u2") + 64]
        cls.entry = desc[0] | desc[1] << 8
        cls.segments = []
        for i in range(desc[2]):
            o = 3 + 7 * i
            cls.segments.append((desc[o] << 8 | desc[o + 1] << 16,
                                 desc[o + 2] | desc[o + 3] << 8,
                                 desc[o + 4] | desc[o + 5] << 8))
        off, length, _ = [s for s in cls.segments if s[2] == u2.DRIVER_ADDR][0]
        cls.driver = cls.flash[off:off + length]

    def segment(self, dest):
        found = [s for s in self.segments if s[2] == dest]
        self.assertEqual(len(found), 1, f"no single segment loads to {dest:#06x}")
        off, length, _ = found[0]
        return self.flash[off:off + length]

    def table(self):
        """Decode the driver's name table back out of the image."""
        off = self.sym["u2_table"] - u2.DRIVER_ADDR
        count = self.driver[self.sym["u2_count"] - u2.DRIVER_ADDR]
        out = []
        for i in range(count):
            e = self.driver[off + i * u2.ENTRY:off + (i + 1) * u2.ENTRY]
            out.append(dict(name=bytes(e[:8]).split(b"\x00")[0].decode(),
                            page=e[8] | e[9] << 8,
                            length=e[10] | e[11] << 8,
                            disk=e[12] & 0x03,
                            writable=bool(e[12] & u2.F_WRITE),
                            crunched=bool(e[12] & u2.F_COMP)))
        return out

    def expected(self, disk, name):
        """The payload as build.py should have stored it: the file with its
        PRG header dropped, plus any patch that applies to it.

        SUBS gets its four vectors repointed here too.  The table entry for
        SUBS has to be the patched copy -- a reload by name would otherwise
        put the original disk routines back and the next load would go to a
        drive that is not there."""
        img = bytearray(self.disks[disk].file(name)[0][2:])
        for fname, addr, want, new, _why in u2.PATCHES:
            if fname != name:
                continue
            off = addr - u2.BASE[fname]
            self.assertEqual(bytes(img[off:off + len(want)]), want,
                             f"{name} does not hold the bytes the patch expects")
            img[off:off + len(new)] = new
        if name == "SUBS":
            for vector, (routine, _original) in u2.VECTORS.items():
                off = vector - u2.SUBS_ADDR
                target = self.sym[routine]
                img[off + 1] = target & 0xFF
                img[off + 2] = target >> 8
            for at, orig, routine, op in u2.SUBS_HOOKS:     # the footstep's
                off = at - u2.SUBS_ADDR
                self.assertEqual(bytes(img[off:off + 3]), bytes.fromhex(orig))
                img[off:off + 3] = bytes([op, self.sym[routine] & 0xFF, self.sym[routine] >> 8])
            off = u2.POWERS_ADDR - u2.SUBS_ADDR     # the launcher's X
            img[off:off + len(self.powers)] = self.powers
        if name == "INTRO":             # the hand-over to ULTIMA, through
            off = u2.INTRO_GO - u2.INTRO_ADDR   # the launcher's options
            self.assertEqual(bytes(img[off:off + 3]), bytes([0x4C, 0x00, 0x50]))
            img[off + 1] = self.sym["u2_go"] & 0xFF
            img[off + 2] = self.sym["u2_go"] >> 8
        if name == "ULTIMA":            # the launcher's X (F7 and B) and V, the footstep
            for at, orig, routine, op in u2.ULTIMA_HOOKS:
                off = at - 0x5000
                self.assertEqual(bytes(img[off:off + 3]), bytes.fromhex(orig))
                img[off:off + 3] = bytes([op, self.sym[routine] & 0xFF, self.sym[routine] >> 8])
        return bytes(img)

    # -- the name table --------------------------------------------------

    def test_every_directory_entry_is_in_the_table(self):
        want = {(n, name) for n, d in self.disks.items()
                for name, _t, _tr, _s, _b in d.directory()}
        got = {(e["disk"], e["name"]) for e in self.table()}
        self.assertEqual(got, want)

    def test_every_entry_resolves_to_the_original_bytes(self):
        """A raw entry's length is the unit's; a crunched entry's is the
        compressed length, which is all tc_stream_open needs -- the stream
        ends itself, so the decrunched size is never recorded."""
        for e in self.table():
            with self.subTest(disk=e["disk"], name=e["name"]):
                want = self.expected(e["disk"], e["name"])
                off = e["page"] << 8
                stored = self.flash[off:off + e["length"]]
                self.assertEqual(zx.decode(stored) if e["crunched"] else stored, want)

    def test_crunching_only_ever_shrinks_a_unit(self):
        """A unit that would grow stays raw -- and one that shrinks is stored
        crunched, or the flag means nothing."""
        for e in self.table():
            if e["writable"]:
                self.assertFalse(e["crunched"], f"{e['name']} is a save slot")
                continue
            want = self.expected(e["disk"], e["name"])
            with self.subTest(disk=e["disk"], name=e["name"]):
                self.assertEqual(e["crunched"], zx.smaller(want) is not None)
                self.assertLessEqual(e["length"], len(want))

    def test_colliding_names_keep_one_entry_per_disk(self):
        """Twelve names exist on both disks with different contents; $8E37
        picks between them, so both entries have to survive."""
        by_name = {}
        for e in self.table():
            by_name.setdefault(e["name"], []).append(e)
        both = {n: es for n, es in by_name.items() if len(es) > 1}
        differing = {n for n in both
                     if self.expected(1, n) != self.expected(2, n)}
        self.assertEqual(len(differing), 12, sorted(differing))
        for name, es in both.items():
            self.assertEqual(sorted(e["disk"] for e in es), [1, 2], name)
        for name in differing:
            pages = {e["page"] for e in both[name]}
            self.assertEqual(len(pages), 2, f"{name} shares one blob for two disks")

    def test_the_table_fits_with_room_declared(self):
        count = self.driver[self.sym["u2_count"] - u2.DRIVER_ADDR]
        self.assertEqual(count, len(self.parts["entries"]))
        self.assertLessEqual(count, self.parts["capacity"])

    # -- saves -----------------------------------------------------------

    def test_writable_set_is_the_player_disk_mob_and_mon_files(self):
        wr = {e["name"] for e in self.table() if e["writable"]}
        want = {name for name, _t, _tr, _s, _b in self.disks[2].directory()
                if u2.writable(name)}
        self.assertEqual(wr, want)
        self.assertEqual(len(wr), 25)
        for e in self.table():
            if e["writable"]:
                self.assertEqual(e["disk"], 2, f"{e['name']} is writable on the wrong disk")

    def test_writable_files_are_seeded_raw_and_the_log_is_empty(self):
        """Each writable file's seed is its raw bytes in the game data (the
        log reads and copies whole pages), and a fresh cart's log is erased:
        no valid half, so every unit is its seed."""
        base, limit = regions.save_base("u2"), regions.REGIONS["u2"][3]
        self.assertEqual(limit - base, 2 * u2.u2log.HALF)
        self.assertEqual(set(self.flash[base:limit]), {0xFF})
        lo, hi = regions.data_base("u2"), regions.REGIONS["u2"][1]
        for e in self.table():
            if e["writable"]:
                a = e["page"] << 8
                self.assertTrue(lo <= a < hi, e["name"])
                self.assertFalse(e["crunched"], e["name"])
                self.assertLessEqual(e["length"], 256, e["name"])
                self.assertEqual(self.flash[a:a + e["length"]], self.expected(2, e["name"]))
        self.assertEqual(self.segment(u2.LOG_ADDR)[self.sym["lg_base"] - u2.LOG_ADDR:][:2],
                         bytes([(base >> 8) & 0xFF, base >> 16]))

    def test_the_player_record_is_seeded_as_an_empty_player_disk(self):
        """Raw track 35 sector 16, no directory entry.  Byte $FF must be zero
        -- non-zero means "not a player disk", and the patched $C9C0 loop in
        INTRO would then spin forever with the prompt removed."""
        off = self.parts["rec_page"] << 8
        record = self.flash[off:off + 256]
        self.assertEqual(record, self.disks[2].sector(u2.REC_TRACK, u2.REC_SECTOR))
        self.assertEqual(record[0xFF], 0x00)
        self.assertEqual(record[0x00], 0x00, "the seeded disk should hold no character")

    # -- the seam --------------------------------------------------------

    def test_the_four_vectors_point_into_the_driver(self):
        subs = self.segment(u2.SUBS_ADDR)
        self.assertEqual(len(subs), 0x1000)
        for vector, (routine, _original) in u2.VECTORS.items():
            off = vector - u2.SUBS_ADDR
            self.assertEqual(subs[off], 0x4C, f"{vector:#06x} is not a JMP")
            target = subs[off + 1] | subs[off + 2] << 8
            self.assertEqual(target, self.sym[routine])

    def test_nothing_else_in_subs_changed(self):
        """Only the two operand bytes of each of the four vectors may differ,
        the footstep's three jumps (SUBS_HOOKS) and the launcher's X
        (u2powers.s) in the block code the vectors left dead, which it must
        not outgrow: the RNG follows at $4F79.  Subset, not equality:
        u2_save happens to land at $B155 and the old target was $4B55, so
        the low byte is unchanged by coincidence."""
        original = self.disks[1].file("SUBS")[0][2:]
        subs = self.segment(u2.SUBS_ADDR)
        self.assertEqual(subs, self.expected(1, "SUBS"))
        diff = {i for i in range(len(original)) if original[i] != subs[i]}
        want = {v - u2.SUBS_ADDR + k for v in u2.VECTORS for k in (1, 2)}
        want |= {at - u2.SUBS_ADDR + k for at, _o, _r, _op in u2.SUBS_HOOKS for k in range(3)}
        self.assertLessEqual(u2.POWERS_ADDR + len(self.powers), u2.POWERS_LIMIT)
        want |= set(range(u2.POWERS_ADDR - u2.SUBS_ADDR,
                          u2.POWERS_ADDR - u2.SUBS_ADDR + len(self.powers)))
        self.assertLessEqual(diff, want)
        self.assertTrue(diff, "the vectors were not repointed at all")

    def test_the_patches_are_applied_and_nothing_else(self):
        for fname in ("INTRO", "ULTIMA"):
            original = self.disks[1].file(fname)[0][2:]
            stored = self.expected(1, fname)
            diff = {i for i in range(len(original)) if original[i] != stored[i]}
            want = set()
            for pf, addr, _w, new, _why in u2.PATCHES:
                if pf != fname:
                    continue
                off = addr - u2.BASE[pf]
                want.update(range(off, off + len(new)))
                # the site itself must hold the replacement, whether or not
                # every byte of it differs from what was there
                self.assertEqual(stored[off:off + len(new)], new, f"{fname} {addr:#06x}")
            if fname == "INTRO":        # and the hand-over through the options
                off = u2.INTRO_GO - u2.INTRO_ADDR + 1
                want.update((off, off + 1))
            if fname == "ULTIMA":       # and the X and V options' hooks
                for at, _orig, _routine, _op in u2.ULTIMA_HOOKS:
                    want.update(range(at - 0x5000, at - 0x5000 + 3))
            self.assertLessEqual(diff, want, fname)
            self.assertTrue(diff, fname)

    def test_f1_f7_and_b(self):
        """u2powers.s (the page's X), run in py65 on the built ULTIMA, SUBS
        and the driver: with pw_on, on the surface, F1 tells where the party
        is and goes back to the prompt (no turn), F7 asks X and Y (two
        digits each, up to 63) and moves the party there, and B where there
        is nothing to board offers a horse, a frigate or a plane; without
        it, or in a town, ILLEGAL COMMAND! and WHAT? as before."""
        try:
            from py65.devices.mpu6502 import MPU
        except ImportError:
            self.skipTest("py65 is not installed (use the repository's .venv)")
        ultima = self.expected(1, "ULTIMA")
        subs = self.segment(u2.SUBS_ADDR)
        sym = self.sym

        def run(pc, on, keys, where=0, a=0, pos=(5, 6)):
            mpu = MPU()
            m = mpu.memory
            m[0x5000:0x5000 + len(ultima)] = list(ultima)
            m[u2.SUBS_ADDR:u2.SUBS_ADDR + len(subs)] = list(subs)
            m[u2.DRIVER_ADDR:u2.DRIVER_ADDR + len(self.driver)] = list(self.driver)
            m[sym["pw_on"]] = 0x80 if on else 0
            m[0x8E14], m[0x02], m[0x03], m[0x13] = where, pos[0], pos[1], 0x7A
            queue = [k | 0x80 for k in keys]
            m[0x38] = queue.pop(0) if queue else 0
            mpu.pc, mpu.a, mpu.sp = pc, a, 0xF0
            if pc == 0x72CD:                        # Board's JSR: its return
                mpu.sp = 0xEE
                m[0x1EF], m[0x1F0] = 0xCC, 0x72     # (as a JSR at $72CD pushes it)
                mpu.pc = (ultima[0x72CE - 0x5000] | ultima[0x72CF - 0x5000] << 8)
            out = []

            def ret():
                sp = mpu.sp
                mpu.pc = (m[0x101 + sp] | m[0x102 + sp] << 8) + 1
                mpu.sp = (sp + 2) & 0xFF
            for _ in range(5000):
                if mpu.pc in (0x50E7, 0x52C0, 0x6702, 0x72D8):
                    self.assertEqual(mpu.sp, 0xF0, "the stack as the loop had it")
                    return mpu.pc, m, "".join(out)
                if mpu.pc == 0x4006:                # print the inline string
                    sp = mpu.sp
                    at = (m[0x101 + sp] | m[0x102 + sp] << 8) + 1
                    while m[at]:
                        out.append(chr(m[at] & 0x7F))
                        at += 1
                    m[0x101 + sp], m[0x102 + sp] = at & 0xFF, at >> 8
                    ret()
                    continue
                if mpu.pc == 0x4057:
                    out.append(chr(mpu.a & 0x7F))
                    ret()
                    continue
                if mpu.pc == 0x4075:                # take the key: the next one
                    m[0x38] = queue.pop(0) if queue else 0
                    ret()
                    continue
                mpu.step()
            self.fail(f"${pc:04x}: no end (${mpu.pc:04x})")
        pc, m, text = run(0x5233, False, [], a=0x88)
        self.assertEqual(pc, 0x6702)
        pc, m, text = run(0x5233, True, [], where=1, a=0x88)
        self.assertEqual(pc, 0x6702, "in a town: not")
        pc, m, text = run(0x5233, False, [], a=0x85)
        self.assertEqual(pc, 0x6702, "F1 without the option: not")
        pc, m, text = run(0x5233, True, [], where=1, a=0x85)
        self.assertEqual(pc, 0x6702, "F1 in a town: not")
        for pos, said in (((5, 6), "POSITION X-05 Y-06\r"), ((63, 0), "POSITION X-63 Y-00\r"),
                          ((10, 59), "POSITION X-10 Y-59\r")):
            with self.subTest(f1=pos):
                pc, m, text = run(0x5233, True, [], a=0x85, pos=pos)
                self.assertEqual((pc, m[0x02], m[0x03]), (0x50E7, *pos), "F1: the prompt, no turn")
                self.assertEqual(text, said)
        pc, m, text = run(0x5233, True, [], a=0x83)
        self.assertEqual(pc, 0x6702, "another key: not")
        pc, m, text = run(0x5233, True, b"1020", a=0x88)
        self.assertEqual((pc, m[0x02], m[0x03]), (0x52C0, 10, 20))
        self.assertEqual(text, "TELEPORT X-10 Y-20")
        pc, m, text = run(0x5233, True, b"6300", a=0x88)
        self.assertEqual((pc, m[0x02], m[0x03]), (0x52C0, 63, 0))
        pc, m, text = run(0x5233, True, b"64", a=0x88)
        self.assertEqual((pc, m[0x02], m[0x03]), (0x52C0, 5, 6))
        self.assertIn("WHAT?", text)
        pc, m, text = run(0x5233, True, b"1\r", a=0x88)
        self.assertEqual((pc, m[0x02]), (0x52C0, 5), "RETURN: no")
        for on, where, keys, end, tile in ((False, 0, b"", 0x72D8, 0x7A), (True, 1, b"", 0x72D8, 0x7A),
                                          (True, 0, b"H", 0x52C0, 0x22), (True, 0, b"F", 0x52C0, 0x24),
                                          (True, 0, b"P", 0x52C0, 0x26), (True, 0, b"Q", 0x52C0, 0x7A)):
            with self.subTest(on=on, where=where, keys=keys):
                pc, m, text = run(0x72CD, on, keys, where)
                self.assertEqual((pc, m[0x13]), (end, tile))
                if end == 0x72D8:
                    self.assertIn("WHAT?", text)

    # every BCD add to the record that CLAMP_HOOKS covers: where to start
    # (A on entry, X = 3, $1F = 3, $20 = $28 = 5), the record's bytes it
    # adds to, as (address, value near the top)
    CLAMP_RUNS = {
        0x713E: (0x712F, 0, [(0x8E22, 0x99), (0x8E23, 0x98)]),
        0x7248: (0x7239, 0, [(0x8E22, 0x99), (0x8E23, 0x98)]),
        0x7932: (0x7925, 5, [(0x8E22, 0x99), (0x8E23, 0x98)]),
        0x7168: (0x7159, 0, [(0x8E20, 0x99), (0x8E21, 0x98)]),
        0x7270: (0x7261, 0, [(0x8E20, 0x99), (0x8E21, 0x98)]),
        0x5DBF: (0x5DB8, 0, [(0x8E1D, 0x99), (0x8E1E, 0x42)]),
        0x817E: (0x8177, 0, [(0x8E1D, 0x99), (0x8E1E, 0x42)]),
        0x64AF: (0x64A5, 0, [(0x8E43, 0x99)]),
        0x7890: (0x7889, 0, [(0x8E43, 0x99)]),
        0x7F43: (0x7F3A, 2, [(0x8E43, 0x99)]),          # TAX / INX: X = 3
        0x81CB: (0x81C4, 0, [(0x8E43, 0x99)]),
        0x639F: (0x6395, 0, [(0x8E63, 0x99)]),
        0x78C2: (0x78BB, 0, [(0x8E63, 0x99)]),
        0x81A4: (0x819D, 0, [(0x8E63, 0x99)]),
        0x5F34: (0x5F2A, 0, [(0x8E83, 0x97)]),
        0x6043: (0x603A, 0, [(0x8E83, 0x97)]),
        0x70AB: (0x70A4, 0, [(0x8EA3, 0x99)]),
        0x70F7: (0x70F0, 0, [(0x8EA3, 0x99)]),
        0x70DA: (0x70D5, 3, [(0x8E2E, 0x98)]),
        0x707D: (0x7076, 0, [(0x8E2F, 0x98)]),
        0x7098: (0x7091, 0, [(0x8E30, 0x99)]),
        0x70C8: (0x70C1, 0, [(0x8EA5, 0x99)]),
        0x7961: (0x795A, 0, [(0x8EAF, 0x99)]),
        0x7F6C: (0x7F6A, 0, [(0x8E18, 0x85)]),          # + 4 x 5
    }

    def test_counts_stop_at_99_and_9999(self):
        """u2clamp.s (the page's V), run in py65: each hooked add in the
        built ULTIMA, from its SED to the end of the hooked code.  Without
        cl_on it does what the original's does (run too, on the disk's
        ULTIMA), the top digit's carry dropped -- 99 + 1 = 0; with it a
        carry out stores 99, both bytes of a 9999; an add that fits is the
        same both ways."""
        try:
            from py65.devices.mpu6502 import MPU
        except ImportError:
            self.skipTest("py65 is not installed (use the repository's .venv)")
        self.assertEqual({h[0] for h in u2.CLAMP_HOOKS}, set(self.CLAMP_RUNS))
        built = self.expected(1, "ULTIMA")
        original = bytes(self.disks[1].file("ULTIMA")[0][2:])
        sym = self.sym

        def run(ultima, site, on, near):
            start, a, values = self.CLAMP_RUNS[site]
            mpu = MPU()
            m = mpu.memory
            m[0x5000:0x5000 + len(ultima)] = list(ultima)
            m[u2.DRIVER_ADDR:u2.DRIVER_ADDR + len(self.driver)] = list(self.driver)
            m[sym["cl_on"]] = 0x80 if on else 0
            m[0x1F], m[0x20], m[0x28] = 3, 5, 5
            for at, v in values:
                m[at] = v if near else 0x12
            mpu.pc, mpu.a, mpu.x, mpu.sp = start, a, 3, 0xF0
            mpu.p &= ~mpu.DECIMAL
            stop = 0x7F7A if site == 0x7F6C else site + 3
            for _ in range(200):
                if mpu.pc == stop and mpu.sp == 0xF0:
                    return bytes(m[0x8E00:0x8F00]), mpu.p & mpu.CARRY
                mpu.step()
            self.fail(f"${site:04x}: no end (${mpu.pc:04x})")

        for site, (_start, _a, values) in self.CLAMP_RUNS.items():
            for near in (True, False):
                with self.subTest(site=f"${site:04x}", near=near):
                    was = run(original, site, False, near)
                    self.assertEqual(run(built, site, False, near), was, "off: not the original's")
                    rec, _c = run(built, site, True, near)
                    if not near:
                        self.assertEqual((rec, _c), was, "an add that fits")
                        continue
                    top = values[0][0]
                    self.assertLess(was[0][top - 0x8E00], values[0][1], "the original wraps")
                    for at, _v in values:
                        self.assertEqual(rec[at - 0x8E00], 0x99, f"${at:04x}")
                    want = bytearray(was[0])
                    for at, _v in values:
                        want[at - 0x8E00] = 0x99
                    self.assertEqual(rec, bytes(want), "nothing else in the record")

    def test_the_footstep_is_played_from_the_irq(self):
        """u2step.s, run in py65 on the built ULTIMA, SUBS and driver: a move
        on foot ($6B01) writes the registers $4DD9's blocks write, with the
        gate on, and goes on to the food at $6B11 without a wait; SUBS' IRQ
        tail ($47A9) counts the frame and turns the gate off at the third
        tick, on at the seventh, off at the ninth.  A horse ($6AF1) plays
        the original's three clicks the same way, and its walk ($6B01 from
        $6BB4) then neither clicks nor waits.  A move waits for the floor
        since the last click; a click in flight is waited for by st_flush,
        or cut with interrupts masked."""
        try:
            from py65.devices.mpu6502 import MPU
            from py65.memory import ObservableMemory
        except ImportError:
            self.skipTest("py65 is not installed (use the repository's .venv)")
        ultima, subs, sym = self.expected(1, "ULTIMA"), self.expected(1, "SUBS"), self.sym
        sid = []
        mem = ObservableMemory()
        mem.subscribe_to_write(range(0xD400, 0xD41D), lambda a, v: sid.append((a, v)))
        mpu = MPU(memory=mem)
        m = mpu.memory
        m[0x4000:0x5000] = list(subs)
        m[0x5000:0x5000 + len(ultima)] = list(ultima)
        m[u2.DRIVER_ADDR:u2.DRIVER_ADDR + len(self.driver)] = list(self.driver)
        m[0x8E1D:0x8E20] = [0x50, 0, 0]
        floor = sym["ST_FLOOR"]

        def run(pc, stop, steps=20000, irq_off=False):
            mpu.pc, mpu.sp = pc, 0xF0
            mpu.p = (mpu.p | mpu.INTERRUPT) if irq_off else (mpu.p & ~mpu.INTERRUPT)
            mpu.p &= ~mpu.DECIMAL
            for _ in range(steps):
                if mpu.pc == stop:
                    return True
                mpu.step()
            return False

        def tick():
            self.assertTrue(run(0x47A9, 0x47AF, 200), "the IRQ's tail does not go on at $47AF")

        # seven bytes a block, as $40A2 copies them: $D414 (sustain, release) too,
        # which the other effects leave at $F4-$FB
        blocks = [(0xD415 + i, subs[0xDDE + i]) for i in range(7)] + \
                 [(0xD40E + i, subs[0xDEA + i]) for i in range(7)]
        self.assertEqual(subs[0xDF0], 0x00, "the click's sustain and release")
        walk = {3: 0x80, 7: 0x81, 9: 0x80}
        for start, stop, events in ((0x6B01, 0x6B11, walk),
                                    (0x6AF1, 0x6B94, {**walk, 14: 0x81, 16: 0x80})):
            with self.subTest(at=f"${start:04x}"):
                m[sym["st_since"]] = 0xFF
                sid.clear()
                self.assertTrue(run(start, stop, 400), "the move waits with no step before it")
                self.assertEqual(sid[0], (0xD412, 0x80))
                self.assertEqual(sorted(sid[1:]), sorted(blocks))
                self.assertEqual(dict(sid[1:])[0xD412], 0x81)
                self.assertEqual(m[sym["st_on"]], 1)
                if start == 0x6AF1:     # the horse's walk: $6BB4 JSR $6B01
                    sid.clear()
                    self.assertTrue(run(0x6B01, 0x6B11, 400), "the horse's walk waits")
                    self.assertEqual(sid, [], "the horse's walk clicks again")
                    self.assertEqual(m[sym["st_skip"]], 0)
                got = {}
                m[0x2D], m[0x2E] = 0xFF, 0x07
                for n in range(1, 21):
                    sid.clear()
                    tick()
                    self.assertTrue(all(a == 0xD412 for a, _v in sid), sid)
                    if sid:
                        got[n] = sid[-1][1]
                self.assertEqual(got, events)
                self.assertEqual(m[sym["st_on"]], 0)
                self.assertEqual((m[0x2D], m[0x2E]), (0x13, 0x08), "the frame count")
                self.assertEqual(m[sym["st_since"]], 20)
                m[sym["st_since"]] = floor - 1
                self.assertFalse(run(start, stop), "a move before the floor")
                m[sym["st_since"]] = floor
                self.assertTrue(run(start, stop, 400), "a move at the floor")
                m[sym["st_skip"]] = 0
        self.assertEqual(floor, 20, "0.2 s: five steps a second")
        # st_since stops at $FF
        m[sym["st_since"]] = 0xFE
        tick()
        tick()
        self.assertEqual(m[sym["st_since"]], 0xFF)
        # a click in flight: st_flush waits with interrupts on, cuts it with them off
        for irq_off in (False, True):
            m[sym["st_on"]] = 1
            m[0x1F0], m[0x1F1] = 0xFF, 0x0F         # its return: $1000
            sid.clear()
            mpu.pc, mpu.sp = sym["st_flush"], 0xEF
            mpu.p = (mpu.p | mpu.INTERRUPT) if irq_off else (mpu.p & ~mpu.INTERRUPT)
            for _ in range(2000):
                if mpu.pc == 0x1000:
                    break
                mpu.step()
            self.assertEqual(mpu.pc == 0x1000, irq_off)
            if irq_off:
                self.assertEqual((m[sym["st_on"]], sid), (0, [(0xD412, 0x80)]))
                self.assertTrue(mpu.p & mpu.INTERRUPT, "the I flag")
        self.assertEqual(subs[0x40A2 - 0x4000:0x40A5 - 0x4000],
                         bytes([0x4C, sym["st_fx"] & 0xFF, sym["st_fx"] >> 8]))

    def test_the_copy_protection_returns_a_read_error(self):
        """$C034 tests for ASCII '2'; the stub has to hand back exactly that."""
        intro = self.segment(u2.INTRO_ADDR)
        off = 0xCED6 - u2.INTRO_ADDR
        self.assertEqual(intro[off:off + 3], bytes([0xA9, 0x32, 0x60]))
        self.assertEqual(intro[0xC034 - u2.INTRO_ADDR:0xC036 - u2.INTRO_ADDR],
                         bytes([0xC9, 0x32]))

    # -- the driver ------------------------------------------------------

    def test_driver_sits_between_the_map_cache_and_intro(self):
        """$A000-$B0FF is the map cache ($6809/$685F copy exactly that much)
        and INTRO loads at $C000, so the driver has $B100-$BFFF."""
        self.assertEqual(u2.DRIVER_ADDR, 0xB100)
        self.assertLessEqual(u2.DRIVER_ADDR + len(self.driver), u2.INTRO_ADDR)
        self.assertEqual(self.driver[0], 0x4C, "the init stub's entry is a JMP")

    def test_driver_flash_map_was_filled_in(self):
        off = self.sym["u2_recpage"] - u2.DRIVER_ADDR
        self.assertNotEqual(self.driver[off:off + 2], b"\xff\xff")
        self.assertEqual(self.driver[off] | self.driver[off + 1] << 8,
                         self.parts["rec_page"])

    def test_init_stub_locks_shift_commodore(self):
        """MODE ($0291) bit 7: Shift+C= does not flip the character set (it
        showed until the raster split put it back); nothing of U2 calls CINT
        or writes $0291."""
        init = self.segment(u2.INIT_ADDR)
        self.assertIn(bytes([0xA9, 0x80, 0x8D, 0x91, 0x02]), init)
        for (number, name) in [(n, e[0]) for n, d in self.disks.items() for e in d.directory()]:
            data = self.disks[number].file(name)[0]
            for pat in (bytes([0x20, 0x81, 0xFF]), bytes([0x8D, 0x91, 0x02]), bytes([0x8E, 0x91, 0x02]),
                        bytes([0x8C, 0x91, 0x02])):
                self.assertNotIn(pat, data, (number, name, pat.hex()))

    def test_init_stub_is_the_entry_point(self):
        self.assertEqual(self.entry, u2.INIT_ADDR)
        init = self.segment(u2.INIT_ADDR)
        self.assertLess(u2.INIT_ADDR + len(init), 0x0286)


if __name__ == "__main__":
    unittest.main()
