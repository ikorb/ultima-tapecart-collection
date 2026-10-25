"""Drive Ultima III in VICE: launch it from the cart, make a party, play.

    from tools.vice.u3_drive import start, key, gkey
    v = start(page_keys="x")     # the launcher's U3 page, X, then L
    gkey(v, ord("B"))            # a command in play

Keys have to be delivered at a poll, not typed (U3 flushes its queue all
over): `key` breaks at the DOS module's $B80C (BOOT's menus, the peers'
waits), `gkey` at the driver's kb_take (ULT3's command loops and SUBS' key
wait since the type-ahead fix), and puts the code in $0277 with $C6 = 1.
Letters as ASCII capitals ($41-$5A: kb_take sets bit 7), F7 is $88.

start() launches the cart's U3 (the page's keys first), optionally pokes the
options byte at the init stub, creates a character in slot 1 and forms a
party of it (CREATE), and returns the machine on Sosaria.
"""
import re
import time
from pathlib import Path

from ultima.flash.tcrt import TCRT
from tools.vice.vice_mon import Vice
from ultima.flash import regions

# C(reate), slot 1, name AB<DEL>C, M(ale), H(uman), F(ighter), 20 15 10 05,
# Y(es); F(orm) party 1, 0; M(enu)? J(ourney)
CREATE = [0x43, 0x31, 0x0d, 0x41, 0x42, 0x14, 0x43, 0x0d, 0x4d, 0x48, 0x46, 0x32, 0x30, 0x0d,
          0x31, 0x35, 0x0d, 0x31, 0x30, 0x0d, 0x30, 0x35, 0x0d, 0x59, 0x46, 0x31, 0x0d, 0x30,
          0x0d, 0x4d, 0x4a]


def syms():
    return {m.group(1): int(m.group(2), 16) for m in
            re.finditer(r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path("build/u3drv.sym").read_text())}


def image(out="build/u3drive.tcrt"):
    """A copy of the finished cart, so the reference image is never written."""
    t = TCRT.read("build/ultima-collection.tcrt")
    TCRT(data_address=t.data_address, data_length=t.data_length, call_address=t.call_address,
         filename="ULTIMA COLL", flash=bytes(t.flash.ljust(regions.FLASH_SIZE, b"\xff"))
         ).write(out, trim=False)
    return out


def wait_stop(v, timeout):
    v.sock.sendall(b"x\n")
    seen, end = "", time.time() + timeout
    while time.time() < end and "Stop on" not in seen:
        seen += v._drain(0.2)
    return "Stop on" in seen


def key(v, code, bp="b80c", timeout=30):
    """One key, delivered at the poll at bp."""
    v.cmd(f"break {bp}", wait=0.2)
    ok = wait_stop(v, timeout)
    v.cmd("delete", wait=0.2)
    if ok:
        v.poke(0x0277, bytes([code]))
        v.poke(0x00C6, bytes([1]))
    return ok


def gkey(v, code, timeout=30):
    return key(v, code, bp=f"{syms()['kb_take']:04x}", timeout=timeout)


def start(page_keys="", opts_or=0, out="build/u3drive.tcrt"):
    v = Vice(image(out), update_tcrt=True)
    v.run(8)
    v.cmd("keybuf 3", wait=0.3)
    v.run(4)
    for k in page_keys:
        v.cmd(f"keybuf {k}", wait=0.3)
        v.run(2)
    v.cmd("keybuf l", wait=0.3)
    v.run_to(0x0200, timeout=60)
    if opts_or:
        s = syms()
        v.cmd("bank ram", wait=0.2)
        o = v.mem(s["pt_opts"], s["pt_opts"])[0]
        v.poke(s["pt_opts"], bytes([o | opts_or]))
    v.run(25)
    key(v, 0x20)
    v.run(8)
    key(v, 0x4F)
    v.run(3)
    for k in CREATE:
        key(v, k)
        v.run(2.5)
    v.run(12)
    return v
