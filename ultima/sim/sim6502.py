#!/usr/bin/env python3
"""Run the collection's 6502 routines on the host, with py65.

    from ultima.sim.sim6502 import Sim
    sim = Sim.assemble("asm/zx02a.s", origin=0x1000, defines={...})
    out = sim.zx02_decode(stream, dest=0x4000)

py65 lives in the repository's .venv (../.venv); `make` uses that python.

The one thing the host has to fake is the tapecart: a routine that pulls a
byte through tc_stream_byte is assembled with `zx_getbyte` pointing at TRAP,
and whenever the CPU gets there the simulator hands over the next byte and
returns -- preserving X, Y and the flags, which is tc_stream_byte's contract
(the decoders depend on the carry surviving the call).  Everything else is
the real code, instruction by instruction.
"""
import os
import re
import subprocess
import tempfile
from pathlib import Path

from py65.devices.mpu6502 import MPU

from ultima import paths

TRAP = 0x0F00                   # "zx_getbyte": the byte source
DONE = 0x0F10                   # where the harness returns to


class PowerCut(Exception):
    """FakeCart.cut_after ran out: the power went, mid-operation."""


class FakeCart:
    """The tapecart's command interpreter, at the byte level.

    A driver talks to the cart only through tclib's tc_sendbyte and
    tc_getbyte, so trapping those two and feeding this model tests every
    layer above the wire -- command framing, addresses, lengths, the
    directory -- against a real flash image.  Flash behaves like flash:
    WRITE_FLASH can only clear bits (a write to unerased flash is caught),
    ERASE_FLASH_BLOCK sets a whole 4 KiB block back to $FF.
    """
    READ, READ_FAST, WRITE, ERASE, SETPARAMS, LOOKUP = 0x10, 0x11, 0x12, 0x15, 0x40, 0x41
    LED_OFF, LED_ON = 0x30, 0x31

    def __init__(self, flash):
        self.flash = bytearray(flash)
        self.out = []                       # reply bytes queued for tc_getbyte
        self.cmd = None
        self.args = bytearray()
        self.dirp = None                    # (address, count, n, m)
        self.log = []                       # every complete command, for tests
        self.cut_after = None               # flash changes until a power cut
        self.before_erase = None            # called (with the cart) before each erase
        self.changes = 0                    # bytes written + blocks erased
        self.led = True                     # entering command mode lights it
        self.lit = 0                        # LED_ON commands seen

    def send(self, b):
        if self.cmd is None:
            self.cmd, self.args = b, bytearray()
            need = self._need()
            if need == 0:
                self._run()
            return
        self.args.append(b)
        if self.cmd == self.WRITE and len(self.args) > 5:
            addr = self.args[0] | self.args[1] << 8 | self.args[2] << 16
            length = self.args[3] | self.args[4] << 8
            i = len(self.args) - 6
            a = addr + i
            if self.flash[a] & b != b:
                raise RuntimeError(f"write of ${b:02x} to unerased flash at ${a:06x}")
            self._change()
            self.flash[a] &= b
            if i + 1 == length:
                self.log.append(("write", addr, length))
                self.cmd = None
            return
        if len(self.args) == self._need():
            self._run()

    def _need(self):
        c = self.cmd
        if c in (self.READ, self.READ_FAST, self.WRITE):
            return 5
        if c == self.ERASE:
            return 3
        if c in (self.LED_OFF, self.LED_ON):
            return 0
        if c == self.SETPARAMS:
            return 7
        if c == self.LOOKUP:
            return self.dirp[2]
        raise RuntimeError(f"unknown cart command ${c:02x}")

    def _run(self):
        c, a = self.cmd, self.args
        if c in (self.READ, self.READ_FAST):
            addr = a[0] | a[1] << 8 | a[2] << 16
            length = a[3] | a[4] << 8
            self.out.extend(self.flash[addr:addr + length])
            self.log.append(("read", addr, length))
        elif c == self.WRITE:
            if (a[3] | a[4] << 8) == 0:
                self.log.append(("write", 0, 0))
            else:
                return                      # data bytes follow
        elif c == self.ERASE:
            addr = (a[0] | a[1] << 8 | a[2] << 16) & ~0xFFF
            if self.before_erase:
                self.before_erase(self)
            self._change()
            self.flash[addr:addr + 0x1000] = b"\xff" * 0x1000
            self.log.append(("erase", addr, 0x1000))
        elif c in (self.LED_OFF, self.LED_ON):
            self.led = c == self.LED_ON
            self.lit += self.led
        elif c == self.SETPARAMS:
            self.dirp = (a[0] | a[1] << 8 | a[2] << 16, a[3] | a[4] << 8, min(a[5], 16), a[6])
            self.log.append(("setparams",) + self.dirp)
        elif c == self.LOOKUP:
            base, count, n, m = self.dirp
            for k in range(count):
                e = base + k * (n + m)
                if self.flash[e:e + n] == a:
                    self.out.append(0)
                    self.out.extend(self.flash[e + n:e + n + m])
                    self.log.append(("lookup", bytes(a), e))
                    break
            else:
                self.out.append(1)
                self.log.append(("lookup", bytes(a), None))
        self.cmd = None

    def _change(self):
        """Count one change to the flash -- or cut the power before it."""
        if self.cut_after is not None and self.changes >= self.cut_after:
            raise PowerCut(self.changes)
        self.changes += 1

    def get(self):
        if not self.out:
            raise RuntimeError("tc_getbyte with nothing to receive")
        return self.out.pop(0)


