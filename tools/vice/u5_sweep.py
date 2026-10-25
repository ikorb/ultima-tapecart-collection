#!/usr/bin/env python3
"""Call Ultima 5's disk entries directly and compare the results with the disks.

    U5_SAVE_FROM=DIR python -m ultima.build build/u5dbg.tcrt
    python -m tools.vice.u5_sweep [step] [--ar | --c128 | --ef] [--sprites] [--menu]

Journey Onward from the seeded save, then park at u5_blk_fetched -- the end
of a raw block read, where the cart is idle and in command mode, which is
what makes hijacking the PC safe -- and from a stub in RAM the memmap shows
unused ($0335-$037F):

  * $6C00 (A = page, X = sector, Y = track) for the first and last block of
    every disk's run and every `step`-th block between, into $4400;
  * $6C24 with an inline name for a set of files, each compared at its load
    address.

Every result is read back with `bank ram` and compared with the original
disk image (as build.py patched it).  The game is not resumed afterwards.

--ar: with an Action Replay 6 ($AR_ROM, default ar-60pal.bin; VICE's -cartar5), whose
music glue makes the driver's reads 2-bit through the AR's RAM.  (The stub
at $0335 is then over the glue's play and restart entries, which nothing
calls while the sweep runs.)

--ef: started from the Ultima VI EasyFlash's launcher (make ef; its 5,
ef/efu5.s), whose music glue in the EasyFlash's bank makes the reads 2-bit
(armusic.s EF_MUSIC).  The tapecart holds the cart as built (read only, no
saved game needed): parked at the main menu's key poll -- the cart idle,
the music playing -- instead of Journey Onward.

--menu (with --ef always): the cart as built instead of the debug image,
parked at the main menu's key poll -- no saved game needed.

--c128: Ultima V in C128 mode (x128, the launcher on build/u5c128.d64),
whose reads go through bank 1 (sub128.s); parked at the first $6C24 after
the launch.  --sprites: sprite 0 on ($D015 = 1) before every call, which
makes the reads 1-bit -- the same build's other path, for timing.
"""
import os
import re
import sys
import time
from pathlib import Path

from tools.vice import menu_check
from ultima.disks.d64 import D64
from tools.vice.u5_drive import U5, ar_boot

from ultima.games.u5 import build as u5b             # noqa: E402

STUB = 0x0335
BUF = 0x44
DUMP = os.path.abspath("build/u5_sweep.bin")
# files to load by name: (disk, name) -- loads that land clear of the stub,
# the driver ($6C00-$7AFF) and the page this harness reads from
FILES = [(2, "MAIN.OUT"), (3, "MAIN.TWN"), (7, "MAIN.DNG"), (2, "MAIN.COMBAT"),
         (3, "TALK.AR"), (1, "CREATE"), (1, "STARTUP"), (2, "SHRINE"), (4, "U")]


def dump(v, start, length):
    if os.path.exists(DUMP):
        os.remove(DUMP)
    v.cmd(f'bsave "{DUMP}" 0 {start:04x} {start + length - 1:04x}', wait=0.3)
    for _ in range(50):
        if os.path.exists(DUMP) and os.path.getsize(DUMP) >= length:
            break
        time.sleep(0.05)
    return Path(DUMP).read_bytes()


CYCLES = {"raw": 0, "named": 0}


SPRITES = [None]                            # --sprites: $D015 before each call


def call(v, code, done, timeout=30, kind=None):
    if SPRITES[0] is not None:
        v.cmd("bank io", wait=0.1)
        v.poke(0xD015, bytes([SPRITES[0]]))
        v.cmd(f"bank {RAM}", wait=0.1)
    v.poke(STUB, code)
    v.cmd(f"break {done:04x}", wait=0.2)
    v.cmd("stopwatch reset", wait=0.1)
    v.sock.sendall(f"g {STUB:04x}\n".encode())
    seen, end = "", time.time() + timeout
    while time.time() < end and f"{done:04x}" not in seen.lower():
        seen += v._drain(0.2)
    v.cmd("delete", wait=0.2)
    if kind:
        m = re.search(r"Stopwatch:\s*(\d+)", v.cmd("stopwatch", wait=0.3))
        CYCLES[kind] += int(m.group(1)) if m else 0
    return f"{done:04x}" in seen.lower()


