#!/usr/bin/env python3
"""Ultima 4: no NMI gets in while the cart talks (u4drv.s u4_in/u4_out).

    python -m tools.vice.u4_nmi_check [--nohold]    (the control: u4_in's hold off, has to fail)

The 2-bit read is timed, so an NMI in the middle of a byte -- RESTORE --
would corrupt it.  u4_in holds the NMI line low with an unacknowledged CIA 2
interrupt, which leaves RESTORE's pulse no edge.  Pressing RESTORE is not
something the monitor can do, so this uses an NMI source on the same line:
CIA 2's timer B, one shot, started right before each LOADBLK call with a
delay that differs per request and spans the call, so its NMI falls
somewhere inside it -- mostly among the 2-bit bytes, which are most of a
call.  The blocks are then compared with the flash as u4_check's sweep
does, and timer B must have run out.  With the hold its NMI never gets in;
without it (--nohold, the control) it lands where it falls and some blocks
have to come out wrong.  (A continuous NMI every 2000 cycles was tried
first and proves nothing: the first one in a call lands among the 1-bit
command bytes, which do not mind, and u4_rti acknowledges nothing, so the
line then stays low for the rest.)
"""
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from tools.vice import u4_check
from tools.vice.vice_mon import Vice
from tools.vice import menu_check

ORG = 0x0340
COUNT = 0x0370                  # NMIs taken; before the delay, before and after the call
REQS = u4_check.sweep_requests()[::10]

STUB = f"""
        * = ${ORG:04x}
stub:   sei
        lda delay
        sta $dd06
        lda delay+1
        sta $dd07
        lda #$19                ; timer B: one shot from the latch, started
        sta $dd0f
        jsr $a45e
        lda $dd0f
        sta tb_after
done:   nop
        nop
nmi:    pha                     ; outside a call: acknowledged, counted
        lda $dd0d
        inc count
        pla
        rti
        * = ${COUNT:04x}
count:    !byte 0
tb_after: !byte 0
delay:    !word 0
"""


def assemble():
    with tempfile.TemporaryDirectory() as tmp:
        src, out, sym = (os.path.join(tmp, n) for n in ("s.s", "o.bin", "o.sym"))
        Path(src).write_text(STUB)
        subprocess.run(["acme", "-f", "plain", "-o", out, "-l", sym, src], check=True)
        syms = {m.group(1): int(m.group(2), 16) for m in
                re.finditer(r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path(sym).read_text())}
        return Path(out).read_bytes(), syms


def main():
    code, sym = assemble()
    image = menu_check.with_autokey(u4_check.U4_MENU_INDEX)
    c = u4_check.Checker(image)
    c.v = v = Vice(image, log="build/u4_nmi_check.log", update_tcrt=True)
    bad = 0
    try:
        v.cmd("bank ram", wait=0.2)
        stop = c.sym["u4_xfer_done"]           # parked where u4_check's sweep parks
        v.cmd(f"break {stop:04x}", wait=0.2)
        v.sock.sendall(b"x\n")
        seen, t_end = "", time.time() + 60
        while time.time() < t_end and f"{stop:04x}" not in seen.lower():
            seen += v._drain(0.3)
        v.cmd("delete", wait=0.2)
        v.poke(ORG, code)
        if "--nohold" in sys.argv:              # the control: u4_in's NMI never enabled
            at = c.sym["u4_in"]
            ram = v.mem(at, at + 63)
            i = ram.find(bytes([0xA9, 0x81, 0x8D, 0x0D, 0xDD]))
            assert i >= 0
            v.poke(at + i + 1, b"\x01")
            print("  (u4_in's hold is off)")
        v.poke(0xFFFA, bytes([sym["nmi"] & 0xFF, sym["nmi"] >> 8]))    # the RAM's vector
        v.poke(0x0318, bytes([sym["nmi"] & 0xFF, sym["nmi"] >> 8]))    # the KERNAL's
        v.cmd("bank io", wait=0.2)
        v.poke(0xDD0D, b"\x82")                 # timer B's NMI on
        v.cmd("bank ram", wait=0.2)
        v.cmd(f"break {sym['done']:04x}", wait=0.2)
        for k, (disk, block, count) in enumerate(REQS):
            # somewhere past the command bytes, inside the call: one block
            # takes 16-19k cycles, and each more ~24-31k
            span = min(64000, 14000 * count) - 2500
            delay = 2500 + (k * 7919) % span
            v.poke(sym["delay"], bytes([delay & 0xFF, delay >> 8]))
            v.poke(c.sym["u4_disk"], bytes([disk]))
            v.poke(u4_check.DK, bytes([1, count, u4_check.SCRATCH & 0xFF,
                                       u4_check.SCRATCH >> 8, block & 0xFF, block >> 8]))
            v.sock.sendall(f"g {ORG:04x}\n".encode())
            seen, t_end = "", time.time() + 60
            while time.time() < t_end and f"{sym['done']:04x}" not in seen.lower():
                seen += v._drain(0.2)
            for _try in range(3):               # the monitor now and then answers nothing
                try:
                    ran_out = not v.mem(sym["tb_after"], sym["tb_after"])[0] & 1
                    break
                except RuntimeError:
                    time.sleep(0.5)
            else:
                raise RuntimeError("no answer for tb_after")
            same = c.dump(u4_check.SCRATCH, count * 256) == c.expected(disk, block, count)
            ok = ran_out and same
            bad += not ok
            print(f"  disk {disk} block {block:3d} x{count:2d}: NMI at +{delay:5d}, "
                  f"{'byte-exact' if same else 'DIFFERENT'}"
                  f"{'' if ran_out else ', timer B still running'}{'' if ok else '  <-- FAIL'}")
    finally:
        v.quit()
    print(f"{len(REQS) - bad} of {len(REQS)} ok")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
