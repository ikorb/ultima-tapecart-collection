"""Verify the Ultima 3 cart image against the original disks.

The catalog is rewritten so each entry's start-block field is a flash page.
Every read-only entry is pulled back out through that rewritten catalog and
compared with the bytes the original disk holds at the same block range.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

from ultima.disks.d64 import D64
from ultima.flash.tcrt import TCRT
from ultima.launcher import patches
from ultima.flash import regions

from ultima.games.u3 import gold  # noqa: E402
from ultima.flash import zx
from ultima import paths

TCRT_PATH = os.path.join(paths.BUILD, "ultima3.tcrt")
DISK_A = paths.disk("u3a")
DISK_B = paths.disk("u3b")

ENTRIES, ENTRY_SIZE = 94, 8
F_WRITABLE = 0x80
F_COMP = 0x8000      # bit 15 of the start-page field
SAVE_SLOT = 2 * regions.ERASE_BLOCK
WRITABLE = ["SOSA", "SOSM", "ROST", "PLRS", "PRTY"]
DISK_A_FILES = {"EXOD", "TEXT", "SHPS", "DEMO", "ULT3",
                "DDAT", "BOOT", "SUBS", "MUSI", "COPY"}
DOS_TRANSFER, DOS_ADDR, DRIVER_ADDR = 0xBA48, 0xB800, 0xBC00


def blocks(disk, start, count):
    out = bytearray()
    for n in range(start, start + count):
        out += disk.sector(*D64.from_linear(n))
    return bytes(out)


class TestU3Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, "-m", "ultima.games.u3.build"],
                       check=True, stdout=subprocess.DEVNULL)
        cls.flash = TCRT.read(TCRT_PATH).flash
        cls.a, cls.b = D64(DISK_A), D64(DISK_B)
        import importlib.util as _il
        _spec = _il.find_spec("ultima.games.u3.build")
        _mod = _il.module_from_spec(_spec)
        _spec.loader.exec_module(_mod)
        cls.parts = _mod.parts()
        cls.mod = _mod
        desc = cls.flash[regions.desc_offset("u3"):regions.desc_offset("u3") + 64]
        cls.entry = desc[0] | desc[1] << 8
        cls.segments = []
        for i in range(desc[2]):
            o = 3 + 7 * i
            cls.segments.append((desc[o] << 8 | desc[o + 1] << 16,
                                 desc[o + 2] | desc[o + 3] << 8,
                                 desc[o + 4] | desc[o + 5] << 8))
        off, length, _ = [s for s in cls.segments if s[2] == 0xB000][0]
        cls.catalog = cls.flash[off:off + length]
        off, length, _ = [s for s in cls.segments if s[2] == DOS_ADDR][0]
        cls.dos = cls.flash[off:off + length]

    def entries(self):
        for i in range(ENTRIES):
            e = i * ENTRY_SIZE
            ent = self.catalog[e:e + ENTRY_SIZE]
            name = bytes(c & 0x7F for c in ent[:4]).decode("latin1").strip()
            yield name, ent[4] | ent[5] << 8, ent[6], ent[7]

    def test_read_only_entries_resolve_to_the_right_disk_bytes(self):
        """Bit 15 of the start-page field (F_COMP) says the unit is stored crunched, with its
        own compressed length in the first two bytes -- the catalog entry is
        eight bytes and has nowhere else to put it."""
        orig = blocks(self.a, 100, 4)     # the catalog as it ships
        for i, (name, page, length, dest) in enumerate(self.entries()):
            if name in WRITABLE:
                continue
            if name == "BOOT":
                # deliberately patched; test_track6_protection_is_neutralised
                # and test_the_rest_of_BOOT_is_untouched cover it exactly
                continue
            with self.subTest(name=name):
                e = i * ENTRY_SIZE
                start = orig[e + 4] | orig[e + 5] << 8
                disk = self.a if name in DISK_A_FILES else self.b
                want = gold.apply(name, blocks(disk, start, orig[e + 6] & 0x7F))
                if name == "EXOD":
                    want = self.mod.patch_exod(want)     # test_the_disk_copier_is_off
                if name == "SUBS":                       # test_keys_typed_ahead_are_kept
                    want = self.mod.patch_subs_keys(want, self.drvsym["kb_take"])
                if name == "ULT3":
                    want = self.mod.patch_ult3_keys(want, self.drvsym["kb_take"])
                    want = self.mod.patch_ult3_trainer(want, self.drvsym)
                if name in ("ULT3", "SUBS", "MUSI"):    # test_the_footstep_is_played_from_the_irq
                    want = self.mod.patch_step(name, want, self.drvsym)
                if name in ("SUBS", "UPDT"):            # the scroll's and the view's tests
                    want = self.mod.patch_draw(name, want, self.drvsym)
                if name in self.mod.PEERS:               # tests/test_u3_peer.py
                    want = self.mod.peer_unit(name, want)
                    self.assertEqual(length & 0x7F, len(want) // 256, "its length in blocks")
                off = (page & 0x7FFF) << 8
                if page & F_COMP:
                    self.assertEqual(zx.unsized(self.flash[off:]), want)
                else:
                    self.assertEqual(self.flash[off:off + len(want)], want)

    def test_gold_trainer_keys_follow_the_option(self):
        """Gold's ingame keys (u3trainer.s): each hook, run in py65 on the built
        ULT3 and the driver's decoder segment, goes Gold's way with tr_on = $80
        and the original's with 0 -- B with nothing to board, F7 and space at
        the surface dispatcher, X in combat, O(ther) -- and the teleport refuses
        coordinates past 63."""
        try:
            from py65.devices.mpu6502 import MPU
        except ImportError:
            self.skipTest("py65 is not installed (use the repository's .venv)")
        sym = self.drvsym
        ult3 = self.parts["unit_data"]["ULT3"]
        off, length, _ = [s for s in self.segments if s[2] == 0xC500][0]
        seg = self.flash[off:off + length]

        def run(pc, on, a=0, x=0, stops=()):
            mpu = MPU()
            mpu.memory[0x5000:0x5000 + len(ult3)] = list(ult3)
            mpu.memory[0xC500:0xC500 + len(seg)] = list(seg)
            mpu.memory[sym["tr_on"]] = 0x80 if on else 0
            mpu.pc, mpu.a, mpu.x, mpu.sp = pc, a, x, 0xF0
            mpu.memory[0x1F1], mpu.memory[0x1F2] = 0xDB, 0x61   # (for the Other hook's JSR)
            for _ in range(20):
                if mpu.pc in stops:
                    return mpu.pc
                mpu.step()
            self.fail(f"${pc:04x}: no stop reached (${mpu.pc:04x})")
        cases = [  # (hook, A, X, off -> , on ->)
            (0x52AF, 0, 0, 0x520F, 0x934C),
            (0x50E5, 0x88, 0, 0x50F5, 0x9383),      # F7: teleport when on
            (0x50E5, 0xA0, 0, 0x50E9, 0x50E9),      # space: a pass either way
            (0x50E5, 0xC1, 0, 0x50F5, 0x50F5),      # anything else: on through
            (0x801E, 0xD8, 0, 0x80FE, 0x834E),      # X: VICTORY! when on
            (0x801E, 0xC1, 0, 0x80FE, 0x80FE),
            (0x61DA, 0xC1, 0, 0x46C3, 0x756B),      # an 8-letter word ending in A
            (0x61DA, 0xC1, 1, 0x46C3, 0x46C3),
            (0x61DA, 0xC5, 0, 0x46C3, 0x46C3),
        ]
        for pc, a, x, off_to, on_to in cases:
            with self.subTest(hook=hex(pc), a=hex(a), x=x):
                stops = {off_to, on_to}
                self.assertEqual(run(pc, False, a, x, stops), off_to)
                self.assertEqual(run(pc, True, a, x, stops), on_to)
        o = 0x93AF - 0x5000
        self.assertEqual(bytes(ult3[o:o + 3]), bytes.fromhex("c9 40 60"), "0-63 only")

    def test_the_trainer_keys_keep_the_map(self):
        """u3trainer.s's tr_pool, tr_back and tr_xit, run in py65 at their hooks
        on the built ULT3, SUBS and decoder segment, and B's edits in Gold's
        tail: the whirlpool's trip clears only the whirlpool's tile and brings
        the party back on a frigate only onto water; X-it parks a frigate on
        water and a horse on grass only; B's S and H skip Board's writes."""
        try:
            from py65.devices.mpu6502 import MPU
        except ImportError:
            self.skipTest("py65 is not installed (use the repository's .venv)")
        units = self.parts["unit_data"]
        off, length, _ = [s for s in self.segments if s[2] == 0xC500][0]
        seg = self.flash[off:off + length]
        X, Y = 44, 18
        square = 0x1000 + Y * 64 + X

        def run(pc, stop, tile, craft=0, a=0):
            mpu = MPU()
            mpu.memory[0x5000:0x5000 + len(units["ULT3"])] = list(units["ULT3"])
            mpu.memory[0x4100:0x4100 + len(units["SUBS"])] = list(units["SUBS"])
            mpu.memory[0xC500:0xC500 + len(seg)] = list(seg)
            mpu.memory[square] = tile
            mpu.memory[0x02], mpu.memory[0x03] = X, Y
            mpu.memory[0xF7], mpu.memory[0xF8] = X, Y
            mpu.memory[0x7E], mpu.memory[0x7F] = square & 0xFF, square >> 8
            mpu.memory[0x0E] = craft
            mpu.pc, mpu.a, mpu.y, mpu.sp = pc, a, 0, 0xF0
            for _ in range(200):
                if mpu.pc == stop:
                    return mpu
                mpu.step()
            self.fail(f"${pc:04x}: ${stop:04x} not reached (${mpu.pc:04x})")

        for tile, left in ((0x30, 0x00), (0x04, 0x04), (0x1C, 0x1C)):   # whirlpool, grass, castle
            with self.subTest(down=hex(tile)):
                self.assertEqual(run(0x762B, 0x7632, tile).memory[square], left)
        for tile, party in ((0x00, 0x16), (0x04, 0x7E), (0x1C, 0x7E)):
            with self.subTest(back=hex(tile)):
                self.assertEqual(run(0x7777, 0x777B, tile).memory[0x60], party)
        for craft, tile, left in ((0x16, 0x00, 0x2C), (0x16, 0x04, 0x04),    # frigate
                                  (0x14, 0x04, 0x28), (0x14, 0x00, 0x00)):   # horse
            with self.subTest(xit=hex(craft), tile=hex(tile)):
                self.assertEqual(run(0x6951, 0x6956, tile, craft, a=tile).memory[square], left)
        ult3 = units["ULT3"]
        for at, to in ((0x9367, 0x52D4), (0x9372, 0x52B6)):
            o = at - 0x5000
            self.assertEqual(bytes(ult3[o:o + 3]), bytes([0x4C, to & 0xFF, to >> 8]))
        o = 0x52D4 - 0x5000
        self.assertEqual(bytes(ult3[o:o + 4]), bytes.fromhex("a9 16 85 0e"), "Board's frigate")
        o = 0x52B6 - 0x5000
        self.assertEqual(bytes(ult3[o:o + 4]), bytes.fromhex("a9 14 85 0e"), "Board's horse")

    def test_a_fight_can_be_avoided(self):
        """"AVOID?" (u3avoid.s, the page's A): a monster reaching the party
        ($78D5) and a dungeon's encounter ($8E01), run in py65 on the built
        ULT3 and the driver's decoder segment: the option off, the fight
        without a question; on, "AVOID?" and Y skips it (the next monster;
        the dungeon's turn as without one), anything else fights -- with the
        monster in X, and $8E01's LDA $23 / CLC done."""
        try:
            from py65.devices.mpu6502 import MPU
        except ImportError:
            self.skipTest("py65 is not installed (use the repository's .venv)")
        sym = self.drvsym
        ult3 = self.parts["unit_data"]["ULT3"]
        off, length, _ = [s for s in self.segments if s[2] == 0xC500][0]
        seg = self.flash[off:off + length]
        for at, orig, name, op in self.mod.AVOID_HOOKS:
            o = at - 0x5000
            self.assertEqual(bytes(ult3[o:o + 3]), bytes([op, sym[name] & 0xFF, sym[name] >> 8]))

        def run(pc, opts, key, stops):
            mpu = MPU()
            m = mpu.memory
            m[0x5000:0x5000 + len(ult3)] = list(ult3)
            m[0xC500:0xC500 + len(seg)] = list(seg)
            m[sym["pt_opts"]] = opts
            m[0x23] = 2
            mpu.pc, mpu.x, mpu.sp = pc, 5, 0xF0
            asked = []
            for _ in range(200):
                if mpu.pc in stops:
                    return mpu.pc, mpu, asked
                if mpu.pc == 0x46C3:                # print the inline string
                    sp = mpu.sp
                    ret = (m[0x101 + sp] | m[0x102 + sp] << 8) + 1
                    text = bytearray()
                    while m[ret]:
                        text.append(m[ret] & 0x7F)
                        ret += 1
                    asked.append(text.decode("latin1"))
                    mpu.sp = (sp + 2) & 0xFF
                    mpu.pc = ret + 1
                    continue
                if mpu.pc == 0x4711:                # the key wait
                    mpu.a = key
                    sp = mpu.sp
                    mpu.pc = (m[0x101 + sp] | m[0x102 + sp] << 8) + 1
                    mpu.sp = (sp + 2) & 0xFF
                    continue
                mpu.step()
            self.fail(f"${pc:04x}: no stop reached (${mpu.pc:04x})")
        av = patches.AVOID
        for opts, key, fight, question in ((0, 0xD9, True, False), (av, 0xD9, False, True),
                                           (av, 0xCE, True, True), (0xFF & ~av, 0xD9, True, False)):
            with self.subTest(opts=hex(opts), key=hex(key)):
                pc, mpu, asked = run(0x78D5, opts, key, {0x5249, 0x78B3})
                self.assertEqual(pc, 0x5249 if fight else 0x78B3)
                if fight:
                    self.assertEqual(mpu.x, 5, "the monster")
                self.assertEqual(asked, ["AVOID?\x7f"] if question else [])
                pc, mpu, asked = run(0x8E01, opts, key, {0x8E04, 0x8B2B})
                self.assertEqual(pc, 0x8E04 if fight else 0x8B2B)
                self.assertEqual(mpu.sp, 0xF0, "the stack as it was")
                if fight:
                    self.assertEqual(mpu.a, 2, "LDA $23")
                    self.assertFalse(mpu.p & 1, "CLC")

    def test_gold_the_dagger_shop(self):
        """SHP3, the weapon shop: Gold's whole ("AMOUNT-" for daggers), the
        rest of its last block as it was; it calls out only where the
        original does and to three jump-table entries (gold.SHP3_NEW_CALLS)."""
        name_at = [i for i, (n, _p, _l, _d) in enumerate(self.entries()) if n == "SHP3"]
        self.assertEqual(len(name_at), 1)
        orig_cat = blocks(self.a, 100, 4)
        e = name_at[0] * ENTRY_SIZE
        start, length = orig_cat[e + 4] | orig_cat[e + 5] << 8, orig_cat[e + 6] & 0x7F
        disk = self.a if "SHP3" in DISK_A_FILES else self.b
        orig = blocks(disk, start, length)
        new = gold.apply("SHP3", orig)
        g = gold._read("shp3.prg")
        self.assertEqual(new[:len(g) - 2], g[2:])
        self.assertEqual(new[len(g) - 2:], orig[len(g) - 2:])
        self.assertEqual(len(new), len(orig))
        self.assertIn("shp3.prg", gold.fingerprint())
        # "AMOUNT-" is in it: Gold's prompt
        self.assertIn(bytes(ord(c) | 0x80 for c in "AMOUNT-"), new)

    @property
    def drvsym(self):
        import re
        return {m.group(1): int(m.group(2), 16) for m in re.finditer(
            r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path(os.path.join(paths.BUILD, "u3drv.sym")).read_text())}

    def test_keys_typed_ahead_are_kept(self):
        """SUBS' key wait and ULT3's six command loops: each poll is the
        driver's kb_take, each flush after it a BIT; kb_take, run: three keys queued come out in order, X
        kept; with none, joystick 2's directions as @ / : ; and fire as E, T
        or A by $62, at most every 5 jiffies; nothing: $FF."""
        try:
            from ultima.sim.sim6502 import Sim
        except ImportError:
            self.skipTest("py65 is not installed")
        sym = self.drvsym
        k = sym["kb_take"]
        off, length, _ = [s for s in self.segments if s[2] == 0xC500][0]
        seg = self.flash[off:off + length]
        sim = Sim(seg, 0xC500, sym)
        sim.mem[0x0277:0x027A] = [0x41, 0x42, 0x43]
        sim.mem[0xC6] = 3
        got = []
        for _ in range(3):
            sim.mpu.x = 0x5A
            sim.call(k)
            got.append(sim.mpu.a)
            self.assertEqual(sim.mpu.x, 0x5A)
        self.assertEqual(got, [0xC1, 0xC2, 0xC3])
        self.assertEqual(sim.mem[0xC6], 0)
        for port, mode, want in ((0x7E, 0, 0xC0), (0x7D, 0, 0xAF), (0x7B, 0, 0xBA), (0x77, 0, 0xBB),
                                 (0x6F, 0, 0xC5), (0x6F, 3, 0xD4), (0x6F, 0x80, 0xC1), (0x7F, 0, 0xFF)):
            with self.subTest(port=hex(port), mode=mode):
                sim.mem[0xDC00], sim.mem[0x62] = port, mode
                sim.mem[0xA2] = (sim.mem[sym["kb_last"]] + 5) & 0xFF
                sim.call(k)
                self.assertEqual(sim.mpu.a, want)
        sim.mem[0xDC00] = 0x7E
        sim.mem[0xA2] = (sim.mem[sym["kb_last"]] + 2) & 0xFF      # too soon again
        sim.call(k)
        self.assertEqual(sim.mpu.a, 0xFF)

    def test_the_footstep_is_played_from_the_irq(self):
        """u3step.s, run in py65 on the built ULT3, SUBS, MUSI, DOS module and
        decoder segment: a move's footstep ($710A) plays its first click (eight
        writes of $D418) and returns A = 0 at once, the second left to the IRQ;
        MUSI's handler calls st_tick, which plays it at the third tick and goes
        on to the player at $9A86 every time; on a horse ($0E = $14) a third
        click three ticks later; with $20 set, none.  The speaker's state is as it
        was after each click.  An effect or a load waits for a click in
        flight, or drops it with interrupts masked.  $72EC no longer draws the
        party's panel, which its callers draw next."""
        try:
            from py65.devices.mpu6502 import MPU
            from py65.memory import ObservableMemory
        except ImportError:
            self.skipTest("py65 is not installed (use the repository's .venv)")
        sym, units = self.drvsym, self.parts["unit_data"]
        ult3, subs, musi = units["ULT3"], units["SUBS"], units["MUSI"]
        off, length, _ = [s for s in self.segments if s[2] == 0xC500][0]
        seg = self.flash[off:off + length]
        off, length, _ = [s for s in self.segments if s[2] == DRIVER_ADDR][0]
        drv = self.flash[off:off + length]
        le = lambda op, a: bytes([op, a & 0xFF, a >> 8])
        self.assertEqual(ult3[0x210F:0x2115], le(0x20, sym["st_foot"]) + b"\xa9\x00\x60")
        self.assertEqual(ult3[0x230D:0x2311], bytes.fromhex("2c d3 71 60"))
        self.assertEqual(subs[0x060E:0x0611], le(0x4C, sym["st_fx"]))
        self.assertEqual(musi[0x7B:0x7E], le(0x20, sym["st_tick"]))
        t = sym["u3_transfer"] - DRIVER_ADDR
        self.assertEqual(drv[t:t + 3], le(0x20, sym["st_flush"]), "a load waits for the clicks")

        speaker = []
        mem = ObservableMemory()
        mem.subscribe_to_write([0xD418], lambda a, v: speaker.append(v))
        mpu = MPU(memory=mem)
        m = mpu.memory
        m[0x4100:0x4100 + len(subs)] = list(subs)
        m[0x5000:0x5000 + len(ult3)] = list(ult3)
        m[0x9A00:0x9A00 + len(musi)] = list(musi)
        m[0xB800:0xB800 + len(self.dos)] = list(self.dos)
        m[0xC500:0xC500 + len(seg)] = list(seg)
        RET = 0x0400

        def call(pc, stop=RET, steps=200000, irq_off=False):
            m[0x1F0], m[0x1F1] = (RET - 1) & 0xFF, (RET - 1) >> 8
            mpu.pc, mpu.sp = pc, 0xEF
            mpu.p = (mpu.p | mpu.INTERRUPT) if irq_off else (mpu.p & ~mpu.INTERRUPT)
            mpu.p &= ~mpu.DECIMAL
            for _ in range(steps):
                if mpu.pc == stop:
                    return True
                mpu.step()
            return False

        state = m[0xB93E]
        for transport, sound, clicks in ((0x7E, 0, [3]), (0x14, 0, [3, 6]), (0x7E, 1, [])):
            with self.subTest(transport=hex(transport), sound=sound):
                m[0x0E], m[0x20] = transport, sound
                speaker.clear()
                self.assertTrue(call(0x710A), "the footstep does not return")
                self.assertEqual((mpu.a, mpu.p & mpu.ZERO), (0, mpu.ZERO), "LDA #$00 / RTS")
                self.assertEqual(len(speaker), 0 if sound else 8, "the first click")
                self.assertEqual(m[0xB93E], state)
                got = []
                for n in range(1, 13):
                    speaker.clear()
                    self.assertTrue(call(sym["st_tick"], stop=0x9A86), "st_tick goes on at $9A86")
                    if speaker:
                        self.assertEqual(len(speaker), 8, f"tick {n}")
                        self.assertEqual(m[0xB93E], state)
                        got.append(n)
                self.assertEqual(got, clicks)
                self.assertEqual(m[sym["st_n"]], 0)

        m[0x0E], m[0x20] = 0x7E, 0
        for routine in ("st_fx", "u3_transfer"):
            with self.subTest(waits=routine):
                self.assertTrue(call(0x710A))
                self.assertFalse(call(sym[routine], stop=0x4D3D, steps=5000), "no wait for the click")
                self.assertEqual(m[sym["st_n"]], 1)
                m[sym["st_n"]] = 0          # the IRQ played it
                if routine == "st_fx":
                    self.assertTrue(call(sym[routine], stop=0x4D3D, steps=50))
                self.assertTrue(call(0x710A))
                speaker.clear()
                mpu.a = 0x5A
                self.assertTrue(call(sym["st_flush"], steps=50, irq_off=True), "masked: no wait")
                self.assertEqual((m[sym["st_n"]], mpu.a, speaker), (0, 0x5A, []))

    def unpatched(self, name):
        """A read-only unit as the disk has it, with Gold's changes."""
        return self.mod.unit_from_disks(name)

    def machine(self, units):
        """py65 with units at their addresses (name -> (address, bytes)), the
        DOS module and the decoder segment; cycles counted."""
        from py65.devices.mpu6502 import MPU
        mpu = MPU()
        m = mpu.memory
        off, length, _ = [s for s in self.segments if s[2] == 0xC500][0]
        for addr, data in [(0xB800, self.dos), (0xC500, self.flash[off:off + length]), *units]:
            m[addr:addr + len(data)] = list(data)
        return mpu

    def run_to(self, mpu, pc, stop, steps=500000):
        """From pc (None: on from where it is) to stop: the cycles."""
        if pc is not None:
            mpu.pc, mpu.sp = pc, 0xEF
            mpu.p &= ~(mpu.DECIMAL | mpu.INTERRUPT)
        start = mpu.processorCycles
        for _ in range(steps):
            if mpu.pc == stop:
                return mpu.processorCycles - start
            mpu.step()
        self.fail(f"${pc:04x}: ${stop:04x} not reached")

    def test_the_message_window_scrolls_as_before(self):
        """u3scroll.s at SUBS $4770, run in py65 against the original routine
        over the same random bitmap, screen RAM and zero page: the same
        memory afterwards but for the stack and the scratch the glyph printer
        and the DOS module's colour hook write before they read ($4912-$4916,
        $B891-$B893), the same A, X and Y, in a third of the cycles."""
        try:
            import py65  # noqa: F401
        except ImportError:
            self.skipTest("py65 is not installed (use the repository's .venv)")
        import random
        subs, text = self.parts["unit_data"]["SUBS"], self.parts["unit_data"]["TEXT"]
        self.assertEqual(subs[0x0670:0x0670 + len(self.mod.scroll_code())], self.mod.scroll_code())
        orig = bytearray(subs)                  # the cart's SUBS with the original scroll
        orig[0x0670:0x06FC] = self.unpatched("SUBS")[0x0670:0x06FC]
        rng = random.Random(3)
        ignore = set(range(0x100, 0x200)) | set(range(0x4770, 0x47FC)) | \
            set(range(0x4912, 0x4917)) | set(range(0xB891, 0xB894))
        for trial in range(3):
            state = bytes(rng.randrange(256) for _ in range(0x10000))
            got = []
            for unit in (orig, subs):
                mpu = self.machine([(0x4100, unit), (0xB400, text)])
                m = mpu.memory
                for lo, hi in ((0x02, 0x100), (0x0400, 0x0800), (0x2000, 0x4000)):
                    m[lo:hi] = list(state[lo:hi])
                m[0x01F0], m[0x01F1] = 0xFF, 0x03          # returns to $0400
                cycles = self.run_to(mpu, 0x4770, 0x0400)
                got.append((cycles, bytes(m[i] for i in range(0x10000)), (mpu.a, mpu.x, mpu.y)))
            (c0, m0, r0), (c1, m1, r1) = got
            with self.subTest(trial=trial):
                diff = [hex(i) for i in range(0x10000) if m0[i] != m1[i] and i not in ignore]
                self.assertEqual(diff, [])
                self.assertEqual(r0, r1, "A, X, Y")
                self.assertLess(c1 * 3, c0, f"{c1} cycles, the original {c0}")

    def test_the_line_of_sight_is_the_original(self):
        """u3view.s, run in py65 against UPDT's own pass from $CA09 to the blit
        ($CB01), over random maps at random places, both ways off the map's
        edge ($0F): the same view at $9900, the same zero page, A, X and Y,
        the pass itself in under 10k cycles (the original: 35-44k on Sosaria)."""
        try:
            import py65  # noqa: F401
        except ImportError:
            self.skipTest("py65 is not installed (use the repository's .venv)")
        import random
        updt, orig = self.parts["unit_data"]["UPDT"], self.unpatched("UPDT")
        rng = random.Random(5)
        # tiles as the map holds them; $0C, $10, $8C and $90 are the blockers
        tiles = [0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C, 0x8C, 0x90, 0x7E, 0x30]
        hidden = 0
        for trial in range(40):
            blockers = rng.choice((0.1, 0.25, 0.5))
            world = bytes(rng.choice(tiles[3:5] + tiles[8:10]) if rng.random() < blockers
                          else rng.choice(tiles) for _ in range(0x1000))
            zp = bytes(rng.randrange(256) for _ in range(0x100))
            got = []
            for unit in (orig, updt):
                mpu = self.machine([(0xCA00, unit), (0x1000, world)])
                m = mpu.memory
                m[0x02:0x100] = list(zp[0x02:])
                m[0x0F] = rng.choice((0xFF, 0x04)) if unit is orig else got[0][3]
                self.run_to(mpu, 0xCA09, 0xCA99)
                cycles = self.run_to(mpu, None, 0xCB01)     # the line of sight
                got.append((cycles, bytes(m[0x9900:0x9979]), bytes(m[0:0x100]), m[0x0F],
                            (mpu.a, mpu.x, mpu.y)))
            (c0, v0, z0, _, r0), (c1, v1, z1, _, r1) = got
            with self.subTest(trial=trial, at=(zp[0xF7], zp[0xF8])):
                self.assertEqual(v1, v0, "the view")
                self.assertEqual(z1, z0, "the zero page")
                self.assertEqual(r1, r0, "A, X, Y")
                self.assertLess(c1, 10000, f"{c1} cycles, the original {c0}")
            hidden += v0.count(0x48)
        self.assertGreater(hidden, 400, "the trials hide squares")

    def test_crunching_only_ever_shrinks_a_unit(self):
        orig = blocks(self.a, 100, 4)
        for i, (name, page, length, dest) in enumerate(self.entries()):
            if name in WRITABLE:
                self.assertFalse(page & F_COMP, f"{name} is a save slot")
                continue
            e = i * ENTRY_SIZE
            start = orig[e + 4] | orig[e + 5] << 8
            disk = self.a if name in DISK_A_FILES else self.b
            raw = blocks(disk, start, length & 0x7F)
            if name == "BOOT":
                continue                    # patched, covered elsewhere
            with self.subTest(name=name):
                self.assertEqual(bool(page & F_COMP),
                                 zx.smaller(raw, zx.sized) is not None)

    def test_writable_entries_point_at_their_own_slots(self):
        seen = set()
        for name, page, length, dest in self.entries():
            if name not in WRITABLE:
                continue
            with self.subTest(name=name):
                self.assertTrue(length & F_WRITABLE, "writable flag not set")
                offset = page << 8
                self.assertEqual(offset % regions.ERASE_BLOCK, 0)
                self.assertGreaterEqual(offset, regions.save_base("u3"))
                self.assertNotIn(offset, seen)
                seen.add(offset)

    def test_writable_slots_are_seeded_from_disk_b(self):
        orig = blocks(self.a, 100, 4)
        for i, (name, page, length, dest) in enumerate(self.entries()):
            if name not in WRITABLE:
                continue
            with self.subTest(name=name):
                e = i * ENTRY_SIZE
                start = orig[e + 4] | orig[e + 5] << 8
                nblk = length & 0x7F
                base = page << 8
                self.assertEqual(self.flash[base:base + 2], b"\xa5\x5a")
                self.assertEqual(self.flash[base + 2], nblk)
                self.assertEqual(self.flash[base + 0x100:base + 0x100 + nblk * 256],
                                 blocks(self.b, start, nblk))

    def test_slots_have_room_for_their_data_plus_a_header_page(self):
        for name, page, length, dest in self.entries():
            if name in WRITABLE:
                with self.subTest(name=name):
                    self.assertLessEqual((length & 0x7F) * 256 + 256, SAVE_SLOT)

    def boot_unit(self):
        """What BOOT decodes to: the unit in flash, decoded with zx.decode
        (the host mirror of the 6502 decoder), checked against build.py's own
        patcher run over the original blocks.  The patcher's output is then
        what the assertions below inspect."""
        import importlib.util as _il
        spec = _il.find_spec("ultima.games.u3.build")
        mod = _il.module_from_spec(spec)
        spec.loader.exec_module(mod)
        patched = gold.apply("BOOT", mod.patch_boot(blocks(self.a, 217, 15)))
        for name, page, length, _dest in self.entries():
            if name != "BOOT":
                continue
            off = (page & 0x7FFF) << 8
            got = zx.unsized(self.flash[off:]) if page & F_COMP \
                else self.flash[off:off + len(patched)]
            self.assertEqual(got, patched, "BOOT in flash is not the patched file")
            return patched
        self.fail("no BOOT entry in the catalog")

    def test_track6_protection_is_neutralised(self):
        """BOOT calls $1DF4 from $103F; that routine reads track 6 sector 8
        with its own KERNAL block reader and hangs at $1E42 if the read
        SUCCEEDS.  Disk A carries an error map with all of track 6 flagged
        "21 no sync", so on an original the read fails and it returns having
        done nothing.  With no drive it would stall on a KERNAL timeout and,
        with a drive attached, seek the head to track 6 for nothing."""
        boot = self.boot_unit()
        off = 0x103F - 0x1000
        self.assertEqual(boot[off:off + 3], b"\xea\xea\xea",
                         "the jsr $1DF4 call site should be NOPed out")

    def test_the_rest_of_BOOT_is_untouched(self):
        """The two patches of our own, and Ultima III Gold's: its menu block,
        the block's two callers, the delete key.  Nothing else."""
        orig = blocks(self.a, 217, 15)
        boot = self.boot_unit()
        allowed = [(0x103F, 0x1042), (0x1055, 0x1058), gold.BOOT_BLOCK,
                   (gold.BOOT_DELETE, gold.BOOT_DELETE + 1)] + \
                  [(a + 1, a + 3) for a in gold.BOOT_CALLERS]
        for i, (x, y) in enumerate(zip(orig, boot)):
            if x != y:
                addr = 0x1000 + i
                self.assertTrue(any(lo <= addr < hi for lo, hi in allowed),
                                f"BOOT changed at ${addr:04x}")

    def test_gold_the_menu_block_is_golds_moved_up(self):
        """Ultima III Gold's BOOT is the original shifted down by $72: its
        menu block, moved up again, is the original's block with every
        operand into BOOT $72 higher -- and its callers go to its one entry."""
        boot = self.boot_unit()
        gb = gold._read("boot.prg")[2:]
        lo, hi = gold.BOOT_BLOCK
        mine = boot[lo - 0x1000:hi - 0x1000]
        theirs = gb[lo - gold.BOOT_SHIFT - 0x1000:hi - gold.BOOT_SHIFT - 0x1000]
        diff = [i for i in range(len(mine)) if mine[i] != theirs[i]]
        for i in diff:                  # only operand high bytes, moved by $72 >> 8
            self.assertLess(lo + i - gold.BOOT_SHIFT, gold.BOOT_CODE_END)
        words = {}
        for i in diff:
            j = i if (mine[i - 1] | mine[i] << 8) - (theirs[i - 1] | theirs[i] << 8) == 0x72 else i + 1
            words[j] = True
        for j in words:
            self.assertEqual((mine[j - 1] | mine[j] << 8) - (theirs[j - 1] | theirs[j] << 8), 0x72)
        for at in gold.BOOT_CALLERS:
            self.assertEqual(boot[at - 0x1000:at - 0x1000 + 3], bytes([0x20, lo & 0xFF, lo >> 8]))
        self.assertEqual(boot[gold.BOOT_DELETE - 0x1000], 0x94, "DEL, not '+', deletes")

    def test_gold_the_tiles_and_font_are_reordered(self):
        """SHPS and TEXT in bitmap order: tile t's top half is 16 bytes at
        t*16, its bottom half $400 on; character c is 8 bytes at c*8."""
        shps = gold.apply("SHPS", blocks(self.a, *self.span("SHPS")))
        orig = blocks(self.a, *self.span("SHPS"))
        for t in (0, 5, 63):
            for r in range(16):
                for b in range(2):
                    self.assertEqual(shps[(r >= 8) * 0x400 + t * 16 + b * 8 + (r & 7)],
                                     orig[r * 0x80 + t * 2 + b])
        text = gold.apply("TEXT", blocks(self.a, *self.span("TEXT")))
        orig = blocks(self.a, *self.span("TEXT"))
        for c in (0, 0x41, 0x7F):
            self.assertEqual(text[c * 8:c * 8 + 8], bytes(orig[r * 0x80 + c] for r in range(8)))

    def span(self, want):
        orig = blocks(self.a, 100, 4)
        for i, (name, _page, length, _dest) in enumerate(self.entries()):
            if name == want:
                e = i * ENTRY_SIZE
                return orig[e + 4] | orig[e + 5] << 8, length & 0x7F
        self.fail(want)

    def test_scenario_disk_prompt_is_skipped(self):
        """BOOT prints "INSERT SCENARIO DISK" at $1055 and then spins at
        $1072-$1078 until a key is pressed.  There is nothing to swap."""
        boot = self.boot_unit()
        off = 0x1055 - 0x1000
        self.assertEqual(boot[off:off + 3], b"\x4c\x79\x10",
                         "should jump past the prompt and its wait loop")

    def test_only_referenced_blocks_are_stored(self):
        """One unit per catalog entry, not two whole disk images.  The
        catalog references 606 of the disks' 1366 blocks, so anything near
        the size of even one disk means the old layout is back."""
        p = self.parts
        used = p["cursor"] - regions.data_base("u3")
        orig = blocks(self.a, 100, 4)
        referenced = sum(orig[i * ENTRY_SIZE + 6] for i in range(ENTRIES)) * 256
        self.assertLess(used, 174848, "a whole disk image is being stored")
        # page rounding plus the DOS module, catalog, driver and init stub
        self.assertLess(used - referenced, 12 * 1024)

    def test_EXOD_is_shared_with_its_boot_segment(self):
        """EXOD is catalog entry 'EXOD' and the $3000 boot segment.  They must
        be one unit -- 22 KiB is a third of this game, and storing it twice,
        or raw so the menu could read it, would undo most of the saving."""
        seg = [s for s in self.segments if s[2] == 0x3000][0]
        entry = [e for e in self.entries() if e[0] == "EXOD"][0]
        self.assertEqual(seg[0], (entry[1] & 0x7FFF) << 8)
        want = self.mod.patch_exod(blocks(self.a, 5, 87))
        self.assertTrue(entry[1] & F_COMP, "EXOD is not crunched")
        stored = self.flash[seg[0]:seg[0] + seg[1]]
        self.assertEqual(seg[1], 2 + (stored[0] | stored[1] << 8))
        self.assertEqual(zx.unsized(stored), want)

    def test_the_disk_copier_is_off(self):
        """EXOD's C at a wait ran COPY, the disk duplicator, which needs a
        drive and crashed: its CMP #$C3 is CMP #$00 now, so C ends the intro
        like any key -- the one byte that differs from the disk."""
        orig = blocks(self.a, 5, 87)
        got = self.mod.patch_exod(orig)
        diff = [i for i in range(len(orig)) if orig[i] != got[i]]
        self.assertEqual(diff, [self.mod.COPY_KEY + 1 - 0x3000])
        self.assertEqual(got[diff[0]], 0x00)

    def test_dos_transfer_is_redirected(self):
        o = DOS_TRANSFER - DOS_ADDR
        self.assertEqual(self.dos[o:o + 3],
                         bytes([0x4C, DRIVER_ADDR & 0xFF, DRIVER_ADDR >> 8]))

    def test_rest_of_the_dos_module_is_untouched(self):
        orig = blocks(self.a, 92, 4)
        o = DOS_TRANSFER - DOS_ADDR
        self.assertEqual(self.dos[:o], orig[:o])
        self.assertEqual(self.dos[o + 3:], orig[o + 3:])

    def test_catalog_names_are_not_disturbed(self):
        orig = blocks(self.a, 100, 4)
        for i in range(ENTRIES):
            e = i * ENTRY_SIZE
            self.assertEqual(self.catalog[e:e + 4], orig[e:e + 4])

    def test_boot_descriptor(self):
        # the entry is the init stub, which sets $01 and jumps to EXOD
        self.assertEqual(self.entry, 0x0200)
        self.assertEqual(sorted(d for _, _, d in self.segments),
                         [0x0200, 0x0825, 0x3000, 0xB000, 0xB800, 0xBC00, 0xC500])

    def test_the_credits_are_shown_but_not_on_journey_onward(self):
        """The boot PRG's own title screen ($0825, its end an RTS), run: the
        credits in screen RAM, white; the init stub calls it unless the
        options byte has JOURNEY."""
        off, length, _ = [s for s in self.segments if s[2] == 0x0825][0]
        credits = self.flash[off:off + length]
        self.assertEqual(credits[0x082C - 0x0825], 0x60)
        try:
            from ultima.sim.sim6502 import Sim
        except ImportError:
            self.skipTest("py65 is not installed")
        sim = Sim(credits, 0x0825, {})
        sim.call(0x0825)
        row = lambda r: bytes(sim.mem[0x0400 + 40 * r:0x0428 + 40 * r])
        scr = lambda text: bytes((ord(c) - 0x40) if c >= "@" else ord(c) for c in text)
        self.assertIn(scr("ORIGIN SYSTEMS"), row(6))
        self.assertIn(scr("EXODUS: ULTIMA III"), row(11))
        self.assertIn(scr("KENNETH W. ARNOLD"), row(18))
        self.assertEqual(sim.mem[0xD800 + 40 * 6 + 13], 1, "white")
        off, length, _ = [s for s in self.segments if s[2] == 0x0200][0]
        stub = self.flash[off:off + length]
        self.assertIn(bytes([0x20, 0x25, 0x08]), stub, "JSR $0825")
        i = stub.find(bytes([0x20, 0x25, 0x08]))
        self.assertEqual(stub[i - 7], 0xAD, "LDA PT_OPTS")
        self.assertEqual(stub[i - 4:i - 2], bytes([0x29, 0x04]), "AND #JOURNEY")

    def test_init_stub_ends_by_jumping_to_EXOD(self):
        off, length, _ = [s for s in self.segments if s[2] == 0x0200][0]
        stub = self.flash[off:off + length]
        self.assertEqual(stub[-3:], bytes([0x4C, 0x20, 0x82]),
                         "init stub must end with JMP $8220")

    def test_fits_its_region(self):
        end = max(o + l for o, l, _ in self.segments)
        self.assertLessEqual(end, regions.REGIONS["u3"][1])
        self.assertLessEqual(regions.save_base("u3") + len(WRITABLE) * SAVE_SLOT,
                             regions.REGIONS["u3"][3])


if __name__ == "__main__":
    unittest.main()
