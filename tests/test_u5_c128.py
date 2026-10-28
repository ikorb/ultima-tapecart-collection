"""Ultima V in C128 mode (ultima/games/u5/c128.inc): the overlay cache, run from
bank 1 (sub128.s), against the original subs.128 running where it did.

Both run on a model C128 (c128sim.py: the MMU's banks and common RAM, the
VDC's RAM, the KERNAL's FETCH/STASH trampolines from the real ROM) from the
same memory -- noise, with the game's files where the game has them -- and
go through the same calls: the music setup, the preload, fetching every
overlay and one that is not cached, the map swap with the VDC, the KERNAL
variables' swap, the song requests, and the mode swap in both its forms,
the second ending in its JMP $8000.  After each, bank 0, bank 1 and the
VDC must match byte for byte, apart from the code that differs by design
(subs.128 and the driver at $7700, temp.subs -- its jump table points at
the driver --, the port in bank 1 and its trampolines in common RAM) and the stack, as must the registers
the original leaves and its MMU setting, $01 and I flag.

A load ($6C24) is trapped: it fills $A700 on with bytes made from the
name, as a disk (or the cart) would, and both machines must ask for the
same names in the same order."""
import os
import random
import unittest

try:
    from ultima.sim import c128sim
except ImportError:                 # py65 is in the repository's .venv
    c128sim = None

import importlib.util as _il
from ultima import paths

_spec = _il.find_spec("ultima.games.u5.build")
u5 = _il.module_from_spec(_spec)
_spec.loader.exec_module(u5)

LOAD = 0x6C24


def overlay(name):
    """What `name` loads to $A700: a length and bytes from the name."""
    r = random.Random(name)
    return bytes(r.randrange(256) for _ in range(0x1200 + 0x80 * len(name) + r.randrange(0x800)))


def pet(text):
    """ASCII as acme's !pet has it: lower case unshifted, upper case shifted."""
    return bytes(ord(ch) - 0x20 if "a" <= ch <= "z" else ord(ch) + 0x80 if "A" <= ch <= "Z"
                 else ord(ch) for ch in text)


def file(p, name):
    (load, body), = [(ld, b) for (n, nm), b in p["bodies"].items()
                     for ld in [p["loads"][(n, nm)]] if n == 1 and nm.lower() == name]
    return load, body


@unittest.skipIf(c128sim is None, "py65 is not installed")
@unittest.skipIf(c128sim is not None and c128sim.kernal_path() is None,
                 "no C128 KERNAL image (VICE's kernal-318020-05.bin; $VICE_ROMS)")
