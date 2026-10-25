#!/usr/bin/env python3
"""A played session of the ORIGINAL Ultima 6, with VICE's memmap recording.

    python -m tools.vice.u6_session start          fresh copies of the six disks, VICE window
    python -m tools.vice.u6_session start trace    ... and log every command the loaders send
    python -m tools.vice.u6_session commands       decode that log
    python -m tools.vice.u6_session zap            reset the memmap (once the game is running)
    python -m tools.vice.u6_session save <name>    write build/u6_mm_<name>.bmp and summarise
    python -m tools.vice.u6_session union          what no saved map has ever touched

The disks are copied from build/disks (make disks) to /tmp/u6play first -- the originals are
never attached, so a save made during play cannot touch them -- and put in a
fliplist, so a swap is Alt+N (next image) in VICE, or the attach dialog.

The memmap only covers what ran, which is why a person playing is worth more
than a script: every path walked, every conversation, every dungeon adds to it.
`zap` after the game is up, because u6load wipes all of RAM at boot and marks
every byte as touched.  Commands pause the emulator for a moment only.
"""
import glob
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from ultima import paths

PLAY = "/tmp/u6play"
PORT = 6512
BUILD = paths.BUILD
TRACE_LOG = "/tmp/u6play/monitor.log"
# Every byte either loader sends to the drive passes through A here, so a
# tracepoint -- which logs the registers and does not stop -- records the
# whole command stream without slowing play down.  The entries mark where a
# command starts (X/Y = the command's address).
SEND = {0x2ABE: "game", 0xC254: "resident"}
ENTRY = {0x29C8: "game", 0xC171: "resident"}
ORDER = ["3B", "1A", "1B", "2A", "2B", "3A"]


REQUESTS = "/tmp/u6play/requests"
LOGGER_PID = "/tmp/u6play/logger.pid"


def logger():
    """Own the monitor connection for a traced session.

    VICE takes one monitor client, and tracepoint hits are only reported to a
    connected one, so this holds the socket for the whole session: everything
    VICE says goes to TRACE_LOG, and zap/save requests arrive as lines in
    REQUESTS, are sent, and the machine is resumed."""
    with open(LOGGER_PID, "w") as fh:
        fh.write(str(os.getpid()))
    s = socket.create_connection(("127.0.0.1", PORT), timeout=5)
    s.settimeout(0.2)
    log = open(TRACE_LOG, "a")

    def pump(seconds):
        end = time.time() + seconds
        while time.time() < end:
            try:
                chunk = s.recv(65536)
                if not chunk:
                    return False
                log.write(chunk.decode("latin1"))
            except socket.timeout:
                pass
            except OSError:
                return False
        log.flush()
        return True

    for addr in list(SEND) + list(ENTRY):
        s.sendall(f"trace exec {addr:04x}\n".encode())
        pump(0.2)
    s.sendall(b"x\n")
    while pump(0.5):
        if os.path.exists(REQUESTS):
            lines = Path(REQUESTS).read_text().splitlines()
            os.remove(REQUESTS)
            for line in lines:
                s.sendall((line + "\n").encode())
                pump(1.0)
            s.sendall(b"x\n")
    log.close()
    s.close()
    os.remove(LOGGER_PID)


def send(cmd, wait=0.8):
    if os.path.exists(LOGGER_PID):          # a traced session owns the socket
        with open(REQUESTS, "a") as fh:
            fh.write(cmd + "\n")
        time.sleep(wait + 1.5)
        return ""
    s = socket.create_connection(("127.0.0.1", PORT), timeout=5)
    s.sendall((cmd + "\n").encode())
    time.sleep(wait)
    s.settimeout(0.5)
    out = b""
    try:
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            out += chunk
    except OSError:
        pass
    s.sendall(b"x\n")           # and let the game run on
    time.sleep(0.2)
    s.close()
    return out.decode("latin1")


def untouched(mm, minlen=128):
    from tools.vice import memmap
    runs, start = [], None
    for a in range(0x10000):
        used = mm[a] & memmap.RAM_ANY or (0xD000 <= a <= 0xDFFF and mm[a] & 0xC0)
        if not used:
            if start is None:
                start = a
        else:
            if start is not None and a - start >= minlen:
                runs.append((start, a - 1))
            start = None
    if start is not None and 0x10000 - start >= minlen:
        runs.append((start, 0xFFFF))
    return runs


