"""Unpack Ultima III Gold's disk on the host: what gold.py takes from it.

Gold (3/gold/GOLD-ANALYSIS.md §2) is packed three ways, and each is undone
here the way the disk itself undoes it, without VICE or the exomizer binary:

  * every data file (BOOT, UPDT, SHP3, ...) is an `exomizer raw` stream:
    exodec.exo_raw;
  * the boot file `ultima iii gold` is an exomizer SFX that unpacks a
    title (stage 1, entry $6D9F), whose exit puts 13 bytes back at $0801 and
    starts a second SFX at $080D (stage 2: $0801-$F7EC, entry $080D again);
  * stage 2 holds SUBS, ULT3, SHPS, TEXT, DEMO and DDAT as five in-memory
    streams that $BE00 unpacks (BOOT calls it with $01 = $34).

The SFX stages and $BE00 are Gold's own 6502 code, run in py65.  One thing
about the C64 has to be modelled: a write to $D000-$DFFF while $01 has I/O
banked in goes to the chips, not the RAM.  The SFX writes the screen's last
colour cell ($DBE7) while it works, and stage 2 has packed data in the RAM
under it: written through, it corrupts ULT3 from $6846 on.

The result was checked against a VICE dump of the unpacked game (taken at
BOOT $1012 right after $BE00) on every range the build takes -- SHPS $0800-$0FFF, SUBS
$4000-$4FFF, ULT3 $5000-$93FF, TEXT $B400-$B7FF: byte-identical; and the
data files against `exomizer raw -d -P0`: all 86 identical.
The rest of the 64 KiB is not the same as that dump (zero page, BOOT, the
intro), and nothing uses it.  About 3.5 million instructions, ~2 s.
"""

from ultima.disks.d64 import D64                     # noqa: E402
from ultima.sim.exodec import exo_raw              # noqa: E402

SFX_FILE = "ultima iii gold"
STAGE1_ENTRY = 0x6D9F                   # the title, once stage 1 is unpacked
TITLE_EXIT = (0x6D92, 0x0801, 13)       # what the title puts back before $080D
STAGE2_ENTRY = 0x080D
UNPACK = 0xBE00                         # the five in-memory streams
DONE = 0x0F10                           # where the harness returns to
# the save files, stored raw ($BAD9): never read -- the build takes nothing of
# Gold's saved state, so a played Gold disk serves as well as a fresh one
SAVES = {"plrs", "prty", "rost", "sosa", "sosm"}


def _mpu():
    """py65 with C64 I/O banking for writes (see the module docstring)."""
    try:
        from py65.devices.mpu6502 import MPU
        from py65.memory import ObservableMemory
    except ImportError:
        raise SystemExit("Ultima III Gold needs py65 to unpack its disk: "
                         "python3 -m venv .venv && .venv/bin/pip install py65 "
                         "in the repository (the Makefile uses its python)")

    ram = bytearray(0x10000)
    mem = ObservableMemory(subject=ram)

    def io_write(addr, value):
        if ram[1] & 0x03 and ram[1] & 0x04:     # I/O visible: RAM keeps its byte
            return ram[addr]
        return None
    mem.subscribe_to_write(range(0xD000, 0xE000), io_write)
    return MPU(memory=mem), ram


def _run_to(mpu, stop, limit, leave_first=False):
    first = leave_first
    for _ in range(limit):
        if mpu.pc == stop and not first:
            return
        first = False
        mpu.step()
    raise SystemExit(f"Ultima III Gold: the unpack never reached ${stop:04X} "
                     f"(pc ${mpu.pc:04X}) -- not the disk the build knows?")


def _files(disk):
    names = [name for name, *_ in disk.directory() if name.strip().lower() not in SAVES]
    return {name.strip().lower(): disk.file(name)[0] for name in names}


def unpack(path):
    """{name: bytes}: every data file but the save files (SAVES) decrunched
    (load address first, as `exomizer raw -d` writes it), and "game", the
    64 KiB after $BE00."""
    files = _files(D64(path))
    if SFX_FILE not in files:
        raise SystemExit(f"{path}: no '{SFX_FILE}' -- not an Ultima III Gold disk")
    out = {}
    for name, data in files.items():
        if name == SFX_FILE:
            continue
        out[name] = exo_raw(data)

    prg = files[SFX_FILE]
    load = prg[0] | prg[1] << 8
    sys_at = prg.index(0x9E) + 1                # the BASIC stub's SYS
    entry = int(bytes(c for c in prg[sys_at:sys_at + 6] if 0x30 <= c <= 0x39))
    mpu, ram = _mpu()
    ram[load:load + len(prg) - 2] = prg[2:]
    ram[0x01] = 0x37
    mpu.sp, mpu.pc = 0xF6, entry
    _run_to(mpu, STAGE1_ENTRY, 20_000_000)
    src, dst, n = TITLE_EXIT
    ram[dst:dst + n] = ram[src:src + n]
    mpu.sp, mpu.pc = 0xF6, STAGE2_ENTRY
    _run_to(mpu, STAGE2_ENTRY, 40_000_000, leave_first=True)
    ram[0x01] = 0x34
    ram[0x1FE], ram[0x1FF] = (DONE - 1) & 0xFF, (DONE - 1) >> 8
    mpu.sp, mpu.pc = 0xFD, UNPACK
    _run_to(mpu, DONE, 40_000_000)
    out["game"] = bytes(ram)
    return out
