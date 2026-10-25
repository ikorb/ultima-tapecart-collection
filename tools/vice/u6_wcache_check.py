#!/usr/bin/env python3
"""Ultima 6 with an REU: the write cache (ultima/games/u6/u6wc.s), in VICE.

    python -m tools.vice.u6_wcache_check [cache|plain] [--shifts N] [--saves N] [--reu KB]

Journey Onward from a copy of the cart with an REU (256 KB unless --reu),
then window shifts and saves (Shift-S, Y), each timed from its start to the
next frame drawn and with the log pages it appended counted (u6_logdata).
`plain` points the resident back at the plain u6bulk once the game runs
(u6_bulkfl, u6_keep dropped): the read cache alone, as before the write
cache -- the same build, for a fair comparison.

Then VICE quits, writing the cart's flash back into the copy and the REU's
contents into an image, and the check is the write cache's invariant: every
copy the REU holds as valid (a count in bank 3, $0300+) is byte for byte the
log's newest version of its unit -- a chunk file's pages, a save sector.
And the state: the game's 3 KiB at $5400-$5FFF as the last save wrote it
(at $3EF0, the end of its sector loop) is what the log holds for 1A T6
S9-20, and what a second launch of the copy, without an REU, loads back
(the state load ends at $3EF0 too).
"""
import os
from ultima import paths
import shutil
import sys
import time

os.chdir(paths.ROOT)
from tools.vice import menu_check
from ultima.launcher import u6log
from ultima.flash.tcrt import TCRT
from tools.vice.u6_shift_bench import PAL, RENDER, SHIFT, regs, resume_until
from tools.vice.vice_mon import Vice
import importlib.util
from pathlib import Path

_spec = importlib.util.find_spec("ultima.games.u6.build")
u6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(u6)

SAVE = 0x3E83
LOOP_END = 0x3EF0                       # the save's and the state load's sector loop done
COPY = "/tmp/u6wc.tcrt"
REU_IMAGE = "/tmp/u6wc.reu"


def u24(b):
    return b[0] | b[1] << 8 | b[2] << 16


def log_state(v, r):
    return u24(v.mem(r["u6_logdata"], r["u6_logdata"] + 2)), u24(v.mem(r["u6_logdir"], r["u6_logdir"] + 2)), \
        int.from_bytes(v.mem(r["u6_dircount"], r["u6_dircount"] + 1), "little")


