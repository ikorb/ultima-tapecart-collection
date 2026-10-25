"""Ultima V's music on a C64 with an Action Replay (ultima/games/u5/armusic.s).

On a model C64 with an AR (armodel.py), with the built cart behind the
driver's tclib (sim6502.FakeCart): xyzzy's hook finds the AR or leaves the
machine alone, the stage image sets the player up in the AR's RAM, and a
sequence of songs is played through the real entries -- temp.subs' play
jumps to `aplay`, the ticks come through the game's own IRQ path (`airq`)
-- with songs loaded from the cart as they are asked for and the cache
dropping them when it is full.  Every SID write the ticks make must be the
original player's (`m` at $7200 with all its songs, the same requests), and
the C64's RAM under the AR's must come out as it went in: the game's mode
roots live there.  Both models of the AR's write decoding (armodel.snoop).
"""
import os
import unittest

try:
    from ultima.sim import armodel
    from ultima.sim.sim6502 import FakeCart
    from py65.devices.mpu6502 import MPU
    from py65.memory import ObservableMemory
except ImportError:
    armodel = None

import importlib.util as _il
from pathlib import Path

_spec = _il.find_spec("ultima.games.u5.build")
u5 = _il.module_from_spec(_spec)
_spec.loader.exec_module(u5)
from ultima.flash.layout import image_from     # noqa: E402
from ultima.flash import regions                    # noqa: E402
from ultima import paths

# the order the game might ask for them in: more than fits, and back again
SEQUENCE = [3, 5, 1, 4, 3, 10, 2, 6, 7, 8, 9, 11, 12, 13, 14, 15, 5, 3]
TICKS = 150


NEXT_AT = 0xA000           # reference(): armusic.s's ar_next, after `m` ($7200-$9FA5)


def init_tc(mem, sim):
    """tclib's tc_init for the C64 driver, as its init stub has it
    (TC_INIT_ELSEWHERE): the stub put at $0200 and its tc_init called."""
    import re
    build = paths.BUILD
    stub = Path(os.path.join(build, "init_u5.bin")).read_bytes()
    mem.ram[0x0200:0x0200 + len(stub)] = stub
    sym = {m.group(1): int(m.group(2), 16) for m in
           re.finditer(r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path(os.path.join(build, "init_u5.sym")).read_text())}
    sim.call(sym["tc_init"])


def reference(m):
    """`m` with armusic.py's one change, as armusic.s's ar_next makes it:
    at a song's end, the same song again starts over at once (as the
    original), another a tick later.  (The routine goes at NEXT_AT, which
    original() loads along with `m`.)"""
    m = bytearray(m)
    at, was = u5.armusic.NEXT_SONG
    assert bytes(m[at - 0x7200:at - 0x7200 + 3]) == was
    m[at - 0x7200:at - 0x7200 + 3] = bytes([0x4C, NEXT_AT & 0xFF, NEXT_AT >> 8])
    start = u5.armusic.START_SONG
    nxt = bytes([0xCD, 0xCE, 0x03,                       # cmp $03CE
                 0xD0, 0x03,                             # bne +3
                 0x4C, start & 0xFF, start >> 8,         # jmp START_SONG
                 0x60])                                  # rts
    assert len(m) <= NEXT_AT - 0x7200
    m = m.ljust(NEXT_AT - 0x7200, b"\x00") + nxt
    return bytes(m)


def original(m, sequence, ticks):
    """The SID writes of the unrelocated player, every song in memory."""
    mem = ObservableMemory()
    mpu = MPU(memory=mem)
    for i, v in enumerate(reference(m)):
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
    del sid[:]                  # (the init's clearing of the SID: armusic.s's
    mem[0x79] = 0x80            # happens at boot, before anything is recorded)
    k = 0
    for song in sequence:
        mem[0x03CC] = mem[0x03CD] = song
        for _ in range(ticks):
            t[0] = k
            k += 1
            call(0x73BC)
    return sid


def original_walk(m, sequence, walk_to, ticks, after):
    """original(), then $03CD set to `walk_to` and `after` more ticks."""
    mem = ObservableMemory()
    mpu = MPU(memory=mem)
    for i, v in enumerate(reference(m)):
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
    mem[0x03CD] = walk_to
    for _ in range(after):
        t[0] = k
        k += 1
        call(0x73BC)
    return sid


