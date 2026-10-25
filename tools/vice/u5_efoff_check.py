#!/usr/bin/env python3
"""Ultima V from the tapecart with an EasyFlash plugged in, in VICE: not an AR.

    make cart ef
    python -m tools.vice.u5_efoff_check

The tapecart's own menu starts Ultima V (menu_check.with_autokey(5)) with
the EasyFlash build in the expansion port, under both of VICE's settings of
its jumper.  The EasyFlash's 256 bytes of RAM at $DF00 read back what is
written there either way; xyzzy's hook (armhook.s) must not take them for an
Action Replay's, or the glue would run from the C64's RAM at $8000 and the
game end at READY.  The pass: the RAM is there,
and after the boot the music is not ($C8 bit 6 clear, $0314 not the glue's)
and the game is running (not in the KERNAL's READY loop).
"""
import os
import shutil
import sys

from ultima import paths
os.chdir(paths.ROOT)
from tools.vice import menu_check                    # noqa: E402
from tools.vice.u5_drive import U5                   # noqa: E402

EF_IMAGE = "build/ultima6-ef.crt"


def one(jumper):
    shutil.copy(EF_IMAGE, "build/autoef.crt")
    u = U5(menu_check.with_autokey(5), extra=["-cartcrt", os.path.abspath("build/autoef.crt"), jumper],
           log="build/u5_efoff_check.log")
    v = u.v
    try:
        v.run(4.0)
        v.cmd("bank io", wait=0.2)
        seen = []
        for b in (0x3C, 0xC3):
            v.poke(0xDFFF, bytes([b]))
            seen.append(v.mem(0xDFFF, 0xDFFF)[0] == b)
        v.cmd("bank ram", wait=0.2)
        v.run(40.0)
        v.cmd("bank ram", wait=0.2)
        c8 = v.mem(0xC8, 0xC8)[0]
        irq = int.from_bytes(v.mem(0x0314, 0x0315), "little")
        pc = v.pc()
        v.shot(os.path.abspath(f"build/u5_efoff_{'on' if jumper[0] == '-' else 'off'}.png"))
    finally:
        v.quit()
    ram = all(seen)
    ok = ram and not c8 & 0x40 and not 0x0100 <= irq < 0x0174 and not 0xE5C0 <= pc < 0xE600
    print(f"{jumper}: $DF00 RAM {'there' if ram else 'NOT there'}, $C8 = ${c8:02x}, "
          f"$0314 = ${irq:04x}, PC ${pc:04x}: {'ok' if ok else 'BAD'}", flush=True)
    return ok


def main():
    if not os.path.exists(EF_IMAGE):
        raise SystemExit(f"no {EF_IMAGE}: make ef")
    menu_check.IMAGE = "build/ultima-collection.tcrt"
    ok = all([one("-easyflashjumper"), one("+easyflashjumper")])
    print("OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
