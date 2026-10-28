"""Verify the Ultima 5 cart image: where the driver lives, and that the raw
sector mapping it relies on is right.

The memory checks matter more than they look.  Everything from $7B57 to
$7FFF is the game's scratch area -- main.twn stamps empty-slot markers into
$7D00-$7D70 -- and an earlier build put half the driver there; the game
overwrote one of its instructions and every raw sector read quietly did
nothing.  So these pin down that no segment reaches that area, that the
resident part stays in $7700-$7AFF, and that the only bytes of temp.subs
that differ from the original are the ones the build means to change.
"""
import os
import unittest

from ultima.disks.d64 import D64
from ultima.flash.layout import image_from
from ultima.flash import regions
from ultima.flash import zx

import importlib.util as _il
from ultima.pin import Pin


def _load_game(name):
    spec = _il.find_spec(f"ultima.games.{name}.build")
    mod = _il.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


u5 = _load_game("u5")

GAME_SCRATCH = (0x7B57, 0x7FFF)     # the game's, not the fastloader's
UNDER_IO = (0xD000, 0xDFFF)         # overwritten during the intro


class TestU5Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.pop("U5_SAVE_FROM", None)     # the shipped layout only
        cls.parts = u5.parts()
        cls.flash = image_from(cls.parts["blobs"], regions.FLASH_SIZE)
        desc = cls.parts["desc"]
        cls.segments = []
        for i in range(desc[2]):
            o = 3 + 7 * i
            cls.segments.append((desc[o] << 8 | desc[o + 1] << 16,
                                 desc[o + 2] | desc[o + 3] << 8,
                                 desc[o + 4] | desc[o + 5] << 8))
        cls.sym = u5.symbols(os.path.join(u5.BUILD, "u5drv.sym"))
        seg = {dest: (off, n) for off, n, dest in cls.segments}
        off, n = seg[u5.SUBS_ADDR]
        cls.subs = cls.flash[off:off + n]
        off, n = seg[u5.FAST_ADDR]
        cls.fast = cls.flash[off:off + n]
        cls.disks = {n: D64(u5.disk_path(t)) for n, t in u5.TAGS.items()}

    def test_no_segment_reaches_the_game_scratch_area(self):
        for off, n, dest in self.segments:
            end = dest + n - 1
            for lo, hi in (GAME_SCRATCH, UNDER_IO):
                self.assertTrue(end < lo or dest > hi,
                                f"segment ${dest:04x}-${end:04x} overlaps ${lo:04x}-${hi:04x}")

    def test_u5siz_o_keeps_its_original_length(self):
        # a reload of the file must never reach $7B57 either
        original, _ = self.disks[1].file("U5SIZ.O")
        self.assertEqual(len(self.fast), len(original) - 2)
        self.assertLessEqual(self.sym["u5_drv_end"], u5.FAST_LIMIT)

    def test_disk_vectors_point_into_the_resident_window(self):
        for vector, (routine, _orig) in u5.VECTORS.items():
            o = vector - u5.SUBS_ADDR
            self.assertEqual(self.subs[o], 0x4C, f"{vector:#06x} is not a JMP")
            target = self.subs[o + 1] | self.subs[o + 2] << 8
            self.assertEqual(target, self.sym[routine])
            self.assertTrue(u5.FAST_ADDR <= target < u5.FAST_LIMIT,
                            f"{vector:#06x} -> {target:#06x} is not resident")

    def test_temp_subs_changes_only_where_intended(self):
        original, _ = self.disks[1].file("TEMP.SUBS")
        original = original[2:]
        allowed = set()
        for vector in u5.VECTORS:
            allowed.update(range(vector + 1, vector + 3))
        for addr, _orig in u5.RECORD_CALLS:
            allowed.update((addr, addr + 1))
        for start, limit, _end in u5.HOLES:
            allowed.update(range(start, limit))
        for fname, addr, _why, _hits in self.parts["applied"]:
            if fname.lower() == "temp.subs":
                allowed.add(addr)
        for fname, addr in u5.MUSIC_GATES:              # lda/bpl -> bit/bvc
            if fname == "temp.subs":
                allowed.update((addr, addr + 2))
        c64 = set(range(u5.AR_PLAY_JMP + 1, u5.AR_PLAY_JMP + 3)) | \
            set(range(u5.AR_RESTART[0], u5.AR_RESTART[0] + 7))    # the AR's play, restart
        for what, body, more in (("C64", self.subs, c64), ("C128", self.parts["c128"]["subs"], set())):
            changed = [u5.SUBS_ADDR + i for i, (a, b) in
                       enumerate(zip(original, body)) if a != b]
            stray = [hex(a) for a in changed if a not in allowed | more]
            self.assertEqual(stray, [], f"{what}: temp.subs changed outside the vectors and holes")
            self.assertEqual(len(body), len(original), what)

    def test_the_c128_build(self):
        """The C128 driver (u5drv.s with U5_C128): subs.128's eight entries at
        $7700 are each JSR C_FAR, the rest is in the same window and holes as
        the C64's; u5siz.o's sound routine is kept; and the C64 build is the
        one the menu loads, untouched by any of it."""
        c = self.parts["c128"]
        self.assertEqual(c["fast"][:24], bytes([0x20, 0x00, 0x02]) * 8)
        self.assertLessEqual(c["sym"]["u5_drv_end"], u5.FAST_LIMIT)
        fast_orig = self.disks[1].file("U5SIZ.O")[0][2:]
        self.assertEqual(c["fast"][0x7B00 - u5.FAST_ADDR:], fast_orig[0x7B00 - u5.FAST_ADDR:],
                         "the sound-effect routine")
        # the C64 build has no entries of its own: tc_init and the directory
        # setup are its init stub's (TC_INIT_ELSEWHERE), their room the journal's
        self.assertNotIn("tc_init", self.sym)
        self.assertNotIn("u5_dirinit", self.sym)
        self.assertIn("jr_begin", self.sym)
        self.assertNotIn("jr_begin", c["sym"], "the C128 build has no journal")
        # the patches to the files both machines load are on C128 paths only:
        # xyzzy's after its `lda $C8 / bpl` at $20D5 and inside the $C024
        # test's branch, qs's after its own at $8073
        body = [b for k, b in self.parts["bodies"].items() if k[0] == 1 and k[1].lower() == "xyzzy"][0]
        self.assertEqual(body[0x20D5 - 0x2000:0x20D9 - 0x2000], bytes.fromhex("a5c81024"))
        at = body.find(bytes.fromhex("a94ccd24c0d0")) + 0x2000     # the $C024 test
        target = at + 7 + body[at + 6 - 0x2000]
        self.assertTrue(at + 7 <= 0x2055 < target, "the DDR patch is on the C128 branch")
        qs = [b for k, b in self.parts["bodies"].items() if k[0] == 1 and k[1].lower() == "qs"][0]
        self.assertEqual(qs[0x8073 - 0x8000:0x8077 - 0x8000], bytes.fromhex("a5c8102a"))
        # and the page the launcher reads
        d = c["desc"]
        self.assertEqual(d[:7], b"U5C128\x01")
        self.assertEqual(d[15:17], b"\x00\x20", "xyzzy")
        segs = [d[17 + 8 * i:25 + 8 * i] for i in range(8)]
        self.assertEqual(d[17 + 8 * 8], 0)
        self.assertEqual([(s[0] & 0x82, s[6] | s[7] << 8) for s in segs],
                         [(0x82, 0x7200), (0x82, 0xE000), (0x80, 0x0200),
                          (0x80, 0x0113), (0x80, 0x0297),       # c128fast.s's two pieces
                          (0x80, 0x2000), (0x80, u5.SUBS_ADDR), (0x80, u5.FAST_ADDR)])

    def test_raw_sectors_map_to_the_right_blocks(self):
        """Every block of every run, looked up through the tables in
        temp.subs and the block map in flash -- the driver's own path -- and
        decoded, is the block on the original disk."""
        def table(name):
            o = self.sym[name] - u5.SUBS_ADDR
            return list(self.subs[o:o + 8])
        lo, hi = table("u5_rfirst_lo"), table("u5_rfirst_hi")
        rmap = [a | b << 8 | c << 16 for a, b, c in
                zip(table("u5_rmap_lo"), table("u5_rmap_mid"), table("u5_rmap_hi"))]
        runs = u5.sector_runs(self.disks)
        checked = 0
        for n in sorted(self.disks):
            i = n - 1
            first = lo[i] | hi[i] << 8
            if runs[n] is None:
                if n == 1:              # the Ultima IV disk's entry, see below
                    self.assertEqual(first, u5.U4_PARTY_BLOCK)
                else:
                    self.assertEqual(first, 0xFFFF, f"disk {n} has no run")
                continue
            self.assertEqual((first, u5.TOTAL_BLOCKS - first), runs[n])
            for blk in range(first, u5.TOTAL_BLOCKS):
                e = self.flash[rmap[i] + 4 * (blk - first):rmap[i] + 4 * (blk - first) + 4]
                addr, length = e[0] | e[1] << 8 | e[2] << 16, e[3]
                got = (self.flash[addr:addr + 256] if length == 0
                       else zx.decode(self.flash[addr:addr + length]))
                want = bytes(self.disks[n].sector(*D64.from_linear(blk)))
                self.assertEqual(got, want, f"disk {n} block {blk}")
                checked += 1
        self.assertEqual(checked, sum(c for _f, c in (r for r in runs.values() if r)))

    def test_every_file_decodes_to_the_original(self):
        """Every directory entry, read the way u5_fetch reads it, is the file
        on the disk it is keyed to (as build.py patched it)."""
        d = self.parts["dir_off"]
        n = self.parts["entries"]
        size = u5.DIR_NAMELEN + u5.DIR_DATALEN
        zx_units = 0
        for k in range(n):
            e = self.flash[d + k * size:d + (k + 1) * size]
            disk, name = e[0], bytes(e[1:u5.DIR_NAMELEN]).rstrip(b"\x00").decode()
            data = e[u5.DIR_NAMELEN:]
            addr = data[0] | data[1] << 8 | data[2] << 16
            length = data[3] | data[4] << 8
            flags = data[7]
            if flags & u5.F_WRITE:
                continue                    # a save slot, checked elsewhere
            stored = self.flash[addr:addr + length]
            body = zx.decode(stored) if flags & u5.F_ZX else stored
            zx_units += bool(flags & u5.F_ZX)
            target = self.parts["targets"][(disk, name)]
            self.assertEqual(body, self.parts["bodies"][(disk, target)],
                             f"disk {disk} {name}")
        self.assertGreater(zx_units, 200)

    def test_the_roster_slot_ends_below_the_row_table(self):
        """ROSTER loads at $1000; the shipped file's 1025th byte would land on
        $1400, startup's bitmap row table, which Journey Onward with no game
        and then creation never rebuild.  The base holds the 1024 bytes the
        game writes."""
        base = self.parts["page"]["U5_ROSTER"]
        self.assertEqual(bytes(self.flash[base:base + 2]), u5.SAVE_MAGIC)
        length = self.flash[base + 2] | self.flash[base + 3] << 8
        self.assertEqual(length, u5.ROSTER_LEN)
        self.assertLessEqual(0x1000 + length, 0x1400)
        self.assertEqual(bytes(self.flash[base + 0x100:base + 0x100 + length]),
                         bytes(self.parts["bodies"][(2, "ROSTER")][:length]))

    def test_the_menu_has_no_number_of_drives(self):
        """Disk 1A's `startup`, as stored, differs from the original only in
        the menu patches: the drives line skipped, the cursor stopped at five
        entries.  The letters A-O still pick a song (`$6C40`)."""
        orig, _ok = D64(u5.disk_path("1A")).file("STARTUP")
        load, orig = orig[0] | orig[1] << 8, orig[2:]
        got = self.parts["bodies"][(1, "STARTUP")]
        self.assertEqual(len(got), len(orig))
        allowed = set()
        for addr, want, new, _why in u5.MENU_PATCHES:
            o = addr - load
            self.assertEqual(bytes(got[o:o + len(new)]), new)
            allowed |= set(range(addr, addr + len(new)))
        for fname, addr in u5.MUSIC_GATES:              # lda/bpl -> bit/bvc
            if fname == "startup":
                self.assertEqual(bytes(got[addr - load:addr - load + 3:2]), bytes([0x24, 0x50]))
                allowed |= {addr, addr + 2}
        diff = {load + i for i, (a, b) in enumerate(zip(orig, got)) if a != b}
        self.assertTrue(diff)
        self.assertLessEqual(diff, allowed)
        # cmp #$C1 / bcc / cmp #$D0 / bcc $85A2 / jmp $854D /
        # and #$0F / tax / jsr $6C40: A-O play songs 1-15
        o = 0x8597 - load
        self.assertEqual(bytes(got[o:o + 17]),
                         Pin("#17:86128c26de6ba0da"))

    def test_the_ultima_iv_transfer_reads_u4s_save_slots(self):
        """`transfer` reads the U4 disk's track 14 sectors 0-1 (U4 blocks
        273-274, its party) through $6C00, after a disk check that makes it
        disk 1's table entry: that entry's run starts at 273, and its map
        sends both blocks, raw, to Ultima IV's own save slots on the cart."""
        u4 = _load_game("u4")
        self.assertEqual((u5.U4_SAVE_FIRST, u5.U4_SAVE_COUNT), (u4.SAVE_FIRST, u4.SAVE_COUNT))
        self.assertEqual(u4.SAVE_SLOT, regions.ERASE_BLOCK)
        self.assertEqual(u4.SAVE_DISK, 2, "U4's save disk is Britannia, disk C")
        self.assertEqual(D64.linear(14, 0), u5.U4_PARTY_BLOCK)
        self.assertEqual(self.parts["rfirst"][0], u5.U4_PARTY_BLOCK)
        base = self.parts["rmap_addr"][0]
        for i, block in enumerate((273, 274)):
            e = self.flash[base + 4 * i:base + 4 * i + 4]
            addr = e[0] | e[1] << 8 | e[2] << 16
            self.assertEqual(e[3], 0, "not a raw page")
            self.assertEqual(addr, regions.save_base("u4") + (block - u4.SAVE_FIRST) * u4.SAVE_SLOT)
        self.assertEqual(len(self.parts["u4_map"]), D64.linear(35, 16) + 1 - u5.U4_PARTY_BLOCK,
                         "the run must reach the last block")

    def test_the_transfer_prompt_no_longer_asks_for_a_disk(self):
        orig, _ok = D64(u5.disk_path("1A")).file("TRANSFER")
        load, orig = orig[0] | orig[1] << 8, orig[2:]
        got = self.parts["bodies"][(1, "TRANSFER")]
        self.assertEqual(len(got), len(orig))
        allowed = set()
        for addr, _was, now in u5.TRANSFER_TEXT:
            self.assertEqual(bytes(got[addr - load:addr - load + len(now)]), u5._hi(now))
            allowed |= set(range(addr, addr + len(now)))
        diff = {load + i for i, (a, b) in enumerate(zip(orig, got)) if a != b}
        self.assertTrue(diff)
        self.assertLessEqual(diff, allowed)

    def test_linear_block_arithmetic_matches_d64(self):
        # u5_block sums sectors per track rather than using a table; mirror it
        def linear(track, sector):
            blk = sector
            for t in range(1, track):
                blk += 21 if t < 18 else 19 if t < 25 else 18 if t < 31 else 17
            return blk
        for t in range(1, 36):
            self.assertEqual(linear(t, 0), D64.linear(t, 0), f"track {t}")


if __name__ == "__main__":
    unittest.main()