class TestC128Cache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.pop("U5_SAVE_FROM", None)
        cls.p = u5.parts()
        cls.c = cls.p["c128"]

    def machines(self):
        p, c = self.p, self.c
        r = random.Random(128)
        noise = [bytes(r.randrange(256) for _ in range(0x10000)) for _ in range(2)]
        vdc = bytes(r.randrange(256) for _ in range(0x4000))
        sims, logs = [], []
        for port in (False, True):
            m = c128sim.C128Mem()
            m.ram[0][:] = noise[0]
            m.ram[1][:] = noise[1]
            m.vdc[:] = vdc
            m.trampolines()
            m.ram[1][0xFFF5:0xFFFA] = b"CBM\x24\xe2"           # the KERNAL's reset
            m[0xFF00] = 0x0E                                    # hook ($E1F0)
            sim = c128sim.C128Sim(m)
            log = []
            sim.traps[LOAD] = self.loader(log)
            sim.stops.add(0x8000)
            uh = file(p, "update.himem")
            m.put(0, uh[0], uh[1])
            music = file(p, "m")
            # the original loads `m` into bank 0 and copies it up; what its
            # later loads do not cover ($7B57-$7FFF, $A000-$A0FF) stays there
            # as residue, which nothing reads.  The cart leaves whatever was
            # there -- the same here, so that the comparison can be total.
            m.put(0, 0x7200, music[1])
            if port:
                m.put(1, 0x7200, music[1])
                # the rest of the original's bank copy ($7200-$A0FF) is
                # whatever bank 0 held there; make it the same
                end = 0x7200 + len(music[1])
                m.ram[1][end:0xA100] = m.ram[0][end:0xA100]
                m.put(1, u5.B1_ORG, c["b1"])
                m.put(0, 0x0200, c["far"])
                m.put(0, u5.SUBS_ADDR, c["subs"])
                m.put(0, u5.FAST_ADDR, c["fast"])
            sims.append(sim)
            logs.append(log)
        return sims, logs

    def loader(self, log):
        def load(sim):
            m, mpu = sim.mem, sim.mpu
            ret = m[0x100 + ((mpu.sp + 1) & 0xFF)] | m[0x100 + ((mpu.sp + 2) & 0xFF)] << 8
            name = bytearray()
            a = ret + 1
            while m[a]:
                name.append(m[a])
                a += 1
            m[0x100 + ((mpu.sp + 1) & 0xFF)] = a & 0xFF        # RTS past the NUL
            m[0x100 + ((mpu.sp + 2) & 0xFF)] = a >> 8
            log.append((bytes(name), mpu.x, m.cr))
            data = overlay(bytes(name))
            m.ram[0][0xA700:0xA700 + len(data)] = data
            mpu.p &= ~1                                          # C clear: loaded
            mpu.a = 1
        return load

    # the original's pieces, placed as its boot placed them
    def original_boot(self, sim):
        m = sim.mem
        self.assertEqual(sim.call(0x720F), c128sim.DONE)          # m's setup
        load, body = file(self.p, "subs.128")
        m.put(0, load, body)
        m.put(0, u5.SUBS_ADDR, self.p["bodies"][self.subs_key()])

    def subs_key(self):
        return next(k for k in self.p["bodies"] if k[0] == 1 and k[1].lower() == "temp.subs")

    # ---- the comparison -------------------------------------------------
    # (and the pointer operands of FETCH and STASH, $02AA/$02B9: the port
    # reads bank 0 through FETCH where the original read bank 1, and every
    # user of the two -- the KERNAL's INDFET included -- sets them first)
    OURS0 = [(0x0100, 0x0123), (0x0174, 0x0200), (0x0200, 0x0220), (0x0292, 0x0297),
             (0x02AA, 0x02AB), (0x02B9, 0x02BA),
             # update.himem's $1D8F, which the port does itself: its operands,
             # which it writes on every entry before it reads them
             (0x1DA5, 0x1DA6), (0x1DB6, 0x1DB7), (0x1DC6, 0x1DC7), (0x1DCB, 0x1DCC),
             (0x1DD2, 0x1DD3),
             (0x00FE, 0x0100),
             (0x6C00, 0x7B00)]          # temp.subs (its table points at a different
                                        # driver) and subs.128 or the driver
    OURS1 = [(0xE000, 0xF000), (0x0000, 0x0400),     # (common RAM is bank 0's)
             (0xFFF5, 0xFFF6)]          # the reset hook's "CBM", which the port clears

    def same(self, sims, what, regs=("a", "x")):
        o, q = sims
        for bank, skip in ((0, self.OURS0), (1, self.OURS1)):
            a, b = bytearray(o.mem.ram[bank]), bytearray(q.mem.ram[bank])
            for lo, hi in skip:
                a[lo:hi] = b[lo:hi] = bytes(hi - lo)
            if a != b:
                i = next(i for i in range(0x10000) if a[i] != b[i])
                self.fail(f"{what}: bank {bank} differs from ${i:04x}: "
                          f"original {a[i]:02x}, port {b[i]:02x}")
        self.assertEqual(o.mem.vdc, q.mem.vdc, f"{what}: the VDC's RAM")
        self.assertEqual(o.mem.io, q.mem.io, f"{what}: I/O")
        self.assertEqual(hex(o.mem.cr), hex(q.mem.cr), f"{what}: the MMU")
        self.assertEqual(o.mem.rcr, q.mem.rcr, f"{what}: common RAM")
        self.assertEqual(o.mpu.p & 0x05, q.mpu.p & 0x05, f"{what}: I and C")
        for r in regs:
            self.assertEqual(getattr(o.mpu, r), getattr(q.mpu, r), f"{what}: {r.upper()}")

    def both(self, sims, addr, what, a=0, x=0, y=0, cr=0x3F, stop=c128sim.DONE,
             regs=("a", "x")):
        for s in sims:
            s.mem[0xFF00] = cr
            s.mpu.p |= 0x04                                      # as a caller might
            self.assertEqual(s.call(addr, a, x, y), stop, what)
        self.same(sims, what, regs)

    def test_the_port_does_what_subs128_did(self):
        sims, logs = self.machines()
        o, q = sims
        self.original_boot(o)
        self.assertEqual(q.call(0x7715), c128sim.DONE)          # our music setup
        o.mem[0xC8] |= 0x40         # (which also says the music is there: the
                                    # gates test bit 6 -- build.py MUSIC_GATES)
        self.same(sims, "the music setup", regs=())
        # the KERNAL's reset hook: the original leaves its "CBM", under the
        # vector startup's NMI stub overwrites (`$82B8`); the port breaks it
        self.assertEqual(bytes(o.mem.ram[1][0xFFF5:0xFFF8]), b"CBM")
        self.assertNotEqual(bytes(q.mem.ram[1][0xFFF5:0xFFF8]), b"CBM")

        o.mem[0x79] = q.mem[0x79] = 0x80                        # music on
        # (with I/O in, as enter.play calls it: the original reaches the VDC
        # before its first $6C03 and would spin on $D600 without)
        self.both(sims, 0x770C, "the preload", cr=0x0E, regs=("a",))
        self.assertEqual(logs[0], logs[1])
        self.assertEqual([n for n, _x, _c in logs[0]], [b"Q"] + [bytes([c]) for c in b"CEIMPRSTUVZ"])
        for letter in b"CEIMPRSTUVZQ":
            self.both(sims, 0x7700, f"fetch {chr(letter)}", a=letter, regs=("a",))
        self.assertEqual(logs[0], logs[1])
        self.assertEqual(logs[0][-1][0], b"Q", "Q is not cached: loaded")
        self.both(sims, 0x770F, "the map to the VDC", a=0x12)
        self.both(sims, 0x770F, "and back", a=0x34, cr=0x0E)
        self.both(sims, 0x7712, "the KERNAL's $0A00 out", regs=("a",))
        self.both(sims, 0x7712, "and in", regs=("a",))
        for s in sims:
            s.mem[0x03CE] = 5                                   # the player has it
        self.both(sims, 0x7703, "play song 5", x=5)
        self.both(sims, 0x7706, "restart the song")
        self.both(sims, 0x7709, "mode swap", x=0x12, y=0x34, regs=("a",))
        self.both(sims, 0x7709, "mode swap back", x=0x12, y=0x34, regs=("a",))
        for s in sims:                                          # the mode root that
            s.mem.ram[1][0xA001:0xA003] = b"\xe9\x81"           # wants $A700 back
        self.both(sims, 0x7709, "mode swap, the other way", stop=0x8000, regs=())
        self.both(sims, 0x7709, "and again, still that way", x=0x12, y=0x34,
                  stop=0x8000, regs=())
        self.assertEqual(logs[0], logs[1])


