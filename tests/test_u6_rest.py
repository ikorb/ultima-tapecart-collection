"""Ultima VI's Rest overlay (ultima/games/u6/build.py REST_FIXES): the guard's "I hear
something!" ends the rest, and the last party member can stand guard --
checked on the overlay as the cart stores it (1A/1B T24 S16-18 through the
block maps), run in py65 with the original's sectors as the control.

Skipped without py65 (the repository's .venv has it)."""
import unittest

try:
    from ultima.sim.sim6502 import Sim
except ImportError:
    Sim = None

from ultima.disks.d64 import D64
from tests import test_u6_compendium as tc
from ultima import paths

u6 = tc.u6



GUARD_ASK, GUARD_SET = 0xC8D6, 0xC8EA      # "?" and the answer, STX $CAE8
ALARM = 0xC930                              # the guard heard something
PRINT, PRINT_RET = 0x0380, 0x0383           # inline print: and go on / and return from the caller
ASK_NUMBER, NAME, DONE_CMD = 0x0362, 0x0311, 0x0239
HOURS_LEFT, STATUS = 0x589F, 0x5A61


def original(tag):
    d = D64(paths.disk("u6-" + tag.lower()))

    return b"".join(bytes(d.sector(u6.REST_TRACK, s)) for s in u6.REST_SECTORS)


def skip_string(sim):
    """The stacked return address past the inline string's $00."""
    m, sp = sim.mem, sim.mpu.sp
    a = (m[0x101 + sp] | m[0x102 + sp] << 8) + 1
    while m[a]:
        a += 1
    m[0x101 + sp], m[0x102 + sp] = a & 0xFF, a >> 8


def print_and_return(sim):
    skip_string(sim)
    sim.mpu.sp = (sim.mpu.sp + 2) & 0xFF     # the trap's RTS then leaves the caller


class TestRest(unittest.TestCase):
    setUpClass = classmethod(tc.TestCompendium.setUpClass.__func__)

    def stored(self, tag):
        n = u6.SECTOR_DISKS[tag]
        out = b""
        for s in u6.REST_SECTORS:
            m = self.p["maps"][n] + (u6.REST_TRACK * u6.GRID + s) * 4
            a = self.flash[m] | self.flash[m + 1] << 8 | self.flash[m + 2] << 16
            out += bytes(self.flash[a:a + 256])
        return out

    def test_differs_only_by_the_fixes(self):
        for tag in u6.SECTOR_DISKS:
            with self.subTest(disk=tag):
                want = bytearray(original(tag))
                for addr, old, new in u6.REST_FIXES:
                    at = addr - u6.REST_ORG
                    self.assertEqual(bytes(want[at:at + len(old)]), old)
                    want[at:at + len(new)] = new
                self.assertEqual(self.stored(tag), bytes(want))

    # -- the guard -----------------------------------------------------
    def guard(self, image, members, answers):
        """The answer stored at $CAE8 after the prompt has been given
        `answers` in turn (one hex digit each, 0 for Return alone)."""
        sim = Sim(image, u6.REST_ORG, {})
        sim.mem[0x15] = members - 1
        given = iter(answers)
        sim.traps[PRINT] = skip_string

        def ask(s):
            s.mpu.x = next(given)
        sim.traps[ASK_NUMBER] = ask
        got = []
        sim.traps[GUARD_SET] = lambda s: got.append(s.mpu.x)
        sim.call(GUARD_ASK, limit=100_000)
        self.assertEqual(len(got), 1)
        return got[0]

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_every_member_can_stand_guard(self):
        """1..party size picks that member, 0 nobody ($FF); anything else is
        asked again (the 0 that follows answers it)."""
        image = self.stored("1A")
        for members in range(1, 7):
            for k in range(16):
                with self.subTest(members=members, answer=k):
                    want = 0xFF if k == 0 else k - 1 if k <= members else 0xFF
                    self.assertEqual(self.guard(image, members, [k, 0]), want)

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_the_original_refused_the_last_member(self):
        image = original("1A")
        for members in range(1, 7):
            with self.subTest(members=members):
                self.assertEqual(self.guard(image, members, [members, 0]), 0xFF)
                if members > 1:
                    self.assertEqual(self.guard(image, members, [members - 1, 0]), members - 2)

    # -- the alarm -----------------------------------------------------
    def alarm(self, image, guard=1):
        party = [1, 2, 3, 4]
        sim = Sim(image, u6.REST_ORG, {})
        m = sim.mem
        m[0x15] = len(party) - 1
        m[0x16:0x16 + len(party)] = party
        m[0xCAE8] = guard
        m[HOURS_LEFT] = 5
        for i, a in enumerate(party):
            m[STATUS + a] = 0x00 if i == guard else 0x91
        sim.traps[PRINT] = skip_string
        sim.traps[PRINT_RET] = print_and_return
        sim.traps[NAME] = lambda s: None
        ended = []
        sim.traps[DONE_CMD] = lambda s: ended.append(True)
        sim.call(ALARM, limit=100_000)
        return m[HOURS_LEFT], [m[STATUS + a] for a in party], bool(ended)

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_the_alarm_ends_the_rest(self):
        """The hours left 0, everyone awake (1, as a rest run to its end
        leaves them), the command ended through $0239."""
        for tag in u6.SECTOR_DISKS:
            for guard in range(4):
                with self.subTest(disk=tag, guard=guard):
                    self.assertEqual(self.alarm(self.stored(tag), guard), (0, [1, 1, 1, 1], True))

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_the_original_went_on_resting(self):
        self.assertEqual(self.alarm(original("1A")), (5, [0x91, 0x00, 0x91, 0x91], False))


if __name__ == "__main__":
    unittest.main()
