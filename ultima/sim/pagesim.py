"""The launcher's page, run on the host: py65 for the 6502, sim6502.FakeCart
for the tapecart, fakedrive.FakeDrive for a 1541 over a disk image in memory,
and the keyboard fed from a list.

Used by the tests of export and import (test_xfer, test_file_xfer,
test_u6_xfer) and by the release build's save import (ultima/disks/importsave.py),
which is the page's own "import from disk" run on a freshly built image.
"""
import os
import re
from pathlib import Path

from ultima.sim.sim6502 import Sim
from ultima.sim.fakedrive import FakeDrive
from ultima.launcher import launcher
from ultima.flash import regions
from ultima.flash.tcrt import TCRT

from ultima import paths

IMAGE = os.path.join(paths.BUILD, "ultima-collection.tcrt")
# PETSCII's colour codes: they change the colour CHROUT prints in, and print
# nothing (the launcher's keys white, the rest light grey)
COLOURS = {5, 28, 30, 31, 129, 144} | set(range(149, 160))
RET, SPACE = 13, 32
NAMES = {"u1": "ULTIMA I", "u2": "ULTIMA II", "u3": "ULTIMA III", "u4": "ULTIMA IV",
         "u5": "ULTIMA V", "u6": "ULTIMA VI"}


def screen(codes):
    """What CHROUT printed, read in the launcher's lower-case character set:
    PETSCII $41-$5A are lower case, $C1-$DA capitals; colour codes left out."""
    out = []
    for b in codes:
        if b in COLOURS:
            continue
        out.append("\n" if b == 13 else "<CLR>" if b == 0x93 else
                   chr(b + 0x20) if 0x41 <= b <= 0x5A else
                   chr(b - 0x80) if 0xC1 <= b <= 0xDA else
                   chr(b) if 0x20 <= b < 0x7F else f"<{b:02x}>")
    return "".join(out)


def launcher_prg(flash=None):
    """The launcher as the initial load leaves it in RAM, from FONT_ORG:
    font, page, menu and the page's export tables after it (XDATA)."""
    if flash is None:
        flash = TCRT.read(IMAGE).flash
    prg = regions.launcher_prg(flash)
    assert prg[:2] == bytes([launcher.FONT_ORG & 0xFF, launcher.FONT_ORG >> 8])
    return prg[2:]


def page_syms():
    text = Path(os.path.join(paths.BUILD, "page_data.s")).read_text()

    return {m.group(1): int(m.group(2), 16)
            for m in re.finditer(r"^(\w+) = \$([0-9a-f]+)", text, re.M)}


def run_page(flash, game, keys, disk, image=None, sym=None, device=8,
             name=None, limit=2_000_000_000):
    """Open `game`'s page on `flash` (a bytearray, changed in place by any
    write) with `disk` in the drive, and type `keys`: ints, or ("swap",
    image) for another disk when the page asks.  Returns (cart, drive,
    [every disk it had], the screen as text)."""
    sim = Sim(image if image is not None else launcher_prg(flash), launcher.FONT_ORG,
              sym if sym is not None else launcher.symbols())
    cart = sim.attach_cart(flash)
    drv = FakeDrive(sim, disk, device)
    taken = [drv.disk]
    ks = list(keys)

    def getin(s):
        while ks and isinstance(ks[0], tuple):
            drv.swap(ks.pop(0)[1])
            taken.append(drv.disk)
        if not ks:
            raise AssertionError("the page wants another key; screen:\n" + screen(drv.screen)[-600:])
        k = ks.pop(0)
        s.mpu.a = k
        s.mpu.p = (s.mpu.p & ~0x82) | (0x80 if k & 0x80 else 0) | (0 if k else 0x02)
    sim.traps[0xFFE4] = getin
    sim.traps[0xFF9F] = lambda s: None
    sim.mem[0], sim.mem[1] = 0x2F, 0x37
    sim.mem[0x0300:0x0310] = list((name or NAMES[game]).encode().ljust(16, b"\x00"))
    sim.mpu.a, sim.mpu.x, sim.mpu.y = regions.DESC_INDEX[game], 0x00, 0x03
    sim.call(launcher.PAGE_ORG, limit=limit)
    return cart, drv, taken, screen(drv.screen)


def import_keys(disks):
    """I(mport) from D(isk), Y(es), RETURN; RETURN after each further disk;
    then SPACE past the result and B(ack) to the list."""
    keys = [ord("I"), ord("D"), ord("Y"), RET]
    for d in disks[1:]:
        keys += [("swap", d), RET]
    return keys + [SPACE, ord("B")]


def import_from_disks(flash, game, disks):
    """The page's import from disk, with `disks` (images, in the order the
    page asks for them).  Returns (flash, screen text, done)."""
    try:
        cart, _drv, _taken, text = run_page(bytearray(flash), game, import_keys(disks), disks[0])
    except AssertionError as e:             # it asked for more: a disk it would not take
        return flash, str(e), False
    return cart.flash, text, "Done." in text
