#!/usr/bin/env python3
"""Ultima 6: a map-window shift timed on the cart and on the original disks.

    python -m tools.vice.u6_shift_bench [cart|disk|both|ef] [--shifts N]

A window shift is game $22C5's: on the surface, with the party's window x/y
($72/$73) below $14 or at least $EC, $22E0 calls the save ($3E83: the four
object files, the BAMs, the 3 KiB state to 1A T6 S9-20), then the window is
recentred and the new window's object files are loaded.  Timed in CPU
cycles (VICE's stopwatch, so warp does not matter) from $22E0 to the next
frame drawn ($08AD), split at $22E3 (the save returned).

cart: Journey Onward from a copy of the built cart, as u6_keep_check.py.
disk: the six original disks copied to /tmp/u6bench, x64sc with true drive
emulation on a 1541, booted from 3B, Journey Onward poked as on the cart
($C025), each "#xx" disk check ($2823 in game) answered by attaching the
disk it asks for before it looks -- so no swap prompt is ever shown.
Both: the party's x poked to $13 and a step west (or the other ways if
west is blocked), the same as u6_keep_check.py.
"""
import glob
import os
import re
import shutil
import socket
import subprocess
import sys
import time

from ultima import paths
os.chdir(paths.ROOT)
from tools.vice import menu_check
from tools.vice.vice_mon import Vice

PAL = 985248
SHIFT, SAVED, RENDER = 0x22E0, 0x22E3, 0x08AD
CHECK = 0x2823                          # game: X = disk index into $289C
PROMPT = 0x284E                         # game: the check failed, "Please insert"
DISKS = {0: "1A", 2: "1B", 4: "2A", 6: "2B", 8: "3A", 10: "3B"}
WORK = "/tmp/u6bench"


class DiskVice(Vice):
    """Vice on disk images, no tapecart, true drive emulation."""

    def __init__(self, boot, port=6514):
        self.port, self.emu, self.logfile, self.bin = port, "x64sc", None, None
        cmd = ["x64sc", "-warp", "-drive8type", "1541", "-drive8truedrive",
               "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}",
               "-autostart", boot]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        self.sock = None
        for _ in range(100):
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=2)
                break
            except OSError:
                time.sleep(0.1)
        if not self.sock:
            self.kill()
            raise RuntimeError("could not reach the remote monitor")
        self.sock.settimeout(30)
        self._drain(0.4)


def wait_stop(v, timeout):
    end, seen = time.time() + timeout, ""
    while time.time() < end:
        seen += v._drain(0.5)
        if "Stop on" in seen or re.search(r"^\.C:[0-9a-f]{4}", seen, re.M):
            return seen
    return None


def regs(v):
    out = v.cmd("r", wait=0.4)
    line = [l for l in out.splitlines() if l.startswith(".;")][-1].split()
    return int(line[0][2:], 16), int(line[-1]), int(line[1], 16), out


def disk_path(tag):
    return os.path.join(WORK, f"u6-{tag.lower()}.d64")


class Swapper:
    """Answer game's disk checks: a breakpoint at $2823, the disk attached."""

    def __init__(self, v):
        self.v, self.current = v, "3B"

    def handle(self, pc, x):
        if pc == PROMPT:
            # the check failed once anyway (the drive had not seen the new
            # disk yet): RETURN at "Please insert", and it checks again
            self.v.cmd("keymatrix 0 1 +15", wait=0.1)
            print("  prompt shown: RETURN", flush=True)
            return True
        if pc != CHECK:
            return False
        if x not in DISKS or self.v.mem(CHECK, CHECK + 5) != bytes.fromhex("bd9c288d9a28"):
            return True                 # not game's check (another program there): go on
        want = DISKS[x]
        if want != self.current:
            self.v.cmd(f'attach "{disk_path(want)}" 8', wait=0.8)
            self.current = want
            print(f"  disk check: {want} attached", flush=True)
        return True


def resume_until(v, stops, swapper, timeout):
    """Continue, answering disk checks, until one of `stops` is hit."""
    while True:
        v.sock.sendall(b"x\n")
        seen = wait_stop(v, timeout)
        if not seen:
            v.cmd("", wait=0.3)
            return None
        pc, sw, x, _ = regs(v)
        if swapper and swapper.handle(pc, x):
            continue
        if pc in stops:
            return pc, sw
        # anything else (a stray stop): go on


