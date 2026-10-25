#!/usr/bin/env python3
"""Every read-only unit of Ultima 1, 2 or 3 through its driver, in VICE.

    python -m tools.vice.unit_check u1|u2|u3 [--time] [--plain]

U4 has u4_check.py; this is the same idea for the three drivers whose units
are whole files.  It launches the game from the cart and parks at the
driver's load entry the first time it is reached (the cart idle, in command
mode).  Then, from a stub, it sends every read-only unit of the game's own
table -- U1's u1_table, U2's u2_table, U3's catalog at $B000 -- through the
driver's own routine for it (raw: u1_xfer / u2_fetch / u3_xfer; crunched:
zxd_unpack, or zxd_unpack_sized for U3) into scratch RAM at $1000, and
compares that with the flash (crunched units decoded on the host).  The
game is not resumed.

For TC_GUARD, each unit gets its own display first: $D011 = $18 | YSCROLL,
with YSCROLL stepping through all eight, and every fifth unit sprites on
($D015 = $FF), which takes the 1-bit read.  --time prints the cycles;
--plain keeps the sprites off throughout, for comparing builds.
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

STUB = 0x0340
SCRATCH = 0x1000
LIMIT = 0x9000                  # scratch ends here, below every driver
GAMES = {"u1": 1, "u2": 2, "u3": 3}     # the list place menu_check wants (the key)


def symbols(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        m = re.match(r"\s*(\w+)\s*=\s*\$([0-9a-fA-F]+)", line)
        if m:
            out[m.group(1)] = int(m.group(2), 16)
    return out


def stub(call):
    """sei / jsr call / done: nop nop"""
    return bytes([0x78, 0x20, call & 0xFF, call >> 8, 0xEA, 0xEA])


class Check:
    def __init__(self, game, timing, plain=False):
        self.game, self.timing, self.plain = game, timing, plain
        self.sym = symbols(f"build/{game}drv.sym")
        self.image = menu_check.with_autokey(GAMES[game])
        self.flash = TCRT.read(self.image).flash
        self.v = None

    def units(self):
        """(name, flash address, stored length, crunched, how) of every
        read-only unit, from the driver's table as it sits in RAM."""
        v, s, out = self.v, self.sym, []
        if self.game == "u1":
            t = v.mem(s["u1_table"], s["u1_table"] + 22 * 8 - 1)
            for i in range(16):                     # 16-21 are the save slots
                e = t[i * 8:i * 8 + 8]
                length = e[2] | e[3] << 8
                if length and not e[6] & 2:
                    out.append((f"file {i}", (e[0] | e[1] << 8) << 8, length, bool(e[6] & 1)))
        elif self.game == "u2":
            t = v.mem(s["u2_table"], s["u2_table"] + 124 * 13 - 1)
            for i in range(124):
                e = t[i * 13:i * 13 + 13]
                length = e[10] | e[11] << 8
                if not length:
                    continue
                name = bytes(c & 0x7F for c in e[:8]).decode("latin1").strip()
                out.append((name, (e[8] | e[9] << 8) << 8, length, bool(e[12] & 0x40)))
        else:
            t = v.mem(0xB000, 0xB000 + 94 * 8 - 1)
            for i in range(94):
                e = t[i * 8:i * 8 + 8]
                start, blocks = e[4] | e[5] << 8, e[6]
                if blocks & 0x80 or not blocks:     # writable: the save slots
                    continue
                name = bytes(c & 0x7F for c in e[:4]).decode("latin1").strip()
                out.append((name, (start & 0x7FFF) << 8, blocks * 256, bool(start & 0x8000)))
        return out

    def expected(self, addr, length, crunched):
        if not crunched:
            return self.flash[addr:addr + length]
        if self.game == "u3":                       # its own length first
            n = self.flash[addr] | self.flash[addr + 1] << 8
            return zx.decode(self.flash[addr + 2:addr + 2 + n])
        return zx.decode(self.flash[addr:addr + length])

    def dump(self, start, length):
        """bsave, which is fast and reads under the ROMs with bank ram"""
        path = os.path.abspath(f"build/unit_check_{self.game}.bin")
        if os.path.exists(path):
            os.remove(path)
        self.v.cmd(f'bsave "{path}" 0 {start:04x} {start + length - 1:04x}', wait=0.3)
        for _ in range(100):
            if os.path.exists(path) and os.path.getsize(path) >= length:
                break
            time.sleep(0.05)
        return Path(path).read_bytes()[:length]

    def routine(self, crunched):
        s = self.sym
        if crunched:
            return s[{"u1": "u1_unpack", "u2": "zxd_unpack", "u3": "zxd_unpack_sized"}[self.game]]
        return s[{"u1": "u1_xfer", "u2": "u2_fetch", "u3": "u3_xfer"}[self.game]]

    def park(self):
        entry = {"u1": "u1_load", "u2": "u2_load", "u3": "u3_transfer"}[self.game]
        v, at = self.v, f"{self.sym[entry]:04x}"
        # a breakpoint fires on the PC whatever the banking: at $A000-$BFFF
        # that is BASIC's ROM during start-up, so only with LORAM+HIRAM not
        # both set (VICE's condition reads the CPU port there)
        v.cmd(f"break {at} if (@cpu:$01 & $03) != $03", wait=0.2)
        v.sock.sendall(b"x\n")
        seen, t_end = "", time.time() + 120
        while time.time() < t_end and at not in seen.lower():
            seen += v._drain(0.3)
        if at not in seen.lower():
            raise SystemExit(f"the driver's {entry} was never reached")
        v.cmd("delete", wait=0.2)

    def run(self):
        self.v = v = Vice(self.image, log=f"build/unit_check_{self.game}.log")
        bad = total = cycles = 0
        try:
            v.cmd("bank ram", wait=0.2)
            self.park()
            units = self.units()
            print(f"{self.game}: {len(units)} read-only units")
            v.poke(self.sym["pt_opts"], b"\x00")        # no option patches on the data
            for k, (name, addr, length, crunched) in enumerate(units):
                want = self.expected(addr, length, crunched)
                if SCRATCH + len(want) > LIMIT:
                    print(f"  skip {name}: {len(want)} bytes do not fit the scratch area")
                    continue
                d011 = 0x18 | (k & 7)
                d015 = 0xFF if k % 5 == 4 and not self.plain else 0x00
                v.cmd("bank io", wait=0.1)
                v.poke(0xD011, bytes([d011]))
                v.poke(0xD015, bytes([d015]))
                v.cmd("bank ram", wait=0.1)
                s = self.sym
                v.poke(s["tc_addr"], bytes([addr & 0xFF, addr >> 8 & 0xFF, addr >> 16]))
                v.poke(s["tc_len"], bytes([length & 0xFF, length >> 8]))
                v.poke(s["tc_dest"], bytes([SCRATCH & 0xFF, SCRATCH >> 8]))
                v.poke(SCRATCH, bytes([0xA5]) * min(len(want), 256))
                v.poke(STUB, stub(self.routine(crunched)))
                v.cmd(f"break {STUB + 4:04x}", wait=0.1)
                v.cmd("stopwatch reset", wait=0.1)
                v.sock.sendall(f"g {STUB:04x}\n".encode())
                seen, t_end = "", time.time() + 30
                while time.time() < t_end and f"{STUB + 4:04x}" not in seen.lower():
                    seen += v._drain(0.2)
                v.cmd("delete", wait=0.1)
                if f"{STUB + 4:04x}" not in seen.lower():
                    print(f"  HANG {name}")
                    bad += 1
                    break
                m = re.search(r"Stopwatch:\s*(\d+)", v.cmd("stopwatch", wait=0.3))
                n = int(m.group(1)) if m else 0
                cycles += n
                got = self.dump(SCRATCH, len(want))
                total += 1
                ok = got == want
                bad += not ok
                note = f"{'crunched' if crunched else 'raw':8} {len(want):5d} B, $D011 ${d011:02x}" \
                       f"{', sprites on' if d015 else ''}"
                if not ok:
                    at = next(i for i in range(len(want)) if got[i] != want[i])
                    print(f"  BAD  {name}: {note}, first difference at +{at:#x}")
                elif self.timing:
                    print(f"  ok   {name}: {note}, {n} cycles")
        finally:
            v.quit()
        print(f"{self.game}: {total - bad} of {total} byte-exact, {cycles} cycles")
        return 1 if bad or not total else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] not in GAMES:
        raise SystemExit(__doc__)
    sys.exit(Check(args[0], "--time" in args, "--plain" in args).run())
