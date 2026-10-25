"""Ultima V's music with the Ultima VI EasyFlash cart (armusic.s EF_MUSIC,
efhook.s; ultima/games/u5/build.py build_efmusic), as tests/test_u5_armusic.py
has it with an Action Replay.

On efsim's C64 with an EasyFlash holding the music's bank, with the
tapecart's own segments in RAM as ultima/ef/efu5.s leaves them (the
patches made) and the built cart behind the driver's tclib: the hook takes
the stage from the bank, arinit sets the player up, and songs are played
through the real entries -- every SID write the ticks make must be the
original player's (`m` at $7200, unchanged: every song is in the bank, so a
song's end is the original's too), nothing is ever loaded, and the C64's RAM
under the cart's window comes out as it went in.  The driver's reads go
2-bit through the bank's receive with the cart mapped for each byte, 1-bit
with a sprite on; neither touches the player's state in the cart's RAM.
"""
import os
import unittest

try:
    from tests.efsim import EFMemory
    from ultima.sim import armodel
    from py65.devices.mpu6502 import MPU
    from py65.memory import ObservableMemory
except ImportError:
    EFMemory = None

from tests import test_u5_armusic as A               # noqa: E402
from ultima.sim.sim6502 import FakeCart               # noqa: E402
from ultima.flash.layout import image_from            # noqa: E402
from ultima.flash import regions                      # noqa: E402
from ultima.ef import efregions as R                  # noqa: E402

u5 = A.u5
BANK = 42
SEQUENCE, TICKS = A.SEQUENCE, A.TICKS


class EFMusicMem(EFMemory if EFMemory else object):
    """efsim's C64 with an EasyFlash, with what armodel.Sim and these tests
    ask of a memory: $01 as `p01`, the SID's writes, $DC0D from `icr`."""

    def __init__(self, flash):
        super().__init__(flash)
        self.sid, self.tick, self.icr = [], 0, 0
        self.control = u5.EF_OFF

    @property
    def p01(self):
        return self.ram[1]

    @p01.setter
    def p01(self, v):
        self.ram[1] = v & 0xFF

    def __getitem__(self, a):
        if a == 0xDC0D and self.region(a) == "io":
            v, self.icr = self.icr, 0
            return v
        return super().__getitem__(a)

    def io_write(self, a, v):
        if 0xD400 <= a < 0xD420:
            self.sid.append((self.tick, a, v))
        super().io_write(a, v)


def original(m, sequence, ticks, walk_to=None, after=0):
    """The SID writes of the unrelocated player, `m` unchanged."""
    mem = ObservableMemory()
    mpu = MPU(memory=mem)
    for i, v in enumerate(m):
        mem[0x7200 + i] = v
    sid, t = [], [0]
    mem.subscribe_to_write(range(0xD400, 0xD420), lambda a, v: sid.append((t[0], a, v)))

    def call(a):
        mpu.sp = 0xFD
        mem[0x1FF], mem[0x1FE] = (0xFFF0 - 1) >> 8, (0xFFF0 - 1) & 0xFF
        mpu.pc = a
        while mpu.pc != 0xFFF0:
            mpu.step()
    call(0x73DA)
    call(0x7303)
    call(0x73DA)
    del sid[:]
    mem[0x79] = 0x80
    k = 0
    for song in sequence:
        mem[0x03CC] = mem[0x03CD] = song
        for _ in range(ticks):
            t[0] = k
            k += 1
            call(0x73BC)
    if walk_to is not None:
        mem[0x03CD] = walk_to
        for _ in range(after):
            t[0] = k
            k += 1
            call(0x73BC)
    return sid


