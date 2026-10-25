#!/usr/bin/env python3
"""Ultima 4: the command level's stack (u4fix.s CMD_SP), in VICE.

    python -m tools.vice.u4_stack_check

Journey Onward from a seeded save to game main's key read ($408F).  SP there,
at cmd_done ($621E) after a Pass, and at combat's command read ($70EB) after
an orc is put beside the party and attacked, must all be CMD_SP: every
command is entered and left by JMP, so fx_top (the party dead, a moongate)
may set it.  Then three moongate jumps (gate to gate, moons 0/0): a stub in
the BASIC input buffer ($0240, dead once the game runs) JSRs a step that
JMPs $8676 with the moongate's tile, as $448D and its siblings do; each must
come back to the key read with SP = CMD_SP, where the original lost two
bytes a jump; and the party must have moved.  The control: the original
JMP $621E poked back at $86CA, one more jump leaves SP two lower.
Screenshot in build/u4_stack_moongate.png.
"""
import re
import sys

from tools.vice import menu_check
from tools.vice import u4_check
from tools.vice.u4_combat_check import syms, queue, ATTACK, COMBAT_KEY, MAIN_LOOP
from tools.vice.vice_mon import Vice

CMD_DONE = 0x621E
MOONGATE = 0x8676
GATE_TILE = 0x43
STUB = 0x0240
LOG = "build/u4_stack_check.log"


def cmd_sp():
    sym = u4_check.symbols("build/u4fix.sym")
    return sym["CMD_SP"]


def regs(v):
    out = v.cmd("r", wait=0.5)
    m = re.search(r"^\.;([0-9a-f]{4}) [0-9a-f]{2} [0-9a-f]{2} [0-9a-f]{2} ([0-9a-f]{2})",
                  out, re.M | re.I)
    return int(m.group(1), 16), int(m.group(2), 16)


def main():
    s = syms()
    want = cmd_sp()
    image = menu_check.with_autokey(4)
    u4_check.seed_saves(image)
    v = Vice(image, log=LOG, update_tcrt=True)
    bad = 0

    def check(what, hit):
        nonlocal bad
        pc, sp = regs(v)
        ok = hit and sp == want
        print(f"{what}: pc ${pc:04x} SP ${sp:02x}", "" if ok else f"-- want ${want:02x}", flush=True)
        bad += not ok

    try:
        v.run_to(0x0200, timeout=90)
        v.cmd("bank ram", wait=0.2)
        v.poke(s["pt_opts"], bytes([0x04]))             # Journey onward
        check("main loop", v.run_to(MAIN_LOOP, timeout=120))
        queue(v, ord(" "))                              # Pass
        check("cmd_done", v.run_to(CMD_DONE, timeout=30))
        v.run_to(MAIN_LOOP, timeout=30)

        def jump():
            v.cmd("bank ram", wait=0.2)
            v.poke(0x22, b"\x00\x00")                  # moons 0/0: gate to gate
            # JSR step / (no return) ; step: LDA #tile / JMP $8676
            step = STUB + 3
            v.poke(STUB, bytes([0x20, step & 0xFF, step >> 8,
                                0xA9, GATE_TILE, 0x4C, MOONGATE & 0xFF, MOONGATE >> 8]))
            v.cmd(f"r pc = {STUB:04x}", wait=0.3)
            return v.run_to(MAIN_LOOP, timeout=60)

        v.cmd("bank ram", wait=0.2)
        start = v.mem(0x10, 0x11)
        for n in range(3):
            check(f"moongate {n + 1}, back at the key read", jump())
        v.cmd("bank ram", wait=0.2)
        moved = v.mem(0x10, 0x11)
        print(f"party ({start[0]}, {start[1]}) -> ({moved[0]}, {moved[1]})", flush=True)
        bad += moved == start
        v.run(1.0)
        v.shot("build/u4_stack_moongate.png")
        v.run_to(MAIN_LOOP, timeout=30)
        v.cmd("bank ram", wait=0.2)
        fixed = v.mem(0x86CB, 0x86CC)
        v.poke(0x86CB, b"\x1e\x62")                   # the control: the original
        hit = jump()
        pc, sp = regs(v)
        print(f"control, the original JMP $621E: SP ${sp:02x}", flush=True)
        bad += not hit or sp != want - 2
        v.poke(0x86CB, fixed)
        v.cmd("r sp = %02x" % want, wait=0.3)
        v.cmd("bank ram", wait=0.2)
        x, y = v.mem(0x10, 0x11)
        tiles = v.mem(0xAC60, 0xAC7F)
        slot = next(i for i in range(len(tiles)) if tiles[i] == 0)
        for table, val in ((0xAC00, 0xC0), (0xAC20, (x + 1) & 0xFF), (0xAC40, y), (0xAC60, 0xC0)):
            v.poke(table + slot, bytes([val]))
        queue(v, ord(";"))
        v.cmd(f"r pc = {ATTACK:04x}", wait=0.3)
        check("combat's command read", v.run_to(COMBAT_KEY, timeout=90))
    finally:
        v.quit()
    print("ok" if not bad else f"{bad} bad")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
