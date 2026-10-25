#!/usr/bin/env python3
"""Boot a game image in VICE and check it reaches a given address.

    ./boot_check.py build/ultima3.tcrt build/boot_u3.prg 0x1000

The address is a point only reachable if the game's own loader ran through
the replacement driver, so reaching it is a real end-to-end signal.
"""
import os
import subprocess
import sys


def main():
    tcrt, prg, addr = sys.argv[1], sys.argv[2], sys.argv[3]
    marker = "build/boot_check.bin"
    os.makedirs("build", exist_ok=True)
    with open("build/mon_boot.txt", "w") as fh:
        fh.write(f'save "{marker}" 0 {int(addr, 0):04x} {int(addr, 0) + 0x10:04x}\nquit\n')
    if os.path.exists(marker):
        os.remove(marker)
    subprocess.run(["x64sc", "-warp", "-limitcycles", "600000000",
                    "-tapeport1device", "6", "-tcrt", tcrt,
                    "-initbreak", addr, "-moncommands", "build/mon_boot.txt",
                    "-autostart", prg],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=400)
    ok = os.path.exists(marker)
    print(f"{os.path.basename(prg)}: reached {addr} -> {'yes' if ok else 'NO'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
