#!/usr/bin/env python3
"""Walk Ultima 5's party around Britannia looking for a fight, and watch
what that does to the driver.

    U5_SAVE_FROM=DIR python -m ultima.build build/u5dbg.tcrt
    python -m tools.vice.u5_wander [steps]

Starts from the seeded save in the starting hut, takes the way out
to Britannia, then snapshots the driver -- the resident window and the three
holes in temp.subs -- and wanders at random.  Every change of the last file
loaded is logged with a screenshot; at the end the driver is compared with
the snapshot, so anything the game wrote into it shows up as changed bytes
(the driver's own variables change too, and are listed separately), and the
memmap of the whole walk is saved to build/u5_wander.bmp.
"""
import os
import random
import sys

from tools.vice import menu_check
from tools.vice.u5_drive import U5

REGIONS = [(0x7700, 0x7AFF), (0x6C49, 0x6CA9), (0x6DE0, 0x6E7A), (0x6EAE, 0x6F4C)]
# the driver's own data: changing is expected (from the listing, see below)
VARIABLE_PREFIXES = ("u5_iflag", "u5_bpage", "u5_bsec", "u5_btrk", "u5_disk", "u5_post",
                     "u5_plen", "u5_cont", "u5_ok", "u5_flags", "u5_save01", "u5_dircount",
                     "u5_wsrc", "u5_wlen", "u5_slot", "u5_hdr", "u5_sd", "u5_blk", "u5_off",
                     "tc_", "u5_pat")


def variable_addrs(sym):
    out = set()
    for name, addr in sym.items():
        if name.startswith(VARIABLE_PREFIXES):
            out.update(range(addr, addr + 4))
    return out


# Debug hooks.  LOG runs on every raw sector read (hooked at u5_block's
# `jsr u5_enter`) and appends (disk, track, sector) to a 12-entry ring,
# bumping a counter; MISS replaces the `jmp u5_exit` at u5_blk_out -- the
# path a read below its disk's run takes, which leaves the buffer untouched
# -- and counts, keeping the last miss's disk/track/sector.
#
# NOT $0380-$03FF: that is live, executed code in U5 (it looks like an IRQ
# handler) and hooks there froze the game.  $0335-$037F and $0200-$0276 are
# what a memmap of 120 steps of play, a fight included, shows untouched.
LOG, MISS = 0x0335, 0x035C
RING, RING_N = 0x0240, 12
RING_IDX, RING_CNT, MISS_CNT = 0x0270, 0x0271, 0x0272      # then last miss at +1..+3


def install_hooks(u):
    s = u.sym
    lo, hi = lambda a: a & 0xFF, lambda a: a >> 8
    log = bytes([0xAE, lo(RING_IDX), hi(RING_IDX),
                 0xAD, lo(s["u5_disk"]), hi(s["u5_disk"]), 0x9D, lo(RING), hi(RING),
                 0xAD, lo(s["u5_btrk"]), hi(s["u5_btrk"]), 0x9D, lo(RING + 1), hi(RING + 1),
                 0xAD, lo(s["u5_bsec"]), hi(s["u5_bsec"]), 0x9D, lo(RING + 2), hi(RING + 2),
                 0xE8, 0xE8, 0xE8, 0xE0, 3 * RING_N, 0x90, 0x02, 0xA2, 0x00,
                 0x8E, lo(RING_IDX), hi(RING_IDX), 0xEE, lo(RING_CNT), hi(RING_CNT),
                 0x4C, lo(s["u5_enter"]), hi(s["u5_enter"])])
    miss = bytes([0xEE, lo(MISS_CNT), hi(MISS_CNT),
                  0xAD, lo(s["u5_disk"]), hi(s["u5_disk"]), 0x8D, lo(MISS_CNT + 1), hi(MISS_CNT + 1),
                  0xAD, lo(s["u5_btrk"]), hi(s["u5_btrk"]), 0x8D, lo(MISS_CNT + 2), hi(MISS_CNT + 2),
                  0xAD, lo(s["u5_bsec"]), hi(s["u5_bsec"]), 0x8D, lo(MISS_CNT + 3), hi(MISS_CNT + 3),
                  0x4C, lo(s["u5_exit"]), hi(s["u5_exit"])])
    assert len(log) <= MISS - LOG and MISS + len(miss) <= 0x0380
    u.v.poke(RING, bytes(0x40))
    u.v.poke(LOG, log)
    u.v.poke(MISS, miss)
    call = s["u5_block"] + 9
    assert u.v.mem(call, call + 2) == bytes([0x20, lo(s["u5_enter"]), hi(s["u5_enter"])])
    assert u.v.mem(s["u5_blk_out"], s["u5_blk_out"] + 2) == \
        bytes([0x4C, lo(s["u5_exit"]), hi(s["u5_exit"])])
    u.v.poke(call, bytes([0x20, lo(LOG), hi(LOG)]))
    u.v.poke(s["u5_blk_out"], bytes([0x4C, lo(MISS), hi(MISS)]))
    return call