@unittest.skipIf(c128sim is None, "py65 is not installed")
class TestC128Launcher(unittest.TestCase):
    """launch128.s on the model C128, against the built cart: loaded where
    DLOAD puts it, SYSed from BASIC's bank 15, it has to leave everything
    where the C128 boot left it -- `m` and the cache in bank 1, the rest in
    bank 0 -- the launcher's option in the driver, the cart pointed at the
    directory, and the MMU as xyzzy expects it."""

    @classmethod
    def setUpClass(cls):
        from ultima.flash.tcrt import TCRT
        cls.p = u5.parts()
        cls.c = cls.p["c128"]
        img = os.path.join(paths.BUILD, "ultima-collection.tcrt")
        cls.flash = bytes(TCRT.read(img).flash.ljust(u5.regions.FLASH_SIZE, b"\xff"))

    def run_launcher(self, settings):
        from ultima.sim.sim6502 import FakeCart
        flash = bytearray(self.flash)
        at = u5.regions.SETTINGS
        flash[at:at + len(settings)] = settings
        cart = FakeCart(flash)
        m = c128sim.C128Mem()
        prg = self.c["prg"]
        m.put(0, 0x1C01, prg[2:])
        m.ram[0][0x2D:0x2F] = b"\x01\x1c"             # TXTTAB, as DLOAD left it
        m.ram[0][0x00], m.ram[0][0x01] = 0x2F, 0x73     # the C128's port after reset
        m.ram[0][0x0A2C] = 0x14                         # the editor's $D018 shadow
        port = []                                       # $01 during the transfers
        self.port = port
        sim = c128sim.C128Sim(m)
        text = bytearray()

        def send(s):
            cart.send(s.mpu.a)
            port.append(s.mem.ram[0][1])

        def get(s):
            s.mpu.a = cart.get()
            s.mpu.p = (s.mpu.p & ~0x82) | (0x80 if s.mpu.a & 0x80 else 0) | (0 if s.mpu.a else 2)

        def cmdmode(s):
            s.mpu.p &= ~1                               # entered
        lsym, dsym = self.c["lsym"], self.c["sym"]
        for sy in (lsym, dsym):
            sim.traps[sy["tc_sendbyte"]] = send
            sim.traps[sy["tc_getbyte"]] = get
        sim.traps[lsym["tc_cmdmode"]] = cmdmode
        def chrout(s):
            text.append(s.mpu.a)
            if s.mpu.a == 14:                   # the editor's lower case set:
                s.mem.ram[0][0x0A2C] |= 0x02    # its $D018 shadow (ROM $C884)
        sim.traps[0xFFD2] = chrout
        self.plots = []
        sim.traps[0xFFF0] = lambda s: self.plots.append((s.mpu.x, s.mpu.y))
        sim.stops.update((0x2000, lsym["segs_done"]))
        stop = sim.call(0x1C01 + 26, limit=200_000_000)
        loaded = None
        if stop == lsym["segs_done"]:           # what the loads left, before
            loaded = [bytes(r) for r in m.ram]  # the driver's init runs
            stop = sim.go(limit=50_000_000)
        self.loaded = loaded
        return stop, sim, cart, bytes(text)

    def test_it_loads_what_the_c128_boot_loaded(self):
        opts = u5.regions.DESC_INDEX["u5"] + 4
        settings = bytearray(b"UCFG" + bytes(12))
        settings[opts] = 0xFF
        stop, sim, cart, text = self.run_launcher(bytes(settings))
        self.assertEqual(stop, 0x2000, "into xyzzy")
        m, c, p = sim.mem, self.c, self.p
        self.assertTrue(text.startswith(b"\x93\x0e"), "a clear screen, the lower case set")
        self.assertEqual(m.io[0x018], 0x16, "and the VIC told, with the IRQ off")
        self.assertIn(pet("Ultima V from the tapecart"), text)
        self.assertEqual(self.plots[0], (11, 7), "centred")
        self.assertEqual(m.ram[0][1] & 0x07, 0x06, "xyzzy's $01, set last")
        music = [b for k, b in p["bodies"].items() if k[0] == 1 and k[1].lower() == "m"][0]
        xyzzy = [b for k, b in p["bodies"].items() if k[0] == 1 and k[1].lower() == "xyzzy"][0]
        subs = c["subs"]
        for bank, addr, want, what in ((1, 0x7200, music, "m"), (1, u5.B1_ORG, c["b1"], "sub128"),
                                       (0, 0x0200, c["far"], "c128far"), (0, 0x2000, xyzzy, "xyzzy"),
                                       (0, u5.SUBS_ADDR, subs, "temp.subs"),
                                       (0, u5.FAST_ADDR, c["fast"], "the driver")):
            if what in ("the driver", "temp.subs"):
                # as loaded: its init then patches tclib's port values in
                self.assertEqual(self.loaded[bank][addr:addr + len(want)], bytes(c[
                    "fast" if what == "the driver" else "subs"]), what)
                continue
            self.assertEqual(bytes(m.ram[bank][addr:addr + len(want)]), bytes(want), what)
        self.assertEqual(m.ram[0][c["sym"]["pt_opts"]], p["options"]["caps"])
        self.assertEqual(m.ram[0][c["sym"]["pt_opts"]], p["options"]["caps"])
        self.assertEqual(m.cr, 0x0E, "the MMU xyzzy starts with")
        self.assertEqual(m.rcr, 0x04, "1 KiB common, at the bottom")
        self.assertEqual((m.ram[0][0], m.ram[0][1]), (0x2F, 0x26))
        self.assertIn(("setparams", p["dir_off"], p["entries"], u5.DIR_NAMELEN, u5.DIR_DATALEN),
                      cart.log)
        # the launcher's own transfers keep $01's bits 0-2 (colour RAM banks,
        # the VIC's charset): the screen does not change while it loads
        launcher_sends = self.port[:len(self.port) - 20]
        self.assertTrue(launcher_sends and all(v & 0x07 == 0x73 & 0x07 for v in launcher_sends),
                        sorted({hex(v) for v in launcher_sends}))
        # the settings page erased (or foreign): the options are off
        stop, sim, _cart, _t = self.run_launcher(b"\xff" * 16)
        self.assertEqual(stop, 0x2000)
        self.assertEqual(sim.mem.ram[0][c["sym"]["pt_opts"]], 0)

    def test_a_cart_without_it_is_refused(self):
        """An image whose descriptor page is not Ultima V's C128 one: a
        message and back to BASIC, nothing loaded."""
        from ultima.sim.sim6502 import FakeCart
        flash = bytearray(self.flash)
        flash[u5.regions.C128_DESC:u5.regions.C128_DESC + 256] = b"\xff" * 256
        self.flash, saved = bytes(flash), self.flash
        try:
            stop, sim, cart, text = self.run_launcher(b"\xff" * 16)
        finally:
            self.flash = saved
        self.assertEqual(stop, c128sim.DONE, "back to BASIC")
        self.assertIn(pet("This tapecart has no Ultima V for"), text)
        self.assertIn(pet("Write the launcher again from the"), text)
        self.assertIn(pet("Ultima V page on a C64."), text)
        self.assertEqual(sim.mem.cr, 0x00, "BASIC's bank 15 again")
        self.assertEqual([e[0] for e in cart.log], ["read"], "the descriptor page only")


