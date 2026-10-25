"""A C64 with an EasyFlash in the expansion port, for py65 (the U6 side
quest, ef/): enough of the machine to run the EF build's real code -- the
drivers in ROM, their RAM primitives, the init, and EAPI itself -- against
the real flash image.

  * the PLA: what $01 (LORAM, HIRAM, CHAREN) and the cartridge lines show
    at each address -- RAM, ROML/ROMH, the KERNAL/BASIC/character ROMs (as
    stand-in bytes: nothing here runs them), I/O -- and where a store goes;
  * the EasyFlash: $DE00 (bank), $DE02 (mode: Ultimax, 8K, 16K, off), 256
    bytes of RAM at $DF00, the boot jumper (Ultimax at reset);
  * two AM29F040s at the command level (reset, autoselect, program, sector
    erase), so EasyFlash's EAPI runs as on the cart -- flash can only clear
    bits, a write over unerased flash is caught, and a power cut can be
    called after any number of changes (`cut_after`, as FakeCart's);
  * or, with `eapi="contract"`, EAPI's jump table trapped and answered by
    the documented contract alone (ProgRef), which leaves the bank and
    $DE02 as a different driver might: a check that nothing relies on
    am29f040 internals -- a cart may come with an EAPI of its own.

The rest of I/O is plain storage (no VIC, no interrupts).  The ROMs read
as $EA so stray reads are visible, never as code that works.
"""
import random

from py65.devices.mpu6502 import MPU

from ultima.sim.sim6502 import DONE, PowerCut

ROM_FILL = 0xEA


class Am29F040:
    """One 512 KiB chip, at the command level.  Program and erase complete
    at once (VICE models program time as zero too)."""
    MFR, DEV = 0x01, 0xA4

    def __init__(self, data, owner):
        self.data = bytearray(data)
        assert len(self.data) == 0x80000
        self.owner = owner
        self.step = 0                   # unlock cycles seen
        self.mode = "read"
        self.erase_armed = False

    def read(self, addr):
        if self.mode == "id":
            return {0: self.MFR, 1: self.DEV, 2: 0x00}.get(addr & 0xFF, 0x00)
        return self.data[addr]

    def write(self, addr, value):
        a = addr & 0x7FF
        if self.mode == "program":              # the data, whatever its value
            self.owner.change(("program", self, addr, value))
            if self.owner.lin_of(self, addr) in self.owner.stuck:
                self.mode = "read"              # a worn cell: it keeps what it had
                return
            if self.data[addr] & value != value:
                raise RuntimeError(f"program of ${value:02x} over ${self.data[addr]:02x} (unerased) "
                                   f"at chip offset ${addr:05x}")
            self.data[addr] &= value
            self.mode = "read"
            return
        if value == 0xF0 and self.step == 0:    # reset, at any address
            self.mode, self.erase_armed = "read", False
            return
        if self.step == 0 and a == 0x555 and value == 0xAA:
            self.step = 1
        elif self.step == 1 and a == 0x2AA and value == 0x55:
            self.step = 2
        elif self.step == 2:
            self.step = 0
            if self.erase_armed:
                self.erase_armed = False
                if value == 0x30:       # sector erase: the 64 KiB containing addr
                    base = addr & ~0xFFFF
                    self.owner.change(("erase", self, base))
                    self.data[base:base + 0x10000] = b"\xff" * 0x10000
                    self.owner.erases.append((self is self.owner.hi, base))
                    return
                if value == 0x10:
                    raise RuntimeError("chip erase: never wanted")
            if a != 0x555:
                return
            if value == 0xA0:
                self.mode = "program"
            elif value == 0x90:
                self.mode = "id"
            elif value == 0x80:
                self.erase_armed = True
            elif value == 0xF0:
                self.mode = "read"
        else:
            self.step = 0