@unittest.skipIf(EFMemory is None, "py65 is not installed (use the repository's .venv)")
class TestEFMusic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.pop("U5_SAVE_FROM", None)
        cls.p = u5.parts()
        blobs = [(a, bytes(b)) for a, b in cls.p["blobs"]]
        cls.e = u5.build_efmusic(cls.p, BANK)
        cls.blobs_after = [(a, bytes(b)) for a, b in cls.p["blobs"]]
        cls.blobs_before = blobs
        cls.flash = image_from(cls.p["blobs"], regions.FLASH_SIZE)
        cls.ef = bytearray(b"\xff" * R.FLASH_SIZE)
        cls.ef[R.lin(BANK):R.lin(BANK) + len(cls.e["image"])] = cls.e["image"]
        cls.sym = cls.p["sym"]
        cls.s = cls.e["ssym"]
        cls.m = bytes([b for k, b in cls.p["bodies"].items() if k[0] == 1 and k[1].lower() == "m"][0])
        cls.want = original(cls.m, SEQUENCE, TICKS)

    def machine(self, flash=None):
        mem = EFMusicMem(bytes(self.ef))
        sim = armodel.Sim(mem)
        cart = FakeCart(flash or self.flash)
        sim.traps[self.sym["tc_sendbyte"]] = lambda s: cart.send(s.mpu.a)

        def get(s):
            s.mpu.a = cart.get()
            s.mpu.p = (s.mpu.p & ~0x82) | (0x80 if s.mpu.a & 0x80 else 0) | (0 if s.mpu.a else 2)
        sim.traps[self.sym["tc_getbyte"]] = get
        sim.traps[0xFF9F] = lambda s: None              # SCNKEY
        # the segments as efu5.s leaves them, then what xyzzy has done by
        # $2090: the $0380 handler copied down, the music API's RTS stubs
        for _a, _n, dest, data in self.e["segs"]:
            mem.ram[dest:dest + len(data)] = data
        for addr, _old, new in self.e["patches"]:
            mem.ram[addr:addr + len(new)] = new
        mem.ram[0x0380:0x03A0] = mem.ram[0x23B5:0x23D5]
        mem.ram[0x0126] = mem.ram[0x0129] = 0x60
        mem.bank = BANK
        mem.p01 = 0x26
        return mem, sim, cart

    def boot(self, mem, sim):
        sim.traps[0x20D5] = lambda s: None
        sim.call(0x2090)

    def tick(self, mem, sim, k=0):
        mem.tick = k
        mem.icr = 0x02                                  # timer B
        sim.mpu.p |= 0x04
        mem.p01 = 0x26                                 # as the handler's $6C03 left it
        sim.call(self.s["airq"])

    def play(self, mem, sim, song):
        mem.ram[0x79] = 0                               # (no spin: nothing ticks)
        sim.call(self.s["aplay"], x=song)
        mem.ram[0x79] = 0x80

    # ---- the build --------------------------------------------------------------
    def test_the_tapecart_image_is_left_alone(self):
        self.assertEqual(self.blobs_after, self.blobs_before)

    def test_the_patches(self):
        """Each patch's original bytes are the segments' as the tapecart
        holds them: the AR's register writes, and the AR's hook."""
        ram = bytearray(0x10000)
        for _a, _n, dest, data in self.e["segs"]:
            ram[dest:dest + len(data)] = data
        got = {}
        for addr, old, new in self.e["patches"]:
            self.assertEqual(bytes(ram[addr:addr + len(old)]), old)
            self.assertEqual(len(old), len(new))
            got[addr] = new
        self.assertEqual(got[self.sym["u5_armap"] + 4], bytes([0xA9, 0x07, 0x8D, 0x02, 0xDE]))
        self.assertEqual(got[self.sym["u5_arout"]], bytes([0xA2, 0x04, 0x8E, 0x02, 0xDE]))
        self.assertLessEqual(0x2090 + len(got[0x2090]), 0x20D5)
        self.assertEqual(len(self.e["patches"]), 3)

    def test_the_bank(self):
        """The jump table at $8000 where the driver jumps; the songs after the
        player as in `m`; the stage at the end, as the hook copies it."""
        img, base = self.e["image"], u5.AR_BASE
        for name in ("AR_J_GET", "AR_J_PICK"):
            self.assertEqual(self.s[name], self.sym[name])
            self.assertEqual(img[self.s[name] - base], 0x4C)
        songs = self.m[u5.armusic.HEADER[0] - 0x7200:u5.armusic.SONGS_END - 0x7200]
        at = self.e["rel"]["header"] - base
        self.assertEqual(img[at:at + len(songs)], songs)
        st = self.e["stage_rom"] - base
        self.assertEqual(img[st:st + len(self.e["stage"])], self.e["stage"])
        self.assertLessEqual(len(img), 0x4000)

    # ---- the music -----------------------------------------------------------------
    def test_the_hook_sets_the_music_up(self):
        mem, sim, cart = self.machine()
        self.boot(mem, sim)
        s = self.s
        self.assertEqual(bytes(mem.ram[0x4000:0x4000 + len(self.e["stage"])]), self.e["stage"])
        self.assertEqual(mem.ram[0xC8] & 0x40, 0x40, "the music is there")
        self.assertEqual(mem.ram[0x79], 0x80, "and on")
        self.assertEqual(mem.ram[0x0314] | mem.ram[0x0315] << 8, s["kirq"])
        self.assertEqual(bytes(mem.ram[0x038C:0x0392]),
                         bytes([0x78, 0x20, s["airq"] & 0xFF, s["airq"] >> 8, 0xEA, 0xEA]))
        self.assertEqual((mem.bank, mem.control, mem.p01), (BANK, u5.EF_OFF, 0x26))
        self.assertEqual(cart.log, [], "nothing read from the tapecart")

    def test_the_songs_play_as_the_player_plays_them(self):
        mem, sim, cart = self.machine()
        self.boot(mem, sim)
        pattern = bytes((i * 37 + 11) & 0xFF for i in range(0x4000))
        mem.ram[0x8000:0xC000] = pattern               # the game's mode roots, overlays
        got, k = [], 0
        for song in SEQUENCE:
            self.play(mem, sim, song)
            mem.sid = []
            for _ in range(TICKS):
                self.tick(mem, sim, k)
                k += 1
            got += mem.sid
            self.assertEqual((mem.control, mem.p01), (u5.EF_OFF, 0x26))
        self.assertEqual(bytes(mem.ram[0x8000:0xC000]), pattern,
                         "the C64's RAM under the cart's window is untouched")
        self.assertEqual(cart.log, [], "nothing loaded: every song is in the bank")
        self.assertGreater(len(self.want), 1000, "the original played")
        self.assertEqual(len(got), len(self.want))
        self.assertEqual(got, self.want)

    def test_a_song_that_selects_itself_loops(self):
        song, ticks = 3, 4000
        want = original(self.m, [song], 50, song, ticks)
        mem, sim, cart = self.machine()
        self.boot(mem, sim)
        self.play(mem, sim, song)
        mem.sid = []
        for k in range(50 + ticks):
            self.tick(mem, sim, k)
        self.assertEqual(mem.sid, want)
        gates = [(t, a, v) for t, a, v in want if a in (0xD404, 0xD40B, 0xD412) and v & 1]
        self.assertGreater(gates[-1][0], 50 + ticks - 400, "the song did not start over")

    def test_the_player_goes_on_to_the_selected_song(self):
        seq, walk_to, ticks = [1, 5, 11, 13, 7, 3], 6, 2600
        want = original(self.m, seq, 50, walk_to, ticks)
        mem, sim, cart = self.machine()
        self.boot(mem, sim)
        got, k = [], 0
        for song in seq:
            self.play(mem, sim, song)
            mem.sid = []
            for _ in range(50):
                self.tick(mem, sim, k)
                k += 1
            got += mem.sid
        mem.ram[0x03CD] = walk_to
        mem.sid = []
        for _ in range(ticks):
            self.tick(mem, sim, k)
            k += 1
        got += mem.sid
        self.assertEqual(mem.ram[0x03CE], walk_to)
        self.assertEqual(got, want)

    def test_the_play_entry_returns_without_ticks(self):
        for current, song in ((5, 0), (5, 3), (2, 7), (9, 9)):
            with self.subTest(current=current, song=song):
                mem, sim, cart = self.machine()
                self.boot(mem, sim)
                mem.ram[0x03CE] = current
                mem.ram[0x79] = 0x80
                sim.call(self.s["aplay"], x=song, limit=3_000_000)

    def test_an_interrupt_restarts_timer_b(self):
        mem, sim, cart = self.machine()
        self.boot(mem, sim)
        self.assertEqual(mem.io[0xC0F], 0x11)
        mem.io[0xC0F] = 0x08
        mem.icr = 0x01
        mem.p01 = 0x26
        sim.mpu.p |= 0x04
        sim.call(self.s["airq"])
        self.assertEqual(mem.io[0xC0F], 0x01)

    IRQ_STUB = 0x0400

    def test_an_interrupt_anywhere(self):
        """An interrupt at every instruction of a play and of the driver's
        mute and unmute: the player ends up playing what was asked, unmuted,
        and the cart off."""
        mem, sim, cart = self.machine()
        self.boot(mem, sim)
        a = self.s["airq"]
        mem.ram[self.IRQ_STUB:self.IRQ_STUB + 26] = bytes([
            0x48, 0x8A, 0x48, 0x98, 0x48, 0xA5, 0x01, 0x48, 0xA9, 0x26, 0x85, 0x01, 0x58,
            0x78, 0x20, a & 0xFF, a >> 8, 0x68, 0x85, 0x01, 0x68, 0xA8, 0x68, 0xAA, 0x68, 0x40])
        sim.probes[self.IRQ_STUB] = lambda s: setattr(mem, "icr", 0x02)
        self.play(mem, sim, 3)
        for _ in range(3):
            self.tick(mem, sim)
        snap = (bytes(mem.ram), bytes(mem.efram), bytes(mem.io), mem.bank, mem.control)

        def restore():
            mem.ram[:], mem.efram[:], mem.io[:], mem.bank, mem.control = snap

        def settled(song):
            for _ in range(3):
                self.tick(mem, sim)
            mute = mem.efram[self.e["rel"]["mute"] & 0xFF]
            return mute, mem.ram[0x03CE], mem.control, mem.p01

        cases = [("play", lambda **kw: sim.call(self.s["aplay"], x=6, **kw), 6),
                 ("mute", lambda **kw: sim.call(0x0126, **kw), 3),
                 ("unmute", lambda **kw: (sim.call(0x0126), setattr(sim.mpu, "p", sim.mpu.p & ~4),
                                          sim.call(0x0129, **kw)), 3)]
        for name, run, song in cases:
            steps = []
            restore()
            sim.mpu.p &= ~0x04
            mem.ram[0x79] = 0
            run(clear=steps)
            for n in sorted(set(steps)):
                with self.subTest(name, at=n):
                    restore()
                    sim.mpu.p &= ~0x04
                    mem.ram[0x79] = 0
                    run(irq_at=n, irq_to=self.IRQ_STUB)
                    mem.ram[0x79] = 0x80
                    if name == "mute":
                        sim.mpu.p &= ~0x04
                        sim.call(0x0129)
                    self.assertEqual(settled(song), (0, song, u5.EF_OFF, 0x26))

    # ---- the driver's reads ----------------------------------------------------
    RAW_AT, ZX_AT = 0x180000, 0x181000

    def reads(self, sprites):
        from ultima.flash import zx
        flash = bytearray(self.flash)
        raw = bytes((i * 73 + (i >> 5)) & 0xFF for i in range(700))
        plain = bytes(b"BRITANNIA " * 200 + bytes(range(256)) * 3)
        packed = zx.crunch(plain)
        flash[self.RAW_AT:self.RAW_AT + len(raw)] = raw
        flash[self.ZX_AT:self.ZX_AT + len(packed)] = packed
        mem, sim, cart = self.machine(bytes(flash))
        s = self.sym
        mem.ram[0x00] = 0x2F
        A.init_tc(mem, sim)
        for _a, _n, dest, data in self.e["segs"]:       # (init_tc put the stub at $0200)
            if dest == 0x0200:
                mem.ram[dest:dest + len(data)] = data
        self.boot(mem, sim)
        mem.io[0x15] = sprites
        cmds, used = [], []
        send, get = sim.traps[s["tc_sendbyte"]], sim.traps[s["tc_getbyte"]]

        def spy_send(sim):
            if cart.cmd is None and sim.mpu.a in (0x10, 0x11):
                cmds.append(sim.mpu.a)
            send(sim)

        def slow(sim):
            used.append(("1-bit", mem.p01 & 7, mem.control))
            get(sim)

        def fast(sim):
            used.append(("2-bit", mem.p01 & 7, mem.control))
            get(sim)
        sim.traps[s["tc_sendbyte"]] = spy_send
        sim.traps[s["tc_getbyte"]] = slow
        sim.traps[self.s["tc_getbyte_guard"]] = fast
        efram = bytes(mem.efram)
        for addr, length, dest, crunched, want in (
                (self.RAW_AT, len(raw), 0x4000, False, raw),
                (self.ZX_AT, len(packed), 0x5000, True, plain),
                (self.RAW_AT, len(raw), 0x8800, False, raw),
                (self.RAW_AT, len(raw), 0xA800, False, raw)):
            cmds.clear(), used.clear()
            mem.ram[s["tc_addr"]:s["tc_addr"] + 3] = [addr & 0xFF, addr >> 8 & 0xFF, addr >> 16]
            mem.ram[s["tc_len"]:s["tc_len"] + 2] = [length & 0xFF, length >> 8]
            mem.ram[s["tc_dest"]:s["tc_dest"] + 2] = [dest & 0xFF, dest >> 8]
            mem.ram[s["u5_flags"]] = 0x02 if crunched else 0x00
            mem.p01 = 0x26
            sim.call(s["u5_fetch"])
            self.assertEqual(bytes(mem.ram[dest:dest + len(want)]), want, (dest, crunched))
            fast_ = not sprites
            self.assertEqual(cmds, [0x11 if fast_ else 0x10])
            self.assertEqual({u[0] for u in used}, {"2-bit" if fast_ else "1-bit"})
            # every byte: ROML, I/O and the KERNAL in, the cart in 16K mode;
            # or tclib's all-RAM banking with the cart off
            self.assertEqual({u[1:] for u in used}, {(7, u5.EF_ON)} if fast_ else {(0, u5.EF_OFF)})
            self.assertEqual((mem.p01, mem.control, mem.bank), (0x26, u5.EF_OFF, BANK))
        self.assertEqual(bytes(mem.efram), efram, "the player's state is left alone")

    def test_2_bit_through_the_easyflash(self):
        self.reads(0x00)

    def test_1_bit_with_a_sprite_on(self):
        self.reads(0x01)


if __name__ == "__main__":
    unittest.main()
