#!/usr/bin/env python3
"""Ultima 6 on EasyFlash (ef/, the side quest): the in-game compaction, in VICE.

    python -m tools.vice.u6ef_compact_check [worst] [image]

`image`: only write the seeded image, build/ef/u6efcompact.crt, for a real
cart (ef/HARDWARE.md): it holds the log banks, so EasyProg writes them too.

Seeds the log of a copy of the EF image with a long game's worth of saves made
of the game's own data -- chunk files as on their disk, links and all, and the
save area as the build has it -- until fewer than three pages are free; `worst`
cycles through every chunk file, so all 84 are live, otherwise four.  Journey
Onward, then window shifts: the first save finds the log full and compacts it
(efdrv.s d_pack), timed as part of its shift on VICE's stopwatch.  VICE is shut
down cleanly so the .crt is written back, and the log is read back out of it
through efinit.s on the host: the other half active, a generation on, and every
seeded key still there.

VICE's erase is a fixed 1M cycles a sector, its program time zero; a real
AM29F040 takes ~1 s a sector (up to 8) and ~14 us a byte -- see docs/developer/easyflash.md.
"""
import os
from ultima import paths
import sys

os.chdir(paths.ROOT)

from ultima.ef import efcrt                                # noqa: E402
from ultima.ef import efregions as R                       # noqa: E402
from ultima.launcher import u6log                                # noqa: E402
from tests.efsim import EFSim                     # noqa: E402
from tools.vice.vice_mon import Vice                   # noqa: E402
from tools.vice import u6_shift_bench as bench              # noqa: E402

from ultima.ef import build as efb                    # noqa: E402
u6 = efb.u6

IMAGE = os.path.join("build", "ef", "u6efcompact.crt")


def disk_pages(d, t, s):
    out = []
    while True:
        sec = bytes(d.sector(t, s))
        out.append(sec)
        if sec[0] == 0:
            return out
        t, s = sec[0], sec[1]


def seed(p, worst):
    f = bytearray(p["flash"])
    log = u6log.Log(f, R.LOG_LO, R.LOG_MID)
    log.header(1)
    d = p["disks"]["1A"]
    names = [n for n, *_ in d.directory()]
    files = [(n, disk_pages(d, *p["starts"][n])) for n in (names if worst else names[:4])]
    area = [(bytes([1, 0, 6, s]), bytes(d.sector(6, s))) for s in range(9, 21)]
    want, i = {}, 0
    while True:
        name, pages = files[i % len(files)]
        i += 1
        if log.free() < len(pages) + 3:
            break
        log.append(b"/" + name.encode(), pages, True)
        want[(b"/" + name.encode()).ljust(12, b"\0")] = b"".join(pages)
        if i % 4 == 0:
            for key, pg in area:
                if log.free() < 4:
                    break
                log.append(key, [pg], False)
                want[key.ljust(12, b"\0")] = pg
    while log.free() >= 3:                  # to the last page
        key, pg = area[log.free() % 12]
        log.append(key, [pg], False)
    count = (R.LOG_MID - log.dir) // 20
    print(f"seeded: {count} entries, {len(want)} keys, {sum(len(v) for v in want.values()) // 256} "
          f"live pages, {log.free()} pages free")
    return f, want


def boot_log(flash, init):
    sim = EFSim(flash)
    m = sim.mem
    m.ram[0x1000:0x1000 + len(init)] = init
    m.control = 0x07
    sim.mpu.pc = 0x1000
    while sim.mpu.pc != 0xC00C:
        sim.mpu.step()
    st = m.efram
    logdir, count = st[0] | st[1] << 8 | st[2] << 16, st[3] | st[4] << 8
    return u6log.view(m.flash(), logdir, count), st[0x1A], st[0x1B] | st[0x1C] << 8


def main():
    worst = "worst" in sys.argv[1:]
    p = efb.build()
    flash, want = seed(p, worst)
    efcrt.write(IMAGE, flash, efb.CART_NAME)            # the log too: it is the test
    if "image" in sys.argv[1:]:
        print(f"-> {IMAGE}")
        return
    v = Vice(None, easyflash=IMAGE, update_tcrt=True)
    try:
        v.ef_launch("j")                                       # Journey onward
        v.run(50.0)
        v.shot("build/ef/shots/compact_play.png")
        res = bench.shifts(v, 3, None, "efcompact")
        v.shot("build/ef/shots/compact_after.png")
    finally:
        v.quit()
    bench.summary("efcompact", res)
    back, _name = efcrt.read(IMAGE)
    view, act, gen = boot_log(back, p["init"])
    print(f"after: half {act // 3} active, generation {gen}, {len(view)} keys")
    lost = [k for k in want if k not in view]
    same = [k for k in want if view.get(k) == want[k]]
    print(f"seeded keys still there: {len(want) - len(lost)} of {len(want)} "
          f"({len(same)} unchanged, the rest saved over by the game)")
    ok = act == 3 and gen == 2 and not lost and len(res) == 3
    print("OK" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
