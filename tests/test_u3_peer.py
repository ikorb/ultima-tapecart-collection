"""Ultima III's gem peer in colour (ultima/games/u3/u3outm.s, u3dngm.s).

Both overlays run in py65 on the real SUBS (its view clear, map read and
glyph printer), TEXT (the font) and the DOS module, with the keyboard
trapped and the raster line counting; the screen RAM starts as a real one
from VICE (tests/data/u3_screen.bin: the frame $E0, text $10, the view in the
tiles' colours).

Surface: while the peer is up every tile of Sosaria (and Ambrosia) shows in
its colour -- decoded from the multicolour bitmap, screen RAM, colour RAM and
$D021 as the VIC would -- or, where a cell of 4 x 4 tiles has more than three
colours, a stand-in, and a town, castle, dungeon, lava or moongate always its
own; everything off the map is blue.  Afterwards the registers, the panels'
screen RAM and the view ($10, its bitmap clear) are as the original leaves
them.  Dungeon: the glyphs are the original DNGM's, byte for byte, each
square's cell has its kind's colour, and the cells get their colours back.
"""
import unittest
from pathlib import Path

from tests import fixtures
from ultima.disks.d64 import D64
from ultima import paths

DISK_B = paths.disk("u3b")
DOS_BLOCKS = range(92, 96)          # disk A T5/S8-S11, loaded to $B800-$BBFF
SCREEN_FIXTURE = fixtures.path("u3_screen.bin")

SCREEN, BITMAP, COLRAM = 0x0400, 0x2000, 0xD800
KB_GET, KB_FLUSH = 0xB80C, 0xB80F
BG = 6
# what each surface tile should look like (tile >> 2 -> top line, bottom line)
GREEN, LGREEN = 5, 13
EXPECT = {0: (BG, BG), 1: (LGREEN, LGREEN), 2: (LGREEN, GREEN), 3: (GREEN, GREEN),
          4: (8, 8), 5: (0, 0), 6: (1, 1), 7: (7, 7), 33: (2, 2), 34: (3, 3), 35: (12, 12)}
PLACES = {0, 1, 2, 3, 7}        # dungeon, town, lava, moongate, castle
DUNGEON_COLOURS = {0xC0: 0x80, 0xA0: 0x40, 0x80: 0xC0, 0x30: 0x30, 0x20: 0x70, 0x10: 0xD0}



def dos_module():
    """The DOS module, as disk A holds it (the analysis of U3, section (a))."""
    d = D64(paths.disk("u3a"))
    return b"".join(bytes(d.sector(*D64.from_linear(n))) for n in DOS_BLOCKS)

def blocks(disk, start, count):
    return b"".join(disk.sector(*D64.from_linear(n)) for n in range(start, start + count))


