"""tclib's TC_GUARD: the 2-bit receive with the screen on (asm/tclib.s,
tc_getbyte_guard).  The real routine runs in py65 against a model VIC: the
raster follows the cycle count (63 cycles a line and 312 lines for PAL, 65
and 263 for NTSC, 64 and 262 for the old NTSC chips), a line is a badline
when it is in $30-$F7 and its low three bits are YSCROLL, and on a badline
the CPU is halted from cycle BA_FROM to BA_TO -- any instruction with a
cycle in there waits until the bus comes back, which is what a badline does
to a read.

Entered at every cycle of the lines where the display starts and ends and
around the raster's bit-8 wrap, for three YSCROLL values, each byte must:
  - put its port accesses at exactly the stock routine's cycles after the
    start signal (ProgRef's getbyte_fast): $00 at +3, $01 read at +8, +17,
    +26, +35, $00 at +48, $01 at +53;
  - keep that whole span MARGIN cycles clear of every badline's halt.
And with the check disabled the same run has to find bytes a badline hits,
or the model proves nothing.

Skipped without py65 (the repository's .venv has it)."""
import os
import unittest
from pathlib import Path
from ultima import paths

try:
    from py65.devices.mpu6502 import MPU
    from py65.memory import ObservableMemory
    from ultima.sim.sim6502 import Sim
except ImportError:
    MPU = None

ORG = 0x1000
DONE = 0xFFF0
BA_FROM, BA_TO = 11, 54         # 0-based from the $D012 change, a cycle wider than
MARGIN = 1                      # the 1-based 12-54 of the VIC papers, then MARGIN
STOCK = [("w", 0x00, 3), ("r", 0x01, 8), ("r", 0x01, 17), ("r", 0x01, 26),
         ("r", 0x01, 35), ("w", 0x00, 48), ("w", 0x01, 53)]
CHIPS = {"PAL": (63, 312), "NTSC": (65, 263), "old NTSC": (64, 262)}


def assemble():
    return Sim.assemble(os.path.join(paths.ASM, "tclib.s"), ORG,
                        defines={"TCLIB_ORG": ORG, "TC_GUARD": 1, "TC_NO_FAST": 1,
                                 "TC_NO_CMDMODE": 1, "TC_NO_LED": 1})


def ar_defines():
    """The constants ultima/games/u5/armusic.s gives its copy of tcguard.s."""
    import re
    out = {}
    for line in Path(os.path.join(paths.ROOT, "ultima", "games", "u5", "armusic.s")).read_text().splitlines():
        m = re.match(r"(TC_\w+|BIT_SENSE)\s*=\s*([$%]?)([0-9a-fA-F]+)", line)
        if m:
            out[m.group(1)] = int(m.group(3), {"$": 16, "%": 2, "": 10}[m.group(2)])
    assert {"TC_GUARD_BARE", "TC_F_START", "TC_F_XOR", "TC_GIO"} <= set(out), out
    return out


def assemble_ar():
    """Ultima 5's copy in the Action Replay's RAM: tcguard.s bare, with
    fixed port values for $01 bits 0-2 = %111."""
    return Sim.assemble(os.path.join(paths.ASM, "tcguard.s"), ORG, defines=ar_defines())


