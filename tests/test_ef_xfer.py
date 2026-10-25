"""The EasyFlash launcher (ultima/ef/efpage.s), on the host: the tapecart page's
Ultima VI transfer code (asm/page_xfer.s, page_u6x.s, page_file.s) over
eflib.s, in py65 on efsim's EasyFlash -- EAPI and all -- with the KERNAL's
I/O on fakedrive.FakeDrive, as tests/test_u6_xfer.py and test_file_xfer.py
run it on the tapecart.

  * L and J put efinit.s at $1000 and jump there, J with Journey onward's
    pokes in its table; J (and E) only with a saved game, whose party the
    page shows;
  * an export writes the log's world to the disks, and to a file;
  * an import logs what differs from the originals into the log's other
    half and makes it the one in use -- as the next boot (efinit.s) sees it;
  * a world goes out and comes back; a bad file leaves the log alone;
  * R makes a new, empty log;
  * to and from the tapecart's collection (eftc.s, on sim6502.FakeCart):
    what the source logged and differs from the originals, into the
    destination's other half, as that cart's next boot finds it -- and
    nothing at all without a tapecart, a collection of this save layout, or
    (importing) a saved game on it.

Skipped without py65, or before the EF image is built (make u6ef).
"""
import random
import unittest

try:
    from tests.efsim import EFSim
except ImportError:
    EFSim = None

from tests import test_ef                          # noqa: E402  (skips itself without the EF build)
from tests.test_ef import built, boot_log     # noqa: E402
from tests import test_u6_xfer as X                # noqa: E402
from tests.test_file_xfer import blank_d64, with_file, NAMES     # noqa: E402
from ultima.sim.fakedrive import FakeDrive, Disk   # noqa: E402
from ultima.launcher.u6log import Log                   # noqa: E402
from ultima.sim.sim6502 import FakeCart, PowerCut  # noqa: E402
from ultima.flash.tcrt import TCRT                   # noqa: E402
from ultima.ef import efregions as R                   # noqa: E402
from ultima.flash import regions                          # noqa: E402

E, I, D, F, Y, J, L, RR, T, N = (ord(c) for c in "EIDFYJLRTN")
RET, SPACE = 13, 32
INIT = 0x1000


class Stop(Exception):
    pass