@fixtures.needs("u3_screen.bin")
class TestU3Peer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import py65  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("py65 is not installed (use the repository's .venv)")
        import importlib.util as _il
        spec = _il.find_spec("ultima.games.u3.build")
        mod = _il.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cls.units = mod.parts()["unit_data"]
        cls.b = D64(DISK_B)
        cls.screen = Path(SCREEN_FIXTURE).read_bytes()[:1000]

    def machine(self, overlay, map_unit, keys_after=40):
        """A U3 in py65: SUBS, TEXT, the DOS module, a map at $1000, the
        overlay at $9400, the screen as in play.  The first keys_after key
        polls answer none, then SPACE."""
        from ultima.sim.sim6502 import Sim
        from py65.memory import ObservableMemory
        sim = Sim(bytes(overlay), 0x9400, {})
        for addr, data in ((0x4100, self.units["SUBS"]), (0xB400, self.units["TEXT"]),
                           (0xB800, dos_module()), (0x1000, map_unit)):

            sim.mem[addr:addr + len(data)] = list(data)
        sim.mem[SCREEN:SCREEN + 1000] = list(self.screen)
        raster = [0]

        def d012(_a):
            raster[0] = (raster[0] + 1) % 312
            return raster[0] & 0xFF
        om = ObservableMemory(subject=sim.mem)
        om.subscribe_to_read([0xD012], d012)
        sim.mpu.memory = sim.mem = om
        sim.mem[0xD016], sim.mem[0xD020], sim.mem[0xD021] = 0xC8, 0xF0, 0xF0
        state = {"polls": 0, "seen": None}

        def get(s):
            state["polls"] += 1
            if state["polls"] == 1:
                state["seen"] = self.snapshot(s)
            s.mpu.a = 0xFF if state["polls"] < keys_after else 0xA0
        sim.traps[KB_GET] = get
        sim.traps[KB_FLUSH] = lambda s: None
        return sim, state

    @staticmethod
    def snapshot(sim):
        m = sim.mem
        return dict(bitmap=bytes(m[BITMAP:BITMAP + 8000]), screen=bytes(m[SCREEN:SCREEN + 1000]),
                    colram=bytes(m[COLRAM + i] & 0x0F for i in range(1000)),
                    d016=m[0xD016], d020=m[0xD020], d021=m[0xD021])

    @staticmethod
    def shown(snap, tx, ty, line):
        """The colour the VIC shows for tile (tx, ty)'s line (0 or 1)."""
        col, row = 4 + tx // 4, 4 + ty // 4
        cell = row * 40 + col
        byte = snap["bitmap"][row * 320 + col * 8 + (ty % 4) * 2 + line]
        pair = byte >> (6 - 2 * (tx % 4)) & 3
        return [snap["d021"] & 15, snap["screen"][cell] >> 4, snap["screen"][cell] & 15,
                snap["colram"][cell]][pair]

    def surface(self, name):
        world = bytes(self.units[name])[:4096]
        sim, state = self.machine(self.units["OUTM"], world)
        sim.mem[0xF7], sim.mem[0xF8] = 20, 30
        sim.call(0x9400)
        seen = state["seen"]
        self.assertIsNotNone(seen, "the peer never waited for a key")
        self.assertEqual(seen["d016"], 0xD8, "multicolour while it is up")
        self.assertEqual((seen["d020"] & 15, seen["d021"] & 15), (BG, BG))
        # every tile
        exact = substituted = 0
        for ty in range(64):
            for tx in range(64):
                tile = world[ty * 64 + tx] >> 2
                want = EXPECT.get(tile, (15, 15))
                got = (self.shown(seen, tx, ty, 0), self.shown(seen, tx, ty, 1))
                if got == want:
                    exact += 1
                    continue
                # only where the cell had more than three colours, never a place
                cx, cy = tx // 4, ty // 4
                colours = {c for y in range(cy * 4, cy * 4 + 4) for x in range(cx * 4, cx * 4 + 4)
                           for c in EXPECT.get(world[y * 64 + x] >> 2, (15, 15)) if c != BG}
                places = colours & PLACES
                self.assertGreater(len(colours), 3, f"{name} tile ({tx},{ty}) {tile:#x}: {got} for {want}")
                if len(places) <= 3:
                    self.assertFalse(set(want) & places, f"{name}: a place lost its colour at ({tx},{ty})")
                substituted += 1
        # everything off the map is the sea
        for cell in range(1000):
            row, col = divmod(cell, 40)
            if 4 <= row < 20 and 4 <= col < 20:
                continue
            if self.screen[cell] in (0x10, 0xE0) or (1 <= row <= 22 and 1 <= col <= 22):
                self.assertEqual(seen["screen"][cell], BG * 17, f"cell {row},{col}")
            self.assertEqual(seen["colram"][cell], BG, f"cell {row},{col}")
        # afterwards
        m = sim.mem
        self.assertEqual((m[0xD016], m[0xD020], m[0xD021]), (0xC8, 0xF0, 0xF0))
        for cell in range(1000):
            row, col = divmod(cell, 40)
            want = 0x10 if 1 <= row <= 22 and 1 <= col <= 22 else self.screen[cell]
            self.assertEqual(m[SCREEN + cell], want, f"cell {row},{col} after")
        for line in range(8, 184):
            for col in range(1, 23):
                a = BITMAP + (line // 8) * 320 + col * 8 + line % 8
                self.assertEqual(m[a], 0, "the view's bitmap is left clear")
        return exact, substituted

    def test_sosaria(self):
        exact, substituted = self.surface("SOSA")
        self.assertGreater(exact, 4000)

    def test_ambrosia(self):
        exact, substituted = self.surface("MAPZ")
        self.assertGreater(exact, 3900)

    def test_the_party_blinks(self):
        world = bytes(self.units["SOSA"])[:4096]
        sim, state = self.machine(self.units["OUTM"], world, keys_after=200)
        sim.mem[0xF7], sim.mem[0xF8] = 21, 30
        frames = []
        orig = sim.traps[KB_GET]

        def get(s):
            frames.append(s.mem[BITMAP + (4 + 7) * 320 + (4 + 5) * 8 + 4])
            orig(s)
        sim.traps[KB_GET] = get
        sim.call(0x9400)
        self.assertGreater(len(set(frames)), 1, "the party's tile toggles")

    def dungeon(self, overlay, level_map):
        sim, state = self.machine(overlay, level_map)
        sim.mem[0x23] = 0
        sim.mem[0xF7], sim.mem[0xF8] = 3, 5
        # $46C3 prints the inline string after the JSR ($FF, 0): skip it
        def skip(s):
            sp = s.mpu.sp
            ret = s.mem[0x101 + sp] | s.mem[0x102 + sp] << 8
            ret += 2
            s.mem[0x101 + sp], s.mem[0x102 + sp] = ret & 0xFF, ret >> 8
        sim.traps[0x46C3] = skip
        sim.traps[0x1800] = lambda s: None          # DDRW's redraw
        sim.call(0x9400)
        return sim, state["seen"]

    def test_dungeon_glyphs_as_the_original_colours_by_kind(self):
        level = blocks(self.b, 216, 8)              # MAPM: a dungeon's levels
        self.assertEqual(level, bytes(self.units["MAPM"])[:2048])
        _, old = self.dungeon(blocks(self.b, 371, 1), level)
        sim, new = self.dungeon(self.units["DNGM"], level)
        self.assertEqual(new["bitmap"], old["bitmap"], "the same glyphs")
        for y in range(16):
            for x in range(16):
                cell = (4 + y) * 40 + 4 + x
                sq = level[y * 16 + x]
                if (x, y) == (3, 5):
                    want = 0x10
                elif sq == 0:
                    want = self.screen[cell]
                else:
                    want = DUNGEON_COLOURS.get(sq, 0xA0)
                self.assertEqual(new["screen"][cell], want, f"square ({x},{y}) {sq:#x}")
        self.assertEqual(bytes(sim.mem[SCREEN:SCREEN + 1000]), self.screen, "the colours back")


if __name__ == "__main__":
    unittest.main()
