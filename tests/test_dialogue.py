"""The dialogue extractors (dialogue/*.py, `make dialogue`) run through
on the original disks: each asserts the code and data layouts it relies
on, so a run that finishes is the check.  Output goes to build/test-dialogue/.
"""
import os
import subprocess
import sys
import unittest
from ultima import paths

OUT = os.path.join(paths.BUILD, "test-dialogue")


def run(module, *args):
    return subprocess.run([sys.executable, "-m", module, *args],
                          cwd=paths.ROOT, capture_output=True, text=True, check=True).stdout


def read(*path):
    with open(os.path.join(OUT, *path)) as fh:
        return fh.read()


class TestDialogue(unittest.TestCase):
    def test_u1(self):
        run("ultima.dialogue.u1talk", "--out", os.path.join(OUT, "u1"))
        text = read("u1", "u1-dialogue.txt")
        self.assertIn("Here, have a cold one!", text)
        self.assertIn("TURRIS-SCIENTIA-MAGNOPERE", text)

    def test_u2(self):
        run("ultima.dialogue.u2talk", "--out", os.path.join(OUT, "u2"))
        text = read("u2", "u2-dialogue.txt")
        self.assertEqual(text.count("(MAP / MON / TLK"), 16)
        self.assertIn("FATHER ANTOS CHANTS:", text)

    def test_u3(self):
        self.assertIn("77 town lines", run("ultima.dialogue.u3talk", "--out", os.path.join(OUT, "u3")))

    def test_u4(self):
        run("ultima.dialogue.u4talk", "--out", os.path.join(OUT, "u4"))
        text = read("u4", "u4-dialogue.txt")
        self.assertEqual(text.count("\n--- "), 256)
        self.assertEqual(text.count("nobody here has it -- unreachable"), 2)   # Thevel, the gate guard
        self.assertIn(">> VIRT", text)

    def test_u5(self):
        got = run("ultima.dialogue.u5talk", "--out", os.path.join(OUT, "u5"))

        self.assertEqual(sum(int(l.split(": ")[1].split()[0]) for l in got.splitlines()
                             if l.endswith("conversations")), 135)
        self.assertIn("Sutek", read("u5", "3B-Dwelling.txt"))


if __name__ == "__main__":
    unittest.main()
