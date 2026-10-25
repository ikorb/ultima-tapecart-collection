"""A Commodore REU (1700/1764/1750) at $DF00, for py65: the registers and the
DMA, just enough for u6reu.s and u6wc.s -- stash, fetch, verify (stopping
at the first byte that differs, status bit 5 set; the status register
clears bits 5-7 when read, as the 8726 does), the C64's address fixed
($DF0A bit 7), executed at once (command bit 4 set) or at the next write to
$FF00 (bit 4 clear).  The DMA goes through the C64's banking as on the
machine: with I/O in, $D000-$DFFF are the chips -- a fetch there writes no
RAM, a stash reads the chips (`IO_NOISE` here) -- so a driver that moves the
RAM under I/O with I/O in gets wrong data, as on real hardware.  Plus what goes wrong with
other hardware: `kind` = "reu" (the real thing), "ar" (an Action Replay's
RAM at $DF00: the registers hold what is written, nothing moves) or "none"
(an open bus).  The registers answer only with I/O banked in ($01 & 7 in 5,
6, 7), as on the machine; otherwise $DF00 is RAM (u6bulk's code is there at
times), and a driver that forgets to bank I/O in gets no DMA and wrong data;
a register written with I/O in leaves the RAM under it as it was, as on the
machine (part B of u6wc.s has code under $DF01-$DF08 in the $DC00 half).
"""
import random

from py65.memory import ObservableMemory

REGS = range(0xDF00, 0xDF0B)
IO_NOISE = 0x5C                                    # what a stash reads from the chips


class REU:
    def __init__(self, sim, kind="reu", kb=512, seed=1, verify_works=True, strict_io=True):
        """kb: 128-512 a Commodore one (a 3-bit bank register), up to 16384
        a clone's (8 bits); verify_works=False: a verify never reports a
        difference (what the launcher's and the game's self-tests are for);
        strict_io=False: reads of $D800-$DFFF with I/O in allowed (the
        launcher's page runs with the KERNAL, I/O in, all the time)."""
        self.strict_io = strict_io
        self.kind, self.size = kind, kb * 1024
        self.banks = 7 if kb <= 512 else 0xFF
        self.verify_works = verify_works
        rng = random.Random(seed)
        self.ram = bytearray(rng.randrange(256) for _ in range(self.size))   # DRAM at power-on: noise
        self.regs = [0] * 11
        self.status = 0
        self.verifies = []                         # (c64, reu, length, the same?) per verify
        self.log = []                              # (command, c64, reu, length) per transfer
        self.bus = 0xDF
        subject = list(sim.mpu.memory)
        self.mem = ObservableMemory(subject=subject)
        self.mem.subscribe_to_write(REGS, self.write)
        self.mem.subscribe_to_read(REGS, self.read)
        # the rest of $D800-$DFFF -- colour RAM, the CIAs, the I/O areas --
        # with I/O in is not RAM: the on-demand code lives there, and must not
        # run (or be read) while the I/O is banked in
        self.mem.subscribe_to_read([a for a in range(0xD800, 0xE000) if a not in REGS], self.io_read)
        self.mem.subscribe_to_write([0xFF00], self.ff00)
        self.armed = None
        self.io_hits = 0                           # bytes a DMA moved to or from the chips
        sim.mpu.memory = self.mem
        sim.mem = self.mem
        self.sim = sim

    def visible(self):
        return self.mem._subject[1] & 7 in (5, 6, 7)

    def read(self, addr):
        if not self.visible():
            return None                            # RAM
        if self.kind == "none":
            return self.bus
        n = addr - 0xDF00
        if n == 0 and self.kind == "reu":
            v, self.status = self.status, self.status & 0x1F
            return v
        v = self.regs[n]
        return v | (0xFF ^ self.banks) if n == 6 and self.kind == "reu" else v

    def io_read(self, addr):
        if self.visible() and self.strict_io:
            raise AssertionError(f"${addr:04X} read with the I/O banked in: it is I/O, not RAM")
        return None

    def write(self, addr, value):
        if not self.visible():
            return None                            # RAM: the bulk code lives there
        n = addr - 0xDF00
        keep = self.mem._subject[addr]             # a write to I/O leaves the RAM
        if self.kind == "none":                    # under it alone (py65 would store
            return keep                            # whatever this returns there)
        self.regs[n] = value
        if n == 1 and self.kind == "reu" and value & 0x80:
            if value & 0x10:
                self.execute(value)
            else:
                self.armed = value
        return keep

    def ff00(self, addr, value):
        if self.armed is not None:
            cmd, self.armed = self.armed, None
            self.execute(cmd)
        return None                                # and the write goes to RAM

    def execute(self, cmd):
        r = self.regs
        c64 = r[2] | r[3] << 8
        reu = r[4] | r[5] << 8 | (r[6] & self.banks) << 16
        n = (r[7] | r[8] << 8) or 0x10000
        fixed = r[10] & 0x80
        self.log.append((cmd & 3, c64, reu, n))
        ram = self.mem._subject
        io = self.visible()
        same = True
        for i in range(n):
            a = (c64 + (0 if fixed else i)) & 0xFFFF
            b = (reu + i) % self.size
            chips = io and 0xD000 <= a <= 0xDFFF
            self.io_hits += chips
            if cmd & 3 == 0:                       # stash
                self.ram[b] = IO_NOISE if chips else ram[a]
            elif cmd & 3 == 1:                     # fetch
                if not chips:
                    ram[a] = self.ram[b]
            elif cmd & 3 == 3:                     # verify: stops at a difference
                if (IO_NOISE if chips else ram[a]) != self.ram[b] and self.verify_works:
                    same = False
                    self.status |= 0x20
                    break
            else:
                raise NotImplementedError(cmd)
        if cmd & 3 == 3:
            self.verifies.append((c64, reu, n, same))
        self.status |= 0x40                        # end of block