class EasyFlashLike(armodel.ARMem if armodel else object):
    """No AR, but 256 bytes of RAM at $DF00 whenever I/O is in, as an
    EasyFlash has whatever its mode (its ROM off here): what a look at
    $DF00 alone takes for an AR."""

    def __init__(self):
        super().__init__(present=False)
        self.df = bytearray(256)

    def __getitem__(self, a):
        if isinstance(a, int) and 0xDF00 <= a < 0xE000 and self._io():
            return self.df[a & 0xFF]
        return super().__getitem__(a)

    def __setitem__(self, a, v):
        if isinstance(a, int) and 0xDF00 <= a < 0xE000 and self._io():
            self.df[a & 0xFF] = v & 0xFF
            return
        super().__setitem__(a, v)


@unittest.skipIf(armodel is None, "py65 is not installed")
class TestARMusic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.pop("U5_SAVE_FROM", None)
        cls.p = u5.parts()
        cls.ar = cls.p["ar"]
        cls.flash = image_from(cls.p["blobs"], regions.FLASH_SIZE)
        cls.sym = u5.symbols(os.path.join(u5.BUILD, "u5drv.sym"))
        cls.m = [b for k, b in cls.p["bodies"].items() if k[0] == 1 and k[1].lower() == "m"][0]
        cls.xyzzy = [b for k, b in cls.p["bodies"].items()
                     if k[0] == 1 and k[1].lower() == "xyzzy"][0]
        cls.want = original(cls.m, SEQUENCE, TICKS)

    def machine(self, snoop=True, present=True, mem=None):
        mem = mem or armodel.ARMem(snoop=snoop, present=present)
        sim = armodel.Sim(mem)
        cart = FakeCart(self.flash)
        sim.traps[self.sym["tc_sendbyte"]] = lambda s: cart.send(s.mpu.a)

        def get(s):
            s.mpu.a = cart.get()
            s.mpu.p = (s.mpu.p & ~0x82) | (0x80 if s.mpu.a & 0x80 else 0) | (0 if s.mpu.a else 2)
        sim.traps[self.sym["tc_getbyte"]] = get
        sim.traps[0xFF9F] = lambda s: None              # SCNKEY
        # what is in RAM when xyzzy's hook runs: the driver and temp.subs,
        # xyzzy with the $0380 handler it has copied down
        for name, at in (("u5siz.o", u5.FAST_ADDR), ("temp.subs", u5.SUBS_ADDR)):
            body = [b for k, b in self.p["bodies"].items() if k[0] == 1 and k[1].lower() == name][0]
            mem.ram[at:at + len(body)] = body
        mem.ram[0x2000:0x2000 + len(self.xyzzy)] = self.xyzzy
        mem.ram[0x0380:0x03A0] = self.xyzzy[0x23B5 - 0x2000:0x23D5 - 0x2000]
        mem.ram[0x0126] = mem.ram[0x0129] = 0x60
        mem.port = 0x26
        return mem, sim, cart

    def quiet_loads(self, mem, sim):
        """Leave out the SID writes a load's mute makes (the voices gated
        off while the cart holds the machine): not the player's music."""
        s, mark = self.ar["ssym"], [None]

        def start(sim):
            mark[0] = len(mem.sid)

        def done(sim):
            del mem.sid[mark[0]:]
        sim.probes[s["AR_J_MUTE"] if "AR_J_MUTE" in s else u5.AR_BASE + 6] = start
        sim.probes[s["es_muted"]] = done

    def boot(self, mem, sim):
        """xyzzy's hook, up to $20D5 where xyzzy goes on."""
        sim.traps[0x20D5] = lambda s: None
        sim.call(0x2090)

    def test_no_ar_no_change(self):
        mem, sim, cart = self.machine(present=False)
        before = bytes(mem.ram)
        self.boot(mem, sim)
        after = bytearray(mem.ram)
        after[0x1FE:0x200] = before[0x1FE:0x200]       # (the harness's own JSR)
        self.assertEqual(bytes(after), before, "a C64 without the AR: nothing touched")
        self.assertEqual(cart.log, [], "and nothing read from the cart")
        self.assertEqual(mem.port, 0x26, "$01 as it was")

    def test_an_easyflash_is_no_ar(self):
        """RAM at $DF00 that is not the AR's (an EasyFlash's): nothing touched,
        nothing read -- whatever the C64's byte at $9FFF, it cannot follow
        both values stored at $DFFF."""
        for fill in (0x00, 0x5A, 0xA5, 0xFF):
            with self.subTest(fill=hex(fill)):
                mem, sim, cart = self.machine(mem=EasyFlashLike())
                mem.ram[0x9FFF] = fill
                before = bytes(mem.ram)
                self.boot(mem, sim)
                after = bytearray(mem.ram)
                after[0x1FE:0x200] = before[0x1FE:0x200]   # (the harness's own JSR)
                self.assertEqual(bytes(after), before)
                self.assertEqual(cart.log, [], "no stage read: no AR")
                self.assertEqual(mem.port, 0x26)
                self.assertEqual(mem.ram[0xC8] & 0x40, 0)

    def test_the_songs_play_as_the_player_plays_them(self):
        for snoop in (True, False):
            with self.subTest(snoop=snoop):
                self.play(snoop)

    def play(self, snoop):
        mem, sim, cart = self.machine(snoop=snoop)
        self.boot(mem, sim)
        s = self.ar["ssym"]
        self.assertEqual(mem.ram[0xC8] & 0x40, 0x40, "the music is there")
        self.assertEqual(mem.ram[0x79], 0x80, "and on")
        self.assertEqual(mem.ram[0x0314] | mem.ram[0x0315] << 8, s["kirq"])
        self.assertEqual(bytes(mem.ram[0x038C:0x0392]),
                         bytes([0x78, 0x20, s["airq"] & 0xFF, s["airq"] >> 8, 0xEA, 0xEA]))
        self.assertEqual(mem.reg, u5.AR_OFF, "the AR's RAM off outside the glue")
        # the game's mode roots under the AR's RAM
        pattern = bytes((i * 37 + 11) & 0xFF for i in range(0x2000))
        mem.ram[0x8000:0xA000] = pattern
        got, k, loads = [], 0, 0
        asked = []                                  # the song, when the mute comes off

        def unmute(sim):
            asked.append((sim.mem.ram[0x03CC], current[0]))
        sim.probes[s["ar_rest"]] = unmute
        # a load and the mute's return happen with interrupts off: the IRQ's
        # own would change `need` in between (the player then stayed muted)
        irqs_on = []
        for name in ("ensure", "settle"):
            sim.probes[s[name]] = lambda sim, n=name: irqs_on.append(n) if not sim.mpu.p & 4 else None
        current = [0]
        for song in SEQUENCE:
            current[0] = song
            n = len(cart.log)
            mem.ram[0x79] = 0                           # (no spin: nothing ticks)
            sim.call(s["aplay"], x=song)
            mem.ram[0x79] = 0x80
            loads += any(e[0] == "read" for e in cart.log[n:])
            mem.sid = []
            for _ in range(TICKS):
                mem.tick = k
                k += 1
                mem.icr = 0x02                          # timer B
                sim.mpu.p |= 0x04                       # (an interrupt: I set)
                mem.port = 0x26                         # as the handler's $6C03 left it
                sim.call(s["airq"])
            got += mem.sid
            self.assertEqual(mem.reg, u5.AR_OFF)
            self.assertEqual(mem.port, 0x26, "$01 as it was")
        self.assertEqual(bytes(mem.ram[0x8000:0xA000]), pattern,
                         "the C64's RAM under the AR's is untouched")
        self.assertGreater(loads, 15, "the cache dropped songs and loaded them again")
        self.assertLess(loads, len(SEQUENCE), "and kept some")
        self.assertEqual(irqs_on, [], "ensure or settle with interrupts on")
        self.assertEqual(len(asked), loads)
        self.assertTrue(all(req == song for req, song in asked),
                        "the mute comes off only once the player is asked for the new song")
        self.assertEqual(len(got), len(self.want))
        self.assertEqual(got, self.want)

    def test_a_song_that_selects_itself_loops(self):
        """The title's second song: $03CD is the song playing, so at its end
        it starts over at once, as the original's -- it did not, when the
        end of a song was only an RTS, and the title went quiet."""
        song, ticks = 3, 4000
        want = original_walk(self.m, [song], song, 50, ticks)
        mem, sim, cart = self.machine()
        self.boot(mem, sim)
        s = self.ar["ssym"]
        mem.ram[0x79] = 0
        sim.call(s["aplay"], x=song)
        mem.ram[0x79] = 0x80
        mem.sid = []
        for k in range(50 + ticks):
            mem.tick = k
            mem.icr = 0x02
            mem.port = 0x26
            sim.mpu.p |= 0x04
            sim.call(s["airq"])
        self.assertEqual(mem.sid, want)
        self.assertEqual(mem.ram[0x03CE], song)
        gates = [(t, a, v) for t, a, v in want if a in (0xD404, 0xD40B, 0xD412) and v & 1]
        self.assertGreater(gates[-1][0], 50 + ticks - 400, "the song did not start over")

    def test_the_play_entry_returns_without_ticks(self):
        """aplay waits for the player to take the song up, but gives up: with
        no tick coming (a stopped timer, or interrupts off) it must return,
        whichever way round $03CE and the song compare.  (It spun for ever
        when $03CE was the higher: the carry of its CPX made the countdown
        step 2 from $FF.)"""
        s = self.ar["ssym"]
        for current, song in ((5, 0), (5, 3), (2, 7), (9, 9)):
            with self.subTest(current=current, song=song):
                mem, sim, cart = self.machine()
                self.boot(mem, sim)
                mem.ram[0x03CE] = current
                mem.ram[0x79] = 0x80
                sim.call(s["aplay"], x=song, limit=3_000_000)

    def test_an_interrupt_restarts_timer_b(self):
        """The KERNAL's serial routines -- startup's drive check at the main
        menu -- leave CIA 1's timer B one-shot and stopped ($DC0F = $08); the
        next interrupt, timer A's, has it running again, continuous."""
        mem, sim, cart = self.machine()
        self.boot(mem, sim)
        self.assertEqual(mem.io[0xC0F], 0x11, "arinit: loaded and running")
        mem.io[0xC0F] = 0x08
        mem.icr = 0x01                              # timer A
        mem.port = 0x26
        sim.mpu.p |= 0x04
        sim.call(self.ar["ssym"]["airq"])
        self.assertEqual(mem.io[0xC0F], 0x01)

    def test_journey_onward_leaves_the_glue_alone(self):
        """enter.play puts the C64's disk-load hooks (sprites off) at $0126
        when it runs on a C64 with the stock KERNAL's LOAD vector -- over the
        glue's music API and ar_call.  Its gate, as the build stores it, skips
        that where the music is ($C8 bit 6); the original's does not."""
        body = [b for k, b in self.p["bodies"].items()
                if k[0] == 1 and k[1].lower() == "enter.play"][0]
        orig = bytearray(body)
        at = 0x802A - 0x8000
        self.assertEqual(bytes(body[at:at + 3]), bytes([0x24, 0xC8, 0x70]))
        orig[at:at + 3] = bytes([0xA5, 0xC8, 0x30])
        for code, intact in ((body, True), (orig, False)):
            with self.subTest(patched=intact):
                mem, sim, cart = self.machine()
                self.boot(mem, sim)
                glue = bytes(mem.ram[0x0100:0x0174])
                mem.ram[0x8000:0x8000 + len(code)] = code
                mem.ram[0x0330:0x0332] = [0xA5, 0xF4]       # the KERNAL's LOAD
                mem.ram[0xE486] = 0x00
                mem.port = 0x26
                sim.traps[0x8047] = lambda s: None          # past the copy
                sim.call(0x802A)
                self.assertEqual(bytes(mem.ram[0x0100:0x0174]) == glue, intact)

    def test_the_player_goes_on_to_the_selected_song(self):
        """The title walk and the ending only set $03CD; the player starts it
        itself when the current song ends.  So it has to be in before then:
        the IRQ loads it -- here with the cache full, which drops every song
        but the one playing and puts the new one beside it -- and the switch
        sounds as the original's."""
        seq, walk_to, ticks = [1, 5, 11, 13, 7, 3], 6, 2600
        want = original_walk(self.m, seq, walk_to, 50, ticks)
        for snoop in (True, False):
            with self.subTest(snoop=snoop):
                mem, sim, cart = self.machine(snoop=snoop)
                self.boot(mem, sim)
                self.quiet_loads(mem, sim)
                s = self.ar["ssym"]
                got, k = [], 0

                def tick():
                    nonlocal k
                    mem.tick = k
                    k += 1
                    mem.icr = 0x02
                    mem.port = 0x26
                    sim.mpu.p |= 0x04
                    sim.call(s["airq"])
                for song in seq:
                    mem.ram[0x79] = 0
                    sim.call(s["aplay"], x=song)
                    mem.ram[0x79] = 0x80
                    mem.sid = []
                    for _ in range(50):
                        tick()
                    got += mem.sid
                mem.ram[0x03CD] = walk_to              # as startup's walk does
                mem.sid = []
                for _ in range(ticks):
                    tick()
                got += mem.sid
                self.assertEqual(mem.ram[0x03CE], walk_to, "the player went on to it")
                self.assertEqual(got, want)

    # the game's IRQ handler, as far as it matters: $01 as its $6C03 leaves
    # it, the glue, $01 back, RTI -- with timer B the source
    IRQ_STUB = 0x0400

    def irq_stub(self, mem, sim):
        s = self.ar["ssym"]["airq"]
        # (with the CLI in its $6C03: the glue runs with interrupts enabled)
        # and the SEI arinit puts in front of the JSR to airq
        mem.ram[self.IRQ_STUB:self.IRQ_STUB + 26] = bytes([
            0x48, 0x8A, 0x48, 0x98, 0x48, 0xA5, 0x01, 0x48, 0xA9, 0x26, 0x85, 0x01, 0x58,
            0x78, 0x20, s & 0xFF, s >> 8, 0x68, 0x85, 0x01, 0x68, 0xA8, 0x68, 0xAA, 0x68, 0x40])

        def source(sim):
            mem.icr = 0x02
        sim.probes[self.IRQ_STUB] = source
        # irq_entry: PHP / JMP stub -- its RTI then returns to our caller
        # (the JSR's return address is on the stack, below the pushed P, and
        # RTI takes P, then the address -- +1 is wrong for RTI, so push the
        # address minus nothing: a JSR pushes ret-1, RTI wants ret; fix up)
        e = self.IRQ_STUB + 0x40
        mem.ram[e:e + 15] = bytes([
            0x68, 0x18, 0x69, 0x01, 0xA8,        # PLA / CLC / ADC #1 / TAY (lo + 1)
            0x68, 0x69, 0x00, 0x48,              # PLA / ADC #0 / PHA        (hi)
            0x98, 0x48,                          # TYA / PHA                 (lo)
            0x08,                                # PHP
            0x4C]) + bytes([self.IRQ_STUB & 0xFF, self.IRQ_STUB >> 8])

    @property
    def irq_entry(self):
        """A subroutine that enters the stub as an interrupt would: it pushes
        a return frame for its RTI (irq_stub puts it there)."""
        return self.IRQ_STUB + 0x40

    def settled(self, mem, sim, song):
        """A few ticks on: the player plays `song`, unmuted."""
        assert len(mem.ram) == 0x10000, "the model's RAM changed size"
        for _ in range(3):
            mem.icr = 0x02
            mem.port = 0x26
            sim.mpu.p |= 0x04
            sim.call(self.ar["ssym"]["airq"])
        mem.reg = u5.AR_ON
        mem.port = 0x27
        mute = mem[self.ar["rel"]["mute"]]
        mem.reg, mem.port = u5.AR_OFF, 0x26
        return mute, mem.ram[0x03CE]

    def snapshot(self, mem, cart):
        return (bytes(mem.ram), bytes(mem.ar), bytes(mem.io), mem.reg, mem.port,
                bytes(cart.flash), list(cart.out))

    def restore(self, mem, cart, snap):
        mem.ram[:], mem.ar[:], mem.io[:], mem.reg, mem.port, flash, out = snap
        cart.flash[:] = flash
        cart.out[:] = out
        cart.cmd = None

    def test_an_interrupt_anywhere(self):
        """An interrupt at every instruction where one can happen -- in the
        driver's mute/unmute around a load, and in a play that loads -- and
        the player always ends up playing what was asked, unmuted.  (Once
        it did not: ar_call set its operand before its SEI, so an interrupt
        there made the game's unmute call the tick instead.)"""
        mem, sim, cart = self.machine()
        self.boot(mem, sim)
        self.irq_stub(mem, sim)
        s = self.ar["ssym"]
        mem.ram[0x79] = 0
        sim.call(s["aplay"], x=3)
        mem.ram[0x79] = 0x80
        self.assertEqual(self.settled(mem, sim, 3), (0, 3))
        base = self.snapshot(mem, cart)
        # the driver's bracket: $0126 ... $0129
        for entry in (0x0126, 0x0129):
            steps = []
            self.restore(mem, cart, base)
            sim.mpu.p &= ~0x04
            if entry == 0x0129:
                sim.call(0x0126)
                sim.mpu.p &= ~0x04
            sim.call(entry, clear=steps)
            for n in sorted(set(steps)):
                with self.subTest(entry=hex(entry), at=n):
                    self.restore(mem, cart, base)
                    sim.mpu.p &= ~0x04
                    if entry == 0x0126:
                        sim.call(0x0126, irq_at=n, irq_to=self.IRQ_STUB)
                        sim.mpu.p &= ~0x04
                        sim.call(0x0129)
                    else:
                        sim.call(0x0126)
                        sim.mpu.p &= ~0x04
                        sim.call(0x0129, irq_at=n, irq_to=self.IRQ_STUB)
                    self.assertEqual(self.settled(mem, sim, 3), (0, 3))
        # a load from the IRQ itself -- at a song's end the player asks for
        # the next song ($03CC) and the next interrupt loads it -- with a
        # second interrupt at every point where one can get in
        steps = []
        self.restore(mem, cart, base)
        mem.ram[0x03CC] = 6
        sim.mpu.p |= 0x04
        sim.call(self.irq_entry, clear=steps)
        for n in sorted(set(steps)):
            with self.subTest(irq_load=6, at=n):
                self.restore(mem, cart, base)
                mem.ram[0x03CC] = 6
                sim.mpu.p |= 0x04
                sim.call(self.irq_entry, irq_at=n, irq_to=self.IRQ_STUB)
                self.assertEqual(self.settled(mem, sim, 6), (0, 6))
        # a play that loads
        steps = []
        self.restore(mem, cart, base)
        sim.mpu.p &= ~0x04
        mem.ram[0x79] = 0
        sim.call(s["aplay"], x=6, clear=steps)
        for n in sorted(set(steps)):
            with self.subTest(play=6, at=n):
                self.restore(mem, cart, base)
                sim.mpu.p &= ~0x04
                mem.ram[0x79] = 0
                sim.call(s["aplay"], x=6, irq_at=n, irq_to=self.IRQ_STUB)
                mem.ram[0x79] = 0x80
                self.assertEqual(self.settled(mem, sim, 6), (0, 6))

    def test_restart_reloads_a_dropped_song(self):
        mem, sim, cart = self.machine()
        self.boot(mem, sim)
        s = self.ar["ssym"]
        mem.ram[0x79] = 0
        for song in (1, 5, 11, 13, 7, 3, 6):            # 6 does not fit: all dropped
            sim.call(s["aplay"], x=song)
        mem.ram[0x03CD] = 1
        n = len(cart.log)
        sim.call(s["arestart"], x=0x42, y=0x24)
        self.assertEqual((sim.mpu.x, sim.mpu.y), (0x42, 0x24), "X and Y kept")
        self.assertEqual(mem.ram[0x03CC], 1)
        self.assertTrue(any(e[0] == "read" for e in cart.log[n:]), "song 1 loaded again")
        n = len(cart.log)
        sim.call(s["arestart"])
        self.assertFalse(any(e[0] == "read" for e in cart.log[n:]), "and not again")


