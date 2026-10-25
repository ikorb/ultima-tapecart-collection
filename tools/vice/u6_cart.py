"""Ultima 6 in VICE: a copy of the built cart with a saved game in it, and
the monitor helpers the U6 checks share.

make_cart(SAVE_FILE) imports a launcher export ("ULTIMA VI SAVE", a file
the page wrote with E then F) into a copy of build/ultima-collection.tcrt
through the host model of the launcher page, as a player's import would."""
import re
import time
from pathlib import Path

from ultima.flash.tcrt import TCRT


def make_cart(save, out="build/u6step.tcrt"):
    from tests import test_file_xfer as T
    T.TestU6File.setUpClass()
    t = T.TestU6File()
    disk = T.with_file(T.NAMES["u6"], Path(save).read_bytes())
    flash, text = t.import_file(t.fresh, disk)
    assert "Done." in text, text[-400:]
    img = TCRT.read("build/ultima-collection.tcrt")
    img.flash = bytes(flash)
    img.write(out, trim=False)
    return out


def sw(v):
    """(PC, the monitor's stopwatch)."""
    out = v.cmd("r", wait=0.4)
    m = re.search(r"^\.;(\w{4}).*?\s(\d+)\s*$", out, re.M)
    return int(m.group(1), 16), int(m.group(2))


def stop(v, timeout=20):
    seen, t = "", time.time()
    while "Stop on" not in seen and time.time() - t < timeout:
        seen += v._drain(0.2)
    return "Stop on" in seen
