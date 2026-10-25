#!/usr/bin/env python3
"""Check every Ultima 4 block transfer against the flash, in the emulator.

    python -m tools.vice.u4_check [--saved] [--reuse] [seconds] [keys...]
    python -m tools.vice.u4_check --sweep [--d011 1b] [--noguard]
                        (the display as the sweep runs; the control without
                        TC_GUARD's badline check, which has to fail)
    python -m tools.vice.u4_check --time          (cycles for a few representative loads)
    python -m tools.vice.u4_check --irq           (the sweep from game main, the music on,
                                         interrupts enabled; counts the IRQs)

The host tests prove the block maps are right; this proves the 6502 code that
walks them is.  It launches U4 from the cart, breaks at the end of every
LOADBLK call (u4_xfer_done) and compares what landed in RAM with the blocks
the flash map says belong there -- read with `bank ram`, so a chunk under the
KERNAL or BASIC is compared too.  Writes are only reported.

Keys (lower case, one per argument) are typed one at a time after the boot
settles, with `seconds` of play between them; each is checked the same way.
"""
import os
import re
import sys
import time
from pathlib import Path

from ultima.flash.tcrt import TCRT
from tools.vice.vice_mon import Vice
from tools.vice import menu_check
from ultima.flash import zx
from ultima.disks.d64 import D64
from ultima import paths

U4_MENU_INDEX = 4
DK = 0xA000
DUMP = os.path.abspath("build/u4_check.bin")