@unittest.skipIf(armodel is None, "py65 is not installed (use the repository's .venv)")
class TestARReads(unittest.TestCase):
    """The driver's reads with an AR (u5drv.s tc_host_pick, u5_arget; the
    AR's ar_pick and its copy of tcguard.s): 2-bit through the AR's RAM
    while no sprite is on, 1-bit as before with one on or without an AR --
    the command and the receive always matching.  The receive itself is
    trapped here (tests/test_tc_guard.py runs it, cycle by cycle and bit by
    bit); what this checks is everything around it: the banking and the
    AR's register at every byte, raw and crunched units, a load into
    $8000-$9FFF under the AR's RAM, which must reach the C64's RAM and leave
    the AR's alone, and both models of the AR's write decoding."""

    RAW_AT, ZX_AT = 0x180000, 0x181000
    setUpClass = classmethod(TestARMusic.setUpClass.__func__)
    machine = TestARMusic.machine
    boot = TestARMusic.boot

    def setUp(self):
        from ultima.flash import zx
        flash = bytearray(self.flash)
        self.raw = bytes((i * 73 + (i >> 5)) & 0xFF for i in range(700))
        self.plain = bytes(b"BRITANNIA " * 200 + bytes(range(256)) * 3)
        self.zx = zx.crunch(self.plain)
        flash[self.RAW_AT:self.RAW_AT + len(self.raw)] = self.raw
        flash[self.ZX_AT:self.ZX_AT + len(self.zx)] = self.zx
        self.flash_copy = bytes(flash)

    def reads(self, snoop=True, present=True):
        saved, self.flash = self.flash, self.flash_copy
        try:
            mem, sim, cart = self.machine(snoop=snoop, present=present)
        finally:
            self.flash = saved
        s, a = self.sym, self.ar["ssym"]
        mem.ram[0x00] = 0x2F
        init_tc(mem, sim)
        if present:
            self.boot(mem, sim)
            self.assertTrue(mem.ram[0xC8] & 0x40, "arinit says the AR's music is there")
        cmds, used = [], []
        send, get = sim.traps[s["tc_sendbyte"]], sim.traps[s["tc_getbyte"]]

        def spy_send(sim):
            if cart.cmd is None and sim.mpu.a in (0x10, 0x11):
                cmds.append(sim.mpu.a)
            send(sim)

        def slow(sim):
            used.append(("1-bit", mem.port & 7, mem.reg & 0x20))
            get(sim)

        def fast(sim):
            used.append(("2-bit", mem.port & 7, mem.reg & 0x20))
            get(sim)
        sim.traps[s["tc_sendbyte"]] = spy_send
        sim.traps[s["tc_getbyte"]] = slow
        if present:
            sim.traps[a["tc_getbyte_guard"]] = fast
        return mem, sim, cmds, used

    def fetch(self, mem, sim, addr, length, dest, crunched):
        s = self.sym
        mem.ram[s["tc_addr"]:s["tc_addr"] + 3] = [addr & 0xFF, addr >> 8 & 0xFF, addr >> 16]
        mem.ram[s["tc_len"]:s["tc_len"] + 2] = [length & 0xFF, length >> 8]
        mem.ram[s["tc_dest"]:s["tc_dest"] + 2] = [dest & 0xFF, dest >> 8]
        mem.ram[s["u5_flags"]] = 0x02 if crunched else 0x00
        mem.port = 0x26
        sim.call(s["u5_fetch"])

    def check(self, snoop, present, sprites):
        mem, sim, cmds, used = self.reads(snoop, present)
        mem.io[0x15] = sprites
        ar_before = bytes(mem.ar)
        for addr, length, dest, crunched, want in (
                (self.RAW_AT, len(self.raw), 0x4000, False, self.raw),
                (self.ZX_AT, len(self.zx), 0x5000, True, self.plain),
                (self.RAW_AT, len(self.raw), 0x8800, False, self.raw)):
            cmds.clear(), used.clear()
            self.fetch(mem, sim, addr, length, dest, crunched)
            self.assertEqual(bytes(mem.ram[dest:dest + len(want)]), want, (dest, crunched))
            fast = present and not sprites
            self.assertEqual(cmds, [0x11 if fast else 0x10])
            self.assertEqual({u[0] for u in used}, {"2-bit" if fast else "1-bit"})
            if fast:        # every byte: ROML, I/O and KERNAL in, the AR's RAM on
                self.assertEqual({u[1:] for u in used}, {(7, 0x20)})
            else:           # tclib's all-RAM banking, the AR's RAM off
                self.assertEqual({u[1:] for u in used}, {(0, 0)})
            self.assertEqual(mem.port, 0x26, "the caller's $01 back")
            if present:
                self.assertEqual(mem.reg, 0x0A, "the AR off again")
        if present:
            self.assertEqual(bytes(mem.ar[:0x1F00]), ar_before[:0x1F00],
                             "a load under the AR's RAM leaves it alone")

    def test_2_bit_through_the_ar(self):
        for snoop in (True, False):
            with self.subTest(snoop=snoop):
                self.check(snoop, True, 0x00)

    def test_1_bit_with_a_sprite_on(self):
        self.check(True, True, 0x01)

    def test_1_bit_without_an_ar(self):
        self.check(True, False, 0x00)

    def test_the_drivers_jumps_are_the_ars(self):
        a = self.ar["ssym"]
        for name in ("AR_J_GET", "AR_J_PICK"):
            self.assertEqual(self.sym[name], a[name])
        self.assertEqual(self.ar["stage"][self.ar["ssym"]["ar_block"] - u5.AR_STAGE + a["AR_J_GET"] - u5.AR_BASE],
                         0x4C)


if __name__ == "__main__":
    unittest.main()