class Reads:
    def __init__(self, u):
        self.u, self.count, self.seen, self.misses = u, 0, set(), 0

    def poll(self):
        m = self.u.v.mem(RING, MISS_CNT + 3)
        cnt = m[RING_CNT - RING]
        new = (cnt - self.count) & 0xFF
        idx = m[RING_IDX - RING]
        for k in range(min(new, RING_N)):
            j = (idx - 3 * (k + 1)) % (3 * RING_N)
            self.seen.add(tuple(m[j:j + 3]))
        if new > RING_N:
            print(f"  (ring overran: {new} reads since the last poll)", flush=True)
        self.count = cnt
        miss = m[MISS_CNT - RING]
        if miss != self.misses:
            o = MISS_CNT - RING
            print(f"  MISS #{miss}: disk {m[o + 1]} track {m[o + 2]} sector {m[o + 3]}", flush=True)
            self.misses = miss


def main():
    steps = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    menu_check.IMAGE = "build/u5dbg.tcrt"
    u = U5(menu_check.with_autokey(5))
    v = u.v
    names = []
    try:
        print("menu:", u.boot_to_menu(), flush=True)
        print("journey:", u.menu_pick(0), flush=True)
        v.run(25.0)
        u.joystick_patch()
        for _ in range(3):
            u.push("down")
        u.key(ord("O"))
        v.run(1.0)
        u.push("down")
        for _ in range(14):
            u.push("down")
        u.key(ord("Y"))
        v.run(25.0)
        v.shot("build/u5w_britannia.png")
        hook = install_hooks(u)
        watch_hits = []
        # data reads of code in the holes: the driver never does that, so
        # every hit is the game reading something it thinks is its own
        for lo_, hi_ in ((0x6C49, 0x6CA9), (0x6DE0, 0x6E7A), (0x6EAE, 0x6F12)):
            v.cmd(f"watch load {lo_:04x} {hi_:04x}", wait=0.2)
        reads = Reads(u)
        ref = {r: v.mem(*r) for r in REGIONS}
        v.cmd("mmzap", wait=0.3)
        last = None
        rnd = random.Random(5)
        dirs = ["up", "down", "left", "right"]
        d = rnd.choice(dirs)
        for i in range(steps):
            if not u.joystick_patch():
                print(f"  step {i}: joystick patch did not take", flush=True)
            if rnd.random() < 0.3:
                d = rnd.choice(dirs)
            for val, t in ((u.JOY[d], 0.5), (0xFF, 0.5)):
                v.poke(u.JOY_BYTE, bytes([val]))
                out = v.run(t)
                # "Stop on" only: the register header has a STOPWATCH column,
                # so looking for "WATCH" matches every dump
                while "Stop on" in out:
                    pc = v.pc()
                    regs = v.cmd("r", wait=0.3).strip().splitlines()[-2:]
                    print(f"  step {i}: WATCH {out.strip().splitlines()[:3]} pc={pc and hex(pc)} {regs}",
                          flush=True)
                    watch_hits.append((i, pc))
                    v.cmd(f"m {max(0, (pc or 0) - 16):04x} {(pc or 0) + 8:04x}", wait=0.3)
                    out = v.run(0.2)
            reads.poll()
            if v.mem(hook, hook) != b"\x20":
                print(f"  step {i}: the driver was reloaded, hooks gone", flush=True)
            if i % 10 == 0:
                v.shot(f"build/u5w_{i:03d}.png")
        v.shot("build/u5w_end.png")
        v.cmd(f'mmsave "{os.path.abspath("build/u5_wander.bmp")}" 0', wait=1.0)
        varaddrs = variable_addrs(u.sym)
        for r in REGIONS:
            now = v.mem(*r)
            diff = [r[0] + i for i, (a, b) in enumerate(zip(ref[r], now)) if a != b]
            code = [a for a in diff if a not in varaddrs]
            print(f"${r[0]:04x}-${r[1]:04x}: {len(diff)} bytes changed, "
                  f"{len(code)} outside the driver's variables: "
                  + " ".join(f"${a:04x}" for a in code[:40]), flush=True)
        print(f"raw reads: {len(reads.seen)} distinct (disk, track, sector), "
              f"{reads.misses} misses", flush=True)
        by_disk = {}
        for dsk, t, sec in reads.seen:
            by_disk.setdefault(dsk, []).append((t, sec))
        for dsk, ts in sorted(by_disk.items()):
            print(f"  disk {dsk}: tracks {min(ts)[0]}-{max(ts)[0]}, {len(ts)} sectors", flush=True)
        print("watchpoint hits:", watch_hits, flush=True)
    finally:
        v.quit()


if __name__ == "__main__":
    main()
