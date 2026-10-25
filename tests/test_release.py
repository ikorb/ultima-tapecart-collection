"""The release side: Gold's host unpack, and the scanner's assembly rules.

The end-to-end checks (every game built from assembled stand-ins, compared
with the normal build) take minutes and are `make release-verify`, not here.
"""
import hashlib
import os
import unittest
from pathlib import Path

from ultima.disks.d64 import D64, DATA_LENGTH        # noqa: E402
from ultima.disks import scan                             # noqa: E402
from ultima import paths

GOLD_DISK = paths.disk("u3gold")
try:
    import py65                         # noqa: F401
    HAVE_PY65 = True
except ImportError:
    HAVE_PY65 = False


def sha(data):
    return hashlib.sha256(bytes(data)).hexdigest()[:16]


@unittest.skipUnless(HAVE_PY65 and os.path.exists(GOLD_DISK), "needs py65 and the Gold disk")
class TestGoldUnpack(unittest.TestCase):
    """goldunpack against what it was checked against: a VICE dump on the
    ranges gold.py uses, and `exomizer raw -d -P0` on the files.  Pinned, so
    a change to the unpack shows."""
    unpacked = None

    @classmethod
    def setUpClass(cls):
        from ultima.games.u3 import goldunpack
        cls.unpacked = goldunpack.unpack(GOLD_DISK)

    def test_game_ranges(self):
        g = self.unpacked["game"]
        for name, lo, hi, want in (("SHPS", 0x0800, 0x1000, "dbc634dafc34275c"),
                                   ("SUBS", 0x4000, 0x5000, "b1a3f7b86da7f956"),
                                   ("ULT3", 0x5000, 0x9400, "1a6fa3f678cb2c6d"),
                                   ("TEXT", 0xB400, 0xB800, "44ed78e7c2fae13a")):
            self.assertEqual(sha(g[lo:hi]), want, name)

    def test_files(self):
        for name, want in (("boot", "ba694305f135302e"), ("updt", "092508760f657a2a"),
                           ("shp3", "de17ab941f38d632")):
            self.assertEqual(sha(self.unpacked[name]), want, name)

    def test_the_save_files_are_not_read(self):
        """Gold's saved state (its five raw save files) is no input: a
        played Gold disk builds the same cart."""
        from ultima.games.u3 import goldunpack
        self.assertEqual(goldunpack.SAVES & self.unpacked.keys(), set())