class Sim:
    def __init__(self, image, origin, symbols):
        self.mpu = MPU()
        self.mem = self.mpu.memory
        self.mem[origin:origin + len(image)] = image
        self.sym = symbols
        self.steps = 0
        self.traps = {}                     # address -> handler(sim), then RTS
        self.cart = None

    def attach_cart(self, flash):
        """Trap tc_sendbyte/tc_getbyte onto a FakeCart holding `flash`.
        Both keep tclib's contract: clobber A and X, keep Y."""
        self.cart = FakeCart(flash)

        # The real routines keep only Y; clobber X as they may, so code that
        # counts in X across them fails here and not only on the hardware.
        def send(sim):
            sim.cart.send(sim.mpu.a)
            sim.mpu.x = (sim.mpu.x * 7 + 0x5B) & 0xFF

        def get(sim):
            sim.mpu.x = (sim.mpu.x * 7 + 0x5B) & 0xFF
            sim.mpu.a = sim.cart.get()
            # tc_getbyte ends with `lda tc_tmp`: N and Z follow the byte
            p = sim.mpu.p & ~0x82
            sim.mpu.p = p | (0x80 if sim.mpu.a & 0x80 else 0) | (0x02 if sim.mpu.a == 0 else 0)

        self.traps[self.sym["tc_sendbyte"]] = send
        self.traps[self.sym["tc_getbyte"]] = get
        if "tc_getbyte_guard" in self.sym:      # TC_GUARD: the 2-bit receive
            self.traps[self.sym["tc_getbyte_guard"]] = get
        return self.cart

    @classmethod
    def assemble(cls, source, origin, defines=None, extra=""):
        """Assemble `source` at `origin` behind a small wrapper."""
        defines = dict(defines or {})
        defines.setdefault("zx_getbyte", TRAP)
        with tempfile.TemporaryDirectory(prefix="sim") as tmp:
            wrap = os.path.join(tmp, "wrap.s")
            with open(wrap, "w") as fh:
                for k, v in defines.items():
                    fh.write(f"{k} = ${v:x}\n")   # unpadded: acme reads $00fb as forced 16-bit
                fh.write(f"        * = ${origin:04x}\n")
                fh.write(extra)
                fh.write(f'!source "{os.path.abspath(source)}"\n')
            out, sym = os.path.join(tmp, "o.bin"), os.path.join(tmp, "o.sym")
            subprocess.run(["acme", "-f", "plain", "-I", paths.ASM,

                            "-o", out, "-l", sym, wrap], check=True)
            image = Path(out).read_bytes()
            symbols = {m.group(1): int(m.group(2), 16) for m in
                       re.finditer(r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path(sym).read_text())}
        return cls(image, origin, symbols)

    def call(self, addr, source=b"", limit=50_000_000):
        """JSR addr with `source` as the byte stream; returns the bytes the
        routine did not consume."""
        mpu = self.mpu
        src = iter(source)
        # return address DONE-1 on the stack, as a JSR would push it
        mpu.sp = 0xFF
        ret = DONE - 1
        self.mem[0x1FF] = ret >> 8
        self.mem[0x1FE] = ret & 0xFF
        mpu.sp = 0xFD
        mpu.pc = addr
        while mpu.pc != DONE:
            handler = self.traps.get(mpu.pc)
            if handler is not None:
                handler(self)
                lo = self.mem[0x100 + ((mpu.sp + 1) & 0xFF)]
                hi = self.mem[0x100 + ((mpu.sp + 2) & 0xFF)]
                mpu.sp = (mpu.sp + 2) & 0xFF
                mpu.pc = ((hi << 8 | lo) + 1) & 0xFFFF
                continue
            if mpu.pc == TRAP:
                try:
                    mpu.a = next(src)
                except StopIteration:
                    raise RuntimeError("the routine read past the end of its stream")
                lo = self.mem[0x100 + ((mpu.sp + 1) & 0xFF)]
                hi = self.mem[0x100 + ((mpu.sp + 2) & 0xFF)]
                mpu.sp = (mpu.sp + 2) & 0xFF
                mpu.pc = ((hi << 8 | lo) + 1) & 0xFFFF
                continue
            mpu.step()
            self.steps += 1
            if self.steps > limit:
                raise RuntimeError(f"no return after {limit} steps, pc=${mpu.pc:04x}")
        return bytes(src)

    # -- the two zx02 decoders -------------------------------------------
    def zx02a_decode(self, stream, dest, length):
        """zx02a.s: destination in zx_put's operand."""
        self.mem[self.sym["zx_put"] + 1] = dest & 0xFF
        self.mem[self.sym["zx_put"] + 2] = dest >> 8
        rest = self.call(self.sym["zx_unpack"], stream)
        return bytes(self.mem[dest:dest + length]), rest

    def zx02s_decode(self, stream, dest, length):
        """zx02s.s: destination in zx_dst, zero page saved and restored."""
        self.mem[self.sym["zx_dst"]] = dest & 0xFF
        self.mem[self.sym["zx_dst"] + 1] = dest >> 8
        rest = self.call(self.sym["zx_unpack"], stream)
        return bytes(self.mem[dest:dest + length]), rest
