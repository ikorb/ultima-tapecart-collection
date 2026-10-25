#!/usr/bin/env python3
"""Run a PRG in VICE with a tapecart attached and print the resulting screen.

    python3 -m tools.vice.run_vice build/u1test.prg build/u1test.tcrt \
        --symbols build/u1test.sym --park st_done --update-tcrt

The program must end by parking in an infinite loop at the label given with
--park; that address becomes the breakpoint the harness catches, so a failing
run is captured just as reliably as a passing one.
"""
import argparse
import os
import re
import subprocess
import sys

SCREEN_DUMP = "build/screen.bin"


def label_address(symfile, name):
    pattern = re.compile(r"^\s*" + re.escape(name) + r"\s*=\s*\$([0-9a-fA-F]+)")
    with open(symfile) as fh:
        for line in fh:
            m = pattern.match(line)
            if m:
                return int(m.group(1), 16)
    raise SystemExit(f"label {name!r} not found in {symfile}")


def decode_screen(path):
    """C64 screen codes -> text.  Only the glyphs we actually print."""
    with open(path, "rb") as fh:
        data = fh.read()[2:]          # drop the 2-byte load address
    out = []
    for row in range(25):
        line = []
        for code in data[row * 40:(row + 1) * 40]:
            code &= 0x7F
            if code == 0:
                line.append("@")
            elif 1 <= code <= 26:
                line.append(chr(64 + code).lower())
            elif 32 <= code <= 63:
                line.append(chr(code))
            else:
                line.append(".")
        out.append("".join(line).rstrip())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prg")
    ap.add_argument("tcrt")
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--park", default="finish")
    ap.add_argument("--cycles", type=int, default=400_000_000)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--update-tcrt", action="store_true",
                    help="let the emulator write flash changes back to the image")
    args = ap.parse_args()

    addr = label_address(args.symbols, args.park)
    os.makedirs("build", exist_ok=True)
    with open("build/mon.txt", "w") as fh:
        fh.write(f'save "{SCREEN_DUMP}" 0 0400 07e7\nquit\n')

    if os.path.exists(SCREEN_DUMP):
        os.remove(SCREEN_DUMP)

    cmd = ["x64sc", "-warp", "-limitcycles", str(args.cycles),
           "-tapeport1device", "6", "-tcrt", args.tcrt,
           "-initbreak", hex(addr), "-moncommands", "build/mon.txt",
           "-autostart", args.prg]
    if args.update_tcrt:
        cmd.insert(1, "-tapecartupdatetcrt")

    subprocess.run(cmd, timeout=args.timeout,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if not os.path.exists(SCREEN_DUMP):
        print(f"FAIL: never reached {args.park} (${addr:04x}) — hung or crashed",
              file=sys.stderr)
        return 1

    for line in decode_screen(SCREEN_DUMP):
        if line:
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