class TestAssembly(unittest.TestCase):
    def test_file_round_trip(self):
        """A file put into a chain reads back the same, links and all, for
        every length around a sector's 254 bytes."""
        chain = [(17, 0), (17, 10), (17, 20), (19, 3)]
        for n in (0, 1, 253, 254, 255, 508, 509, 1000):
            img = bytearray(DATA_LENGTH)
            data = bytes((i * 7 + n) & 0xFF for i in range(n))
            used = chain[:max(1, -(-n // 254))]
            scan._put_file(img, used, data)
            self.assertEqual(scan._file_bytes(img, {"chain": used}), data, n)
            o = D64.offset(*used[-1])
            self.assertEqual(img[o], 0, "the last sector ends the chain")

    def test_seed_rules(self):
        self.assertEqual(scan._seed_bytes({"fill": 0}, 256, {}, {}), bytes(256))
        prty = scan._seed_bytes({"fill": 0, "set": {4: 0x08, 5: 0xFF}}, 256, {}, {})
        self.assertEqual(prty[:8], bytes([0, 0, 0, 0, 8, 0xFF, 0, 0]))
        ro = scan._seed_bytes({"header": 0x2000, "fill": 0, "len": 64}, 0, {}, {})
        self.assertEqual(ro, bytes([0x00, 0x20]) + bytes(64))
        a = bytearray(DATA_LENGTH)
        a[254 * 256:257 * 256] = bytes(range(256)) * 3
        rec = scan._seed_bytes({"template": ["A", 256, 1], "set": {0x0F: 0}}, 256, {"A": a}, {})
        self.assertEqual(rec[0x0E:0x11], bytes([0x0E, 0x00, 0x10]))

    def test_template_disk_incomplete(self):
        """A complete disk whose save takes its template from an incomplete
        disk is not assembled (U4's Britannia and the program disk)."""
        seed = {"kind": "seed", "seed": {"template": ["A", 254, 1], "block": 0, "of": [273, 1]}}
        mm = {"disks": {"A": {"files": {}, "sectors": {}},
                        "B": {"files": {}, "sectors": {"14/0": seed}}}}
        res = {"A": {"missing": [("sector", "12/0")], "got": {}}, "B": {"missing": [], "got": {}}}
        self.assertEqual(scan.assemble(mm, res), {})
        res["A"]["missing"] = []
        self.assertEqual(sorted(scan.assemble(mm, res)), ["A", "B"])

    def test_fixups_hold_on_the_reference(self):
        """Every declared fixup's target byte is the reference disk's, and the
        variant differs from it only there."""
        from ultima.disks import manifest
        for (disk, (t, sec)), fixes in manifest.FIXUPS.items():
            path = paths.disk(disk)

            if not os.path.exists(path):
                self.skipTest(f"{disk} not here")
            data = D64(path).sector(t, sec)
            for off, theirs, ours, _why in fixes:
                self.assertEqual(data[off], ours, (disk, t, sec, off))
                self.assertNotEqual(theirs, ours)

    def test_resets_hold_on_the_reference(self):
        """Every reset's bytes are the reference disk's: putting them back
        changes nothing on an unplayed disk."""
        from ultima.disks import manifest
        for (disk, (t, sec)), fields in manifest.RESETS.items():
            path = paths.disk(disk)
            if not os.path.exists(path):
                self.skipTest(f"{disk} not here")
            data = D64(path).sector(t, sec)
            for off, ours, _why in fields:
                self.assertEqual(data[off:off + len(ours)], ours, (disk, t, sec, off))

    def test_a_new_character_is_put_back(self):
        """A Surface disk with a character made on it (name, sex, attributes,
        magic points, the tables at $5FB0) resolves, its save area comes back
        as the factory's, and the stand-in is the unplayed disk's; one more
        byte of the state (the Avatar's x) and it is refused."""
        import json
        from ultima.disks import manifest
        path = paths.disk("u6-1a")
        if not os.path.exists(path):
            self.skipTest("u6-1a not here")
        m = json.loads(Path(scan.DEFAULT_MANIFEST).read_text())
        mm = {"version": m["version"], "disks": {"u6-1a": m["disks"]["u6-1a"]}}
        clean = Path(path).read_bytes()[:DATA_LENGTH]
        made = bytearray(clean)

        def poke(addr, data):
            t, s = 6, 9 + ((addr - manifest.U6_STATE) >> 8)
            o = D64.offset(t, s) + ((addr - manifest.U6_STATE) & 0xFF)
            made[o:o + len(data)] = data

        poke(0x5700, bytes([0x46, 0x12, 0x01, 0x0E, 0x1A, 0, 0, 0, 0]))
        poke(0x578C, b"\x16"), poke(0x57A3, b"\x10"), poke(0x57D1, b"\x15"), poke(0x5844, b"\x2A")
        poke(0x588B, b"\x01"), poke(0x5FB0, bytes([0x99] * 37 + [0x66] * 43))
        r = scan.resolve(mm, [scan.Image("made", bytes(made))])["u6-1a"]
        self.assertEqual(r["missing"], [])
        self.assertEqual(bytes(scan.assemble(mm, {"u6-1a": r})["u6-1a"]),
                         bytes(scan.assemble(mm, scan.resolve(mm, [scan.Image("clean", clean)]))["u6-1a"]))
        poke(0x5B26, b"\x01")                       # the Avatar's x, low byte
        r = scan.resolve(mm, [scan.Image("moved", bytes(made))])["u6-1a"]
        self.assertEqual([k for _kind, k in r["missing"]], ["6/16"])

    def u3b(self):
        import json
        path = paths.disk("u3b")
        if not os.path.exists(path):
            self.skipTest("u3b not here")
        m = json.loads(Path(scan.DEFAULT_MANIFEST).read_text())
        return {"version": m["version"], "disks": {"u3b": m["disks"]["u3b"]}}, \
            Path(path).read_bytes()[:DATA_LENGTH]

    def test_a_played_sosaria_is_put_back(self):
        """A Player Master with what play leaves on Sosaria -- monsters in
        SOSM (one on a chest), chests on grass, brush and forest, a parked
        horse and frigate, the whirlpool, the moon gate moved -- resolves,
        and the stand-in is the unplayed disk's; a chest on mountains ($24:
        what was under it is not recorded) is refused."""
        from ultima.disks import world
        mm, clean = self.u3b()
        sosa_at, sosm_at = world.SOSA_FIRST * 256, world.SOSM_BLOCK * 256
        sosa = clean[sosa_at:sosa_at + 4096]
        squares = {v: [i for i, b in enumerate(sosa) if b == v] for v in (0x00, 0x04, 0x08, 0x0C, 0x10)}
        water, grass = squares[0x00], squares[0x04]
        played = bytearray(clean)
        sosm = bytearray(256)

        def put(i, v):
            played[sosa_at + i] = v

        for n, (i, tile, under) in enumerate([(grass[0], 0x60, 0x04),      # an orc
                                              (water[0], 0x3C, 0x00),      # a pirate
                                              (grass[1], 0x64, 0x25)]):    # a skeleton on a chest
            put(i, tile)
            sosm[n], sosm[0x20 + n], sosm[0x40 + n], sosm[0x60 + n] = tile, under, i % 64, i // 64
        put(squares[0x08][0], 0x26), put(squares[0x0C][0], 0x27)           # chests on brush, forest
        put(grass[2], 0x28), put(water[1], 0x2C)                           # a horse, a frigate
        put(water[2], 0x30)                                                # the whirlpool
        sosm[0xFC], sosm[0xFD], sosm[0xFE], sosm[0xFF] = water[2] % 64, water[2] // 64, 1, 0
        self.assertEqual((sosa[29 * 64 + 15], sosa[31 * 64 + 31]), (0x88, 0x04))
        put(29 * 64 + 15, 0x04), put(31 * 64 + 31, 0x88)                   # the moon gate moved
        played[sosm_at:sosm_at + 256] = sosm

        r = scan.resolve(mm, [scan.Image("played", bytes(played))])["u3b"]
        self.assertEqual(r["missing"], [])
        self.assertEqual({x[2]["why"] for x in r["got"].values() if len(x) == 3}, {world.WHY["u3b"]})
        self.assertEqual(bytes(scan.assemble(mm, {"u3b": r})["u3b"]),
                         bytes(scan.assemble(mm, scan.resolve(mm, [scan.Image("clean", clean)]))["u3b"]))

        i = squares[0x10][0]
        put(i, 0x24)
        r = scan.resolve(mm, [scan.Image("mountains", bytes(played))])["u3b"]
        t, s = D64.from_linear(world.SOSA_FIRST + i // 256)
        self.assertEqual([k for _kind, k in r["missing"]], [f"{t}/{s}"])

    def test_golds_sosaria_is_put_back(self):
        """Ultima III Gold's SOSA and SOSM hold a played state (10 squares);
        on a Player Master they resolve to the unplayed map.  (The stand-in
        does not carry them: the Gold disk among your images does.)"""
        from ultima.disks import world
        mm, clean = self.u3b()
        images, _skipped = scan.gather([paths.USER_DISKS])
        gold = next((im for im in images if {"ULTIMA III GOLD", "SOSA", "SOSM"}
                     <= {n.strip().upper() for n in im.by_name}), None)
        if gold is None:
            self.skipTest("no Ultima III Gold disk in disks/")
        files = {n.strip().lower(): data[2:] for n, data in gold.by_name.items()}
        played = bytearray(clean)
        played[world.SOSA_FIRST * 256:(world.SOSA_FIRST + 16) * 256] = files["sosa"]
        played[world.SOSM_BLOCK * 256:(world.SOSM_BLOCK + 1) * 256] = files["sosm"]
        self.assertNotEqual(bytes(played), clean)
        r = scan.resolve(mm, [scan.Image("gold's world", bytes(played))])["u3b"]
        self.assertEqual(r["missing"], [])

    def test_a_played_gold_disk_is_taken(self):
        """Gold's five save files are no input: with every one of them
        changed (a party formed and saved), the Gold disk still resolves."""
        import json
        from ultima.games.u3 import goldunpack
        images, _skipped = scan.gather([paths.USER_DISKS])
        gold = next((im for im in images if "ULTIMA III GOLD" in
                     {n.strip().upper() for n in im.by_name}), None)
        if gold is None:
            self.skipTest("no Ultima III Gold disk in disks/")
        m = json.loads(Path(scan.DEFAULT_MANIFEST).read_text())
        mm = {"version": m["version"], "disks": {"u3gold": m["disks"]["u3gold"]}}
        played = bytearray(gold.d.data[:DATA_LENGTH])
        changed = 0
        for name, _typ, t, s, _b in gold.d.directory():
            if name.strip().lower() in goldunpack.SAVES:
                while t:
                    o = D64.offset(t, s)
                    played[o + 2] ^= 0xFF
                    changed += 1
                    t, s = played[o], played[o + 1]
        self.assertGreaterEqual(changed, 5)
        r = scan.resolve(mm, [scan.Image("played", bytes(played))])["u3gold"]
        self.assertEqual(r["missing"], [])

    def test_u5_base_is_no_game(self):
        """U5's generated roster starts with $00: Journey Onward says "No
        active game!" (docs/developer/u5.md, confirmed in VICE)."""
        from ultima.disks import manifest
        rule = manifest.SEEDS[(manifest.U5A, "ROSTER")]
        data = scan._seed_bytes(rule, 0, {}, {})
        self.assertEqual(data[:2], bytes([0x00, 0x10]))      # loads at $1000
        self.assertEqual(data[2], 0)


if __name__ == "__main__":
    unittest.main()


class TestImages(unittest.TestCase):
    """ultima/disks/images.py: .g64 decoded, zips opened."""
    REF = paths.disk("u6-2a")

    def g64_of(self, d):
        """The disk as VICE's c1541 writes a .g64 of it, block by block."""
        import shutil, subprocess, tempfile
        from ultima.disks.d64 import SECTORS_PER_TRACK
        if not shutil.which("c1541"):
            self.skipTest("no c1541 (VICE)")
        with tempfile.TemporaryDirectory() as tmp:
            g = os.path.join(tmp, "t.g64")
            bam = d.sector(18, 0)
            name = bytes(bam[0x90:0xA0]).rstrip(b"\xa0").decode("latin1").lower() or "x"
            did = bytes(bam[0xA2:0xA4]).decode("latin1").lower()
            subprocess.run(["c1541", "-format", f"{name},{did}", "g64", g], check=True, capture_output=True)
            args = ["c1541", "-attach", g]
            for t in range(1, 36):
                for s in range(SECTORS_PER_TRACK[t]):
                    f = os.path.join(tmp, f"b{t}_{s}")
                    Path(f).write_bytes(d.sector(t, s))
                    args += ["-bwrite", f, str(t), str(s)]
            subprocess.run(args, check=True, capture_output=True)
            return Path(g).read_bytes()

    def test_a_g64_reads_as_its_d64(self):
        if not os.path.exists(self.REF):
            self.skipTest("the reference disk is not here")
        from ultima.disks import images
        d = D64(self.REF)
        g64 = self.g64_of(d)
        (_n, data, errmap), = images._one("t.g64", g64)
        self.assertEqual(data, d.data)
        self.assertEqual(set(errmap), {1})
        # a data byte damaged on track 10: that sector's checksum fails ...
        blob = bytearray(g64)
        at = int.from_bytes(blob[0x0C + 4 * 18:0x10 + 4 * 18], "little")      # half track 18 = track 10
        size = int.from_bytes(blob[at:at + 2], "little")
        track = images._track(bytes(blob[at + 2:at + 2 + size]), 10)
        self.assertEqual(sorted(track), list(range(21)))
        blob[at + 2 + size // 2] ^= 0x01
        (_n, _data, errmap), = images._one("t.g64", bytes(blob))
        codes = errmap[D64.linear(10, 0):D64.linear(10, 20) + 1]
        self.assertTrue(set(codes) - {1} <= {4, 5} and any(c != 1 for c in codes),
                        "a sector of track 10 does not read (its GCR or its checksum)")
        # ... and a track gone: every sector of it "header not found"
        blob = bytearray(g64)
        blob[0x0C + 4 * 18:0x10 + 4 * 18] = bytes(4)
        (_n, _data, errmap), = images._one("t.g64", bytes(blob))
        self.assertEqual(set(errmap[D64.linear(10, 0):D64.linear(10, 20) + 1]), {2})
        self.assertEqual(set(errmap[:D64.linear(10, 0)]), {1})

    def test_zips_and_zips_in_zips(self):
        import io
        import zipfile
        from ultima.disks import images
        d64 = bytes(range(256)) * 683
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as z:
            z.writestr("b.d64", d64)
        outer = io.BytesIO()
        with zipfile.ZipFile(outer, "w") as z:
            z.writestr("a.d64", d64 + bytes([1]) * 683)
            z.writestr("more.zip", inner.getvalue())
            z.writestr("readme.txt", b"not a disk")
        got = images._from_zip("pile.zip", outer.getvalue(), nested=True)
        self.assertEqual([n for n, _d, _e in got], ["pile.zip:a.d64", "pile.zip:more.zip:b.d64"])
        self.assertTrue(all(d == d64 for _n, d, _e in got))
        self.assertEqual(len(got[0][2]), 683, "an error map kept")


class TestImport(unittest.TestCase):
    """ultima/disks/importsave.py: what counts as a saved game, and one imported
    end to end through the page."""

    def test_the_pages_own_tests(self):
        from ultima.disks import importsave
        disk = importsave.SAVE_DISKS["u4"][0]
        blank = bytearray(DATA_LENGTH)
        im = scan.Image("x", bytes(blank))
        self.assertFalse(importsave.holds_a_game("u4", disk, im), "party size 0")
        o = D64.offset(*D64.from_linear(275))
        blank[o + 0x0F] = 2
        self.assertTrue(importsave.holds_a_game("u4", disk, scan.Image("x", bytes(blank))))
        blank[o + 0x0F] = 9
        self.assertFalse(importsave.holds_a_game("u4", disk, scan.Image("x", bytes(blank))), "no party of 9")

    def test_another_name_is_handed_over_as_the_pages(self):
        from ultima.disks import importsave
        img = bytearray(DATA_LENGTH)
        o = D64.offset(18, 0)
        img[o + 0x90:o + 0xA0] = b"ULTIMA III-SCEN." 
        img[o + 0xA2:o + 0xA4] = b"U3"
        desc = {"bam_name": b"PLAYER MASTER".ljust(16, b"\xa0").hex(), "id": b"64".hex(), "check_id": False}
        out = importsave.as_the_page_wants(bytes(img), desc)
        self.assertEqual(out[o + 0x90:o + 0xA0], b"PLAYER MASTER".ljust(16, b"\xa0"))
        self.assertEqual(out[o + 0xA2:o + 0xA4], b"U3", "the ID only where the page checks it")

    def test_a_u4_game_goes_in(self):
        """A played Britannia disk -- the reference's with a party of one
        written into block 275 -- imported by the page into a fresh cart: the
        slot holds that block."""
        ref = paths.disk("u4c")
        cart = os.path.join(paths.BUILD, "ultima-collection.tcrt")
        if not (HAVE_PY65 and os.path.exists(ref) and os.path.exists(cart)):
            self.skipTest("needs py65, the reference disk and a built cart")
        import json
        from ultima.sim import pagesim
        from ultima.flash import regions
        from ultima.flash.tcrt import TCRT
        disk = bytearray(Path(ref).read_bytes()[:DATA_LENGTH])
        o = D64.offset(*D64.from_linear(275))
        disk[o + 0x0F] = 1
        fresh = bytearray(TCRT.read(cart).flash.ljust(regions.FLASH_SIZE, b"\xff"))
        flash, text, done = pagesim.import_from_disks(fresh, "u4", [bytes(disk)])
        self.assertTrue(done, text[-300:])
        slots = json.loads(Path(os.path.join(paths.BUILD, "xfer.json")).read_text())["u4"][0]["slots"]
        rec = [sl for sl in slots if sl.get("sectors") == [list(D64.from_linear(275))]]
        self.assertEqual(len(rec), 1)
        base = rec[0]["base"]               # header 0: the sector, raw, at the slot's base
        self.assertEqual(rec[0]["hdr"], 0)
        self.assertEqual(bytes(flash[base:base + 256]), bytes(disk[o:o + 256]))
