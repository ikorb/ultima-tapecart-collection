"""Ultima 6 on the host: `game`'s routines run in py65 over a whole-RAM image
captured from VICE (tools/vice/fixtures.py), with the cycle count py65 keeps.

Flat 64 KiB RAM: `$01` is a plain byte, so a store through the colour-RAM
pointer ($D8xx) lands in the same flat RAM as the sprite images there; both
the original and the patched code see the same model, which is all an
equivalence test needs.
"""
import os

from py65.devices.mpu6502 import MPU

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SENTINEL = 0xFFF0                 # where a call returns to (RAM: an RTS-less loop end)


def fixture(name):
    with open(os.path.join(DATA, name), "rb") as fh:
        raw = fh.read()
    assert len(raw) == 65536
    return list(raw)


class Machine:
    def __init__(self, ram):
        self.mpu = MPU(memory=ram)
        self.mem = self.mpu.memory

    def call(self, addr, limit=3_000_000, regs=None):
        """JSR addr and run to its RTS; returns the cycles it took."""
        m = self.mpu
        regs = regs or {}
        m.a, m.x, m.y = regs.get("a", 0), regs.get("x", 0), regs.get("y", 0)
        m.sp = 0xF0
        ret = SENTINEL - 1
        self.mem[0x1F0] = ret >> 8                 # RTS pulls low, then high
        self.mem[0x1EF] = ret & 0xFF
        m.sp = 0xEE
        m.pc = addr
        m.p = 0x20
        c0 = m.processorCycles
        n = 0
        while m.pc != SENTINEL:
            m.step()
            n += 1
            if n > limit:
                raise RuntimeError(f"no return from ${addr:04x} after {limit} instructions")
        return m.processorCycles - c0


def run_to(machine, start, stop, limit=3_000_000):
    """Run from `start` (no return address pushed) until the PC reaches `stop`."""
    m = machine.mpu
    m.sp = 0xEE
    m.pc = start
    m.p = 0x20
    n = 0
    while m.pc != stop:
        m.step()
        n += 1
        if n > limit:
            raise RuntimeError(f"${start:04x} did not reach ${stop:04x}")
    return n


def patched(ram, blobs):
    """A copy of `ram` with each (address, bytes) laid over it."""
    out = list(ram)
    for addr, data in blobs:
        out[addr:addr + len(data)] = list(data)
    return out


def diff(a, b, ignore=()):
    skip = set(ignore)
    return [i for i in range(65536) if a[i] != b[i] and i not in skip]


def profile(machine, addr, limit=3_000_000):
    """Run JSR addr and attribute the cycles: {routine: [self, inclusive]},
    routines being the targets of the JSRs met (the entry itself included)."""
    m = machine.mpu
    mem = machine.mem
    m.sp = 0xEE
    ret = SENTINEL - 1
    mem[0x1F0] = ret >> 8
    mem[0x1EF] = ret & 0xFF
    m.pc = addr
    m.p = 0x20
    stack = [addr]
    own, incl = {}, {}
    n = 0
    while m.pc != SENTINEL:
        op = mem[m.pc]
        target = mem[m.pc + 1] | mem[m.pc + 2] << 8 if op == 0x20 else None
        c0 = m.processorCycles
        m.step()
        d = m.processorCycles - c0
        own[stack[-1]] = own.get(stack[-1], 0) + d
        if op == 0x20:
            stack.append(target)
        elif op == 0x60 and len(stack) > 1:
            done = stack.pop()
            incl[done] = incl.get(done, 0)      # (inclusive totals are summed below)
        n += 1
        if n > limit:
            raise RuntimeError("runaway")
    return own
