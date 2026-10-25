"""The save editor (editor/, a web page) against the launcher's own page.

For every game: the seeded save exported by the real page (py65), edited by
the editor's code (editor/cli.ts under node -- the same modules the page
bundles), imported into a fresh cart by the real page, and exported again:
the page must take the edited file ("Done.") and give back exactly it, so
the edit reached the cart and nothing else changed.  The editor's own tests
(make editor-test) check that an edit changes only its own bytes.

And on the cart itself (.tcrt, every game's save on it at once): the same
edits made there must leave the flash exactly as the page's import of the
edited file does -- the whole 2 MiB, so no other game's save moves either;
and a journal a power cut left on it is finished as the first stage does.

Skipped without node or py65.
"""
import os
import shutil
import subprocess
import unittest


import random

from tests import test_file_xfer as T
from tests import test_journal
from tests import test_page
from tests import test_u6_xfer
from tests import test_xfer
from ultima.flash.tcrt import TCRT
from tests.test_xfer import Sim
from ultima.flash import regions
from ultima import paths

CLI = os.path.join(paths.ROOT, "editor", "cli.ts")
OUT = os.path.join(paths.BUILD, "editor-e2e")


def ts_runner():
    """What runs the editor's TypeScript as it is: node 22.18 or later (it
    strips the types itself), else bun, else nothing."""
    node = shutil.which("node")
    if node and subprocess.run([node, "-e", "process.exit(process.features.typescript ? 0 : 1)"],
                               capture_output=True).returncode == 0:
        return [node]
    bun = shutil.which("bun")
    return [bun] if bun else None


NODE = ts_runner()

EDITS = {
    "u1": ["p1.food=999", "p1.name=Brendan", "p2.str=40"],
    "u2": ["hp=1500", "coins=250", "torches=9"],
    "u3": ["plrs1.hp=275", "plrs0.gold=999", "plrs2.status=$d0"],
    "u4": ["p0.str=25", "gold=9999", "p0.class=7", "rune.0=1"],
    "u5": ["c1.hp=60", "gold=999", "c0.eq4=2"],
    "u6": ["c0.str=29", "c1.exp=1000", "c2.name=Shamin", "c0.poisoned=1", "karma=42", "month=12", "spell.2.6=1"],
}


def all_six(tx, tu):
    """A cart with every game's save on it: U1-U5 seeded as test_page seeds
    them, U6 the played user session imported (make_fixtures' cart.tcrt)."""
    flash = bytearray(tx.fresh)
    for game in ("u1", "u2", "u3", "u4", "u5"):
        test_page.SEEDS[game](flash, tx.s)
    played = {t: test_u6_xfer.original(t, test_u6_xfer.PLAYED) for t in test_u6_xfer.DISKS}
    flash, _text = tu.imported(flash, played["1A"], played["1B"])
    return bytes(flash)