def symbols(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        m = re.match(r"\s*(\w+)\s*=\s*\$([0-9a-fA-F]+)", line)
        if m:
            out[m.group(1)] = int(m.group(2), 16)
    return out


class Checker:
    def __init__(self, image):
        self.flash = TCRT.read(image).flash
        self.sym = symbols("build/u4drv.sym")
        self.maps = {}          # read from the driver itself, as the build patched it
        self.v = None
        self.hits = self.bad = self.writes = 0
        self.seen = {}
        self.written = {}       # (disk, block) -> the page the game wrote
        self.cycles = {}        # sweep request -> cycles, from the stopwatch

    def map_addr(self, disk):
        lo = self.mem(self.sym["u4_map_lo"] + disk - 1, self.sym["u4_map_lo"] + disk - 1)[0]
        mid = self.mem(self.sym["u4_map_mid"] + disk - 1, self.sym["u4_map_mid"] + disk - 1)[0]
        hi = self.mem(self.sym["u4_map_hi"] + disk - 1, self.sym["u4_map_hi"] + disk - 1)[0]
        return lo | mid << 8 | hi << 16

    def mem(self, a, b):
        return self.v.mem(a, b)

    def expected(self, disk, block, count):
        base = self.maps.setdefault(disk, self.map_addr(disk))
        out = bytearray()
        for b in range(block, block + count):
            e = self.flash[base + 4 * b:base + 4 * b + 4]
            addr, length = e[0] | e[1] << 8 | e[2] << 16, e[3]
            out += (self.flash[addr:addr + 256] if length == 0
                    else zx.decode(self.flash[addr:addr + length]))
        return bytes(out)

    def check_written(self, image):
        """After a clean quit, every block the game wrote must be in the
        image's flash, where the block map sends reads of it."""
        flash = TCRT.read(image).flash
        bad = 0
        for (disk, blk), data in sorted(self.written.items()):
            base = self.maps[disk] if disk in self.maps else None
            if base is None:
                print(f"  ? no map address known for disk {disk}")
                bad += 1
                continue
            e = flash[base + 4 * blk:base + 4 * blk + 4]
            addr, length = e[0] | e[1] << 8 | e[2] << 16, e[3]
            got = flash[addr:addr + 256]
            ok = length == 0 and got == data
            bad += not ok
            print(f"  {'ok  ' if ok else 'BAD '} written disk {disk} block {blk} "
                  f"is in flash at {addr:#08x}")
        return bad

    def dump(self, start, length):
        if os.path.exists(DUMP):
            os.remove(DUMP)
        self.v.cmd(f'bsave "{DUMP}" 0 {start:04x} {start + length - 1:04x}', wait=0.3)
        for _ in range(50):
            if os.path.exists(DUMP) and os.path.getsize(DUMP) >= length:
                break
            time.sleep(0.05)
        return Path(DUMP).read_bytes()

    def hit(self):
        dk = self.mem(DK, DK + 5)
        op, cnt, adr, blk = dk[0], dk[1], dk[2] | dk[3] << 8, dk[4] | dk[5] << 8
        disk = self.mem(self.sym["u4_disk"], self.sym["u4_disk"])[0]
        self.hits += 1
        key = (op, disk, blk, cnt, adr)
        if op == 2:
            self.writes += 1
            data = self.dump(adr, cnt * 256)
            for i in range(cnt):
                self.written[(disk, blk + i)] = data[i * 256:(i + 1) * 256]
            print(f"  write disk {disk} block {blk} x{cnt} from ${adr:04x}")
            return
        if cnt == 0:
            return
        got = self.dump(adr, cnt * 256)
        want = self.expected(disk, blk, cnt)
        ok = got == want
        first = key not in self.seen
        self.seen[key] = ok
        if not ok:
            self.bad += 1
            diff = next(i for i in range(len(want)) if i >= len(got) or got[i] != want[i])
            print(f"  BAD  disk {disk} block {blk} x{cnt} -> ${adr:04x}: "
                  f"first difference at +{diff:#x} (got {len(got)} bytes)")
        elif first:
            print(f"  ok   disk {disk} block {blk:3d} x{cnt:2d} -> ${adr:04x}")

    def loop(self, seconds):
        """Resume, checking every transfer, until `seconds` pass with none."""
        v = self.v
        stop = self.sym["u4_xfer_done"]
        v.cmd(f"break {stop:04x}", wait=0.2)
        deadline = time.time() + seconds
        while time.time() < deadline:
            v.sock.sendall(b"x\n")
            seen = ""
            t_end = deadline
            while time.time() < t_end:
                seen += v._drain(0.3)
                if f"{stop:04x}" in seen.lower() and ("stop on" in seen.lower() or "#" in seen):
                    break
            else:
                v.cmd("", wait=0.2)
                break
            self.hit()
            deadline = max(deadline, time.time() + 4)
        v.cmd("delete", wait=0.2)


# A saved game in the five slots lets Journey Onward reach the overworld (and
# $0A7F's map reads) without playing through character creation: the party
# of one tests/test_page.py seeds.  Debug only: the image written is
# build/auto.tcrt.
def seed_saves(image):
    from ultima.flash import regions
    from tests import test_page
    img = TCRT.read(image)
    flash = bytearray(img.flash.ljust(regions.FLASH_SIZE, b"\xff"))
    test_page.seed_u4(flash, test_page.page_syms())
    img.flash = bytes(flash)
    img.write(image, trim=False)
    print("u4: save slots seeded (tests/test_page.py seed_u4)")


STUB = 0x0340                  # sei / jsr $a45e / nop / nop
SCRATCH = 0x2000                # every sweep request lands here; 80 pages fit


def sweep_requests():
    """Every chunk and record the kernel's tables name, on every disk, plus
    a sample of the overworld blocks $0A7F reads by hand."""
    from ultima.games.u4 import build as u4
    k = u4.kernel_image(D64(paths.disk("u4a")))

    def at(a):
        return k[a - u4.KERNEL_ADDR]

    def w(a):
        return at(a) | at(a + 1) << 8
    # the six tables tile $A218-$A428: 29 records ($00-$1C), 96 chunks ($40-$9F)
    chunks = [(w(0xA369 + 2 * i), at(0xA2A9 + i)) for i in range(96)
              if at(0xA2A9 + i) != 0xFF and at(0xA309 + i) != 0xFF]
    records = [w(0xA26F + 2 * i) for i in range(29) if w(0xA26F + 2 * i) != 0xFFFF]
    reqs = []
    for disk in (1, 2, 3, 4):
        reqs += [(disk, start, count) for start, count in chunks]
        reqs += [(disk, block, 1) for block in records]
    reqs += [(2, b, 1) for b in range(1, 257, 15)]
    return sorted(set(reqs))


# A few requests that stand for the game's real mix: the 80-block chunk
# Journey Onward loads, the 32-block module, a map overlay, a record, and
# the one-block overworld reads $0A7F makes every time the party crosses a
# chunk boundary.
D011 = None                     # --d011: set before a sweep
NOGUARD = False                 # --noguard: cmp #$06 -> #$08, the check never waits
IRQ = False                     # --irq: in the game, the music on, CLI in the stub
MAIN_LOOP = 0x408F              # game main's key read, between commands
KCOUNT = 0x0360                 # --irq: u4_kirq's JSR $FFEA counted here, via $0350

TIMED = [(1, 1, 80), (1, 359, 32), (3, 257, 5), (1, 252, 1),
         (2, 142, 1), (2, 126, 1), (4, 391, 30)]


def sweep(c, timing=False):
    """Call LOADBLK directly for every request, from a stub.

    Parked at the end of the boot's first transfer -- the cart is idle and
    in command mode there, which is what makes hijacking the PC safe."""
    v = c.v
    if IRQ:
        # Journey onward to game main's key read: the music playing, the
        # kernel's IRQ path in place, the cart idle
        v.run_to(0x0200, timeout=90)
        v.cmd("bank ram", wait=0.2)
        v.poke(c.sym["pt_opts"], bytes([0x04]))
        print("sweep: parked in game main at", v.run_to(MAIN_LOOP, timeout=120))
    else:
        stop = c.sym["u4_xfer_done"]
        v.cmd(f"break {stop:04x}", wait=0.2)
        v.sock.sendall(b"x\n")
        seen = ""
        t_end = time.time() + 60
        while time.time() < t_end and f"{stop:04x}" not in seen.lower():
            seen += v._drain(0.3)
        v.cmd("delete", wait=0.2)
    v.cmd("bank io", wait=0.2)
    if D011 is not None:                # --d011: the display as the sweep wants it
        v.poke(0xD011, bytes([D011]))
    print(f"sweep: $D011 = ${v.mem(0xD011, 0xD011)[0]:02x}, $D015 = ${v.mem(0xD015, 0xD015)[0]:02x}")
    v.cmd("bank ram", wait=0.2)
    if NOGUARD:                         # the control: TC_GUARD's check never waits
        at = c.sym["tc_gg_wait"] + 10
        assert v.mem(at - 1, at) == b"\xc9\x06"
        v.poke(at, b"\x08")
        print("sweep: the badline check is off")
    v.poke(STUB, bytes([0x58 if IRQ else 0x78, 0x20, 0x5E, 0xA4, 0xEA, 0xEA]))
    if IRQ:
        # count u4_kirq's calls -- it is $0314 only while a load runs
        k = c.sym["u4_kirq"]
        assert v.mem(k, k + 5) == bytes.fromhex("20 ea ff 4c 7b ea"), v.mem(k, k + 5).hex()
        v.poke(0x0350, bytes.fromhex("ee 60 03 d0 03 ee 61 03 4c ea ff"))
        v.poke(KCOUNT, b"\0\0")
        v.poke(k + 1, bytes([0x50, 0x03]))
    v.cmd(f"break {STUB + 4:04x}", wait=0.2)
    reqs = TIMED if timing else sweep_requests()
    print(f"sweep: {len(reqs)} requests")
    for disk, block, count in reqs:
        v.poke(c.sym["u4_disk"], bytes([disk]))
        v.poke(DK, bytes([1, count, SCRATCH & 0xFF, SCRATCH >> 8, block & 0xFF, block >> 8]))
        v.cmd("stopwatch reset", wait=0.2)
        v.sock.sendall(f"g {STUB:04x}\n".encode())
        seen = ""
        t_end = time.time() + 30
        while time.time() < t_end and f"{STUB + 4:04x}" not in seen.lower():
            seen += v._drain(0.2)
        if f"{STUB + 4:04x}" not in seen.lower():
            print(f"  HANG disk {disk} block {block} x{count}")
            c.bad += 1
            break
        c.hits += 1
        if timing:
            v.cmd("", wait=0.1)
        m = re.search(r"Stopwatch:\s*(\d+)", v.cmd("stopwatch", wait=0.3))
        if m:
            c.cycles[(disk, block, count)] = int(m.group(1))
        if timing:
            print(f"  disk {disk} block {block:3d} x{count:2d}: "
                  f"{c.cycles.get((disk, block, count), 0):8d} cycles")
            c.seen[(disk, block, count)] = True
            continue
        got = c.dump(SCRATCH, count * 256)
        want = c.expected(disk, block, count)
        c.seen[(disk, block, count)] = got == want
        if got != want:
            c.bad += 1
            diff = next(i for i in range(len(want)) if i >= len(got) or got[i] != want[i])
            print(f"  BAD  disk {disk} block {block} x{count}: first difference at +{diff:#x}")
    ok = sum(c.seen.values())
    print(f"sweep: {ok} of {len(reqs)} byte-exact")
    if IRQ:
        n = v.mem(KCOUNT, KCOUNT + 1)
        n = n[0] | n[1] << 8
        k = v.mem(0x0314, 0x0315)
        print(f"sweep: {n} KERNAL IRQs taken inside loads; $0314 = ${k[1]:02x}{k[0]:02x} after")
        c.bad += n == 0 or k != b"\x31\xea"
    if c.cycles:
        blocks = sum(n for (_d, _b, n) in c.cycles)
        total = sum(c.cycles.values())
        print(f"sweep: {total} cycles for {blocks} blocks, "
              f"{total / blocks:.0f} per block ({total / blocks / 985.248:.1f} ms PAL)")
        for key in ((1, 1, 80), (2, 142, 1)):
            if key in c.cycles:
                print(f"  disk {key[0]} block {key[1]} x{key[2]}: {c.cycles[key]} cycles")


def main():
    args = sys.argv[1:]
    global IRQ
    IRQ = "--irq" in args
    if IRQ:
        args += ["--saved", "--sweep"]
    saved = "--saved" in args
    reuse = "--reuse" in args           # boot build/auto.tcrt as a previous run left it
    do_sweep = "--sweep" in args        # call LOADBLK for every chunk on every disk
    timing = "--time" in args           # time TIMED instead, and compare nothing
    global D011, NOGUARD
    NOGUARD = "--noguard" in args
    args = [a for a in args if a not in ("--noguard", "--irq")]
    if "--d011" in args:                # e.g. --d011 1b: display on, YSCROLL 3
        i = args.index("--d011")
        D011 = int(args[i + 1], 16)
        del args[i:i + 2]
    args = [a for a in args if a not in ("--saved", "--reuse", "--sweep", "--time")]
    seconds = float(args[0]) if args else 40
    keys = args[1:]
    image = "build/auto.tcrt" if reuse else menu_check.with_autokey(U4_MENU_INDEX)
    if saved:
        seed_saves(image)
    c = Checker(image)
    c.v = Vice(image, log="build/u4_check.log", update_tcrt=True)
    try:
        c.v.cmd("bank ram", wait=0.2)
        if do_sweep or timing:
            sweep(c, timing)
            keys = []
        else:
            c.loop(seconds)
        c.v.shot("build/u4_check_00.png")
        for n, k in enumerate(keys, 1):
            print(f"-- key {k!r}")
            c.v.keys(k)
            c.loop(seconds)
            c.v.shot(f"build/u4_check_{n:02d}.png")
    finally:
        c.v.quit()
    time.sleep(1)
    if c.written:
        c.bad += c.check_written(image)
    print(f"{c.hits} transfers, {len(c.seen)} distinct, {c.bad} bad, {c.writes} writes")
    return 1 if c.bad or not c.hits else 0


if __name__ == "__main__":
    sys.exit(main())