@unittest.skipIf(c128sim is None, "py65 is not installed (use the repository's .venv)")
class TestC128Reads(unittest.TestCase):
    """The C128 build's reads (u5drv.s TC_PICK/TC_FETCH, c128fast.s in
    common RAM, sub128.s b1_pick/b1_get in bank 1): 2-bit with no sprite on,
    1-bit with one, both receives in bank 1.

    Bit level: sub128.s's own code, b1_pick then the receive it picked, in
    py65 against tests/test_tc_guard.py's model of the cart -- all 256
    values, for tclib's port value and one with $01 bits 0-2 set (which
    b1_pick's table has to take out).  And the plumbing on the model C128
    after a real launch: the driver's u5_fetch, raw and crunched, with both
    receives trapped -- the MMU at MMU_B1IO for each byte, the command and
    the receive matching, the MMU back at MMU_B0 and the data right."""

    RAW_AT, ZX_AT = 0x180000, 0x181000

    @classmethod
    def setUpClass(cls):
        cls.launcher = TestC128Launcher
        TestC128Launcher.setUpClass.__func__(cls)

    def pick(self, port, sprites):
        from py65.devices.mpu6502 import MPU
        from py65.memory import ObservableMemory
        b1, s = self.c["b1"], self.c["b1sym"]
        mem = ObservableMemory()
        for i, b in enumerate(b1):
            mem[u5.B1_ORG + i] = b
        mem[0x0297] = 0x60                          # C_BACK: an RTS will do
        mem[0x00], mem[0x01], mem[0xD015] = 0x2F, port, sprites
        mpu = MPU(memory=mem)
        mpu.sp = 0xFD
        mem[0x1FF], mem[0x1FE] = 0xFF, 0xEF
        mpu.pc = s["b1_pick"]
        for _ in range(5000):
            if mpu.pc == 0xFFF0:
                break
            mpu.step()
        else:
            self.fail("b1_pick did not return")
        target = mem[s["b1_fetch"] + 1] | mem[s["b1_fetch"] + 2] << 8
        return mpu.a, target, bytes(mem[u5.B1_ORG:u5.B1_ORG + len(b1)])

    def test_the_bank_1_receive_at_bit_level(self):
        from tests import test_tc_guard as g
        s = self.c["b1sym"]
        for port in (0x20, 0x27):
            with self.subTest(port=port):
                cmd, target, image = self.pick(port, 0)
                self.assertEqual((cmd, target), (0x11, s["tc_getbyte_guard"]))
                vic = g.Vic(63, 312, 3)
                for b in range(256):
                    out = []
                    g.run_byte(image, s, vic, 0x10 * 63, byte=b, result=out, org=u5.B1_ORG)
                    self.assertEqual(out, [b], f"${b:02x}")
        cmd, target, _image = self.pick(0x20, 0x04)
        self.assertEqual((cmd, target), (0x10, s["b1_slow"]))

    def test_the_bank_1_receive_misses_the_badlines(self):
        from tests import test_tc_guard as g
        s = self.c["b1sym"]
        _cmd, _t, image = self.pick(0x20, 0)
        vic = g.Vic(63, 312, 3)
        for t0 in g.phases(vic.n, vic.lines):
            got, start, end = g.run_byte(image, s, vic, t0, org=u5.B1_ORG)
            self.assertEqual(got, g.STOCK, t0)
            self.assertGreaterEqual(vic.clearance(start, end), g.MARGIN, t0)

    def machine(self):
        from ultima.flash import zx
        flash = bytearray(self.flash)
        raw = bytes((i * 73 + (i >> 5)) & 0xFF for i in range(700))
        plain = bytes(b"BRITANNIA " * 200 + bytes(range(256)) * 3)
        packed = zx.crunch(plain)
        flash[self.RAW_AT:self.RAW_AT + len(raw)] = raw
        flash[self.ZX_AT:self.ZX_AT + len(packed)] = packed
        self.flash, saved = bytes(flash), self.flash
        try:
            stop, sim, cart, _text = TestC128Launcher.run_launcher(self, b"\xff" * 16)
        finally:
            self.flash = saved
        self.assertEqual(stop, 0x2000)
        return sim, cart, raw, plain, packed

    def test_the_driver_reads_through_bank_1(self):
        sim, cart, raw, plain, packed = self.machine()
        m, d, b = sim.mem, self.c["sym"], self.c["b1sym"]
        self.assertEqual(bytes(m.ram[0][0x0113:0x0123]), self.c["c_fast"], "C_PICK, C_GET")
        self.assertEqual(bytes(m.ram[0][0x0297:0x029D]), self.c["c_back"], "C_BACK")
        cmds, used = [], []
        send = sim.traps[d["tc_sendbyte"]]
        get = sim.traps[d["tc_getbyte"]]

        def spy(s):
            if cart.cmd is None and s.mpu.a in (0x10, 0x11):
                cmds.append(s.mpu.a)
            send(s)

        def receive(name):
            def trap(s):
                used.append((name, m.cr))
                get(s)
            return trap
        sim.traps[d["tc_sendbyte"]] = spy
        sim.traps[b["tc_getbyte_guard"]] = receive("2-bit")
        sim.traps[b["b1_slow"]] = receive("1-bit")
        for sprites in (0x00, 0x10):
            m.io[0x15] = sprites
            for addr, length, dest, flags, want in (
                    (self.RAW_AT, len(raw), 0x4000, 0x00, raw),
                    (self.ZX_AT, len(packed), 0x5000, 0x02, plain)):
                with self.subTest(sprites=sprites, crunched=bool(flags)):
                    cmds.clear(), used.clear()
                    r = m.ram[0]
                    r[d["tc_addr"]:d["tc_addr"] + 3] = [addr & 0xFF, addr >> 8 & 0xFF, addr >> 16]
                    r[d["tc_len"]:d["tc_len"] + 2] = [length & 0xFF, length >> 8]
                    r[d["tc_dest"]:d["tc_dest"] + 2] = [dest & 0xFF, dest >> 8]
                    r[d["u5_flags"]] = flags
                    m[0xFF00] = 0x3F                # as u5_enter leaves it
                    sim.call(d["u5_fetch"])
                    self.assertEqual(bytes(m.ram[0][dest:dest + len(want)]), want)
                    fast = not sprites
                    self.assertEqual(cmds, [0x11 if fast else 0x10])
                    self.assertEqual(set(used), {("2-bit" if fast else "1-bit", 0x7E)})
                    self.assertEqual(m.cr, 0x3F, "back in bank 0, all RAM")


if __name__ == "__main__":
    unittest.main()
