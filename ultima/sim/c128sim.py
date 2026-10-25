#!/usr/bin/env python3
"""A C128 in C128 mode, as far as Ultima V's C128 code needs one, for py65.

The MMU's configuration register ($FF00, and $D500 with I/O in) picks the RAM
bank and what is ROM or I/O over it; the RAM configuration register ($D506)
makes the bottom and/or top of memory common -- always bank 0.  Writes to a
ROM area go to the RAM under it.  The VDC is its 16 KiB of RAM behind the
address/data register pair $D600/$D601, registers 18/19 (address) and 31
(data, stepping the address).  The KERNAL's FETCH/STASH/CMPARE trampolines
are copied into RAM at $02A2 from the ROM ($F800), as the KERNAL does at reset.

    mem = C128Mem()
    sim = C128Sim(mem)
    sim.call(0x7700)          # JSR, until it returns (or reaches a stop)
"""
from pathlib import Path

from py65.devices.mpu6502 import MPU

from ultima.sim import roms

KERNAL = "kernal-318020-05.bin"      # $C000-$FFFF, the editor at $C000 (VICE's: roms.py)


def kernal_path():
    return roms.find("C128", KERNAL, "x128")
DONE = 0xFFF9                        # where call() returns to: no routine starts there


class C128Mem:
    def __init__(self, kernal=None):
        self.ram = [bytearray(0x10000), bytearray(0x10000)]
        self.io = bytearray(0x1000)
        self.cr = 0x00                  # bank 15 after reset
        self.rcr = 0x04                 # 1 KiB common at the bottom
        self.vdc = bytearray(0x4000)
        self.vreg = 0
        self.vaddr = 0
        if kernal is None:
            path = kernal_path()
            kernal = Path(path).read_bytes() if path else None
        self.kernal = kernal
        self._remap()
        self.trampolines()

    def trampolines(self):
        """FETCH, STASH, CMPARE: $F800.. in the ROM, $02A2.. in RAM"""
        if self.kernal:
            self.ram[0][0x02A2:0x02CD] = self.kernal[0xF800 - 0xC000:0xF82B - 0xC000]

    # -- where an address goes: a table of pages, rebuilt on a change -----
    RAM0, RAM1, ROM, IO, MMU = 0, 1, 2, 3, 4

    def _remap(self):
        cr, rcr = self.cr, self.rcr
        size = (0x4, 0x10, 0x20, 0x40)[rcr & 3]           # pages
        kinds = []
        for pg in range(256):
            a = pg << 8
            if (rcr & 4 and pg < size) or (rcr & 8 and pg >= 256 - size):
                bank = 0
            else:
                bank = (cr >> 6) & 1
            if 0x40 <= pg < 0x80:
                rom = not cr & 2
            elif 0x80 <= pg < 0xC0:
                rom = (cr >> 2) & 3 != 3
            elif pg >= 0xC0:
                rom = (cr >> 4) & 3 != 3
            else:
                rom = False
            if 0xD0 <= pg < 0xE0 and not cr & 1:
                kinds.append((self.IO, bank))
            elif rom:
                kinds.append((self.ROM, bank))
            else:
                kinds.append((bank, bank))
        self.kinds = kinds

    def __getitem__(self, a):
        if isinstance(a, slice):
            return [self[i] for i in range(*a.indices(0x10000))]
        kind, bank = self.kinds[a >> 8]
        if kind < 2:
            if a >= 0xFF00 and a <= 0xFF04:
                return self.cr
            return self.ram[kind][a]
        if 0xFF00 <= a <= 0xFF04:
            return self.cr
        if kind == self.IO:
            return self._io_read(a)
        if a >= 0xC000 and self.kernal:
            return self.kernal[a - 0xC000]
        return 0xEA                     # BASIC or function ROM: not modelled

    def __setitem__(self, a, v):
        if isinstance(a, slice):
            for i, b in zip(range(*a.indices(0x10000)), v):
                self[i] = b
            return
        v &= 0xFF
        if a >= 0xFF00:
            if a == 0xFF00:
                self.cr = v
                self._remap()
                return
            if a <= 0xFF04:
                return                  # the preconfigurations: not used
        kind, bank = self.kinds[a >> 8]
        if kind == self.IO:
            return self._io_write(a, v)
        self.ram[bank][a] = v

    def __len__(self):
        return 0x10000

    # -- I/O ------------------------------------------------------------------
    def _io_read(self, a):
        if a == 0xD500:
            return self.cr
        if a == 0xD506:
            return self.rcr
        if a == 0xD600:
            return 0x80                 # always ready
        if a == 0xD601:
            if self.vreg == 31:
                v = self.vdc[self.vaddr & 0x3FFF]
                self.vaddr = (self.vaddr + 1) & 0xFFFF
                return v
            if self.vreg == 18:
                return self.vaddr >> 8
            if self.vreg == 19:
                return self.vaddr & 0xFF
            return 0
        return self.io[a - 0xD000]

    def _io_write(self, a, v):
        if a == 0xD500:
            self.cr = v
            self._remap()
        elif a == 0xD506:
            self.rcr = v
            self._remap()
        elif a == 0xD600:
            self.vreg = v & 0x3F
        elif a == 0xD601:
            if self.vreg == 18:
                self.vaddr = v << 8 | (self.vaddr & 0xFF)
            elif self.vreg == 19:
                self.vaddr = (self.vaddr & 0xFF00) | v
            elif self.vreg == 31:
                self.vdc[self.vaddr & 0x3FFF] = v
                self.vaddr = (self.vaddr + 1) & 0xFFFF
        else:
            self.io[a - 0xD000] = v

    # -- helpers for tests ------------------------------------------------
    def put(self, bank, addr, data):
        self.ram[bank][addr:addr + len(data)] = bytes(data)


class C128Sim:
    """Run code against a C128Mem.  `traps`: address -> handler(sim); the
    handler runs instead of the code there and then an RTS is done.
    `stops`: addresses that end call() (a JMP into the game, say)."""
    def __init__(self, mem):
        self.mem = mem
        self.mpu = MPU(memory=mem)
        self.traps = {}
        self.stops = set()
        self.steps = 0

    def rts(self):
        m, mpu = self.mem, self.mpu
        lo = m[0x100 + ((mpu.sp + 1) & 0xFF)]
        hi = m[0x100 + ((mpu.sp + 2) & 0xFF)]
        mpu.sp = (mpu.sp + 2) & 0xFF
        mpu.pc = ((hi << 8 | lo) + 1) & 0xFFFF

    def call(self, addr, a=0, x=0, y=0, limit=20_000_000):
        """JSR addr with A/X/Y; returns the address it stopped at (DONE when
        it returned)."""
        mpu, m = self.mpu, self.mem
        mpu.sp = 0xFD
        ret = DONE - 1
        m[0x1FF] = ret >> 8
        m[0x1FE] = ret & 0xFF
        mpu.a, mpu.x, mpu.y = a, x, y
        mpu.pc = addr
        return self.go(limit)

    def go(self, limit=20_000_000):
        """Run on from where the machine is, to a stop or DONE."""
        mpu = self.mpu
        n = 0
        if mpu.pc in self.stops:          # (resuming from one)
            mpu.step()
            n = 1
        while mpu.pc != DONE and mpu.pc not in self.stops:
            h = self.traps.get(mpu.pc)
            if h is not None:
                h(self)
                self.rts()
                continue
            mpu.step()
            n += 1
            if n > limit:
                raise RuntimeError(f"no return after {limit} steps, pc=${mpu.pc:04x}")
        self.steps += n
        return mpu.pc