def shifts(v, n, swapper, label):
    results = []
    for k in range(n):
        got = None
        for way in (4, 1, 2, 8):                     # west, north, south, east
            v.poke(0x72, b"\x13" if way != 8 else b"\x14")
            v.cmd(f"joystick 2 {way} +6", wait=0.1)
            v.cmd(f"break {SHIFT:04x}", wait=0.1)
            got = resume_until(v, {SHIFT}, swapper, 8)
            v.cmd(f"delete", wait=0.2)
            if swapper:
                v.cmd(f"break {CHECK:04x}", wait=0.1)
                v.cmd(f"break {PROMPT:04x}", wait=0.1)
            if got:
                break
        if not got:
            v.shot(f"build/u6_bench_{label}_{k}.png")
            print(f"{label} shift {k}: did not start", flush=True)
            continue
        t0 = got[1]
        for a in (SAVED, RENDER):
            v.cmd(f"break {a:04x}", wait=0.1)
        _, t1 = resume_until(v, {SAVED}, swapper, 600)
        v.cmd(f"delete", wait=0.2)
        if swapper:
            v.cmd(f"break {CHECK:04x}", wait=0.1)
            v.cmd(f"break {PROMPT:04x}", wait=0.1)
        v.cmd(f"break {RENDER:04x}", wait=0.1)
        _, t2 = resume_until(v, {RENDER}, swapper, 600)
        v.cmd(f"delete", wait=0.2)
        if swapper:
            v.cmd(f"break {CHECK:04x}", wait=0.1)
            v.cmd(f"break {PROMPT:04x}", wait=0.1)
        save, rest = (t1 - t0) / PAL, (t2 - t1) / PAL
        results.append((save, rest))
        print(f"{label} shift {k}: {save + rest:6.2f} s  (save {save:5.2f} s, "
              f"then load and draw {rest:5.2f} s)", flush=True)
        v.run(3)
    return results


def cart(n):
    extra = ["-reu", "-reusize", os.environ["U6_REU"]] if os.environ.get("U6_REU") else None
    v = Vice(menu_check.with_autokey(6), update_tcrt=False, extra=extra)
    try:
        v.u6_journey_onward()                                  # Journey onward
        v.run(50.0)
        v.shot("build/u6_bench_cart_play.png")
        return shifts(v, n, None, "cart")
    finally:
        v.quit()


def ef(n):
    """The EasyFlash build (ef/, the side quest), from a copy of its .crt."""
    shutil.copy("build/ultima6-ef.crt", "/tmp/u6bench-ef.crt")
    v = Vice(None, easyflash="/tmp/u6bench-ef.crt")
    try:
        v.ef_launch("j")                                       # Journey onward
        v.run(50.0)
        v.shot("build/u6_bench_ef_play.png")
        return shifts(v, n, None, "ef")
    finally:
        v.quit()


def disk(n):
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    for src in glob.glob(os.path.join(paths.STAND_INS, "u6-*.d64")):
        shutil.copy(src, WORK)
    v = DiskVice(disk_path("3B"))
    sw = Swapper(v)
    try:
        # the cold start, once loaded: Journey onward
        v.cmd("break c023", wait=0.2)
        if not resume_until(v, {0xC023}, None, 300):
            v.shot("build/u6_bench_disk_boot.png")
            raise SystemExit("disk: never reached $C023")
        v.cmd("delete", wait=0.2)
        v.cmd("bank ram", wait=0.2)
        print("  at $C023:", v.mem(0xC023, 0xC026).hex(" "), flush=True)
        v.poke(0xC025, bytes([0xF0, (0xC054 - 0xC027) & 0xFF]))
        # into the game: answer disk checks until the first frame is drawn
        v.cmd(f"break {CHECK:04x}", wait=0.1)
        v.cmd(f"break {PROMPT:04x}", wait=0.1)
        v.cmd(f"break {RENDER:04x}", wait=0.1)
        if not resume_until(v, {RENDER}, sw, 600):
            v.shot("build/u6_bench_disk_start.png")
            raise SystemExit("disk: the game never drew a frame")
        v.cmd(f"delete", wait=0.2)
        v.cmd(f"break {CHECK:04x}", wait=0.1)
        v.cmd(f"break {PROMPT:04x}", wait=0.1)
        # let it settle, answering any check meanwhile
        end = time.time() + 20
        while time.time() < end:
            v.sock.sendall(b"x\n")
            seen = wait_stop(v, 2)
            if seen:
                pc, _, x, _ = regs(v)
                sw.handle(pc, x)
        v.cmd("", wait=0.3)
        v.shot("build/u6_bench_disk_play.png")
        return shifts(v, n, sw, "disk")
    finally:
        v.quit()


def summary(label, res):
    if not res:
        return
    tot = [a + b for a, b in res]
    print(f"{label}: {len(res)} shifts, total {min(tot):.2f}-{max(tot):.2f} s, "
          f"mean {sum(tot) / len(tot):.2f} s (save {sum(a for a, _ in res) / len(res):.2f}, "
          f"load+draw {sum(b for _, b in res) / len(res):.2f})")


def main():
    what = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "both"
    n = int(sys.argv[sys.argv.index("--shifts") + 1]) if "--shifts" in sys.argv else 3
    res = {}
    if what in ("disk", "both"):
        res["disk"] = disk(n)
    if what in ("cart", "both"):
        res["cart"] = cart(n)
    if what == "ef":
        res["ef"] = ef(n)
    for k, r in res.items():
        summary(k, r)


if __name__ == "__main__":
    main()
