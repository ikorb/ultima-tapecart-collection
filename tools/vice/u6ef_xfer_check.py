#!/usr/bin/env python3
"""The EasyFlash launcher's export and import (ultima/ef/efpage.s), in VICE with a
real 1541 (true drive emulation) and VICE's own EAPI -- what
tests/test_ef_xfer.py checks on a model.

    python -m tools.vice.u6ef_xfer_check [file] [disks] [tapecart] [play]
                                                (default: all four)

file:  the image with test_ef_xfer's logged world; E F Y RETURN onto a blank
       disk, the file compared with the host model's; then the image with an
       empty log and that disk: I F Y RETURN, and the log the .crt holds after
       VICE's clean exit (read through efinit.s on the host) compared with the
       logged world.
disks: the logged world exported onto copies of the original 1A and 1B (E D
       Y, RETURN, 1B attached, RETURN), each compared with the host model's
       export; then those disks imported into the empty log (I D Y ...), the
       log compared again.
tapecart: both carts plugged in, the collection's .tcrt (its U6 log played:
       test_ef_xfer.tp_world) on the tape port.  E T Y: the tapecart's log
       VICE writes back compared with the host model's export; then I T Y
       into an empty log, the .crt's log compared with the logged world.
       The copy's time in each direction (VICE's stopwatch).
play:  test_u6_xfer's made-up played session imported into
       the EasyFlash (the host model), E T Y onto the collection in VICE,
       then the tapecart alone: the menu picks Ultima VI, Journey onward,
       and at the main loop's first turn ($0449) the game's save area in RAM
       ($5400-$5FFF) is the played disk's 1A T6 S9-20; a screenshot 20 s on,
       to build/ef/xfercheck/play.png.

About two minutes each.  Needs VICE 3.11 or later (keymatrix, the tapecart).
"""
import os
from ultima import paths
import sys
import time
from pathlib import Path

os.chdir(paths.ROOT)

from ultima.ef import efcrt                                # noqa: E402
from ultima.flash.tcrt import TCRT                       # noqa: E402
from tools.vice.vice_mon import Vice                   # noqa: E402
from ultima.sim.fakedrive import Disk                  # noqa: E402
from tests import test_ef_xfer as T                    # noqa: E402
from tests.test_file_xfer import blank_d64, NAMES     # noqa: E402
from tools.vice.xfer_file_check import launcher_text   # noqa: E402
from tools.vice.u6_shift_bench import wait_stop, regs

OUT = "build/ef/xfercheck"
DRIVE = 8


def crt(flash, name):
    path = os.path.join(OUT, name)
    efcrt.write(path, bytes(flash), "Ultima VI")        # the log too
    return path


def wait_for(v, words, timeout=120):
    end = time.time() + timeout
    while time.time() < end:
        v.run(1)
        v.cmd("bank ram", wait=0.1)
        text = launcher_text(v)
        if any(w.lower() in text.lower() for w in words):
            return text
    raise RuntimeError(f"no {words} on the screen:\n{launcher_text(v)}")


def session(image, disk, keys, swap=None, port=6560):
    """The launcher: keys (E or I, then D or F), Y, RETURN at each disk
    prompt (swap: the disk for the second), until Done; then J, so the
    machine leaves the launcher, and a clean exit writes the .crt back."""
    v = Vice(None, easyflash=image, update_tcrt=True, port=port,
             extra=[f"-{DRIVE}", disk, f"-drive{DRIVE}type", "1541", f"-drive{DRIVE}truedrive"])
    try:
        wait_for(v, ["Journey onward", "No saved game"], 30)
        for k in keys:
            v.tap(k, gap=1)
        wait_for(v, ["(Y/N)"], 30)
        v.tap("y", gap=1)
        wait_for(v, ["press RETURN"], 120)
        v.tap("\r", gap=1)
        if swap:
            wait_for(v, ["Dungeon (1B)"], 900)
            v.cmd(f'attach "{os.path.abspath(swap)}" {DRIVE}', wait=1.0)
            v.run(2)
            v.tap("\r", gap=1)
        text = wait_for(v, ["Done.", "Failed", "The file is", "failed"], 900)
        return text
    finally:
        v.quit()


