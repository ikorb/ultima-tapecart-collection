"""Ultima 6's key queue, in `game`'s IRQ (ultima/games/u6/u6key.s): the real code,
original and as built, run in py65 once per frame -- $0196 holding the key
the scan found that frame, as $1F71 leaves it -- counting what is queued at
$D7E4.

The original drops a quick second tap of the same key whatever the gap
(measured in VICE before the fix: 4 frames down, 3 or 12 up, 4 down -- one
key).  The fix must queue it, keep a held key's repeat as it was, and still
take a key that bounces up for a frame mid-press as if it had been held.

Skipped without py65 (the repository's .venv has it).
"""
import importlib.util
import unittest

from ultima import paths
from ultima.disks.d64 import D64

try:
    from ultima.sim.sim6502 import Sim
except ImportError:
    Sim = None

_spec = importlib.util.find_spec("ultima.games.u6.build")
u6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(u6)

BLOCK = 0x1F76
J, K, RETURN, UP = 0x4A, 0x4B, 0x0D, 0x40     # UP: '@', a direction key only


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestU6Keys(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = u6.parts()
        cls.built = cls.p["game"]
        orig = bytearray(cls.built)
        o = BLOCK - u6.GAME_ADDR
        game = bytes(D64(paths.disk("u6-3b")).file("GAME")[0])     # the original, PRG header first
        orig[o:o + len(u6.KEY_QUEUE)] = game[2 + o:2 + o + len(u6.KEY_QUEUE)]
        assert orig[o:o + len(u6.KEY_QUEUE)] == u6.KEY_QUEUE
        cls.orig = bytes(orig)

    def frames(self, image, presses):
        """presses: (key or 0, frames) runs; returns the keys queued."""
        sim = Sim(image, u6.GAME_ADDR, self.p["rsym"])
        sim.mem[0x45] = 0
        sim.mem[0x43] = 0
        sim.mem[0x0197] = 0
        got = []
        for key, n in presses + [(0, 30)]:
            for _ in range(n):
                sim.mem[0x01] = 0x35
                sim.mem[0x47] = 0
                sim.mem[0x0196] = key
                sim.mpu.a = key
                sim.call(BLOCK)
                self.assertEqual(sim.mem[0x01], 0x35, "$01 not put back")
                got += list(sim.mem[0xD7E4:0xD7E4 + sim.mem[0x45]])
                sim.mem[0x45] = 0               # the main loop takes them
        return got

    def test_the_original_drops_a_second_tap(self):
        self.assertEqual(self.frames(self.orig, [(J, 4), (0, 3), (J, 4)]), [J])
        self.assertEqual(self.frames(self.orig, [(J, 4), (0, 12), (J, 4)]), [J])
        self.assertEqual(self.frames(self.orig, [(J, 4), (0, 3), (K, 4)]), [J, K])

    def test_a_second_tap_counts(self):
        """...if it is down on the 10th frame after the first, when a held
        key would have repeated; after any longer gap at once."""
        for hold in range(1, 9):
            for gap in range(1, 300):
                got = self.frames(self.built, [(J, hold), (0, gap), (J, hold)])
                self.assertEqual(got, [J, J] if 2 * hold + gap >= 10 else [J],
                                 f"{hold} down, {gap} up")
        # Return (also the fire bit) through a conversation, 5.5 taps a second
        self.assertEqual(self.frames(self.built, [(RETURN, 4), (0, 5)] * 5), [RETURN] * 5)
        self.assertLess(len(self.frames(self.orig, [(RETURN, 4), (0, 5)] * 5)), 5)

    def test_a_bounce_is_as_if_held(self):
        """A frame up mid-press never makes another key: no more keys than
        the original queues for the press held throughout (one fewer when
        the frame up is the one a repeat was due on: it comes a frame later)."""
        for before in range(1, 25):
            for after in range(1, 25):
                got = self.frames(self.built, [(J, before), (0, 1), (J, after)])
                held = self.frames(self.orig, [(J, before + 1 + after)])
                self.assertIn(len(got), (len(held), len(held) - 1), f"{before} down, 1 up, {after} down")
                self.assertGreaterEqual(len(got), 1)

    def test_a_held_key_repeats_as_before(self):
        for n in (1, 9, 10, 18, 19, 40):
            self.assertEqual(self.frames(self.built, [(J, n)]), self.frames(self.orig, [(J, n)]), n)
        self.assertEqual(len(self.frames(self.built, [(J, 40)])), 5)

    def test_directions_go_to_the_joystick_bits_only(self):
        for image in (self.orig, self.built):
            sim = Sim(image, u6.GAME_ADDR, self.p["rsym"])
            sim.mem[0x45], sim.mem[0x47], sim.mem[0x01] = 0, 0, 0x35
            sim.mem[0x0196] = sim.mpu.a = UP
            sim.call(BLOCK)
            self.assertEqual((sim.mem[0x45], sim.mem[0x47]), (0, 0x04))
            sim.mem[0x0196] = sim.mpu.a = RETURN        # direction table, fire bit: both
            sim.call(BLOCK)
            self.assertEqual((sim.mem[0x45], sim.mem[0xD7E4], sim.mem[0x47] & 0x10), (1, RETURN, 0x10))

    def test_a_full_queue_takes_nothing(self):
        sim = Sim(self.built, u6.GAME_ADDR, self.p["rsym"])
        sim.mem[0x45], sim.mem[0x43], sim.mem[0x01] = 0x1B, 0, 0x35
        sim.mem[0x0196] = sim.mpu.a = J
        sim.call(BLOCK)
        self.assertEqual(sim.mem[0x45], 0x1B)


if __name__ == "__main__":
    unittest.main()


class CIA1:
    """Memory with CIA 1's port A as far as the text boxes' key wait uses it:
    the data register and its direction ($DC00/$DC02), the keyboard matrix
    read on $DC01 (a row is selected by a pin driven low), joystick 2 on
    port A's pins (fire = bit 4 low).  Port B is all inputs."""

    def __init__(self):
        self.ram = bytearray(0x10000)
        self.pra, self.ddra = 0xFF, 0x00
        self.keys = set()               # (row, column) held
        self.fire = False

    def pins_a(self):
        out = (self.pra | ~self.ddra) & 0xFF         # driven, or pulled up
        return out & (0xEF if self.fire else 0xFF)

    def __getitem__(self, a):
        if isinstance(a, slice):
            return [self[i] for i in range(*a.indices(0x10000))]
        if a == 0xDC00:
            return self.pins_a()
        if a == 0xDC01:
            rows = self.pins_a()
            col = 0xFF
            for r, c in self.keys:
                if not rows & (1 << r):
                    col &= ~(1 << c)
            return col & 0xFF
        if a == 0xDC02:
            return self.ddra
        return self.ram[a]

    def __setitem__(self, a, v):
        if isinstance(a, slice):
            for i, x in zip(range(*a.indices(0x10000)), v):
                self[i] = x
            return
        if a == 0xDC00:
            self.pra = v & 0xFF
        elif a == 0xDC02:
            self.ddra = v & 0xFF
        else:
            self.ram[a] = v & 0xFF

    def __len__(self):
        return 0x10000


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestU6KeyWait(unittest.TestCase):
    """The text boxes' "press a key" in OPENING, INTRO and END (build.py
    KEYWAIT; in the Introduction only the joystick works, on the original
    disks too): Z set when Space (row 7, column 4) or fire
    is down -- whatever rows the title menu's scan left selected (none: port
    A's data register $FF) -- after a few polls at most; X and Y kept."""
    SPACE = (7, 4)

    @classmethod
    def setUpClass(cls):
        from ultima.disks.d64 import D64
        disks = {"3B": D64(u6.disk_path("3B"))}
        cls.files = {}
        for name in u6.KEYWAIT:
            data = bytearray(disks["3B"].file(name)[0])
            u6.patch(data, u6.KEYWAIT[name], 0x0200, u6.KEYWAIT_OLD, u6.KEYWAIT_NEW, name)
            cls.files[name] = bytes(data)
        cls.orig = {name: disks["3B"].file(name)[0] for name in u6.KEYWAIT}

    def polls(self, image, name, mem, n):
        """Z after each of n calls of the routine."""
        from py65.devices.mpu6502 import MPU
        mem.ram[0x0200:0x0200 + len(image) - 2] = image[2:]
        mpu = MPU(memory=mem)
        out = []
        for _ in range(n):
            mpu.sp, mpu.x, mpu.y = 0xFD, 0x5A, 0xA5
            mem.ram[0x1FE], mem.ram[0x1FF] = 0xFF, 0xEF       # return to $F000
            mpu.pc = u6.KEYWAIT[name]
            while mpu.pc != 0xF000:
                mpu.step()
            self.assertEqual((mpu.x, mpu.y), (0x5A, 0xA5), "X and Y kept")
            self.assertEqual(mem.ddra, 0x00, "port A left as inputs")
            out.append(bool(mpu.p & 0x02))
        return out

    def test_space_after_the_menu_left_no_row_selected(self):
        for name, image in self.files.items():
            mem = CIA1()
            mem.keys.add(self.SPACE)
            got = self.polls(image, name, mem, 10)
            self.assertTrue(got[-1], f"{name}: Space never seen")
            self.assertTrue(all(got[got.index(True):]), f"{name}: Space seen, then lost")
            self.assertLessEqual(got.index(True), 8)
            # the original: never
            mem = CIA1()
            mem.keys.add(self.SPACE)
            self.assertFalse(any(self.polls(self.orig[name], name, mem, 10)), "the bug, as found")

    def test_nothing_held_and_fire(self):
        for name, image in self.files.items():
            mem = CIA1()
            self.assertFalse(any(self.polls(image, name, mem, 12)), name)
            mem.fire = True
            self.assertTrue(all(self.polls(image, name, mem, 3)), name)
            mem.fire = False
            mem.keys.add((1, 2))                    # A: another column, not a "key" here
            self.assertFalse(any(self.polls(image, name, mem, 3)), name)