def path(v, s):
    """Which read tclib's fetches point at now, and $C8 (bit 6: an AR)."""
    c8 = v.mem(0xC8, 0xC8)[0]
    f = v.mem(s["tc_fetch"] + 1, s["tc_fetch"] + 2)
    b = v.mem(s["tc_sb_call"] + 1, s["tc_sb_call"] + 2)
    name = {s["tc_getbyte"]: "tc_getbyte", s.get("u5_arget", -1): "u5_arget"}
    return (f"$C8 = ${c8:02x}, tc_fetch -> {name.get(f[0] | f[1] << 8, hex(f[0] | f[1] << 8))}, "
            f"tc_sb_call -> {name.get(b[0] | b[1] << 8, hex(b[0] | b[1] << 8))}")


C128_DISK = os.path.abspath("build/u5c128.d64")
RAM = "ram"                                 # the monitor's bank for the dumps


def boot_c128():
    """x128 on a copy of the cart, the launcher from the disk; parked at the
    first $6C24 after it (the cart idle, the MMU on bank 0)."""
    import shutil
    from tools.vice.vice_mon import Vice
    from tools.vice.u5_drive import symbols
    if not os.path.exists(C128_DISK):
        raise SystemExit(f"no {C128_DISK}: make build/u5c128.d64 (make play128 makes it too)")
    shutil.copy("build/ultima-collection.tcrt", "build/auto128.tcrt")
    v = Vice("build/auto128.tcrt", emu="x128", update_tcrt=True, extra=["-8", C128_DISK],
             keybuf='run"ultima v 128"\n', log="build/u5_sweep.log")
    return v, symbols("build/u5drv128.sym")


EF_IMAGE = "build/ultima6-ef.crt"


def boot_ef(log="build/u5_sweep.log", port=6510, update=False):
    """Both carts: the EasyFlash (a copy of its .crt) and menu_check.IMAGE
    on the tapecart (written back with `update`, else read only); the
    EasyFlash's 5, on to the init stub."""
    import shutil
    from tools.vice.vice_mon import Vice
    from tools.vice.u5_drive import symbols
    if not os.path.exists(EF_IMAGE):
        raise SystemExit(f"no {EF_IMAGE}: make ef")
    shutil.copy(EF_IMAGE, "build/autoef.crt")
    v = Vice(None, easyflash="build/autoef.crt", log=log, port=port,
             extra=["-tapeport1device", "6", "-tcrt", os.path.abspath(menu_check.IMAGE),
                    "-tapecartloglevel", "2"] + (["-tapecartupdatetcrt"] if update else []))
    try:
        v.ef_launch_u5()
    except Exception:
        v.quit()
        raise
    u = U5.__new__(U5)
    u.v, u.sym = v, symbols()
    return u