def check_file(t):
    os.makedirs(OUT, exist_ok=True)
    src, _want, _save = t.logged_world()
    disk = os.path.join(OUT, "file.d64")
    with open(disk, "wb") as fh:
        fh.write(blank_d64(b"SAVES"))
    text = session(crt(src, "file_src.crt"), disk, ["e", "f"])
    got = Disk(Path(disk).read_bytes()).read_file(NAMES["u6"])
    _s, drv, _d, _t = t.launch(src, [T.E, T.F, T.Y, T.RET, T.SPACE, T.J], blank_d64())
    want = drv.disk.read_file(NAMES["u6"])
    ok_e = "Done." in text and got == want
    print(f"file: export {'done' if 'Done.' in text else 'FAILED'}, {len(got or b'')} bytes, "
          f"{'as the host model writes it' if got == want else 'NOT as the host model writes it'}")
    dst = crt(t.fresh(gen=2), "file_dst.crt")
    text = session(dst, disk, ["i", "f"], port=6564)
    back, _n = efcrt.read(dst)
    same = t.active(back)[2] == t.active(src)[2]
    print(f"file: import {'done' if 'Done.' in text else 'FAILED'}; the log "
          f"{'holds the exported world' if same else 'DIFFERS from the exported world'}")
    if not (ok_e and same):
        print(text)
    return ok_e and same


def tp_session(image, tcrt, key, port, lsym):
    """The launcher with the tapecart on the tape port: key (E or I), T, Y,
    until Done; both images written back at a clean exit.  Returns the
    screen and the copy's time in seconds of a PAL C64 (VICE's stopwatch,
    from tx_copy to x_done2: the erases, the copy, the header)."""
    v = Vice(None, easyflash=image, update_tcrt=True, port=port,
             extra=["-tapeport1device", "6", "-tcrt", tcrt, "-tapecartupdatetcrt"])
    try:
        wait_for(v, ["Journey onward", "No saved game"], 30)
        v.tap(key, gap=1)
        v.tap("t", gap=1)
        wait_for(v, ["(Y/N)", "Press a key"], 60)
        v.cmd(f"break {lsym['tx_copy']:04x}", wait=0.2)
        v.cmd(f"break {lsym['x_done2']:04x}", wait=0.2)
        row = next(r for r, keys in enumerate(v.MATRIX) if "y" in keys)
        v.cmd(f"keymatrix {row:x} {v.MATRIX[row].index('y'):x} +4", wait=0.1)
        sw = []
        for _ in range(2):
            v.sock.sendall(b"x\n")
            if not wait_stop(v, 900):
                raise RuntimeError("the copy never reached its breakpoint")
            sw.append(regs(v)[1])
        v.cmd("del", wait=0.2)
        text = wait_for(v, ["Done.", "Failed", "failed", "none answers", "no Ultima", "no saved game"], 900)
        return text, (sw[1] - sw[0]) / 985248
    finally:
        v.quit()


def check_tapecart(t):
    os.makedirs(OUT, exist_ok=True)
    src, _want, _save = t.logged_world()
    tflash, tp_want = t.tp_world(gen=2)
    tpath = os.path.join(OUT, "collection.tcrt")
    img = TCRT.read(T.X.IMAGE)
    img.flash = bytes(tflash)
    img.write(tpath, trim=False)
    text, secs = tp_session(crt(src, "tp_src.crt"), tpath, "e", 6576, t.p["lsym"])
    got = T.TCRT.read(tpath).flash.ljust(len(tflash), b"\xff")
    cart = T.FakeCart(tflash)
    t.launch(src, [T.E, T.T, T.Y, T.SPACE, T.J], tapecart=cart)
    same = bytes(got) == bytes(cart.flash)
    print(f"tapecart: export {'done' if 'Done.' in text else 'FAILED'} in {secs:.1f} s (PAL, VICE); "
          f"its flash {'is the host model export' if same else 'DIFFERS from the host model export'}; "
          f"its log {'holds the exported world' if t.tp_active(got)[2] == t.active(src)[2] else 'DIFFERS'}")
    ok_e = "Done." in text and same
    if not ok_e:
        print(text)
    img.flash = bytes(tflash)
    img.write(tpath, trim=False)
    dst = crt(t.fresh(gen=2), "tp_dst.crt")
    text, secs = tp_session(dst, tpath, "i", 6580, t.p["lsym"])
    back, _n = efcrt.read(dst)
    same = t.active(back)[2] == tp_want
    print(f"tapecart: import {'done' if 'Done.' in text else 'FAILED'} in {secs:.1f} s (PAL, VICE); the log "
          f"{'holds the tapecart world' if same else 'DIFFERS from the tapecart world'}")
    if not same:
        print(text)
    return ok_e and same


