"""Run Ultima 6's in-game driver -- resident and on-demand parts, the real
6502 code -- against the real flash image, on the host.

py65 executes `game` with the driver built into it; tc_sendbyte and
tc_getbyte are trapped onto a model of the tapecart's command interpreter
(sim6502.FakeCart) holding the flash the build produced.  Each test sends the
driver the game's own command strings (U6 notes 5b) through $29BE and checks
the result against the original disks: that is every layer above the wire --
parsing, the block maps, the cart directory, zx02, the write log.

Skipped without py65 (the repository's .venv has it).
"""
import importlib.util
import unittest

try:
    from ultima.sim.sim6502 import Sim
except ImportError:
    Sim = None

from ultima.flash.layout import image_from
from ultima.flash import regions

_spec = importlib.util.find_spec("ultima.games.u6.build")
u6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(u6)

CMD = 0xC000            # command strings (free in the simulator)
DEST = 0x4000           # where results land


def chain_bytes(d, name):
    """A file's bytes as the drive sends them: every data byte of its chain --
    and as the cart has them: the three conversations with the copy-protection
    questions accept any answer (build.py, COMPENDIUM), and the opening's,
    the intro's and the ending's text-box split is steady (SPLIT_FILES) and
    their "press a key" sees the keyboard (KEYWAIT)."""
    for n, _t, t, s, _b in d.directory():
        if n == name:
            data = d.chain(t, s)[0]
            if name in u6.COMPENDIUM and d.path.endswith("u6-2a.d64"):
                data = u6.any_answer_is_right(data, u6.COMPENDIUM[name], name)
            if name in u6.SPLIT_FILES and d.path.endswith("u6-3b.d64"):
                data = u6.steady_split(data, name)
            if name in u6.KEYWAIT and d.path.endswith("u6-3b.d64"):
                data = bytearray(data)
                u6.patch(data, u6.KEYWAIT[name], 0x0200, u6.KEYWAIT_OLD, u6.KEYWAIT_NEW, name)
                data = bytes(data)
            return data
    raise KeyError(name)


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestU6Driver(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = u6.parts()
        cls.flash = image_from(cls.p["blobs"], regions.FLASH_SIZE)
        cls.disks = cls.p["disks"]

    def setUp(self):
        self.sim = Sim(self.p["game"], u6.GAME_ADDR, self.p["rsym"])
        self.cart = self.sim.attach_cart(self.flash)
        self.sim.mem[0x27] = 0x00           # half A on screen: B is idle

    def run_cmd(self, cmd, disk=None):
        if disk is not None:                # $2823: X = 0 Surface, 2 Dungeon
            self.sim.mpu.x = {"1A": 0, "1B": 2}[disk]
            self.sim.call(0x2823)
        self.sim.mem[CMD:CMD + len(cmd)] = list(cmd)
        self.sim.mpu.x, self.sim.mpu.y = CMD & 0xFF, CMD >> 8
        self.sim.call(0x29BE)
        return self.sim.mpu.p & 1           # the carry: set = failure

    def mem(self, addr, n):
        return bytes(self.sim.mem[addr:addr + n])

    # -- ^ sector reads ------------------------------------------------
    def test_sector_reads_whole_and_partial(self):
        checked = 0
        for tag in ("1A", "1B"):
            d = self.disks[tag]
            infile = u6.file_sectors(d)
            for t in (1, 5, 6, 18, 20, 26, 30, 33, 34, 35):
                for s in (0, 4, 9, 16):
                    if s >= u6.SECTORS[t] or (t, s) in infile:
                        continue
                    want = bytes(d.sector(t, s))
                    for off, cnt in ((0, 0), (64, 64), (128, 128), (0x40, 16), (34, 222)):
                        self.sim.mem[DEST:DEST + 256] = [0xA5] * 256
                        c = self.run_cmd(bytes([0x5E, t, s, off, cnt, DEST & 0xFF, DEST >> 8]), tag)
                        n = cnt or 256
                        self.assertEqual(c, 0)
                        self.assertEqual(self.mem(DEST, n), want[off:off + n],
                                         f"{tag} T{t} S{s} +{off} x{n}")
                        self.assertEqual(self.sim.mem[DEST + n] if n < 256 else 0xA5, 0xA5,
                                         "the read ran past its count")
                        checked += 1
        self.assertGreater(checked, 100)

    # -- loads by name -------------------------------------------------
    def test_loads_by_name(self):
        for tag, name in (("2A", "T005"), ("3A", "T201"), ("2B", "T100"), ("1A", "SCC"),
                          ("1B", "DAA"), ("1A", "SDC")):
            want = chain_bytes(self.disks[tag], name)
            cmd = b"/" + name.encode() + b"\x80" + bytes([DEST & 0xFF, DEST >> 8])
            self.assertEqual(self.run_cmd(cmd), 0, name)
            self.assertEqual(self.mem(DEST, len(want)), want, name)

    def test_percent_names_drop_the_prg_header(self):
        want = chain_bytes(self.disks["3B"], "COLORS")[2:]
        cmd = b"%COLORS\xff" + bytes([DEST & 0xFF, DEST >> 8])
        self.assertEqual(self.run_cmd(cmd), 0)
        self.assertEqual(self.mem(DEST, len(want)), want)

    def test_a_chain_of_names(self):
        a = chain_bytes(self.disks["2A"], "T005")
        b = chain_bytes(self.disks["2A"], "T018")
        cmd = (b"/T005\x00" + bytes([0x00, 0x40]) + b"/T018\x80" + bytes([0x00, 0x60]))
        self.assertEqual(self.run_cmd(cmd), 0)
        self.assertEqual(self.mem(0x4000, len(a)), a)
        self.assertEqual(self.mem(0x6000, len(b)), b)

    def test_an_unknown_name_fails_with_carry_set(self):
        self.assertEqual(self.run_cmd(b"/NOSUCH\x80\x00\x40"), 1)

    def test_find_returns_the_first_track_and_sector(self):
        for name in ("SCC", "SDD", "DEA"):
            self.assertEqual(self.run_cmd(b"!" + name.encode() + b"\xff\x00\x40"), 0)
            self.assertEqual(tuple(self.mem(DEST, 2)), self.p["starts"][name], name)

    # -- the write log ---------------------------------------------------
    def test_a_save_session_round_trips(self):
        """What the save does per chunk file (traced): `!NAME`, read the BAM,
        write the file's sectors, write the BAM; then the save area.  After
        it, the file loads by name with the new contents, the save area
        reads back as written, the BAM as the original (M_BAM) -- and other
        files are unaffected."""
        d = self.disks["1A"]
        start = self.p["starts"]["SCC"]
        # a new SCC, 3 sectors, chained 16/16 -> 16/17 -> 16/18
        new = bytes((i * 7 + 3) & 0xFF for i in range(254 * 2 + 100))
        chain = [start, (16, 17), (16, 18)]
        self.assertEqual(self.run_cmd(b"!SCC\xff\x00\x40", "1A"), 0)
        for i, (t, s) in enumerate(chain):
            if i + 1 < len(chain):
                sec = bytes(chain[i + 1]) + new[254 * i:254 * (i + 1)]
            else:
                tail = new[254 * i:]
                sec = bytes([0, len(tail) + 1]) + tail
                sec = sec.ljust(256, b"\x00")
            self.sim.mem[0x5000:0x5100] = list(sec)
            self.assertEqual(self.run_cmd(bytes([0x26, t, s, 0, 0, 0x00, 0x50])), 0)
        bam = bytes(range(256))
        self.sim.mem[0x5000:0x5100] = list(bam)
        self.assertEqual(self.run_cmd(bytes([0x26, 18, 0, 0, 0, 0x00, 0x50])), 0)
        save = [bytes([s] * 256) for s in range(9, 21)]
        for s in range(9, 21):
            self.sim.mem[0x5000:0x5100] = list(save[s - 9])
            self.assertEqual(self.run_cmd(bytes([0x26, 6, s, 0, 0, 0x00, 0x50])), 0)

        # read everything back
        self.assertEqual(self.run_cmd(b"/SCC\x80\x00\x40"), 0)
        self.assertEqual(self.mem(0x4000, len(new)), new)
        # the BAM write went nowhere: it always reads as the original
        self.assertEqual(self.run_cmd(bytes([0x5E, 18, 0, 0, 0, 0x00, 0x40]), "1A"), 0)
        self.assertEqual(self.mem(0x4000, 256), bytes(d.sector(18, 0)))
        self.assertEqual(self.run_cmd(bytes([0x5E, 6, 12, 64, 64, 0x00, 0x40])), 0)
        self.assertEqual(self.mem(0x4000, 64), save[3][64:128])
        # the Dungeon disk's BAM was not written: still the original
        self.assertEqual(self.run_cmd(bytes([0x5E, 18, 0, 0, 0, 0x00, 0x40]), "1B"), 0)
        self.assertEqual(self.mem(0x4000, 256), bytes(self.disks["1B"].sector(18, 0)))
        # another chunk file is untouched
        want = chain_bytes(d, "SCD")
        self.assertEqual(self.run_cmd(b"/SCD\x80\x00\x40"), 0)
        self.assertEqual(self.mem(0x4000, len(want)), want)
        # and a second save of SCC wins over the first
        self.assertEqual(self.run_cmd(b"!SCC\xff\x00\x40", "1A"), 0)
        sec = bytes([0, 11]) + b"second!!!!"
        self.sim.mem[0x5000:0x5100] = list(sec.ljust(256, b"\x00"))
        self.assertEqual(self.run_cmd(bytes([0x26, start[0], start[1], 0, 0, 0x00, 0x50])), 0)
        self.assertEqual(self.run_cmd(bytes([0x26, 18, 0, 0, 0, 0x00, 0x50])), 0)
        self.assertEqual(self.run_cmd(b"/SCC\x80\x00\x40"), 0)
        self.assertEqual(self.mem(0x4000, 10), b"second!!!!")
        # writes only ever landed in the log
        lo, hi = self.p["log"]
        for kind, *rest in self.cart.log:
            if kind == "write":
                addr, length = rest
                self.assertTrue(lo <= addr and addr + length <= hi, f"write at {addr:#08x}")

    def test_saves_never_use_up_the_bam(self):
        """The save allocates each chunk file's sectors from the BAM it
        reads after `!NAME`.  A drive frees the file's old chain in `!`; the
        cart does not, so it must never let the allocations accumulate:
        the BAM reads back as the original after any number of saves, and
        the BAM write still ends the file's session (the file is complete,
        and the next write is not part of it)."""
        d = self.disks["1A"]
        start = self.p["starts"]["SCC"]
        for n in range(8):
            self.assertEqual(self.run_cmd(b"!SCC\xff\x00\x40", "1A"), 0)
            self.assertEqual(self.run_cmd(bytes([0x5E, 18, 0, 0, 0, 0x00, 0x40])), 0)
            self.assertEqual(self.mem(0x4000, 256), bytes(d.sector(18, 0)), f"save {n}")
            bam = bytearray(d.sector(18, 0))
            bam[4 * 5 + 1:4 * 5 + 4] = b"\x00\x00\x00"      # the save allocates
            sec = bytes([0, 9]) + bytes([n]) * 8
            self.sim.mem[0x5000:0x5100] = list(sec.ljust(256, b"\x00"))
            self.assertEqual(self.run_cmd(bytes([0x26, start[0], start[1], 0, 0, 0x00, 0x50])), 0)
            self.sim.mem[0x5000:0x5100] = list(bam)
            self.assertEqual(self.run_cmd(bytes([0x26, 18, 0, 0, 0, 0x00, 0x50])), 0)
            # a stray chunk-style write after the BAM belongs to no session
            self.sim.mem[0x5000:0x5100] = [0xEE] * 256
            self.assertEqual(self.run_cmd(bytes([0x26, 16, 17, 0, 0, 0x00, 0x50])), 0)
            self.assertEqual(self.run_cmd(b"/SCC\x80\x00\x40"), 0)
            self.assertEqual(self.mem(0x4000, 8), bytes([n]) * 8)
        self.assertEqual(self.run_cmd(bytes([0x5E, 18, 0, 0, 0, 0x00, 0x40]), "1B"), 0)
        self.assertEqual(self.mem(0x4000, 256), bytes(self.disks["1B"].sector(18, 0)))

    def test_a_write_outside_a_session_is_dropped(self):
        before = bytes(self.cart.flash)
        self.sim.mem[0x5000:0x5100] = [0x55] * 256
        self.assertEqual(self.run_cmd(bytes([0x26, 16, 16, 0, 0, 0x00, 0x50]), "1A"), 0)
        self.assertEqual(bytes(self.cart.flash), before)

    # -- where the on-demand part runs ---------------------------------------
    def bulk_fetches(self):
        """How often the resident has fetched the on-demand part so far."""
        fl = self.mem(self.p["rsym"]["u6_bulkfl"], 7)
        at = {fl[0] << 16 | fl[1] << 8 | fl[2], fl[4] << 16 | fl[5] << 8 | fl[6]}
        return sum(1 for e in self.cart.log if e[0] == "read" and e[1] in at)

    def test_a_save_fetches_the_on_demand_part_twice(self):
        """A save as the game sends it (U6-save-game.md 2.4): `!NAME`, the
        BAM read, the file's sectors, the BAM; per file; then $2823 (#SU) and
        the save area.  The on-demand part stays in its half from the first
        `!` to $2823 and from the first save-area write to the closing $2823:
        two fetches of the kilobyte, where every command used to fetch it.
        And what was saved reads back."""
        d = self.disks["1A"]
        files = [(n, self.p["starts"][n]) for n in ("SCC", "SCD", "SDC", "SDD")]
        new = {n: bytes((i * k + 5) & 0xFF for i in range(300)) for k, (n, _) in enumerate(files, 3)}
        self.sim.mpu.x = 0
        self.sim.call(0x2823)
        before = self.bulk_fetches()
        for name, (t, s) in files:
            self.assertEqual(self.run_cmd(b"!" + name.encode() + b"\xff\x00\x40"), 0)
            self.assertEqual(self.run_cmd(bytes([0x5E, 18, 0, 0, 0, 0x00, 0x41])), 0)
            data = new[name]
            secs = [bytes([16, 17]) + data[:254], bytes([0, len(data) - 254 + 1]) + data[254:]]
            for (tt, ss), sec in zip([(t, s), (16, 17)], secs):
                self.sim.mem[0x5000:0x5100] = list(sec.ljust(256, b"\x00"))
                self.assertEqual(self.run_cmd(bytes([0x26, tt, ss, 0, 0, 0x00, 0x50])), 0)
            self.sim.mem[0x5000:0x5100] = list(d.sector(18, 0))
            self.assertEqual(self.run_cmd(bytes([0x26, 18, 0, 0, 0, 0x00, 0x50])), 0)
        self.assertEqual(self.bulk_fetches() - before, 1, "the files' commands")
        self.sim.mpu.x = 0                  # #SU
        self.sim.call(0x2823)
        for s in range(9, 21):
            self.sim.mem[0x5000:0x5100] = [s] * 256
            self.assertEqual(self.run_cmd(bytes([0x26, 6, s, 0, 0, 0x00, 0x50])), 0)
        self.assertEqual(self.bulk_fetches() - before, 2, "and the save area's")
        self.sim.mpu.x = 0                  # $3EEB: JMP $2813
        self.sim.call(0x2823)
        # read back; every load by name fetches the on-demand part afresh
        for k, (name, _) in enumerate(files):
            self.assertEqual(self.run_cmd(b"/" + name.encode() + b"\x80\x00\x40"), 0)
            self.assertEqual(self.mem(0x4000, 300), new[name], name)
            self.assertEqual(self.bulk_fetches() - before, 3 + k)
        for s in range(9, 21):              # the state load ($3EBD): kept again
            self.assertEqual(self.run_cmd(bytes([0x5E, 6, s, 0, 0, 0x00, 0x40])), 0)
            self.assertEqual(self.mem(0x4000, 256), bytes([s] * 256))
        self.assertEqual(self.bulk_fetches() - before, 7)

    def test_the_object_files_fetch_the_on_demand_part_once(self):
        """`game`'s $2453 loads the window's four object files in a row
        through its command string at $243B, quadrant by quadrant ($2445/
        $2446 = 00/00, 80/00, 00/80, 80/80), no frame drawn between them: one
        fetch for the four.  After the fourth the next load fetches again;
        a load through another command string fetches, and leaves nothing
        kept."""
        def load(name, qx, qy, at=0x243B):
            self.sim.mem[0x2445], self.sim.mem[0x2446] = qx, qy
            cmd = b"/" + name.encode() + b"\x80\x00\xc0"
            self.sim.mem[at:at + len(cmd)] = list(cmd)
            self.sim.mpu.x, self.sim.mpu.y = at & 0xFF, at >> 8
            self.sim.call(0x29BE)
            self.assertEqual(self.sim.mpu.p & 1, 0, name)
            self.assertEqual(self.mem(0xC000, 64), chain_bytes(self.disks["1A"], name)[:64], name)
        self.sim.mpu.x = 0
        self.sim.call(0x2823)
        before = self.bulk_fetches()
        for name, qx, qy in (("SBG", 0, 0), ("SBH", 0x80, 0), ("SCG", 0, 0x80), ("SCH", 0x80, 0x80)):
            load(name, qx, qy)
        self.assertEqual(self.bulk_fetches() - before, 1)
        load("SDD", 0, 0, at=0x5000)
        self.assertEqual(self.bulk_fetches() - before, 2)
        load("SDC", 0, 0, at=0x5000)
        self.assertEqual(self.bulk_fetches() - before, 3)
        load("SCC", 0, 0)                   # a new group's first: kept
        load("SCD", 0, 0, at=0x5000)
        self.assertEqual(self.bulk_fetches() - before, 4)
        load("SCC", 0x80, 0x80)
        self.assertEqual(self.bulk_fetches() - before, 5)

    def test_the_on_demand_part_is_fetched_again_when_it_may_be_gone(self):
        """Kept only while nothing can have drawn into its half: a load by
        name, $2823, or the other half being the idle one each mean a fetch;
        and after a compaction (u6pack fetched over it) too."""
        def fetched(cmd, disk=None):
            n = self.bulk_fetches()
            self.assertEqual(self.run_cmd(cmd, disk), 0)
            return self.bulk_fetches() - n
        find = b"!SCC\xff\x00\x40"
        bam = bytes([0x26, 18, 0, 0, 0, 0x00, 0x50])
        self.assertEqual(fetched(find, "1A"), 1)
        self.assertEqual(fetched(bam), 0)
        self.assertEqual(fetched(b"/T005\x80\x00\x40"), 0)  # (not in a save)
        self.assertEqual(fetched(find), 1)                  # ... and dropped
        self.assertEqual(fetched(find, "1A"), 1)            # $2823
        self.sim.mem[0x27] = 0x10                           # the other half idle
        self.assertEqual(fetched(bam), 1)
        self.assertEqual(self.sim.mem[self.p["rsym"]["u6_keep"]], u6.BULK_A >> 8)
        self.sim.mem[0x27] = 0x00
        self.assertEqual(fetched(bam), 1)
        self.assertEqual(self.sim.mem[self.p["rsym"]["u6_keep"]], u6.BULK_B >> 8)

    def test_the_on_demand_part_uses_only_the_idle_half(self):
        for z27, idle, shown in ((0x00, u6.BULK_B, u6.BULK_A), (0x10, u6.BULK_A, u6.BULK_B)):
            self.sim.mem[0x27] = z27
            self.sim.mem[shown:shown + 0x400] = [0x3C] * 0x400
            self.sim.mem[idle:idle + 0x400] = [0x00] * 0x400
            self.assertEqual(self.run_cmd(b"/T005\x80\x00\x40"), 0)
            self.assertEqual(self.mem(shown, 0x400), bytes([0x3C] * 0x400),
                             "the shown half was touched")
            self.assertNotEqual(self.mem(idle, 16), bytes(16), "nothing ran in the idle half")

    def test_the_load_prompt_loads_on_yes(self):
        """Shift-L: the Y/N prompt ($3E6C) returns carry set for Y, so the
        branch back to play must be BCC -- in the original it was BCS."""
        m = self.sim.mem
        self.assertEqual(list(m[0x2EF6:0x2EFE]), [0x20, 0x6C, 0x3E, 0x90, 0xE5, 0x4C, 0xFC, 0x03])
        self.assertEqual(list(m[0x2ED8:0x2EDD]), [0x20, 0x6C, 0x3E, 0x90, 0x03],
                         "the save prompt, the pattern it follows")

    # -- the ending ------------------------------------------------------------
    def test_the_ending_loads(self):
        """The ending overlay, fetched the way `game` fetches it (three sector
        reads of 1A T23 S16-18 through the driver), then its loader called
        as the overlay calls it -- the music, then ICHARS and END, which
        overwrites `game`, the resident driver included."""
        for s in (16, 17, 18):
            dest = 0xC800 + (s - 16) * 256
            self.assertEqual(self.run_cmd(bytes([0x5E, 23, s, 0, 0, dest & 0xFF, dest >> 8]), "1A"), 0)
        self.assertEqual(bytes(self.sim.mem[0xC800:0xCB00]), self.p["ending"])
        # run it with the overlay's own tclib trapped onto the same cart
        sym = self.p["end_sym"]
        sim = Sim(b"", 0, sym)
        sim.mem[:] = self.sim.mem[:]
        cart = sim.attach_cart(self.cart.flash)
        d = self.disks["3B"]
        for ptr, loads in ((0xC86F, [("THEME2", 0x9000)]),
                           (0xC879, [("ICHARS", 0x8000), ("END", 0x0200)])):
            sim.mpu.x, sim.mpu.y = ptr & 0xFF, ptr >> 8
            sim.call(0xC8C2)
            self.assertEqual(sim.mpu.p & 1, 0, f"the load at {ptr:#06x} failed")
            self.assertEqual(sim.mem[0x01], 0x34)
            for name, dest in loads:
                want = chain_bytes(d, name)[2:]
                self.assertEqual(bytes(sim.mem[dest:dest + len(want)]), want, name)
        # (the loader's own variables change; what is before it must not)
        self.assertEqual(bytes(sim.mem[0xC800:0xC8C2]), self.p["ending"][:0xC2], "the overlay was hit")

    def test_the_ending_overlay_changes_only_its_loader(self):
        orig = b"".join(bytes(self.disks["1A"].sector(23, s)) for s in (16, 17, 18))
        new = self.p["ending"]
        diff = [0xC800 + i for i, (a, b) in enumerate(zip(orig, new)) if a != b]
        self.assertTrue(diff)
        self.assertEqual([a for a in diff if a < 0xC8C2], [0xC892, 0xC893],
                         "only the IRQ's LDA #$35 -> ORA #$05 before the loader")

    def test_the_led_is_lit_only_while_data_moves(self):
        """tclib's tc_enter lights the LED and tc_leave puts it out, so after
        any command -- a sector read, a load by name, a write -- it is dark,
        and it was lit meanwhile."""
        self.sim.mem[0x5000:0x5100] = [0x55] * 256
        for cmd, disk in ((bytes([0x5E, 18, 0, 0, 0, DEST & 0xFF, DEST >> 8]), "1A"),
                          (b"/T005\x80\x00\x40", None),
                          (bytes([0x26, 18, 0, 0, 0, 0x00, 0x50]), "1A")):
            with self.subTest(cmd=cmd[:1]):
                before = self.cart.lit
                self.assertEqual(self.run_cmd(cmd, disk), 0)
                self.assertGreater(self.cart.lit, before, "never lit")
                self.assertFalse(self.cart.led, "left lit")

    def test_the_access_light_is_lit_only_while_data_moves(self):
        """The frame cell below the cursor (u6.inc LIGHT_CELL, row 24 col 23)
        is white ($81) while any byte crosses the bus and the frame's own
        $89 again after every command."""
        cell = 0xCC00 + 24 * 40 + 23
        self.sim.mem[cell] = 0x89
        seen, off = [], []
        for addr, sends in ((self.p["rsym"]["tc_sendbyte"], True), (self.p["rsym"]["tc_getbyte"], False)):
            inner = self.sim.traps[addr]

            def trap(sim, inner=inner, sends=sends):
                sp = sim.mpu.sp                         # sent by tc_led: an LED
                ret = sim.mem[0x101 + sp] | sim.mem[0x102 + sp] << 8    # command
                led = sends and self.p["rsym"]["tc_led"] < ret < self.p["rsym"]["tc_led"] + 8
                if led and sim.mpu.a == 0x30:           # (OFF goes out after the
                    off.append(sim.mem[cell])           # cell is put back)
                elif not led:
                    seen.append(sim.mem[cell])
                inner(sim)
            self.sim.traps[addr] = trap
        self.sim.mem[0x5000:0x5100] = [0x55] * 256
        for cmd, disk in ((bytes([0x5E, 18, 0, 0, 0, DEST & 0xFF, DEST >> 8]), "1A"),
                          (b"/T005\x80\x00\x40", None),
                          (bytes([0x26, 18, 0, 0, 0, 0x00, 0x50]), "1A")):
            with self.subTest(cmd=cmd[:1]):
                del seen[:], off[:]
                self.assertEqual(self.run_cmd(cmd, disk), 0)
                self.assertGreater(len(seen), 4)
                self.assertEqual(set(seen), {0x81}, "not lit while data moved")
                self.assertTrue(off and set(off) == {0x89})
                self.assertEqual(self.sim.mem[cell], 0x89, "not put back")
        self.assertEqual(self.mem(cell - 23, 40), bytes([0]) * 23 + b"\x89" + bytes([0]) * 16,
                         "something else in the row changed")

    def test_exit_state(self):
        self.sim.mem[0x01] = 0x35
        self.assertEqual(self.run_cmd(b"/T005\x80\x00\x40"), 0)
        self.assertEqual(self.sim.mem[0x01] & 0x07, 0x04, "$01 is not left at $34")


if __name__ == "__main__":
    unittest.main()