def main():
    global RAM
    flags = ("--ar", "--c128", "--ef", "--sprites", "--menu")
    args = [a for a in sys.argv[1:] if a not in flags]
    step = int(args[0]) if args else 13
    ar = "--ar" in sys.argv
    c128 = "--c128" in sys.argv
    ef = "--ef" in sys.argv
    menu = ef or "--menu" in sys.argv
    sprites = "--sprites" in sys.argv
    parts = u5b.parts()                     # the patched bodies, as flashed
    disks = {n: D64(u5b.disk_path(t)) for n, t in u5b.TAGS.items()}
    runs = u5b.sector_runs(disks)
    if c128:
        v, s = boot_c128()
        RAM = "ram00"
    elif ef:
        menu_check.IMAGE = "build/ultima-collection.tcrt"
        u = boot_ef()
        v, s = u.v, u.sym
    else:
        menu_check.IMAGE = "build/ultima-collection.tcrt" if menu else "build/u5dbg.tcrt"
        image = menu_check.with_autokey(5)
        for attempt in range(6):
            u = U5(image, log="build/u5_sweep.log", ar=ar)
            if not ar or ar_boot(u.v):
                break
            u.v.quit()
        else:
            print("the AR never booted into the game")
            return 1
        v, s = u.v, u.sym
    SPRITES[0] = 0x01 if sprites else (0x00 if c128 else None)
    bad = total = 0
    try:
        if c128:
            print("parked:", v.run_to(0x6C24, timeout=180), flush=True)
            v.cmd(f"bank {RAM}", wait=0.2)
        elif menu:
            print("menu:", u.boot_to_menu(), "; " + path(v, s), flush=True)
            v.cmd("bank ram", wait=0.2)
        else:
            print("menu:", u.boot_to_menu(), flush=True)
            print("journey:", u.menu_pick(0), flush=True)
            v.run(20.0)
            v.cmd("bank ram", wait=0.2)
            print("parked:", v.run_to(s["u5_blk_fetched"], timeout=120), flush=True)

        for n in sorted(disks):
            if runs[n] is None:
                continue
            first, count = runs[n]
            blocks = sorted(set([first, first + count - 1] + list(range(first, first + count, step))))
            nbad = 0
            for blk in blocks:
                t, sec = D64.from_linear(blk)
                v.poke(s["u5_disk"], bytes([n]))
                # sei / lda #BUF / ldx #sec / ldy #t / jsr $6C00 / nop / nop
                code = bytes([0x78, 0xA9, BUF, 0xA2, sec, 0xA0, t, 0x20, 0x00, 0x6C, 0xEA, 0xEA])
                if not call(v, code, STUB + 10, kind="raw"):
                    print(f"  HANG disk {n} T{t} S{sec}", flush=True)
                    return 1
                got = dump(v, BUF << 8, 256)
                total += 1
                if got != bytes(disks[n].sector(t, sec)):
                    bad += 1; nbad += 1
                    print(f"  BAD disk {n} block {blk} (T{t} S{sec})", flush=True)
            where = "" if c128 else "; " + path(v, s)
            print(f"disk {n}: {len(blocks)} blocks, {nbad} bad{where}", flush=True)

        for n, name in FILES:
            body = parts["bodies"][(n, name)]
            load = None
            for d in (disks[n],):
                data, _ok = d.file(name)
                load = data[0] | data[1] << 8
            v.poke(s["u5_disk"], bytes([n]))
            # sei / ldx #0 / jsr $6C24 / "NAME",0 / nop / nop
            code = bytes([0x78, 0xA2, 0x00, 0x20, 0x24, 0x6C]) + name.encode() + b"\x00\xEA\xEA"
            if not call(v, code, STUB + len(code) - 2, kind="named"):
                print(f"  HANG loading {n}/{name}", flush=True)
                return 1
            got = dump(v, load, len(body))
            total += 1
            ok = got == body
            bad += not ok
            print(f"  {'ok ' if ok else 'BAD'} {n}/{name}: {len(body)} bytes at ${load:04x}", flush=True)
        # the torch, items and powers options: pt_opts = TORCH | ITEMS | POWERS,
        # every file with a site of one loaded by name -- the driver's pt_apply
        # streams its table from the cart -- and each must come out as the
        # disk's with exactly those patches applied (as pt_apply's rule: the
        # option on and every original byte in place), nothing else changed
        from ultima.launcher import patches
        opts = patches.TORCH | patches.ITEMS | patches.POWERS
        v.poke(s["pt_opts"], bytes([opts]))
        tag_of = {t: k for k, t in u5b.TAGS.items()}
        sites = [(w, name) for w, _a, name in u5b.TORCH_SITES + u5b.KEY_SITES + u5b.GEM_SITES]
        sites += [(w, name) for w, _m, _c, name in u5b.CAST_SITES]
        sites += [(u5b.TAGS[n], "MAIN.OUT") for n in u5b.TELE]
        for where, name in sorted(set(sites)):
            tag = tag_of[u5b._site_disks(where)[0]]
            body = bytes(parts["bodies"][(tag, name)])
            load = parts["loads"][(tag, name)]
            v.poke(s["u5_disk"], bytes([tag]))
            code = bytes([0x78, 0xA2, 0x00, 0x20, 0x24, 0x6C]) + name.encode() + b"\x00\xEA\xEA"
            if not call(v, code, STUB + len(code) - 2):
                print(f"  HANG loading {tag}/{name} with the options", flush=True)
                return 1
            got = dump(v, load, len(body))
            want = bytearray(body)
            applied = []
            for pt in u5b.OPTION_PATCHES:
                o = pt.addr - load
                if pt.option & opts and 0 <= o and o + len(pt.orig) <= len(body) \
                        and body[o:o + len(pt.orig)] == pt.orig:
                    want[o:o + len(pt.new)] = pt.new
                    applied.append(f"${pt.addr:04x}")
            total += 1
            ok = got == bytes(want) and applied
            bad += not ok
            diff = [f"${load + i:04x}" for i in range(len(body)) if got[i] != want[i]]
            print(f"  {'ok ' if ok else 'BAD'} options {u5b.TAGS[tag]} {name}: {', '.join(applied)}"
                  + (f"; differs at {diff[:8]}" if diff else ""), flush=True)
        v.poke(s["pt_opts"], b"\x00")
    finally:
        v.quit()
    print(f"{total} transfers checked, {bad} bad")
    print(f"cycles: raw blocks {CYCLES['raw']}, named files {CYCLES['named']}")
    try:
        log = Path("build/u5_sweep.log").read_text(errors="replace")
        print(f"cart: {log.count('received command 0x11')} READ_FLASH_FAST, "
              f"{log.count('received command 0x10')} READ_FLASH")
    except OSError:
        pass
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