@unittest.skipIf(EFSim is None, "py65 is not installed (use the repository's .venv)")
class TestEFLauncher(unittest.TestCase):
    eapi = "real"

    @classmethod
    def setUpClass(cls):
        cls.p = built()
        cls.lsym = cls.p["lsym"]
        cls.orig = {tag: Disk(X.original(tag)) for tag in X.DISKS}
        cls.orig_files = {tag: X.files_of(d) for tag, d in cls.orig.items()}

    def fresh(self, gen=1):
        """The built image with an empty log (a header) in half 0."""
        f = bytearray(self.p["flash"])
        Log(f, R.LOG_LO, R.LOG_MID).header(gen)
        return f

    def launch(self, flash, keys, disk=None, tapecart=None, until=INIT):
        """The launcher from its start until it jumps to efinit at $1000
        (or `until`).  Returns (the sim, the drive, the disks it was given,
        the screen).  tapecart: a FakeCart on the tape port, or None for none
        (its tc_cmdmode times out)."""
        p = self.p
        sim = EFSim(bytes(flash), eapi=self.eapi)
        self.plug(sim, tapecart)
        if self.eapi == "contract":
            sim.contract_init_at(self.lsym["EL_SLOT"])
        m = sim.mem
        m.stuck = set(getattr(self, "stuck", ()))
        org = self.lsym["PAGE_ORG"]
        m.ram[org:org + len(p["launcher"])] = p["launcher"]
        m.ram[0], m.ram[1] = 0x2F, 0x37
        m.control = 0x07                        # as efstart.s leaves it
        drv = FakeDrive(sim, disk)
        taken = [drv.disk]
        ks = list(keys)

        def getin(s):
            while ks and isinstance(ks[0], tuple):
                drv.swap(ks.pop(0)[1])
                taken.append(drv.disk)
            if not ks:
                raise AssertionError("the launcher wants another key; screen:\n" +
                                     X.test_page.screen(drv.screen)[-700:])
            k = ks.pop(0)
            s.mpu.a = k
            s.mpu.p = (s.mpu.p & ~0x82) | (0 if k else 0x02)
        sim.traps[0xFFE4] = getin
        for a in (0xFF9F, 0xFF84, 0xFF8A, 0xFF81):          # SCNKEY IOINIT RESTOR CINT
            sim.traps[a] = lambda s: None
        mpu = sim.mpu
        mpu.pc, mpu.sp = org, 0xFD
        steps = 0
        while mpu.pc != until:
            h = sim.traps.get(mpu.pc)
            if h is not None:
                h(sim)
                lo = m.ram[0x100 + ((mpu.sp + 1) & 0xFF)]
                hi = m.ram[0x100 + ((mpu.sp + 2) & 0xFF)]
                mpu.sp = (mpu.sp + 2) & 0xFF
                mpu.pc = ((hi << 8 | lo) + 1) & 0xFFFF
                continue
            mpu.step()
            steps += 1
            if steps > 400_000_000:
                raise RuntimeError(f"no launch, pc=${mpu.pc:04x}")
        self.assertEqual(ks, [], "keys left over")
        return sim, drv, taken, X.test_page.screen(drv.screen)

    def plug(self, sim, cart):
        """The tapecart's tclib (eftc.s, at TCX_ORG once read in) onto `cart`,
        as Sim.attach_cart does: tc_sendbyte and tc_getbyte keep only Y."""
        t = self.p["tsym"]

        def send(s):
            cart.send(s.mpu.a)
            s.mpu.x = (s.mpu.x * 7 + 0x5B) & 0xFF

        def get(s):
            s.mpu.x = (s.mpu.x * 7 + 0x5B) & 0xFF
            s.mpu.a = cart.get()
            p = s.mpu.p & ~0x82
            s.mpu.p = p | (0x80 if s.mpu.a & 0x80 else 0) | (0x02 if s.mpu.a == 0 else 0)

        def cmdmode(s):
            s.mpu.p = (s.mpu.p & ~0x01) if cart else (s.mpu.p | 0x01)
            if cart:
                cart.opened = getattr(cart, "opened", 0) + 1
        sim.traps[t["tc_cmdmode"]] = cmdmode
        if cart:
            sim.traps[t["tc_sendbyte"]] = send
            sim.traps[t["tc_getbyte"]] = get

    def active(self, flash):
        """What the next boot finds: (generation, active half, the log's contents)."""
        view, st = boot_log(flash)
        return st["gen"], st["act"], X.contents(view)

    def check_disk(self, disk, tag, want):
        X.TestU6Xfer.check_disk(self, disk, tag, want)

    def export(self, flash, d1a, d1b):
        sim, drv, disks, text = self.launch(flash, [E, D, Y, RET, ("swap", d1b), RET, SPACE, L], d1a)
        self.assertIn("Done.", text, text[-500:])
        self.assertEqual(bytes(sim.mem.flash()), bytes(flash), "an export changed the cart")
        return disks

    def imported(self, flash, d1a, d1b):
        sim, drv, disks, text = self.launch(flash, [I, D, Y, RET, ("swap", d1b), RET, SPACE, L], d1a)
        self.assertIn("Done.", text, text[-500:])
        return sim.mem.flash(), text

    def logged_world(self):
        """A log with new versions of some chunk files and of part of the
        save area (test_file_xfer.TestU6File.logged_world)."""
        flash = self.fresh()
        log = Log(flash, R.LOG_LO, R.LOG_MID, logdir=R.LOG_MID - 20)
        rng = random.Random(6)
        want = {t: dict(f) for t, f in self.orig_files.items()}
        for tag, names in (("1A", ["SCC", "SDD", "SAA"]), ("1B", ["DAA"])):
            for name in names:
                n = rng.randint(1, 7)
                content = rng.randbytes(254 * (n - 1) + rng.randint(1, 254))
                pages = []
                for i in range(n):
                    part = content[254 * i:254 * (i + 1)]
                    link = bytes([17, i]) if i + 1 < n else bytes([0, len(part) + 1])
                    pages.append((link + part).ljust(256, b"\x00"))
                log.append(b"/" + name.encode(), pages, True)
                want[tag][name] = content
        save = {s: rng.randbytes(256) for s in (9, 12, 13, 20)}
        for s, pg in save.items():
            log.append(bytes([1, 0, 6, s]), [pg], False)
        return flash, want, save

    def played_party(self):
        """A log with the played session's save area (its party), as a
        character created and saved leaves it."""
        flash = self.fresh()
        log = Log(flash, R.LOG_LO, R.LOG_MID, logdir=R.LOG_MID - 20)
        played = Disk(X.original("1A", X.PLAYED))
        for sec in range(9, 21):
            log.append(bytes([1, 0, 6, sec]), [bytes(played.sector(6, sec))], False)
        return flash

    # -- L and J ---------------------------------------------------------------
    def test_launch_and_journey_onward(self):
        p = self.p
        o = self.lsym["EFI_POKES"] - INIT
        for key, pokes in ((J, bytes([6, 0x25, 0xC0, 0xF0, 0x26, 0xC0, 0xC054 - 0xC027])), (L, bytes([0]))):
            sim, _d, _t, text = self.launch(self.played_party(), [key])
            m = sim.mem
            got = bytes(m.ram[INIT:INIT + len(p["init"])])
            self.assertEqual(got[o:o + len(pokes)], pokes)
            self.assertEqual(got[:o] + got[o + len(pokes):], p["init"][:o] + p["init"][o + len(pokes):],
                             "efinit's image, as built")
            self.assertEqual((m.ram[1], m.control, sim.mpu.p & 0x04), (0x37, 0x07, 0x04),
                             "the cart in, $01 = $37, interrupts off: efinit's entry")
        self.assertIn("Journey onward", text)

    def test_the_font_is_ultima_vis_text_box_font(self):
        from ultima.launcher import launcher
        sim, _d, _t, _text = self.launch(self.fresh(), [L])
        ichars = self.p["disks"]["3B"].file("ICHARS")[0][2:]
        want = launcher.font(bytes(b ^ 0xFF for b in ichars[:0x400]), own_slash=False)
        self.assertEqual(bytes(sim.mem.ram[0x4800:0x5000]), want)
        self.assertEqual(want[0x01 * 8:0x02 * 8], bytes(b ^ 0xFF for b in ichars[0x61 * 8:0x62 * 8]),
                         "screen code 1 is U6's 'a'")

    def test_the_page_shows_the_party_or_no_saved_game(self):
        # a world never saved (or reset): no party, and no J or E -- the
        # game's own menu says "Create a Character first" then
        sim, _d, _t, text = self.launch(self.fresh(), [J, ord("E"), L])
        self.assertIn("No saved game", text)
        self.assertNotIn("Journey onward", text)
        self.assertNotIn("Export", text)
        self.assertEqual(sim.mem.ram[self.lsym["EFI_POKES"]], 0, "J did nothing: L launched")
        _s, _d, _t, text = self.launch(self.played_party(), [L])
        self.assertNotIn("No saved game", text)
        self.assertRegex(text, r"\n   \S+ +HP +\d+/\d+\n", "a member, its hit points")
        self.assertLess(text.index("Launch the game"), text.index("Journey onward"), "L, then J")
        self.assertIn("EAPI: Am/M29F040 V1.4", text, "the EAPI EasyProg put in, by name")

    # -- to and from the game's disks ---------------------------------------------
    def test_an_export_writes_the_logged_world(self):
        flash, want, save = self.logged_world()
        d1a, d1b = self.export(flash, X.original("1A"), X.original("1B"))
        self.check_disk(d1a, "1A", want["1A"])
        self.check_disk(d1b, "1B", want["1B"])
        for s in range(9, 21):
            self.assertEqual(bytes(d1a.sector(6, s)), save.get(s, bytes(self.orig["1A"].sector(6, s))))

    def test_an_import_logs_what_differs(self):
        played = {tag: Disk(X.original(tag, X.PLAYED)) for tag in X.DISKS}
        flash, _text = self.imported(self.fresh(gen=4), bytes(played["1A"].data), bytes(played["1B"].data))
        gen, act, got = self.active(flash)
        self.assertEqual((gen, act), (5, 3), "the other half, a generation on")
        self.assertEqual(flash[R.LOG_LO:R.LOG_MID], b"\xff" * (R.LOG_MID - R.LOG_LO), "the old half erased")
        want = {}
        for tag in X.DISKS:
            for name, content in X.files_of(played[tag]).items():
                if content != self.orig_files[tag][name]:
                    want[b"/" + name.encode()] = content
        for s in range(9, 21):
            if played["1A"].sector(6, s) != self.orig["1A"].sector(6, s):
                want[bytes([1, 0, 6, s])] = bytes(played["1A"].sector(6, s))
        self.assertTrue(want)
        self.assertEqual(got, want)

    def test_a_cancelled_import_leaves_the_log(self):
        flash, _w, _s = self.logged_world()
        before = self.active(flash)
        sim, _d, _t, text = self.launch(flash, [I, D, Y, RET, 0x5F, L], X.original("1A", X.PLAYED))
        self.assertEqual(self.active(sim.mem.flash()), before)

    def test_a_world_goes_out_and_comes_back(self):
        played = {tag: X.original(tag, X.PLAYED) for tag in X.DISKS}
        flash, _t = self.imported(self.fresh(), played["1A"], played["1B"])
        d1a, d1b = self.export(flash, X.original("1A"), X.original("1B"))
        for tag, disk in (("1A", d1a), ("1B", d1b)):
            self.check_disk(disk, tag, X.files_of(Disk(played[tag])))
        again, _t = self.imported(self.fresh(), bytes(d1a.data), bytes(d1b.data))
        self.assertEqual(self.active(again)[2], self.active(flash)[2])

    # -- to and from a file -----------------------------------------------------------
    def test_a_world_goes_to_a_file_and_back(self):
        src, _w, _s = self.logged_world()
        sim, drv, _d, text = self.launch(src, [E, F, Y, RET, SPACE, L], blank_d64())
        self.assertIn("Done.", text, text[-500:])
        self.assertEqual(bytes(sim.mem.flash()), bytes(src))
        disk = drv.disk
        sim, _drv, _d, text = self.launch(self.fresh(gen=2), [I, F, Y, RET, SPACE, L], bytes(disk.data))
        self.assertIn("Done.", text, text[-500:])
        gen, act, got = self.active(sim.mem.flash())
        self.assertEqual((gen, act), (3, 3))
        self.assertEqual(got, self.active(src)[2])

    def test_a_bad_file_leaves_the_log(self):
        src, _w, _s = self.logged_world()
        _sim, drv, _d, _text = self.launch(src, [E, F, Y, RET, SPACE, L], blank_d64())
        good = drv.disk.read_file(NAMES["u6"])
        old = self.fresh(gen=2)
        before = self.active(old)
        for bad in (good[:-1], good[:-2] + bytes([good[-2] ^ 1, good[-1]])):
            sim, _drv, _d, text = self.launch(old, [I, F, Y, RET, SPACE, L], with_file(NAMES["u6"], bad))
            self.assertIn("The file is", text, text[-400:])
            self.assertEqual(self.active(sim.mem.flash()), before)

    # -- R ---------------------------------------------------------------------------
    def test_reset_makes_an_empty_log(self):
        flash, _w, _s = self.logged_world()
        sim, _d, _t, text = self.launch(flash, [RR, Y, SPACE, L])
        self.assertIn("Done.", text, text[-300:])
        gen, act, got = self.active(sim.mem.flash())
        self.assertEqual((gen, act, got), (2, 3, {}))
        sim, _d, _t, _text = self.launch(flash, [RR, ord("N"), L])
        self.assertEqual(bytes(sim.mem.flash()), bytes(flash), "N: nothing")


    def test_a_failed_write_keeps_the_old_log(self):
        # a byte that will not program (a worn cell): the import must not make
        # its half the one in use, nor erase the old one -- and says so
        flash, _w, _s = self.logged_world()
        before = self.active(flash)
        played = {tag: X.original(tag, X.PLAYED) for tag in X.DISKS}
        self.stuck = {R.LOG_MID}                 # the first page's link: never $FF
        try:
            sim, _d, _t, text = self.launch(flash, [I, D, Y, RET, ("swap", played["1B"]), RET, SPACE, L],
                                            played["1A"])
        finally:
            self.stuck = set()
        self.assertIn("A write to the cartridge failed", text, text[-500:])
        self.assertEqual(self.active(sim.mem.flash()), before)


    # -- to and from the tapecart ---------------------------------------------------
    TP_LO = regions.save_base("u6")
    TP_HI = regions.REGIONS["u6"][3]
    TP_MID = TP_LO + (TP_HI - TP_LO) // 2

    def tapecart(self):
        """The collection's flash as built (its settings page stamped), U6's
        log empty."""
        f = bytearray(TCRT.read(X.IMAGE).flash.ljust(regions.FLASH_SIZE, b"\xff"))
        self.assertEqual(f[regions.SETTINGS:regions.SETTINGS + 4], b"UCFG")
        self.assertEqual(f[self.TP_LO:self.TP_HI], b"\xff" * (self.TP_HI - self.TP_LO))
        return f

    def tp_active(self, flash):
        """The tapecart's log as its boot picks it (asm/init_u6.s; test_u6_xfer
        active): (generation, the half's base, the contents), or None."""
        halves = []
        for base, top in ((self.TP_LO, self.TP_MID), (self.TP_MID, self.TP_HI)):
            e = flash[top - 20:top]
            if e[0] == 0xFF:
                continue
            gen = 0
            if e[0] == 0xFE:
                g, c = e[12] | e[13] << 8, e[14] | e[15] << 8
                self.assertEqual(g ^ c, 0xFFFF, "a torn header")
                gen = g
            n, d = 0, top
            while flash[d - 20] != 0xFF:
                d -= 20
                n += 1
            halves.append((gen, base, d, n))
        if not halves:
            return None
        gen, base, d, n = max(halves)       # (the other may be half erased)
        return gen, base, X.contents(X.view(flash, d, n))

    @staticmethod
    def pages(content, n=None):
        """A chunk file's sectors as the log keeps them: links and all."""
        n = n or max(1, (len(content) + 253) // 254)
        out = []
        for i in range(n):
            part = content[254 * i:254 * (i + 1)]
            link = bytes([17, i]) if i + 1 < n else bytes([0, len(part) + 1])
            out.append((link + part).ljust(256, b"\x00"))
        return out

    def tp_world(self, gen=None, header=True):
        """A tapecart whose U6 log holds a played world: chunk files, a saved
        party (S12, S13) and more of the save area -- and, never to be
        copied, a chunk file and a sector logged unchanged and an older
        version under a newer one."""
        flash = self.tapecart()
        log = Log(flash, self.TP_LO, self.TP_MID)
        if header:
            log.header(gen or 0)
        rng = random.Random(16)
        want = {}
        for name in ("SAB", "SHH", "DCC", "SAB"):           # SAB twice: the newer wins
            content = rng.randbytes(254 * rng.randint(0, 4) + rng.randint(1, 254))
            log.append(b"/" + name.encode(), self.pages(content), True)
            want[b"/" + name.encode()] = content
        same = self.orig_files["1A"]["SBB"]
        log.append(b"/SBB", self.pages(same), True)
        for sec in (9, 12, 13, 17):
            pg = rng.randbytes(256)
            log.append(bytes([1, 0, 6, sec]), [pg], False)
            want[bytes([1, 0, 6, sec])] = pg
        log.append(bytes([1, 0, 6, 15]), [bytes(self.orig["1A"].sector(6, 15))], False)
        return flash, want

    def test_a_world_goes_to_the_tapecart(self):
        flash, want, save = self.logged_world()
        cart = FakeCart(self.tapecart())
        sim, _d, _t, text = self.launch(flash, [E, T, Y, SPACE, L], tapecart=cart)
        self.assertIn("Done.", text, text[-500:])
        self.assertEqual(bytes(sim.mem.flash()), bytes(flash), "an export changed the EasyFlash")
        gen, base, got = self.tp_active(cart.flash)
        self.assertEqual((gen, base), (0, self.TP_LO), "a cart with no log: half 0, generation 0")
        self.assertEqual(got, self.active(flash)[2])
        self.assertFalse(cart.led, "the LED off after")
        outside = bytearray(cart.flash)
        outside[self.TP_LO:self.TP_HI] = self.tapecart()[self.TP_LO:self.TP_HI]
        self.assertEqual(bytes(outside), bytes(self.tapecart()), "nothing outside U6's log")
        # and the tapecart's own page (asm/page.s, test_u6_xfer) exports it to
        # the game's disks as this cart would
        X.TestU6Xfer.setUpClass()
        tp = X.TestU6Xfer("test_an_export_writes_the_logged_world")
        d1a, d1b = tp.export(cart.flash, X.original("1A"), X.original("1B"))
        self.check_disk(d1a, "1A", want["1A"])
        self.check_disk(d1b, "1B", want["1B"])
        for s in range(9, 21):
            self.assertEqual(bytes(d1a.sector(6, s)), save.get(s, bytes(self.orig["1A"].sector(6, s))))

    def test_a_world_comes_from_the_tapecart(self):
        tflash, want = self.tp_world(gen=7)
        cart = FakeCart(tflash)
        sim, _d, _t, text = self.launch(self.fresh(gen=4), [I, T, Y, SPACE, L], tapecart=cart)
        self.assertIn("Done.", text, text[-500:])
        self.assertEqual(bytes(cart.flash), bytes(tflash), "an import changed the tapecart")
        gen, act, got = self.active(sim.mem.flash())
        self.assertEqual((gen, act), (5, 3), "the other half, a generation on")
        self.assertEqual(got, want, "what differs from the originals, the newest of each")
        self.assertIn("Journey onward", self.launch(sim.mem.flash(), [L])[3], "a saved game")

    def test_a_tapecart_log_from_before_headers(self):
        # a half whose top slot is an ordinary entry: generation 0 (init_u6.s)
        tflash, want = self.tp_world(header=False)
        sim, _d, _t, text = self.launch(self.fresh(), [I, T, Y, SPACE, L], tapecart=FakeCart(tflash))
        self.assertIn("Done.", text, text[-500:])
        self.assertEqual(self.active(sim.mem.flash())[2], want)

    def test_a_world_goes_round_through_the_tapecart(self):
        src, _w, _s = self.logged_world()
        tflash, _want = self.tp_world(gen=2)
        cart = FakeCart(tflash)
        self.launch(src, [E, T, Y, SPACE, L], tapecart=cart)
        gen, base, got = self.tp_active(cart.flash)
        self.assertEqual((gen, base), (3, self.TP_MID), "the other half, a generation on")
        self.assertEqual(cart.flash[self.TP_LO:self.TP_MID], b"\xff" * (self.TP_MID - self.TP_LO),
                         "the old half erased")
        self.assertEqual(got, self.active(src)[2])
        sim, _d, _t, text = self.launch(self.fresh(gen=9), [I, T, Y, SPACE, L], tapecart=cart)
        self.assertIn("Done.", text, text[-500:])
        self.assertEqual(self.active(sim.mem.flash())[2], self.active(src)[2])

    def test_nothing_without_the_right_tapecart(self):
        tflash, _want = self.tp_world(gen=1)
        flash, _w, _s = self.logged_world()
        wrong = bytearray(tflash)
        wrong[regions.SETTINGS + regions.SET_LAYOUT] = regions.LAYOUT + 1
        blank = bytearray(tflash)
        blank[regions.SETTINGS:regions.SETTINGS + 16] = b"\xff" * 16
        for cart, says in ((None, "none answers"), (FakeCart(wrong), "has no Ultima collection"),
                           (FakeCart(blank), "has no Ultima collection")):
            for key in (E, I):
                with self.subTest(says=says, key=chr(key)):
                    before = bytes(cart.flash) if cart else None
                    sim, _d, _t, text = self.launch(flash, [key, T, SPACE, L], tapecart=cart)
                    self.assertIn(says, text, text[-400:])
                    self.assertEqual(bytes(sim.mem.flash()), bytes(flash))
                    if cart:
                        self.assertEqual(bytes(cart.flash), before)
        empty = FakeCart(self.tapecart())               # no saved game there
        sim, _d, _t, text = self.launch(flash, [I, T, SPACE, L], tapecart=empty)
        self.assertIn("no saved game", text, text[-400:])
        self.assertEqual(bytes(sim.mem.flash()), bytes(flash))
        cart = FakeCart(tflash)                         # N: nothing
        for key in (E, I):
            sim, _d, _t, _text = self.launch(flash, [key, T, N, L], tapecart=cart)
            self.assertEqual(bytes(sim.mem.flash()), bytes(flash))
            self.assertEqual(bytes(cart.flash), bytes(tflash))

    def test_a_power_cut_during_an_export_leaves_one_world(self):
        src, _w, _s = self.logged_world()
        tflash, _want = self.tp_world(gen=2)
        old, new = self.tp_active(tflash)[2], self.active(src)[2]
        cart = FakeCart(tflash)
        self.launch(src, [E, T, Y, SPACE, L], tapecart=cart)
        total = cart.changes
        for cut in sorted({1, 31, 32, total // 2, total - 34, total - 33, total - 32, total - 1}):
            with self.subTest(cut=cut):
                cart = FakeCart(tflash)
                cart.cut_after = cut
                with self.assertRaises(PowerCut):
                    self.launch(src, [E, T, Y, SPACE, L], tapecart=cart)
                self.assertIn(self.tp_active(cart.flash)[2], (old, new))

    def test_a_failed_write_keeps_the_old_log_from_the_tapecart(self):
        flash, _w, _s = self.logged_world()
        before = self.active(flash)
        tflash, _want = self.tp_world(gen=1)
        self.stuck = {R.LOG_MID}
        try:
            sim, _d, _t, text = self.launch(flash, [I, T, Y, SPACE, L], tapecart=FakeCart(tflash))
        finally:
            self.stuck = set()
        self.assertIn("A write to the cartridge failed", text, text[-500:])
        self.assertEqual(self.active(sim.mem.flash()), before)


class TestEFLauncherByContract(TestEFLauncher):
    """The same, with EAPI answered by its documented contract alone."""
    eapi = "contract"


if __name__ == "__main__":
    unittest.main()