def timed(v, start, label, r, start_timeout=8, at_start=None):
    """Run to `start`, then to the next frame drawn: (seconds, pages appended).
    at_start: what Vice.u6_save_keys said (the breakpoint armed; True:
    stopped there already)."""
    if at_start:
        got = regs(v)[:2]
    else:
        if at_start is None:
            v.cmd(f"break {start:04x}", wait=0.1)
        got = resume_until(v, {start}, None, start_timeout)
    v.cmd("delete", wait=0.2)
    if not got:
        return None
    before = log_state(v, r)[0]
    t0 = got[1]
    v.cmd(f"break {RENDER:04x}", wait=0.1)
    got = resume_until(v, {RENDER}, None, 600)
    if not got:
        pc = regs(v)[0]
        v.shot(f"build/u6wc_stuck_{label.replace(' ', '_')}.png")
        print(f"{label}: no frame drawn, pc=${pc:04x}\n" + v.cmd("r", wait=0.4)
              + v.cmd(f"d {pc:04x} {pc + 24:04x}", wait=0.5)
              + v.cmd("m 13ca 13d9", wait=0.4) + v.cmd(f"m {r['u6_keep']:04x} {r['u6_keep']:04x}", wait=0.3)
              + v.cmd("m 0100 01ff", wait=0.6) + v.cmd("chis 400", wait=3.0),
              flush=True)
        raise SystemExit(2)
    t1 = got[1]
    v.cmd("delete", wait=0.2)
    after = log_state(v, r)[0]
    return (t1 - t0) / PAL, (after - before) // 256


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "cache"
    arg = lambda name, d: int(sys.argv[sys.argv.index(name) + 1]) if name in sys.argv else d
    n_shifts, n_saves, kb = arg("--shifts", 4), arg("--saves", 3), arg("--reu", 256)
    p = u6.parts()
    r = p["rsym"]
    import glob
    newest = max(os.path.getmtime(f) for f in glob.glob("ultima/games/u6/*.s") + glob.glob("ultima/games/u6/*.inc"))
    if os.path.getmtime(menu_check.IMAGE) < newest:
        raise SystemExit(f"{menu_check.IMAGE} is older than the U6 sources: make collection first")
    shutil.copy(menu_check.with_autokey(6), COPY)
    if os.path.exists(REU_IMAGE):
        os.remove(REU_IMAGE)
    with open(REU_IMAGE, "wb") as fh:
        fh.write(bytes(kb * 1024))
    v = Vice(COPY, update_tcrt=True,
             extra=["-reu", "-reusize", str(kb), "-reuimage", REU_IMAGE, "-reuimagerw"])
    results = []
    try:
        v.u6_journey_onward()
        v.run(50.0)
        rc_on = v.mem(u6.REU_ROOM["RC_VARS"], u6.REU_ROOM["RC_VARS"])[0]
        print(f"rc_on = {rc_on}; u6_bulkfl = {v.mem(r['u6_bulkfl'], r['u6_bulkfl'] + 6).hex(' ')}", flush=True)
        if rc_on != 1:
            raise SystemExit("the REU was not found")
        if mode == "plain":
            fl = bytearray()
            for org in (u6.BULK_B, u6.BULK_A):
                a = p["bulk_at"][org]
                fl += bytes([a >> 16, (a >> 8) & 0xFF, a & 0xFF])
                if org == u6.BULK_B:
                    fl.append(0xFF)
            v.poke(r["u6_bulkfl"], bytes(fl))
            v.poke(r["u6_keep"], b"\xff")
            print("plain: the resident fetches the plain u6bulk", flush=True)
        v.shot(f"build/u6wc_{mode}_play.png")
        for k in range(n_shifts):
            got = None
            for way in (4, 1, 2, 8):
                v.poke(0x72, b"\x13" if way != 8 else b"\x14")
                v.cmd(f"joystick 2 {way} +6", wait=0.1)
                got = timed(v, SHIFT, f"shift {k}", r, 5)
                if got:
                    break
            print(f"{mode} shift {k}: " + (f"{got[0]:6.2f} s, {got[1]} pages written" if got else "did not start"),
                  flush=True)
            if got:
                results.append(("shift", k) + got)
            v.run(3)
        for k in range(n_saves):
            mark = log_state(v, r)[0]
            begun = v.u6_save_keys(SAVE)
            got = timed(v, SAVE, f"save {k}", r, 20, at_start=begun)
            print(f"{mode} save {k}: " + (f"{got[0]:6.2f} s, {got[1]} pages written" if got else "did not start"),
                  flush=True)
            if not got:
                v.shot(f"build/u6wc_{mode}_save{k}_nostart.png")
                print(f"  (meanwhile {(log_state(v, r)[0] - mark) // 256} pages written: "
                      "the save ran before its breakpoint was set, if not 0)", flush=True)
            if got:
                results.append(("save", k) + got)
            v.run(3)
        # one more save, stopped at the end of its sector loop: the state it wrote
        if not v.u6_save_keys(LOOP_END) and not resume_until(v, {LOOP_END}, None, 60):
            raise SystemExit("the last save did not run")
        v.cmd("delete", wait=0.2)
        state = v.mem(0x5400, 0x5FFF)
        logdata, logdir, count = log_state(v, r)
        v.run(5)
        v.shot(f"build/u6wc_{mode}_end.png")
    finally:
        v.quit()
    time.sleep(1.0)

    # ---- the invariant: every valid copy is the log's newest -------------
    flash = bytes(TCRT.read(COPY).flash).ljust(0x200000, b"\xff")
    reu = Path(REU_IMAGE).read_bytes()
    newest = u6log.view(flash, logdir, count)
    sdir = p["sdir"]
    bang = {}
    for i in range(p["entries"]):
        e = flash[sdir + i * 20:sdir + (i + 1) * 20]
        if e[0] == 0x21:
            bang[e[16]] = (e[1:12].rstrip(b"\x00"), e[13], e[14], e[15])
    counts = reu[3 * 65536 + 0x300:3 * 65536 + 0x400]
    checked, bad = 0, []
    for ix, n in enumerate(counts):
        if not n:
            continue
        if ix >= 0x80:
            s = ix - 0x80
            k = bytes([1, 0, 6, s]).ljust(12, b"\x00")
            a = 2 * 65536 + (0xC0 | s) * 256
            got, want = reu[a:a + 256], newest.get(k)
            what = f"T6 S{s}"
        else:
            name, page, bank, _cap = bang[ix]
            k = (b"/" + name).ljust(12, b"\x00")
            a = bank * 65536 + page * 256
            got, want = reu[a:a + 256 * n], newest.get(k)
            what = name.decode()
        checked += 1
        if got != want:
            bad.append(what)
    print(f"invariant: {checked} valid copies checked, {len(bad)} differ from the log's newest"
          + (f": {bad}" if bad else ""), flush=True)

    logged = b"".join(newest.get(bytes([1, 0, 6, s]).ljust(12, b"\x00"), b"") for s in range(9, 21))
    print(f"the last save's state is the log's: {logged == state}", flush=True)

    # ---- a second launch, no REU: the state loaded back ------------------
    v = Vice(COPY, update_tcrt=False)
    try:
        v.u6_journey_onward()
        v.cmd(f"break {LOOP_END:04x}", wait=0.1)
        again = None
        for _ in range(3):                      # (the opening may pass it first)
            if resume_until(v, {LOOP_END}, None, 120):
                again = v.mem(0x5400, 0x5FFF)
                if again == state:
                    break
        v.cmd("delete", wait=0.2)
        v.run(40.0)
        v.shot(f"build/u6wc_{mode}_relaunch.png")
    finally:
        v.quit()
    print(f"relaunch: the state loaded back is the one saved: {again == state}", flush=True)
    for kind in ("shift", "save"):
        rs = [x for x in results if x[0] == kind]
        if rs:
            print(f"{mode} {kind}s: " + ", ".join(f"{t:.2f} s/{n}p" for _k, _i, t, n in rs), flush=True)
    if bad or logged != state or again != state:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
