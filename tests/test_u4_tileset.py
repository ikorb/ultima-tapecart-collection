"""Ultima IV Remastered's tile set as a launch-time switch (ultima/games/u4/
tileset.py): a fifth block map holds disk A with the new tiles, the launcher's
G points the driver's disk-A map at it.  Checked on the cart as stored."""
import hashlib
import unittest
from pathlib import Path

from tests import fixtures
from tests import test_u4_build as tb
from tests import test_page
from ultima.launcher import patches
from ultima.flash import regions


u4 = tb.u4
ts = u4.tileset

# SHA-256 (first 16 digits) of an independent port of the kit's generators
# and of its creation units built by the kit's own rules: what tiles.py and
# kit_creation() must reproduce from the kit's sources (and disk A)
GRAPHICS = {"bitmap": "7333cd317ee338f0", "font": "bed70665b4ddcaee",
            "table 0 and the font's colours": "b459304e419d752b",
            "tables 1-3": "8bcca6b6ad6671db"}
UNITS = {"145": "3c8d2b6cc8bd565b", "146": "a3eee80e3f7d6fa7", "147": "f205dc5132072a84",
         "148": "e3a0af2abd4a7b95", "149": "2c6bcb007b92a86e", "14a": "c65d5911247a1954",
         "14b": "844b14f490394502", "151": "c64a38778a57637d", "152": "be026c7c72a443da",
         "19f": "365eea03cdb8716a"}


def sha(data):
    return hashlib.sha256(data).hexdigest()[:16]