def check_play(t):
    os.makedirs(OUT, exist_ok=True)
    played = {tag: T.X.original(tag, T.X.PLAYED) for tag in T.X.DISKS}
    ef, _text = t.imported(t.fresh(), played["1A"], played["1B"])
    tpath = os.path.join(OUT, "play.tcrt")
    TCRT.read(T.X.IMAGE).write(tpath, trim=False)
    text, secs = tp_session(crt(ef, "play_src.crt"), tpath, "e", 6584, t.p["lsym"])
    print(f"play: export {'done' if 'Done.' in text else 'FAILED'} in {secs:.1f} s (PAL, VICE)")
    from tools.vice import menu_check
    menu_check.IMAGE = tpath
    v = Vice(menu_check.with_autokey(6), update_tcrt=False, port=6588)
    try:
        v.u6_journey_onward()
        if not v.run_to(0x0449, 120):           # the main loop's first turn
            raise RuntimeError("Journey onward never reached the main loop")
        v.cmd("bank ram", wait=0.2)
        got = v.mem(0x5400, 0x5FFF)
        v.run(20.0)
        v.shot(os.path.abspath(os.path.join(OUT, "play.png")))
    finally:
        v.quit()
    want = b"".join(bytes(Disk(played["1A"]).sector(6, sec)) for sec in range(9, 21))
    diff = [0x5400 + i for i, (a, b) in enumerate(zip(got, want)) if a != b]
    print(f"play: Journey onward from the tapecart; $5400-$5FFF "
          f"{'is the played save area' if not diff else f'differs in {len(diff)} bytes, first ${diff[0]:04x}'}")
    return "Done." in text and not diff


def check_disks(t):
    os.makedirs(OUT, exist_ok=True)
    src, _want, _save = t.logged_world()
    paths = {}
    for tag in ("1A", "1B"):
        paths[tag] = os.path.join(OUT, f"{tag}.d64")
        with open(paths[tag], "wb") as fh:
            fh.write(T.X.original(tag))
    text = session(crt(src, "disks_src.crt"), paths["1A"], ["e", "d"], swap=paths["1B"], port=6568)
    d1a, d1b = t.export(src, T.X.original("1A"), T.X.original("1B"))
    same = all(Disk(Path(paths[tag]).read_bytes()).data == d.data for tag, d in (("1A", d1a), ("1B", d1b)))
    print(f"disks: export {'done' if 'Done.' in text else 'FAILED'}; the disks "
          f"{'are the host model export' if same else 'DIFFER from the host model export'}")
    ok_e = "Done." in text and same
    dst = crt(t.fresh(gen=2), "disks_dst.crt")
    text = session(dst, paths["1A"], ["i", "d"], swap=paths["1B"], port=6572)
    back, _n = efcrt.read(dst)
    same = t.active(back)[2] == t.active(src)[2]
    print(f"disks: import {'done' if 'Done.' in text else 'FAILED'}; the log "
          f"{'holds the exported world' if same else 'DIFFERS from the exported world'}")
    if not (ok_e and same):
        print(text)
    return ok_e and same


def main():
    what = sys.argv[1:] or ["file", "disks", "tapecart", "play"]
    T.TestEFLauncher.setUpClass()
    t = T.TestEFLauncher("test_reset_makes_an_empty_log")
    results = [{"file": check_file, "disks": check_disks, "tapecart": check_tapecart, "play": check_play}[w](t) for w in what]
    print("OK" if all(results) else "DIFFERENCES")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