def decode_trace(path):
    """Turn the tracepoint log into one line per command sent."""
    import re
    out, cur, who = [], None, None
    reg = re.compile(r"\.C:([0-9a-f]{4}).*?A:([0-9a-f]{2}) X:([0-9a-f]{2}) Y:([0-9a-f]{2})", re.I)
    reg2 = re.compile(r"^\.;?([0-9a-f]{4})\s+([0-9a-f]{2})\s+([0-9a-f]{2})\s+([0-9a-f]{2})", re.I)
    for line in Path(path).read_text(errors="replace").splitlines():
        m = reg.search(line) or reg2.search(line.strip())
        if not m:
            continue
        pc, a, x, y = (int(g, 16) for g in m.groups())
        if pc in ENTRY:
            if cur:
                out.append(cur)
            cur, who = [ENTRY[pc], x | y << 8, bytearray()], ENTRY[pc]
        elif pc in SEND and cur is not None:
            cur[2].append(a)
    if cur:
        out.append(cur)
    lines = []
    for who, ptr, data in out:
        text = bytes(b if 32 <= b < 127 else 46 for b in data[:24]).decode()
        kind = {0x23: "id", 0x5E: "read", 0x26: "write", 0x21: "find"}.get(data[0] if data else 0, "load")
        detail = data[:8].hex(" ") if kind != "write" else data[:6].hex(" ") + f" +{len(data) - 6} bytes"
        lines.append(f"{who:8s} ${ptr:04x} {kind:5s} {detail:40s} {text}")
    return lines


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else "start"
    if what == "start":
        shutil.rmtree(PLAY, ignore_errors=True)
        os.makedirs(PLAY)
        disks = []
        for tag in ORDER:
            src = paths.disk("u6-" + tag.lower())
            dst = os.path.join(PLAY, os.path.basename(src))
            shutil.copy(src, dst)
            disks.append(dst)
        flip = os.path.join(PLAY, "fliplist.vfl")
        with open(flip, "w") as fh:
            fh.write("# Vice fliplist file\n\nUNIT 8\n" + "\n".join(disks) + "\n")
        subprocess.Popen(["x64sc", "-remotemonitor",
                          "-remotemonitoraddress", f"ip4://127.0.0.1:{PORT}",
                          "-flipname", flip, "-autostart", disks[0]],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        print(f"VICE started on the disks in {PLAY}; fliplist order: {', '.join(ORDER)}")
        if len(sys.argv) > 2 and sys.argv[2] == "trace":
            time.sleep(3)
            subprocess.Popen([sys.executable, os.path.abspath(__file__), "logger"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            print(f"tracing loader commands to {TRACE_LOG}")
    elif what == "zap":
        send("mmzap")
        print("memmap reset")
    elif what == "save":
        name = sys.argv[2]
        path = os.path.join(BUILD, f"u6_mm_{name}.bmp")
        if os.path.exists(path):
            os.remove(path)
        send(f'mmsave "{path}" 0', wait=1.5)
        from tools.vice import memmap
        runs = untouched(memmap.read_bmp(path))
        print(f"{path}: {len(runs)} untouched runs of 128+ bytes")
        for a, b in runs:
            print(f"  ${a:04x}-${b:04x} {b - a + 1:6d}")
    elif what == "logger":
        logger()
    elif what == "commands":
        for line in decode_trace(TRACE_LOG):
            print(line)
    elif what == "union":
        from tools.vice import memmap
        maps = [memmap.read_bmp(p) for p in sorted(glob.glob(os.path.join(BUILD, "u6_mm_*.bmp")))
                if "opening" not in p and not p.endswith("_game.bmp")]
        merged = bytearray(0x10000)
        for mm in maps:
            for a in range(0x10000):
                merged[a] |= mm[a]
        print(f"{len(maps)} maps")
        for a, b in untouched(merged):
            print(f"  ${a:04x}-${b:04x} {b - a + 1:6d}")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