class TestTileset(unittest.TestCase):
    setUpClass = classmethod(tb.TestU4Build.setUpClass.__func__)
    mapped = tb.TestU4Build.mapped
    map_entry = tb.TestU4Build.map_entry
    segment = tb.TestU4Build.segment
    expected_image = tb.TestU4Build.expected_image
    journey_body = tb.TestU4Build.journey_body
    _disk1_patches = tb.TestU4Build._disk1_patches

    def chunk_span(self, index):
        start, count, dest = u4.chunk_entry(u4.kernel_image(self.disks[1]), index)
        return start * 256, (start + count) * 256, dest

    def test_the_graphics_are_the_kits(self):
        """tiles.py against an independent port of the kit's generators:
        the bitmap, the tables, the font and its colours."""
        bm, tabs, fb, fc = ts.graphics()
        got = {"bitmap": sha(bm), "font": sha(fb),
               "table 0 and the font's colours": sha(tabs[0] + fc),
               "tables 1-3": sha(b"".join(tabs[1:]))}
        self.assertEqual(got, GRAPHICS)

    def test_the_fifth_map_is_disk_a_with_the_tiles(self):
        """Every block through the tile set's map: disk A as the classic map
        has it, but for the tile bitmap, the font, table 0 and the font's
        colours, and the five routines' slots."""
        classic = self.mapped(1)
        self.assertEqual(classic, self.expected_image(1))
        got = self.mapped(u4.TILESET)
        allowed = set()
        for chunk in (0x41, 0x42):
            lo, hi, _d = self.chunk_span(chunk)
            allowed |= set(range(lo, hi))
        lo, _hi, dest = self.chunk_span(0x4C)
        allowed |= set(range(lo + ts.TABLE0 - dest, lo + ts.FONT_COLOURS + 0x80 - dest))
        for seg, (addr, size) in ts.SLOTS.items():
            lo, _hi, dest = self.chunk_span(ts.CHUNK_OF[seg])
            o = lo + (addr - dest)
            allowed |= set(range(o, o + size))
        for chunk in (ts.TITLE_BITMAP, ts.TITLE_COLOURS):  # the title's view
            lo, hi, _d = self.chunk_span(chunk)
            allowed |= set(range(lo, hi))
        for chunk in ts.CREATION:                   # and Remastered's creation
            lo, hi, _d = self.chunk_span(chunk)
            allowed |= set(range(lo, hi + (256 if chunk == ts.LONGER else 0)))
        diff = {i for i, (a, b) in enumerate(zip(classic, got)) if a != b}
        self.assertTrue(diff)
        self.assertLessEqual(diff, allowed)
        # and what is there is what tileset.py makes of it
        want, _t2 = ts.variant(classic, self.disks[1].data,
                               lambda c: u4.chunk_entry(u4.kernel_image(self.disks[1]), c), u4.patch)
        self.assertEqual(got, want)

    def test_the_renderers_read_the_four_tables(self):
        """The kit's drawview and the title's copy, stored: table 0 at $E1B0
        and tables 1-3 at $A700-$A9FF -- never the kit's $F300 (read in play)
        -- and each within its slot."""
        got = self.mapped(u4.TILESET)
        for seg in ("DRAWVIEW", "DRAWVIEWTITLE"):
            addr, size = ts.SLOTS[seg]
            lo, _hi, dest = self.chunk_span(ts.CHUNK_OF[seg])
            code = got[lo + addr - dest:lo + addr - dest + size]
            for tab in (ts.TABLE0, ts.TABLES, ts.TABLES + 0x100, ts.TABLES + 0x200):
                self.assertIn(bytes([0xBD, tab & 0xFF, tab >> 8]), code, (seg, hex(tab)))
            for page in (0xF2, 0xF3):
                self.assertNotIn(bytes([0xBD, 0x00, page]), code, (seg, hex(page)))

    def test_creation_is_the_kits(self):
        """Remastered's creation, as stored: each of its units the kit's
        byte for byte where the kit changed the original, ours elsewhere --
        and chunk $9F's sixth block (disk A 296) its last page, loading to
        $9D00, where no chunk or record of the game loads."""
        got, classic, orig = self.mapped(u4.TILESET), self.mapped(1), self.disks[1].data
        kernel = u4.kernel_image(self.disks[1])
        units = ts.kit_creation(orig, lambda c: u4.chunk_entry(kernel, c))
        self.assertEqual({n: sha(p) for n, p in units.items()}, UNITS)
        for chunk, name in ts.CREATION.items():
            lo, hi, dest = self.chunk_span(chunk)
            prg = units[name]
            self.assertEqual(prg[0] | prg[1] << 8, dest, name)
            kit = prg[2:]
            for i, b in enumerate(kit):
                self.assertEqual(got[lo + i], b if b != orig[lo + i] else classic[lo + i],
                                 f"{name} at {dest + i:#06x}")
            self.assertEqual(-(-len(kit) // 256), (hi - lo) // 256 + (chunk == ts.LONGER))
        lo, hi, dest = self.chunk_span(ts.LONGER)
        self.assertEqual((hi // 256, dest + (hi - lo)), (296, 0x9D00))
        kernel = u4.kernel_image(self.disks[1])
        for c in range(u4.CHUNK_FIRST, 0xA0):
            _s, n, d = u4.chunk_entry(kernel, c)
            self.assertFalse(n and d < 0x9E00 and d + n * 256 > 0x9D00, hex(c))

    @fixtures.needs("u4_title_frame.bin")
    def test_the_title_picture_is_the_renderers_frame(self):
        """The title's dissolve shows its picture (bitmap $43, colours $9E)
        before the renderer draws the view: with the tile set, its view is
        what our renderer draws -- the first frame captured in VICE
        (tests/data/u4_title_frame.bin: the bitmap at $2000, then the
        screen at $0400), every cell but the scrolling water's -- and the
        classic map keeps the original picture."""
        frame = Path(fixtures.path("u4_title_frame.bin")).read_bytes()
        fbm, fsc = frame[:8000], frame[8000:]
        got, classic, orig = self.mapped(u4.TILESET), self.mapped(1), self.disks[1].data
        ps, pe, _pd = self.chunk_span(ts.TITLE_BITMAP)
        cs, ce, _cd = self.chunk_span(ts.TITLE_COLOURS)
        self.assertEqual(classic[ps:pe], orig[ps:pe])
        self.assertEqual(classic[cs:ce], orig[cs:ce])
        ts_, te, _ = self.chunk_span(0x41)
        view = ts.view_map(orig[ps:pe], orig[ts_:te])
        self.assertEqual(len(view), ts.VIEW_H * ts.VIEW_W)
        water = 0
        for r, c, t in view:
            for rr, cc in ((r, c), (r, c + 1), (r + 1, c), (r + 1, c + 1)):
                # the colours, but a black background under the dissolve
                self.assertEqual(got[cs + rr * 40 + cc], fsc[rr * 40 + cc] & 0xF0, (rr, cc))
                if t in ts.WATER:
                    water += 1
                    continue
                o = rr * 320 + cc * 8
                self.assertEqual(got[ps + o:ps + o + 8], fbm[o:o + 8], (rr, cc, t))
        self.assertLess(water, 4 * len(view))
        # outside the view the picture is the original's
        rows = range(ts.VIEW_ROW * 320, (ts.VIEW_ROW + 2 * ts.VIEW_H) * 320)
        for o in range(pe - ps):
            if o not in rows:
                self.assertEqual(got[ps + o], orig[ps + o], hex(o))

    def test_the_tables_are_a_boot_segment(self):
        _bm, tabs, _fb, _fc = ts.graphics()
        self.assertEqual(self.segment(ts.TABLES), tabs[1] + tabs[2] + tabs[3])
        self.assertEqual(ts.TABLES + 0x300, 0xAA00, "up to the save-game buffers")

class TestTilesetPage(unittest.TestCase):
    """G on U4's page: the setting persists, and a launch with it on pokes the
    driver's disk-A map entry with the tile set's map."""
    run_page = test_page.TestPage.run_page
    option = test_page.TestPage.option

    @classmethod
    def setUpClass(cls):
        test_page.TestPage.setUpClass.__func__(cls)
        cls.p = u4.parts()

    def pokes(self, sim):
        p = sim.mpu.x | sim.mpu.y << 8
        return [(sim.mem[p + 1 + 3 * i] | sim.mem[p + 2 + 3 * i] << 8, sim.mem[p + 3 + 3 * i])
                for i in range(sim.mem[p])]

    def test_g_switches_the_map(self):
        want = self.p["options"]["pokes"][patches.TILES]
        maps = self.p["map_addr"][u4.TILESET]
        self.assertEqual([v for _a, v in want[:3]], [maps & 0xFF, maps >> 8 & 0xFF, maps >> 16])
        # chunk $9F one block longer in the kernel's table (Remastered's creation)
        self.assertEqual(want[3], (u4.CHUNK_CNT + ts.LONGER - u4.CHUNK_FIRST, 6))
        flash = bytearray(self.fresh)
        sim, cart, text = self.run_page(flash, "u4", [ord("G"), ord("L")])
        self.assertEqual(self.option("Graphics"), "Remastered")
        got = self.pokes(sim)
        for poke in want:
            self.assertIn(poke, got)
        page = cart.flash[regions.SETTINGS:regions.SETTINGS + 256]
        self.assertEqual(page[4 + regions.DESC_INDEX["u4"]] & patches.TILES, patches.TILES)
        # the next launch remembers; G again turns it off
        sim, cart, text = self.run_page(bytearray(cart.flash), "u4", [ord("L")])
        self.assertTrue(all(p in self.pokes(sim) for p in want))
        sim, cart, text = self.run_page(bytearray(cart.flash), "u4", [ord("G"), ord("L")])
        self.assertEqual(self.option("Graphics").rstrip(), "original")
        self.assertFalse([p for p in self.pokes(sim) if p in want])

    def test_other_games_have_no_tile_set(self):
        for g in ("u1", "u3", "u5"):
            _sim, _cart, text = self.run_page(bytearray(self.fresh), g, [ord("G"), ord("B")])
            self.assertNotIn("Graphics", text)


if __name__ == "__main__":
    unittest.main()
