"""Ultima VI's copy-protection questions accept any answer (ultima/games/u6/build.py,
COMPENDIUM): in the conversations as the cart stores them, every question's
catch-all answer goes where its correct answer goes, "bye" still leaves, and
nothing else in the three scripts changed."""
import importlib.util
import os
import unittest

from ultima.disks.d64 import D64
from ultima.flash.tcrt import TCRT
from ultima.flash import regions
from ultima.dialogue import u6_dialogue
from ultima.flash import zx
from ultima import paths

_spec = importlib.util.find_spec("ultima.games.u6.build")
u6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(u6)

IMAGE = os.path.join(paths.BUILD, "ultima-collection.tcrt")
DISK = paths.disk("u6-2a")


class TestCompendium(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = u6.parts()
        cls.flash = TCRT.read(IMAGE).flash.ljust(regions.FLASH_SIZE, b"\xff")
        cls.disk = D64(DISK)

    def stored(self, name):
        """The conversation as the cart has it: its static directory entry,
        decoded."""
        key = ("/" + name).encode().ljust(u6.KEYLEN, b"\x00")
        e = u6.KEYLEN + u6.DATALEN
        for i in range(self.p["entries"]):
            ent = self.flash[self.p["sdir"] + i * e:self.p["sdir"] + (i + 1) * e]
            if ent[:u6.KEYLEN] == key:
                a = ent[12] | ent[13] << 8 | ent[14] << 16
                n = ent[15] | ent[16] << 8
                data = self.flash[a:a + n]
                return zx.decode(data) if ent[17] & u6.F_ZX else data
        self.fail(f"/{name} is not in the directory")

    def test_any_answer_is_right(self):
        for name, questions in u6.COMPENDIUM.items():
            with self.subTest(name=name):
                data = self.stored(name)
                orig = self.disk.file(name)[0]
                self.assertEqual(len(data), len(orig))
                changed = [i for i in range(len(orig)) if data[i] != orig[i]]
                self.assertLessEqual(len(changed), 3 * len(questions))
                for q in questions:
                    at = u6.find_question(data, q)
                    ask = data.index(0xF7, at)
                    end = data.index(0xEE, ask)
                    first = data.index(0xF6, ask)
                    right = data[first + 1:first + 4]
                    star = data.find(bytes([0xEF, 0x2A, 0xF6]), ask, end)
                    self.assertEqual(data[star + 3:star + 6], right, q)
                    bye = data.find(bytes([0xEF]) + u6.u6_text("bye") + bytes([0xF6]), ask, end)
                    self.assertGreater(bye, 0, f"{q}: bye is still an answer")
                    self.assertEqual(data[bye + 5:bye + 8], orig[bye + 5:bye + 8], f"{q}: bye")
                # and it still decodes cleanly: every jump on an instruction
                _items, bad = u6_dialogue.Script(data, {}).decode()
                self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