def edit(game, data, ext="seq", extra=()):
    os.makedirs(OUT, exist_ok=True)
    src, dst = os.path.join(OUT, f"{game}.{ext}"), os.path.join(OUT, f"{game}_edited.{ext}")
    with open(src, "wb") as fh:
        fh.write(data)
    r = subprocess.run([*NODE, CLI, "set", src, dst, *EDITS[game], *extra], capture_output=True, text=True)
    if r.returncode:
        raise AssertionError(f"editor: {r.stderr}")
    with open(dst, "rb") as fh:
        return fh.read(), r.stdout


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
@unittest.skipIf(NODE is None, "no node 22.18 or later, and no bun")
class TestEditor(unittest.TestCase):
    def test_an_edited_file_goes_through_the_page(self):
        T.TestFileXfer.setUpClass()
        tx = T.TestFileXfer("run")
        for game in ("u1", "u2", "u3", "u4", "u5"):
            with self.subTest(game=game):
                f0 = tx.export_file(tx.seeded(game), game).read_file(T.NAMES[game])
                edited, log = edit(game, f0)
                self.assertNotEqual(edited, f0)
                # (U1's name also renames the roster's copy: one change more)
                self.assertEqual(len(log.splitlines()), len(EDITS[game]) + (game == "u1"), log)
                flash, text = tx.import_file(tx.fresh, game, T.with_file(T.NAMES[game], edited))
                self.assertIn("Done.", text, text[-300:])
                again = tx.export_file(flash, game).read_file(T.NAMES[game])
                self.assertEqual(again, edited)

    def test_an_edited_world_goes_through_the_page(self):
        T.TestU6File.setUpClass()
        tu = T.TestU6File("run")
        played = {t: test_u6_xfer.original(t, test_u6_xfer.PLAYED) for t in test_u6_xfer.DISKS}
        src, _t = tu.imported(tu.fresh, played["1A"], played["1B"])
        f0 = tu.export_file(src).read_file(T.NAMES["u6"])
        edited, log = edit("u6", f0)
        self.assertNotEqual(edited, f0)
        flash, text = tu.import_file(tu.fresh, T.with_file(T.NAMES["u6"], edited))
        self.assertIn("Done.", text, text[-300:])
        again = tu.export_file(flash).read_file(T.NAMES["u6"])
        self.assertEqual(again, edited)

    def test_an_edited_cart_is_the_page_import(self):
        T.TestFileXfer.setUpClass()
        T.TestU6File.setUpClass()
        tx, tu = T.TestFileXfer("run"), T.TestU6File("run")
        src = all_six(tx, tu)
        image = TCRT.read(test_xfer.IMAGE)
        image.flash = src
        cart = image.pack()
        for game in ("u1", "u2", "u3", "u4", "u5", "u6"):
            with self.subTest(game=game):
                number = int(game[1])
                ts, log = edit(game, cart, "tcrt", [f"--game={number}"])
                flash = TCRT.parse(ts).flash.ljust(regions.FLASH_SIZE, b"\xff")
                self.assertEqual(len(log.splitlines()), len(EDITS[game]) + (game == "u1"), log)
                if game == "u6":
                    f0 = tu.export_file(src).read_file(T.NAMES[game])
                    seq, _log = edit(game, f0)
                    want, text = tu.import_file(src, T.with_file(T.NAMES[game], seq))
                else:
                    f0 = tx.export_file(src, game).read_file(T.NAMES[game])
                    seq, _log = edit(game, f0)
                    want, text = tx.import_file(src, game, T.with_file(T.NAMES[game], seq))
                self.assertIn("Done.", text, text[-300:])
                diff = [a for a in range(0, regions.FLASH_SIZE, 0x1000)
                        if flash[a:a + 0x1000] != bytes(want[a:a + 0x1000])]
                self.assertEqual([hex(a) for a in diff], [], "blocks unlike the page's import")
                self.assertNotEqual(flash, src)

    def test_a_cart_with_a_journal_is_the_first_stage(self):
        """Journals planted for U3 (two blocks, some pages erased: skipped)
        and U4 (one, a torn header: only erased), then U4's gold edited: the
        flash is the real first stage's repair followed by the page's import."""
        T.TestFileXfer.setUpClass()
        T.TestU6File.setUpClass()
        test_journal.TestJournal.setUpClass()
        tx, tu, tj = T.TestFileXfer("run"), T.TestU6File("run"), test_journal.TestJournal("run")
        rng = random.Random(3)
        flash = bytearray(all_six(tx, tu))
        u3, _n = regions.journal("u3")
        slot = regions.save_base("u3") + 2 * 0x2000                 # ROST
        for p in (1, 2, 3, 9, 30):
            flash[u3 + p * 256:u3 + p * 256 + 256] = rng.randbytes(256)
        flash[u3:u3 + 4] = b"JN" + bytes([slot >> 8 & 0xFF, slot >> 16])
        u4, _n = regions.journal("u4")
        flash[u4 + 256:u4 + 512] = rng.randbytes(256)
        flash[u4:u4 + 4] = b"J\xff\xff\xff"
        image = TCRT.read(test_xfer.IMAGE)
        image.flash = bytes(flash)
        ts, _log = edit("u4", image.pack(), "tcrt", ["--game=4"])
        _sim, cart = tj.first_stage(bytearray(flash))
        repaired = bytes(cart.flash)
        self.assertNotEqual(repaired[slot:slot + 0x2000], bytes(flash[slot:slot + 0x2000]), "a journal to finish")
        f0 = tx.export_file(repaired, "u4").read_file(T.NAMES["u4"])
        seq, _log = edit("u4", f0)
        want, text = tx.import_file(repaired, "u4", T.with_file(T.NAMES["u4"], seq))
        self.assertIn("Done.", text, text[-300:])
        got = TCRT.parse(ts).flash.ljust(regions.FLASH_SIZE, b"\xff")
        diff = [hex(a) for a in range(0, regions.FLASH_SIZE, 0x1000) if got[a:a + 0x1000] != bytes(want[a:a + 0x1000])]
        self.assertEqual(diff, [])


if __name__ == "__main__":
    unittest.main()