class EFMemory:
    """The CPU's view: py65 indexes this for every access."""

    def __init__(self, flash, jumper_boot=True, seed=7):
        self.ram = bytearray(0x10000)
        self.io = bytearray(0x1000)             # $D000-$DFFF registers (storage)
        rng = random.Random(seed)
        self.efram = bytearray(rng.randrange(256) for _ in range(256))
        self.lo = Am29F040(b"".join(flash[b * 0x4000:b * 0x4000 + 0x2000] for b in range(64)), self)
        self.hi = Am29F040(b"".join(flash[b * 0x4000 + 0x2000:b * 0x4000 + 0x4000] for b in range(64)), self)
        self.bank = 0
        self.control = 0
        self.jumper_boot = jumper_boot
        self.cut_after = None
        self.changes = 0
        self.erases = []
        self.stuck = set()                      # linear addresses that will not program
        self.ram[0] = 0x2F
        self.ram[1] = 0x37

    # -- the flash, as the build lays it out (lhlh) -------------------------
    def flash(self):
        out = bytearray()
        for b in range(64):
            out += self.lo.data[b * 0x2000:(b + 1) * 0x2000]
            out += self.hi.data[b * 0x2000:(b + 1) * 0x2000]
        return out

    def lin_of(self, chip, addr):
        """A chip offset as the build's linear (lhlh) address."""
        return (addr // 0x2000) * 0x4000 + (0x2000 if chip is self.hi else 0) + (addr & 0x1FFF)

    def change(self, what):
        if self.cut_after is not None and self.changes >= self.cut_after:
            raise PowerCut(self.changes)
        self.changes += 1

    # -- the lines --------------------------------------------------------------
    def lines(self):
        """(exrom active, game active) as the cartridge drives them."""
        c = self.control
        exrom = bool(c & 0x02)
        if c & 0x04:
            game = bool(c & 0x01)
        else:
            game = self.jumper_boot
        return exrom, game

    def port(self):
        p = self.ram[1] | (~self.ram[0] & 0x17)     # inputs read high
        return bool(p & 1), bool(p & 2), bool(p & 4)

    def region(self, addr):
        """What a read of addr sees: 'ram', 'roml', 'romh', 'io', 'char',
        'kernal', 'basic', or None (Ultimax's open bus)."""
        exrom, game = self.lines()
        lo, hi, ch = self.port()
        if game and not exrom:                      # Ultimax
            if addr < 0x1000:
                return "ram"
            if 0x8000 <= addr < 0xA000:
                return "roml"
            if 0xD000 <= addr < 0xE000:
                return "io"
            if addr >= 0xE000:
                return "romh"
            return None
        if addr < 0x8000 or 0xC000 <= addr < 0xD000:
            return "ram"
        if not lo and not hi:
            return "ram"
        if addr < 0xA000:
            return "roml" if exrom and lo and hi else "ram"
        if addr < 0xC000:
            if exrom and game:
                return "romh" if hi else "ram"
            return "basic" if lo and hi else "ram"
        if addr < 0xE000:
            return "io" if ch else "char"
        return "kernal" if hi else "ram"

    def chip_addr(self, addr):
        return self.bank * 0x2000 + (addr & 0x1FFF)

    def __getitem__(self, addr):
        if isinstance(addr, slice):
            return [self[a] for a in range(*addr.indices(0x10000))]
        r = self.region(addr)
        if r == "ram":
            return self.ram[addr]
        if r == "roml":
            return self.lo.read(self.chip_addr(addr))
        if r == "romh":
            return self.hi.read(self.chip_addr(addr))
        if r == "io":
            if 0xDF00 <= addr:
                return self.efram[addr & 0xFF]
            if 0xDE00 <= addr < 0xDF00:
                return 0xFF                         # write-only registers
            if addr == 0xDD0D or addr == 0xDC0D:
                return 0x00
            return self.io[addr - 0xD000]
        return ROM_FILL

    def __setitem__(self, addr, value):
        if isinstance(addr, slice):
            for a, v in zip(range(*addr.indices(0x10000)), value):
                self[a] = v
            return
        value &= 0xFF
        exrom, game = self.lines()
        lo, hi, ch = self.port()
        if game and not exrom:                      # Ultimax: the chips take writes
            if addr < 0x1000:
                self.ram[addr] = value
            elif 0x8000 <= addr < 0xA000:
                self.lo.write(self.chip_addr(addr), value)
            elif addr >= 0xE000:
                self.hi.write(self.chip_addr(addr), value)
            elif 0xD000 <= addr < 0xE000:
                self.io_write(addr, value)
            return                                  # $1000-$7FFF, $A000-$CFFF: nowhere
        if 0xD000 <= addr < 0xE000 and (lo or hi) and ch:
            self.io_write(addr, value)
            return
        self.ram[addr] = value                      # under every ROM: RAM

    def io_write(self, addr, value):
        if addr >= 0xDF00:
            self.efram[addr & 0xFF] = value
        elif addr == 0xDE00:
            self.bank = value & 0x3F
        elif addr == 0xDE02:
            self.control = value & 0x87
        elif 0xDE00 <= addr < 0xDF00:
            pass
        else:
            self.io[addr - 0xD000] = value

    def __len__(self):
        return 0x10000


class EFSim:
    """py65 on EFMemory, with Sim's calling convention."""

    def __init__(self, flash, eapi="real", seed=7):
        self.mem = EFMemory(flash, seed=seed)
        self.mpu = MPU(memory=self.mem)
        self.steps = 0
        self.traps = {}
        self.eapi = eapi
        self.rng = random.Random(seed)
        if eapi == "contract":
            self._contract()

    # -- EAPI by its contract alone -------------------------------------------
    def _contract(self):
        """Trap EAPI's jump table ($DF80...) and EAPIInit at any slot: the
        documented effects only, the undocumented left in a state no caller
        should rely on."""
        st = {"bank": 0, "ptr": 0, "mode": 0xD0}
        m = self.mem

        def scramble():
            m.bank = self.rng.randrange(64)         # "$DE00 = the shadow bank" is not promised
            m.control = 0x07                        # (am29f040's leaves 16K mode, LED off)

        def lin(bank, addr):                        # an address as EAPISetPtr/WriteFlash take it
            chip = 1 if addr >= 0xA000 else 0
            return bank * 0x4000 + chip * 0x2000 + (addr & 0x1FFF)

        def program(off, value):
            chip = m.hi if (off & 0x2000) else m.lo
            a = (off >> 14) * 0x2000 + (off & 0x1FFF)
            m.change(("program", chip, a, value))
            if chip.data[a] & value != value:
                raise RuntimeError(f"program over unerased flash at ${off:06x}")
            chip.data[a] &= value

        def write_inc(sim):
            if st["ptr"] in m.stuck:                # it will not program: C set, not inc'ed
                scramble()
                sim.mpu.p |= 0x01
                return
            program(st["ptr"], sim.mpu.a)
            st["ptr"] += 1
            scramble()
            sim.mpu.p &= ~0x01

        def erase(sim):
            bank, base = sim.mpu.a, sim.mpu.y
            assert bank % 8 == 0 and base in (0x80, 0xA0, 0xE0), (bank, base)
            chip = m.lo if base == 0x80 else m.hi
            a = bank * 0x2000
            m.change(("erase", chip, a))
            chip.data[a:a + 0x10000] = b"\xff" * 0x10000
            m.erases.append((chip is m.hi, a))
            scramble()
            sim.mpu.p &= ~0x01

        def setbank(sim):
            st["bank"] = sim.mpu.a
            m.bank = sim.mpu.a

        def setptr(sim):
            assert sim.mpu.a == 0xD0, "only lhlh is used"
            addr = sim.mpu.x | sim.mpu.y << 8
            assert 0x8000 <= addr < 0xC000
            st["ptr"] = lin(st["bank"], addr)

        self.traps.update({0xDF83: erase, 0xDF86: setbank, 0xDF8C: setptr, 0xDF95: write_inc})
        self.contract_state = st

    def contract_init_at(self, slot):
        """EAPIInit (slot + 20) by the contract: C clear, A/X/Y the IDs."""
        def init(sim):
            sim.mpu.a, sim.mpu.x, sim.mpu.y = 0xA4, 0x01, 64
            self.mem.bank = 0
            self.mem.control = 0x07
            sim.mpu.p &= ~0x01
        self.traps[slot + 20] = init

    # -- running -------------------------------------------------------------------
    def call(self, addr, limit=200_000_000):
        mpu = self.mpu
        mpu.sp = 0xFF
        ret = DONE - 1
        self.mem.ram[0x1FF] = ret >> 8
        self.mem.ram[0x1FE] = ret & 0xFF
        mpu.sp = 0xFD
        mpu.pc = addr
        while mpu.pc != DONE:
            handler = self.traps.get(mpu.pc)
            if handler is not None:
                handler(self)
                lo = self.mem.ram[0x100 + ((mpu.sp + 1) & 0xFF)]
                hi = self.mem.ram[0x100 + ((mpu.sp + 2) & 0xFF)]
                mpu.sp = (mpu.sp + 2) & 0xFF
                mpu.pc = ((hi << 8 | lo) + 1) & 0xFFFF
                continue
            mpu.step()
            self.steps += 1
            if self.steps > limit:
                raise RuntimeError(f"no return after {limit} steps, pc=${mpu.pc:04x}")
        return self

    def cycles(self):
        return self.mpu.processorCycles