class Vic:
    def __init__(self, line_cycles, lines, yscroll):
        self.n, self.lines, self.ys = line_cycles, lines, yscroll

    def line(self, t):
        return (t // self.n) % self.lines

    def bad(self, line):
        return 0x30 <= line <= 0xF7 and line & 7 == self.ys

    def halt(self, t, cycles):
        """Cycles an instruction starting at t waits for the bus."""
        for k in range(cycles):
            c = t + k
            if self.bad(self.line(c)) and BA_FROM <= c % self.n <= BA_TO:
                return c - c % self.n + BA_TO + 1 - c
        return 0

    def clearance(self, start, end):
        """Cycles between [start, end] and the nearest badline halt."""
        best = 1 << 30
        for line_start in range(start - start % self.n - self.n, end + self.n, self.n):
            if not self.bad(self.line(line_start)):
                continue
            a, b = line_start + BA_FROM, line_start + BA_TO
            if b < start:
                best = min(best, start - b - 1)
            elif a > end:
                best = min(best, a - end - 1)
            else:
                return -1
        return best


PAIRS = [(5, 4), (7, 6), (1, 0), (3, 2)]    # sense, write: the firmware's order
WINDOW = (5, 12)                            # each pair on the lines, from the start + 9k


def run_byte(image, sym, vic, t0, byte=0xA5, result=None, org=ORG, setup=None):
    """One tc_getbyte_guard from cycle t0 (the cart ready at once); returns
    (the port accesses from the start signal on, as (kind, reg, offset),
    the start signal's cycle, the last access's).  The cart is a model of
    the firmware's fast_sendbyte: from the start signal it puts `byte`'s bit
    pairs on sense (bit 4) and write (bit 3) for WINDOW of every 9 cycles and
    the inverted pair between them, so a read on the wrong cycle gets the
    wrong bits.  $01's output bits read back as last written, bits 6-7 as
    1s.  `result`, a list, gets the byte the routine returned.  `image` is
    at `org`; `setup(mem)` may put more in memory first."""
    mem = ObservableMemory()
    for i, b in enumerate(image):
        mem[org + i] = b
    if setup:
        setup(mem)
    mpu = MPU(memory=mem)
    now = [0]
    events = []
    port = {"out": 0x30, "start": None}

    def rd01(_a):
        events.append(("r", 1, now[0]))
        out = (port["out"] & 0x27) | 0xC0
        if port["start"] is None:
            return out | 0x10                   # sense high: ready
        off = now[0] - port["start"]
        k = min(max((off - WINDOW[0]) // 9, 0), 3)
        hi, lo = PAIRS[k]
        pair = ((byte >> hi) & 1) << 4 | ((byte >> lo) & 1) << 3
        if not WINDOW[0] + 9 * k <= off <= WINDOW[1] + 9 * k:
            pair ^= 0x18
        return out | pair

    def wr01(_a, v):
        events.append(("w", 1, now[0], v))
        port["out"] = v
        if v & 0x08 and port["start"] is None:
            port["start"] = now[0]

    def d012(_a):
        return vic.line(now[0]) & 0xFF

    def d011(_a):
        line = vic.line(now[0])
        return 0x18 | vic.ys | (0x80 if line & 0x100 else 0)

    mem.subscribe_to_read([0xD012], d012)
    mem.subscribe_to_read([0xD011], d011)
    mem.subscribe_to_read([0x01], rd01)
    mem.subscribe_to_write([0x01], wr01)
    mem.subscribe_to_write([0x00], lambda a, v: events.append(("w", a, now[0], v)))
    mem[0xD015] = 0
    mpu.sp = 0xFD
    mem[0x1FF], mem[0x1FE] = DONE >> 8, (DONE - 1) & 0xFF
    mpu.pc = sym["tc_getbyte_guard"]
    t = t0
    while mpu.pc != DONE:
        n = mpu.cycletime[mem[mpu.pc]]
        t += vic.halt(t, n)
        now[0] = t + n - 1                  # these reads and writes are last-cycle
        before = mpu.processorCycles
        mpu.step()
        t += mpu.processorCycles - before
    if result is not None:
        result.append(mpu.a)
    start = next(i for i, e in enumerate(events)
                 if e[0] == "w" and e[1] == 1 and e[3] & 0x08)
    t_start = events[start][2]
    got = [(e[0], e[1], e[2] - t_start) for e in events[start + 1:]]
    return got, t_start, events[-1][2]


def phases(line_cycles, lines):
    """Every cycle of the lines around the display's start and end and the
    raster's wrap."""
    for line in list(range(0x2A, 0x3A)) + list(range(0xEE, 0x102)) + [lines - 2, lines - 1, 0, 1]:
        for c in range(line_cycles):
            yield line * line_cycles + c


@unittest.skipIf(MPU is None, "py65 is not installed (use the repository's .venv)")
class TestGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sim = assemble()
        cls.sym = sim.sym
        cls.image = bytes(sim.mem[ORG:ORG + 0x400])

    def sweep(self, image, chip, yscroll, sym=None):
        vic = Vic(*CHIPS[chip], yscroll)
        for t0 in phases(vic.n, vic.lines):
            got, start, end = run_byte(image, sym or self.sym, vic, t0)
            yield t0, got, vic.clearance(start, end), start - t0

    def test_every_byte_misses_the_badlines(self):
        self.misses(self.image, self.sym)

    def test_the_ars_copy_misses_them_too(self):
        """Ultima 5's copy (ultima/games/u5/armusic.s): the same code but for its
        port values and the nibble table, so the same cycles."""
        sim = assemble_ar()
        self.misses(bytes(sim.mem[ORG:ORG + 0x100]), sim.sym, chips=("PAL", "NTSC"))

    def test_with_interrupts_on_too(self):
        """TC_IRQ_ON: PHP / SEI before the raster check and PLP after the
        last timed access -- the cycles from the check to the start signal
        unchanged, so the same clearance; every value; the I flag as it was."""
        sim = Sim.assemble(os.path.join(paths.ASM, "tclib.s"), ORG,
                           defines={"TCLIB_ORG": ORG, "TC_GUARD": 1, "TC_NO_FAST": 1,
                                    "TC_IRQ_ON": 1, "TC_NO_CMDMODE": 1, "TC_NO_LED": 1})
        image = bytes(sim.mem[ORG:ORG + 0x400])
        self.misses(image, sim.sym, chips=("PAL", "NTSC"), wait_limit=66)   # (PHP / SEI: 5 more)
        vic = Vic(63, 312, 3)
        for b in (0x00, 0x5A, 0xA5, 0xFF):
            out = []
            run_byte(image, sim.sym, vic, 0x10 * 63, byte=b, result=out)
            self.assertEqual(out, [b])

    def test_every_value_comes_through(self):
        """All 256 bytes, through tclib's receive (all-RAM banking) and the
        AR's (%111, the table taking the flip out) -- and with the AR's port
        values in tclib's copy, or tclib's table in the AR's, they do not."""
        sim = assemble_ar()
        ar = (bytes(sim.mem[ORG:ORG + 0x100]), sim.sym)
        vic = Vic(63, 312, 3)
        t0 = 0x10 * 63                              # the top border
        for name, (image, sym) in (("tclib", (self.image, self.sym)), ("AR", ar)):
            with self.subTest(copy=name):
                for b in range(256):
                    out = []
                    run_byte(image, sym, vic, t0, byte=b, result=out)
                    self.assertEqual(out, [b], f"byte ${b:02x}")
        # the AR's copy with an ORA table: bits 0-1 of each nibble wrong
        at = ar[1]["tc_nibbletab"] - ORG
        wrong = bytearray(ar[0])
        wrong[at:at + 16] = bytes(n << 4 for n in range(16))
        out = []
        run_byte(bytes(wrong), ar[1], vic, t0, byte=0x00, result=out)
        self.assertNotEqual(out, [0x00])

    def misses(self, image, sym, chips=tuple(CHIPS), wait_limit=60):
        for chip in chips:
            for ys in (0, 3, 7):
                worst, waited = 1 << 30, []
                for t0, got, clear, wait in self.sweep(image, chip, ys, sym):
                    if got != [(k, r, o) for k, r, o in STOCK] or clear < MARGIN:
                        self.fail(f"{chip} yscroll {ys} from line {t0 // CHIPS[chip][0]:#x} "
                                  f"cycle {t0 % CHIPS[chip][0]}: {got}, clear {clear}")
                    worst = min(worst, clear)
                    waited.append(wait)
                with self.subTest(chip=chip, yscroll=ys):
                    self.assertGreaterEqual(worst, MARGIN)
                    # the check and its waits: two lines in eight, 16 cycles a byte or so
                    self.assertLess(sum(waited) / len(waited), wait_limit)

    def test_without_the_check_badlines_hit(self):
        """cmp #$06 -> cmp #$08: never waits, same cycles."""
        at = self.sym["tc_gg_wait"] + 10 - ORG
        self.assertEqual(self.image[at - 1:at + 1], b"\xc9\x06")
        broken = bytearray(self.image)
        broken[at] = 0x08
        hits = sum(1 for _t0, got, clear, _w in self.sweep(bytes(broken), "PAL", 3)
                   if got != STOCK or clear < 0)
        self.assertGreater(hits, 100)


@unittest.skipIf(MPU is None, "py65 is not installed (use the repository's .venv)")
class TestPick(unittest.TestCase):
    """tc_read and the stream take READ_FLASH_FAST and the guarded receive
    with every sprite off, READ_FLASH and the 1-bit one otherwise."""

    def setUp(self):
        self.sim = sim = assemble()
        flash = bytes((i * 37 + 11) & 0xFF for i in range(0x3000))
        self.flash = flash
        self.cart = sim.attach_cart(flash)
        self.cmds, self.used = [], []
        send, get = sim.traps[sim.sym["tc_sendbyte"]], sim.traps[sim.sym["tc_getbyte"]]

        def spy_send(s):
            if self.cart.cmd is None:
                self.cmds.append(s.mpu.a)
            send(s)
        sim.traps[sim.sym["tc_sendbyte"]] = spy_send
        for name in ("tc_getbyte", "tc_getbyte_guard"):
            sim.traps[sim.sym[name]] = lambda s, name=name: (self.used.append(name), get(s))
        sim.mem[0x00], sim.mem[0x01] = 0x2F, 0x37
        sim.call(sim.sym["tc_init"])

    def setup_read(self, addr, length, dest):
        m, s = self.sim.mem, self.sim.sym
        m[s["tc_addr"]:s["tc_addr"] + 3] = [addr & 0xFF, addr >> 8 & 0xFF, addr >> 16]
        m[s["tc_len"]:s["tc_len"] + 2] = [length & 0xFF, length >> 8]
        m[s["tc_dest"]:s["tc_dest"] + 2] = [dest & 0xFF, dest >> 8]

    def test_tc_read(self):
        for sprites, cmd, used in ((0, 0x11, "tc_getbyte_guard"), (0x04, 0x10, "tc_getbyte")):
            with self.subTest(sprites=sprites):
                self.cmds.clear(), self.used.clear()
                self.sim.mem[0xD015] = sprites
                self.setup_read(0x1234, 300, 0x4000)
                self.sim.call(self.sim.sym["tc_read"])
                self.assertEqual(self.cmds, [cmd])
                self.assertEqual(set(self.used), {used})
                self.assertEqual(bytes(self.sim.mem[0x4000:0x4000 + 300]), self.flash[0x1234:0x1234 + 300])
                self.assertEqual(self.sim.mem[0x01], 0x37)

    def test_the_stream(self):
        sym = self.sim.sym
        for sprites, cmd, used in ((0, 0x11, "tc_getbyte_guard"), (0x80, 0x10, "tc_getbyte")):
            with self.subTest(sprites=sprites):
                self.cmds.clear(), self.used.clear()
                self.sim.mem[0xD015] = sprites
                self.setup_read(0x2001, 40, 0)
                self.sim.call(sym["tc_stream_open"])
                got = []
                for _ in range(10):
                    self.sim.call(sym["tc_stream_byte"])
                    got.append(self.sim.mpu.a)
                self.sim.call(sym["tc_stream_close"])     # drains the other 30
                self.assertEqual(self.cmds, [cmd])
                self.assertEqual(set(self.used), {used})
                self.assertEqual(len(self.used), 40)
                self.assertEqual(bytes(got), self.flash[0x2001:0x200B])
                self.assertEqual(self.sim.mem[0x01], 0x37)


@unittest.skipIf(MPU is None, "py65 is not installed (use the repository's .venv)")
class TestNmiHold(unittest.TestCase):
    """TC_NMI_HOLD: tc_enter arms CIA 2's timer A NMI with the RAM's vector
    at an RTI, puts the vector back no sooner than 8 cycles after the timer
    starts (it runs out ~3 cycles on), and tc_leave switches the NMI off and
    acknowledges it; both keep X, Y and the carry, as they always have."""

    def run_routine(self, image, sym, name, x, y, carry, mem):
        mpu = MPU(memory=mem)
        now, log = [0], []
        for a in (0x01, 0xDD04, 0xDD05, 0xDD0D, 0xDD0E, 0xFFFA, 0xFFFB):
            mem.subscribe_to_write([a], lambda a, v: log.append(("w", a, v, now[0])))
        mem.subscribe_to_read([0xDD0D], lambda a: log.append(("r", a, None, now[0])) or 0)
        mpu.x, mpu.y = x, y
        mpu.p = (mpu.p & ~1) | carry
        mpu.sp = 0xFD
        mem[0x1FF], mem[0x1FE] = DONE >> 8, (DONE - 1) & 0xFF
        mpu.pc = sym[name]
        t = 0
        while mpu.pc != DONE:
            n = mpu.cycletime[mem[mpu.pc]]
            now[0] = t + n - 1
            before = mpu.processorCycles
            mpu.step()
            t += mpu.processorCycles - before
        self.assertEqual((mpu.x, mpu.y, mpu.p & 1), (x, y, carry), name)
        return log

    def test_enter_and_leave(self):
        sim = Sim.assemble(os.path.join(paths.ASM, "tclib.s"), ORG,
                           defines={"TCLIB_ORG": ORG, "TC_GUARD": 1, "TC_NO_FAST": 1,
                                    "TC_NMI_HOLD": 1, "TC_NO_CMDMODE": 1, "TC_NO_LED": 1})
        sym = sim.sym
        mem = ObservableMemory()
        for i, b in enumerate(sim.mem[ORG:ORG + 0x400]):
            mem[ORG + i] = b
        mem[0x00], mem[0x01] = 0x2F, 0x37
        mem[0xFFFA], mem[0xFFFB] = 0x43, 0xFE
        self.run_routine(None, sym, "tc_init", 0, 0, 0, mem)
        rti = sym["tc_rti"]
        self.assertEqual(mem[rti], 0x40)
        for carry in (0, 1):
            log = self.run_routine(None, sym, "tc_enter", 0x5A, 0xA5, carry, mem)
            w = [(a, v) for k, a, v, _t in log if k == "w"]
            self.assertIn((0xFFFA, rti & 0xFF), w)
            self.assertIn((0xFFFB, rti >> 8), w)
            self.assertEqual([v for a, v in w if a == 0xDD0D], [0x81])
            start = next(t for k, a, v, t in log if a == 0xDD0E and v == 0x19)
            back = [t for k, a, v, t in log if a == 0xFFFA and v == 0x43]
            self.assertEqual(len(back), 1)
            self.assertGreaterEqual(back[0] - start, 8)
            self.assertEqual((mem[0xFFFA], mem[0xFFFB]), (0x43, 0xFE))
            self.assertFalse(mem[0x01] & 0x07, "a transfer runs in all-RAM banking")
            log = self.run_routine(None, sym, "tc_leave", 0x5A, 0xA5, carry, mem)
            seq = [(k, a, v) for k, a, v, _t in log if a == 0xDD0D]
            self.assertEqual(seq, [("w", 0xDD0D, 0x01), ("r", 0xDD0D, None)])
            self.assertEqual(mem[0x01], 0x37)


if __name__ == "__main__":
    unittest.main()
