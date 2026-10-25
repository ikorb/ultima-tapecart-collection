#!/usr/bin/env python3
"""Golden files for the save editor's tests, from the launcher's own export
path: the page (asm/page_file.s) run in py65 against the built cart, each
game seeded as tests/test_page.py seeds it (U6: tests/test_u6_xfer.py's
played disks).

    python3 editor/make_fixtures.py          (make editor-test runs it)

Writes build/editor-fixtures/:
  u1.seq ... u6.seq        the SEQ file as the page writes it
  u1.s00 ... u6.s00        the same in a PC64 header
  u1.d64 ... u6.d64        a blank disk holding the file, as the page left it
  cart.tcrt                the cart with all six saves on it at once; each
                           game's export from it is checked to be its .seq
  layout.json              the save layout the editor's cart code must match
  zoggins_u2.d64 ...       C64UltimaEditor's played save disks (U2-U4) and
  zoggins_u1_p3.prg        its Ultima I character, as further read fixtures,
                           when the submodule external/c64ultimaeditor is
                           checked out (it is not by default)
Needs py65 (the repository's .venv) and build/ultima-collection.tcrt.
"""
import json
import os
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from tests import test_file_xfer as T           # noqa: E402
from tests import test_u6_xfer                  # noqa: E402
from tests import test_xfer                     # noqa: E402
from tests import test_editor                   # noqa: E402
from ultima.flash.tcrt import TCRT              # noqa: E402
from ultima.flash import regions                # noqa: E402
from ultima import paths                        # noqa: E402

OUT = os.path.join(paths.BUILD, "editor-fixtures")
# another editor's sample save disks (github.com/zoggins/C64UltimaEditor):
# an opt-in submodule, `git submodule update --init --checkout external/c64ultimaeditor`
ZOGGINS = os.path.join(REPO, "external", "c64ultimaeditor", "C64UltimaEditor", "UltimaData.UnitTest", "Data")


def pc64(name, data):
    """A PC64 wrapper: "C64File", NUL, 16 bytes of name padded with NUL,
    NUL, the REL record size (0)."""
    return b"C64File\0" + name.ljust(16, b"\0") + b"\0\0" + data


def put(game, disk):
    data = disk.read_file(T.NAMES[game])
    for ext, blob in (("seq", data), ("s00", pc64(T.NAMES[game], data)), ("d64", bytes(disk.data))):
        with open(os.path.join(OUT, f"{game}.{ext}"), "wb") as fh:
            fh.write(blob)
    print(f"{game}: {len(data)} bytes")


def main():
    os.makedirs(OUT, exist_ok=True)
    T.TestFileXfer.setUpClass()
    tx = T.TestFileXfer("run")
    for game in ("u1", "u2", "u3", "u4", "u5"):
        put(game, tx.export_file(tx.seeded(game), game))
    T.TestU6File.setUpClass()
    tu = T.TestU6File("run")
    played = {t: test_u6_xfer.original(t, test_u6_xfer.PLAYED) for t in test_u6_xfer.DISKS}
    src, _text = tu.imported(tu.fresh, played["1A"], played["1B"])
    put("u6", tu.export_file(src))
    # the cart with every game's save at once: the seeds touch only their
    # own regions, so each game exports from it as it did alone
    flash = test_editor.all_six(tx, tu)
    for game in ("u1", "u2", "u3", "u4", "u5"):
        with open(os.path.join(OUT, f"{game}.seq"), "rb") as fh:
            assert tx.export_file(flash, game).read_file(T.NAMES[game]) == fh.read(), game
    with open(os.path.join(OUT, "u6.seq"), "rb") as fh:
        assert tu.export_file(flash).read_file(T.NAMES["u6"]) == fh.read(), "u6"
    cart = TCRT.read(test_xfer.IMAGE)
    cart.flash = bytes(flash)
    cart.write(os.path.join(OUT, "cart.tcrt"))
    print("cart.tcrt: all six")
    with open(os.path.join(OUT, "layout.json"), "w") as fh:
        json.dump(dict(layout=regions.LAYOUT, settings=regions.SETTINGS, set_layout=regions.SET_LAYOUT,
                       journals={int(g[1]): [regions.save_region(g)[0], *regions.journal(g)]
                                 for g in regions.JOURNAL},
                       u2_log=tx.s["U2_LOG"], u6=[tx.s["U6_LO"], tx.s["U6_MID"], tx.s["U6_HI"]]), fh)
    if os.path.isdir(ZOGGINS):
        for g in ("u2", "u3", "u4"):
            shutil.copyfile(os.path.join(ZOGGINS, f"{g}data.dat"), os.path.join(OUT, f"zoggins_{g}.d64"))
        shutil.copyfile(os.path.join(ZOGGINS, "p3.prg"), os.path.join(OUT, "zoggins_u1_p3.prg"))
        print("C64UltimaEditor's sample disks copied")


if __name__ == "__main__":
    main()
