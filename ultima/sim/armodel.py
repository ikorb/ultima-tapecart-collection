#!/usr/bin/env python3
"""A C64 with an Action Replay (4.2, 5, 6), as far as Ultima V's music needs
one, for py65.

$01 banks as on a C64 (LORAM, HIRAM, CHAREN); the AR's register at $DE00 is
write-only (reading it is said to crash real machines, so a read here is an
error): bits 0-1 the mode (0 = 8K game, 2 = off, 3 = Ultimax), bit 5 its
8 KiB RAM at ROML and in the I/O2 window, $DF00-$DFFF = the RAM's last page.
In 8K mode with the RAM on, ROML ($8000-$9FFF) reads the AR's RAM when LORAM
and HIRAM are both set, and a store there reaches the C64's RAM as well.

Whether the AR's RAM also takes a store to $8000-$9FFF while ROML is *not*
selected (LORAM clear) differs: VICE's model does (actionreplay_roml_store
from raml_no_ultimax_store); `snoop=False` models a card that only sees its
own ROML.  The glue must work with either, so the tests run both.

The SID's writes are recorded; $DC0D reads what `icr` says (and clears it).
"""
from py65.devices.mpu6502 import MPU

DONE = 0xFFF9


class ARMem:
    def __init__(self, snoop=True, present=True):
        self.ram = bytearray(0x10000)
        self.ar = bytearray(0x2000)
        self.io = bytearray(0x1000)
        self.reg = 0x0A                 # as the AR's fastload install leaves it
        self.present = present
        self.snoop = snoop
        self.port = 0x37
        self.sid = []
        self.tick = 0
        self.icr = 0

    def _game8k(self):
        """EXROM low: 8K game mode (or the AR's broken $22, which acts so)."""
        return self.present and (self.reg & 0x03 == 0 or self.reg & 0x23 == 0x22)

    def _io(self):
        p = self.port & 7
        return p & 4 and p & 3

    def __getitem__(self, a):
        if isinstance(a, slice):
            return [self[i] for i in range(*a.indices(0x10000))]
        if a == 1:
            return self.port
        if 0x8000 <= a < 0xA000 and self._game8k() and self.port & 3 == 3 and self.reg & 0x20:
            return self.ar[a - 0x8000]
        if 0xD000 <= a < 0xE000 and self._io():
            if a == 0xDE00 and self.present:
                raise RuntimeError("a read of the AR's $DE00")
            if 0xDF00 <= a and self.present and self.reg & 0x20:
                return self.ar[0x1F00 + (a & 0xFF)]
            if a == 0xDC0D:
                v, self.icr = self.icr, 0
                return v
            if a >= 0xDE00 and not self.present:
                return a >> 8           # open I/O1/I/O2: the bus, not what was stored
            return self.io[a - 0xD000]
        return self.ram[a]

    def __setitem__(self, a, v):
        if isinstance(a, slice):
            for i, b in zip(range(*a.indices(0x10000)), v):
                self[i] = b
            return
        v &= 0xFF
        if a == 1:
            self.port = v
            return
        if 0xD000 <= a < 0xE000 and self._io():
            if 0xDE00 <= a < 0xDF00 and self.present:
                self.reg = v
                return
            if 0xDF00 <= a and self.present and self.reg & 0x20:
                self.ar[0x1F00 + (a & 0xFF)] = v
                return
            if a >= 0xDE00 and not self.present:
                return                  # nothing there to take it
            if 0xD400 <= a < 0xD420:
                self.sid.append((self.tick, a, v))
            self.io[a - 0xD000] = v
            return
        if 0x8000 <= a < 0xA000 and self._game8k() and self.reg & 0x20:
            if self.snoop or self.port & 3 == 3:
                self.ar[a - 0x8000] = v
        self.ram[a] = v

    def __len__(self):
        return 0x10000


class Sim:
    def __init__(self, mem):
        self.mem = mem
        self.mpu = MPU(memory=mem)
        self.traps = {}
        self.probes = {}                # address -> fn(sim), run before it

    def call(self, addr, a=0, x=0, y=0, limit=5_000_000, irq_at=None, irq_to=None,
             clear=None):
        """JSR addr.  irq_at: after that many instructions, the first time
        interrupts are enabled, an interrupt: P and PC pushed, I set, on to
        irq_to (which ends in RTI).  clear: a list that gets the step numbers
        at which interrupts were enabled."""
        mpu, m = self.mpu, self.mem
        mpu.sp = 0xFD
        m.ram[0x1FF], m.ram[0x1FE] = (DONE - 1) >> 8, (DONE - 1) & 0xFF
        mpu.a, mpu.x, mpu.y, mpu.pc = a, x, y, addr
        n = 0
        while mpu.pc != DONE:
            if not mpu.p & 4:
                if clear is not None:
                    clear.append(n)
                if irq_at is not None and n >= irq_at:
                    irq_at = None
                    for v in (mpu.pc >> 8, mpu.pc & 0xFF, mpu.p & ~0x10):
                        m.ram[0x100 + mpu.sp] = v
                        mpu.sp = (mpu.sp - 1) & 0xFF
                    mpu.p |= 4
                    mpu.pc = irq_to
            p = self.probes.get(mpu.pc)
            if p is not None:
                p(self)
            h = self.traps.get(mpu.pc)
            if h is not None:
                h(self)
                lo, hi = m.ram[0x100 + ((mpu.sp + 1) & 0xFF)], m.ram[0x100 + ((mpu.sp + 2) & 0xFF)]
                mpu.sp = (mpu.sp + 2) & 0xFF
                mpu.pc = ((hi << 8 | lo) + 1) & 0xFFFF
                continue
            mpu.step()
            n += 1
            if n > limit:
                raise RuntimeError(f"no return after {limit} steps, pc=${mpu.pc:04x}")
        return n
