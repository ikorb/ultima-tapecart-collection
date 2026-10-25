"""Ultima IV Remastered's fixes in the cart as stored (ultima/games/u4/remastered.py),
each checked against evidence of its own rather than the build's tables:
an independent build of the dungeon view, the conversations'
and maps' meaning, the dungeon rooms' floor, and the patched code run in
py65.  Every block is read the way the driver reads it: through the block
map in flash, decoded."""
import hashlib
import os
import unittest
from pathlib import Path

try:
    from ultima.sim.sim6502 import Sim
except ImportError:
    Sim = None

from tests import test_u4_build as tb


u4 = tb.u4
rm = u4.remastered
A, C, B, D = 1, 2, 3, 4
# the kit's dungeon.s with its colour tables on $E1B0 and the torch's
# white back (light_color: $10 from 32 on), built on its own: its length
# and SHA-256 (first 16 digits)
DUNGEON_ALONE = (3931, "668c70060f06f226")
FLOOR = 0x16


class TestRemastered(unittest.TestCase):
    setUpClass = classmethod(tb.TestU4Build.setUpClass.__func__)
    mapped = tb.TestU4Build.mapped
    map_entry = tb.TestU4Build.map_entry

    def disk(self, n):
        if not hasattr(self, "_disks"):
            type(self)._disks = {}
        if n not in self._disks:
            self._disks[n] = self.mapped(n)
        return self._disks[n]

    def chunk(self, n, index):
        """Chunk `index` as stored on disk n, and where it loads."""
        start, count, dest = u4.chunk_entry(u4.kernel_image(self.disks[1]), index)
        return self.disk(n)[start * 256:(start + count) * 256], dest

    def original_chunk(self, n, index):
        start, count, dest = u4.chunk_entry(u4.kernel_image(self.disks[1]), index)
        return self.disks[n].data[start * 256:(start + count) * 256], dest

    # -- the dungeon view ------------------------------------------------

    def test_the_dungeon_view_is_the_kits_standing_alone(self):
        """Chunk $95 on disk D: an independent build of the kit's dungeon.s
        with the colour tables on $E1B0 (DUNGEON_ALONE), the rest of the
        chunk as it was."""
        n, want = DUNGEON_ALONE
        got, dest = self.chunk(D, 0x95)
        orig, _ = self.original_chunk(D, 0x95)
        self.assertEqual(dest, 0x8C00)
        self.assertEqual(hashlib.sha256(got[:n]).hexdigest()[:16], want)
        self.assertEqual(got[n:], orig[n:])

    # -- conversations and maps ------------------------------------------

    def page(self, i):
        o = (rm.TALK_FIRST + i) * 256
        return rm.talk_decode(self.disk(B)[o:o + 256])

    def test_the_lost_conversations_are_reachable(self):
        """A map's NPC table ends in a conversation number per NPC
        (+$4E0); the page is town x 16 + conversation - 1.  Serpent's Hold
        (town 3): NPCs 28 and 29, the gate guards, used Sentri's; Britain
        (town 5): NPC 13 was a second Joe, and Thevel's page was nobody's."""
        for chunk, town, npcs, conv, name in ((0x5F, 3, (28, 29), 2, "GUARD"),
                                              (0x61, 5, (13,), 6, "THEVEL")):
            with self.subTest(town=town):
                data, _ = self.chunk(B, chunk)
                for n in npcs:
                    self.assertEqual(data[0x4E0 + n], conv)
                self.assertIn(name, self.page(town * 16 + conv - 1)["name"].upper())

    def test_the_conversation_fixes(self):
        """Questions that were never asked (trigger 0, or after the wrong
        keyword, or an index that does not exist), and keywords nobody
        could type -- the analysis's table.  Triggers: 5 = after keyword
        1, 6 = after keyword 2."""
        self.assertEqual(self.page(0x55)["trigger"], 5)          # Thevel: after ORBS
        for i in (0x09, 0x86, 0xA0, 0xFE):                       # Water, Alkerion, Shamino, Charm
            self.assertEqual(self.page(i)["trigger"], 6, hex(i))
        self.assertEqual(self.page(0x3F)["keyword_2"], "VISIT")  # Michelle, not HEAL(ER)
        self.assertEqual(self.page(0x17)["keyword_1"][:4], "RESE")   # Estro: RESEARCH
        self.assertEqual(self.page(0x78)["keyword_1"][:4], "SINN")   # the beggar: SINNED
        # and every keyword still upper case: the talk code compares them
        # with the typed letters, which arrive as capitals
        for i in range(256):
            p = self.page(i)
            for k in ("keyword_1", "keyword_2"):
                self.assertEqual(p[k], p[k].upper(), (hex(i), k))

    def test_the_content_fixes_touch_20_pages(self):
        """In the original's upper case: 20 pages, and the two the analysis
        found too long left alone (Zorin, Dupre)."""
        imgs = {n: bytearray(d.data) for n, d in self.disks.items()}
        pages, skipped = rm.talk_fixes(imgs)
        self.assertEqual(len(pages), 20)
        self.assertEqual(skipped, [0x07, 0x90])

    # -- mixed case ------------------------------------------------------

    def only_case_differs(self, n, chunk):
        """The flips of case in a chunk; anything else differs only where
        one of fork_fixes' code patches is, which is then exactly that."""
        got, dest = self.chunk(n, chunk)
        orig, _ = self.original_chunk(n, chunk)
        self.assertEqual(len(got), len(orig))
        _code, fx = rm.helpers()
        fixed = set()
        for what, c, addr, _want, new, disks in rm.fork_fixes(fx, rm.helpers("u4ff")[1]):
            if c == chunk and n in disks:
                o = addr - dest
                self.assertEqual(bytes(got[o:o + len(new)]), new, what)
                fixed.update(range(o, o + len(new)))
        flips = 0
        for i, (a, b) in enumerate(zip(orig, got)):
            if a != b and i not in fixed:
                self.assertEqual(a ^ b, 0x20, f"chunk ${chunk:02X}: not a case change")
                self.assertTrue(0xC1 <= a <= 0xDA, f"chunk ${chunk:02X}: not a capital")
                flips += 1
        return flips

    @unittest.skipUnless(rm.MIXED_CASE, "mixed case is off")
    def test_the_talk_code_the_shops_and_lord_british_only_change_case(self):
        for n, chunk in [(B, 0x78), (C, 0x87), (C, 0x88)] + [(B, c) for c in range(0x6D, 0x77)]:
            with self.subTest(chunk=hex(chunk)):
                self.assertGreater(self.only_case_differs(n, chunk), 20)

    @unittest.skipUnless(rm.MIXED_CASE, "mixed case is off")
    def test_lord_british_resurrects_in_mixed_case(self):
        """Chunk $89 (the resurrection, $8800), which the kit has no unit for:
        Lord British's words in mixed case, the narration still in capitals,
        and nothing else changed."""
        data, dest = self.chunk(C, 0x89)
        self.assertEqual(dest, 0x8800)
        self.assertEqual(bytes(data).count(rm.t("Lord British\rsays: I have\rpulled thy\r")), 1)
        self.assertEqual(bytes(data).count(rm.t("ALL IS DARK...")), 1)
        (old, new), = rm.MANUAL_CASE[0x89]
        self.assertEqual(self.only_case_differs(C, 0x89), sum(a != b for a, b in zip(old, new)))

    @unittest.skipUnless(rm.MIXED_CASE, "mixed case is off")
    def test_the_keyword_tables_stay_in_capitals(self):
        """Typed input arrives in capitals, and the talk code and Lord
        British compare it with these."""
        for n, chunk, words in ((B, 0x78, b"BYE NAMELOOKJOB HEAL"),
                                (C, 0x87, b"BYE NAMELOOKJOB HEALTRUTLOVECOUR")):
            data, _ = self.chunk(n, chunk)
            self.assertEqual(bytes(data).count(rm.t(words.decode())), 1, hex(chunk))

    @unittest.skipUnless(rm.MIXED_CASE, "mixed case is off")
    def test_every_conversation_is_the_kits_in_the_original_format(self):
        """Keywords and triggers as the content fixes have them (in
        capitals), the strings the kit's -- or, where a page would not fit,
        the original's words in the kit's case."""
        import json
        talk = json.loads(Path(os.path.join(rm.KIT, "src", "talk", "talk.json")).read_text())
        imgs = {n: bytearray(d.data) for n, d in self.disks.items()}
        upper, _skipped = rm.talk_fixes(imgs)
        mixed = 0
        for i in range(256):
            with self.subTest(page=hex(i)):
                p = self.page(i)
                o = rm.talk_decode(self.disks[B].data[(i + 1) * 256:(i + 2) * 256])
                ref = rm.talk_decode(upper[i][0]) if i in upper else o
                for k in ("keyword_1", "keyword_2", "trigger"):
                    self.assertEqual(p[k], ref[k], k)
                for k in rm.KEYS:
                    self.assertIn(rm.alnum(p[k]), (rm.alnum(talk[i][k]), rm.alnum(ref[k])), k)
                mixed += any(c.islower() for k in rm.KEYS for c in p[k])
        self.assertEqual(mixed, 256)

    # -- the dungeon rooms ----------------------------------------------

    def test_the_rooms_start_positions_are_on_the_floor(self):
        """A room page: start x at $40/$50/$60/$70 and y at +8 per entry
        direction (N E S W), the 11 x 11 map at $80.  The rooms the kit
        fixes had (0,0), a wall corner, or nothing at all."""
        for room, edits in rm.ROOMS.items():
            page = self.disk(D)[(room + 1) * 256:(room + 2) * 256]
            for xoff in sorted({o for o, _ in edits if o >= 0x40 and (o & 0x0F) == 0}):
                with self.subTest(room=hex(room), entry=hex(xoff)):
                    for k in range(8):
                        x, y = page[xoff + k], page[xoff + 8 + k]
                        self.assertEqual(page[0x80 + y * 11 + x], FLOOR, (x, y))

    def test_hythloths_room_9_opens_its_west_wall(self):
        """The trigger the kit adds (tile, then positions x << 4 | y):
        stepping on (9,8), the chest in the south-east corner, turns (0,5)
        and (0,4) into floor -- cells of the west wall ($7F), next to the new
        west start positions, the only way out that side."""
        page = self.disk(D)[0x6A * 256:0x6B * 256]
        self.assertEqual(bytes(page[0:4]), bytes([FLOOR, 0x98, 0x05, 0x04]))
        at = lambda x, y: page[0x80 + y * 11 + x]
        self.assertEqual(at(9, 8), 0x3C)            # a chest: the party can step on it
        self.assertEqual((at(0, 5), at(0, 4)), (0x7F, 0x7F))
        self.assertEqual((at(1, 5), at(1, 4)), (FLOOR, FLOOR))

    # -- code, run -------------------------------------------------------

    def sim(self, n, index):
        data, dest = self.chunk(n, index)
        return Sim(bytes(data), dest, {})

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_the_shrine_counts_its_cycles(self):
        """$8907, as stored: 0 cycles is no meditation at all ($8A76) -- it
        started one of 256; 1-3 are counted; 4 or more is asked again."""
        for n, want in ((0, 0x8A76), (1, 0x8919), (2, 0x8919), (3, 0x8919), (4, 0x88E8),
                        (9, 0x88E8)):
            with self.subTest(cycles=n):
                s = self.sim(C, 0x82)
                hit = []

                def get_number(sim, n=n):       # ends in PLA: Z follows A
                    sim.mpu.a = n
                    sim.mpu.p = (sim.mpu.p & ~0x82) | (0x02 if n == 0 else 0)
                for a in (0x8A76, 0x8919, 0x88E8):
                    s.traps[a] = lambda sim, a=a: hit.append(a)
                s.traps[0x8BD9] = get_number
                s.call(0x8907)
                self.assertEqual(hit, [want])
                if want == 0x8919:
                    self.assertEqual((s.mem[0x8BF3], s.mem[0x8BF4]), (n, n))

    def test_the_shrine_gives_a_hint_per_cycle(self):
        data, dest = self.chunk(C, 0x82)
        o = 0x8BFE - dest                           # shrine_msg_per_cycle
        self.assertEqual(bytes(data[o:o + 4]), bytes([0x18, 0, 1, 2]))

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_board_is_a_ship_only_in_britannia(self):
        """B on tiles $10-$13: a ship in Britannia ($1A = 0) goes on to
        $480B and back; anywhere else (a dungeon's ladder) "WHAT?" at the
        command's own stack depth."""
        for loc, want in ((0, 0x47B3), (1, 0x4112), (3, 0x4112)):
            with self.subTest(location=loc):
                s = self.sim(A, 0x5B)
                s.mem[0x1A] = loc
                hit = []
                s.traps[0x480B] = lambda sim: None
                for a in (0x47B3, 0x4112):
                    s.traps[a] = lambda sim, a=a: hit.append((a, sim.mpu.sp))
                s.call(0x47B0)             # (Sim.call: the routine starts at SP = $FD)
                self.assertEqual([a for a, _ in hit], [want])
                self.assertEqual(hit[0][1], 0xFD, "the stack as the command left it")

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_enter_is_refused_while_flying(self):
        for loc, flying, want in ((0, 0, 0x4FE1), (0, 1, 0x4112), (2, 0, 0x4112)):
            with self.subTest(location=loc, flying=flying):
                s = self.sim(A, 0x5B)
                s.mem[0x1A], s.mem[0x74] = loc, flying
                hit = []
                for a in (0x4FE1, 0x4112):
                    s.traps[a] = lambda sim, a=a: hit.append(a)
                s.call(0x4FDA)
                self.assertEqual(hit, [want])

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_a_game_loads_flying_as_it_was_saved(self):
        """$405C after the saved state is in: $74 (flying) = the saved $1D,
        and A = 0 for the stores that follow, as before."""
        for saved in (0, 1):
            with self.subTest(flying=saved):
                s = self.sim(A, 0x5B)
                ff, _f = rm.helpers("u4ff")             # $405C calls u4ff.s's dg_load
                s.mem[0xFF00:0xFF00 + len(ff)] = list(ff)
                s.mem[0x1B] = 1                         # on the surface
                s.mem[0x1D], s.mem[0x74], s.mem[0x1A] = saved, 0x55, 0x55
                s.traps[0x4064] = lambda sim: None
                s.call(0x405C)
                self.assertEqual((s.mem[0x1D], s.mem[0x74], s.mem[0x1A]), (saved, saved, 0))

    @staticmethod
    def stop(hit):
        """A trap that notes SP and ends Sim.call there, whatever the stack."""
        from ultima.sim.sim6502 import DONE

        def trap(sim):
            hit.append(sim.mpu.sp)
            sp = sim.mpu.sp
            sim.mem[0x100 + ((sp + 1) & 0xFF)] = (DONE - 1) & 0xFF
            sim.mem[0x100 + ((sp + 2) & 0xFF)] = (DONE - 1) >> 8
        return trap

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_the_stack_leaks_are_closed(self):
        """Each JMP that used to leave a return address on the stack now
        goes through PLA / PLA to the same place: attacked, the bridge
        trolls, a moongate into a shrine."""
        for site, target in ((0x670C, 0x4731), (0x62E7, 0x6EA3), (0x8698, 0x5183)):
            with self.subTest(at=hex(site)):
                s = self.sim(A, 0x5B)
                hit = []
                s.traps[target] = lambda sim: hit.append(sim.mpu.sp)
                # the leaked return address, then the JMP
                stub = [0x20, 0x06, 0x04, 0x60, 0, 0, 0x4C, site & 0xFF, site >> 8]
                s.mem[0x0400:0x0400 + len(stub)] = stub
                s.call(0x0400)             # (Sim.call: the routine starts at SP = $FD)
                self.assertEqual(len(hit), 1)
                self.assertEqual(hit[0], 0xFD, "the extra return address is gone")

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_the_party_dead_and_a_moongate_reset_the_stack(self):
        """The party dead ($83E0, from one to four calls deep: a sinking
        ship) and a moongate jump ($86CA) reach cmd_done ($621E) with the
        command level's stack, $BE (u4fix.s CMD_SP, measured in VICE: see
        tools/vice/u4_stack_check.py), however deep they were."""
        _code, fx = rm.helpers()
        self.assertEqual(fx["CMD_SP"], 0xBE)
        for site in (0x83E0, 0x86CA):
            for depth in (1, 2, 4):
                with self.subTest(at=hex(site), calls=depth):
                    s = self.sim(A, 0x5B)
                    hit = []
                    s.traps[0x621E] = self.stop(hit)
                    # `depth` JSRs, each to the next, the last one JMPs
                    stub = []
                    for i in range(depth):
                        nxt = 0x0400 + 3 * (i + 1)
                        stub += [0x20, nxt & 0xFF, nxt >> 8]
                    stub += [0x4C, site & 0xFF, site >> 8]
                    s.mem[0x0400:0x0400 + len(stub)] = stub
                    s.call(0x0400)
                    self.assertEqual(hit, [0xBE])

    def test_the_forks_jsr_and_pla_slips(self):
        """Ztats in combat ($7CEA) and Z-down on the lowest level ($4DFC)
        go on by JMP, as their targets end in JMPs; "ALL MUST USE THE SAME
        EXIT!" ($7918) pops nothing (combat's move is entered by JMP)."""
        data, dest = self.chunk(A, 0x5B)
        at = lambda a, n: bytes(data[a - dest:a - dest + n])
        self.assertEqual(at(0x7CEA, 3), bytes.fromhex("4c c8 5c"))
        self.assertEqual(at(0x4DFC, 3), bytes.fromhex("4c b9 4e"))
        self.assertEqual(at(0x7918, 5), bytes.fromhex("ea ea 20 21 08"))
        self.assertEqual(at(0x793F, 3), bytes.fromhex("4c 33 71"), "and leaves by JMP $7133")

    # -- Sean Gugler's continuation of the kit (remastered.fork_fixes) ------

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_a_non_monsters_strength_index(self):
        """$7D9B (A = the foe's tile, N set by it): a non-monster's index
        into the strength table is (tile & $1F) / 2 + $24 -- two animation
        frames a foe, as the monsters' branch halves -- and the monsters'
        is the original's."""
        for tile in range(256):
            with self.subTest(tile=hex(tile)):
                s = self.sim(A, 0x5B)
                s.mpu.a = tile
                s.mpu.p = (s.mpu.p & ~0x82) | (0x80 if tile & 0x80 else 0)
                s.call(0x7D9B)
                if tile < 0x80:
                    want = (tile & 0x1F) // 2 + 0x24
                else:
                    want = (tile & 0x7F) >> 1
                    if want >= 8:
                        want = (want >> 1) + 4
                self.assertEqual(s.mpu.a, want)

    def test_ztats_shows_the_key_after_bell_or_book(self):
        """$60AF, no candle: the branch lands on the 3-part key's display
        ($60BA LDA $AB0F), past "CANDL", not inside the key's letters."""
        data, dest = self.chunk(A, 0x5B)
        at = lambda a, n: bytes(data[a - dest:a - dest + n])
        self.assertEqual(at(0x60AF, 2), bytes.fromhex("f0 09"))
        self.assertEqual(at(0x60B1 + 9, 3), bytes.fromhex("ad 0f ab"))
        self.assertEqual(at(0x60B4, 6), rm.t("CANDL") + b"\0")

    def test_the_inn_wakes_a_sleeper_good(self):
        """Chunk $73 (B): status 'S' becomes 'G' in the morning, not 'A'."""
        data, dest = self.chunk(B, 0x73)
        o = 0x8A6E - dest
        self.assertEqual(bytes(data[o:o + 8]), bytes.fromhex("c9 d3 d0 04 a9 c7 91 7e"))

    def test_the_last_gold_piece_is_sacrifice(self):
        """Chunk $78 (B), the gift that empties the purse: virtue 4,
        Sacrifice, as the shrine of Sacrifice's first hint has it."""
        data, dest = self.chunk(B, 0x78)
        o = 0x8CCA - dest
        self.assertEqual(bytes(data[o:o + 15]),
                         bytes.fromhex("ad 14 ab 0d 13 ab d0 07 a9 03 a0 04 20 d2 8d"))

    def test_the_healers_flash_inverts_the_view(self):
        """Chunk $72 (B): the line's address from $E008 and $E0C8 (low,
        high), the view's $B0 bytes a row."""
        data, dest = self.chunk(B, 0x72)
        o = 0x8E75 - dest
        self.assertEqual(bytes(data[o:o + 0x1A]), bytes.fromhex(
            "ad 08 e0 18 69 08 85 7e ad c8 e0 69 00 85 7f a0 00 b1 7e 49 ff 91 7e c8 c0 b0"))

    def test_hawkwind_and_the_shrine_share_a_cooldown(self):
        """The seer (chunk $76, B) compares last_meditated ($29) with the
        counter byte the shrine (chunk $82, C) does, $2E."""
        seer, _ = self.chunk(B, 0x76)
        shrine, _ = self.chunk(C, 0x82)
        self.assertEqual(bytes(seer).count(bytes.fromhex("a5 2e c5 29")), 1)
        self.assertEqual(bytes(seer).count(bytes.fromhex("a5 2f c5 29")), 0)
        self.assertEqual(bytes(shrine).count(bytes.fromhex("a5 2e c5 29")), 1)

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_only_reagents_set_the_search_cooldown(self):
        """Chunk $79 (C): "YOU FIND..." ($8841) no longer sets $2A; mandrake
        ($8869) and nightshade ($88AB), at new moons, find nothing ($880A)
        within the cooldown, else set it and find."""
        s = self.sim(C, 0x79)
        s.mem[0x2A], s.mem[0x2F] = 0x11, 0x35
        s.call(0x8851)
        self.assertEqual(s.mem[0x2A], 0x11, "a find leaves the cooldown")
        for entry in (0x8869, 0x88AB):
            for last, want in ((0x30, 0x880A), (0x20, 0x8841)):
                with self.subTest(at=hex(entry), last=hex(last)):
                    s = self.sim(C, 0x79)
                    hit = []

                    def note(a):
                        stop = self.stop([])

                        def trap(sim):
                            hit.append(a)
                            stop(sim)
                        return trap
                    for a in (0x880A, 0x8841):
                        s.traps[a] = note(a)
                    s.mem[0x22], s.mem[0x23] = 0, 0             # new moons
                    s.mem[0x2A], s.mem[0x2F] = last, 0x35
                    s.call(entry)
                    self.assertEqual(hit, [want])
                    self.assertEqual(s.mem[0x2A], 0x30)

    def test_meditating_drops_the_keys_typed(self):
        """Chunk $82 (C), after the meditation's dots: the kernel's clear
        keyboard ($A112) where the Apple II's strobe was read."""
        data, dest = self.chunk(C, 0x82)
        o = 0x895A - dest
        self.assertEqual(bytes(data[o:o + 7]), bytes.fromhex("20 12 a1 a9 00 85 38"))

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_the_skull_destroyed_raises_every_virtue(self):
        """Chunk $7A (C) $8AD6: virtues 7 down to 0, +$10 each through
        $8C04 (Y the virtue; it was $6A eight times); and the shake's two
        sounds are JSRs, on C and on B's stale copy alike."""
        s = self.sim(C, 0x7A)
        got = []
        s.traps[0x8C04] = lambda sim: got.append((sim.mpu.y, sim.mpu.a))
        s.traps[0x8B86] = self.stop([])
        s.call(0x8AD6)
        self.assertEqual(got, [(v, 0x10) for v in range(7, -1, -1)])
        for n in (C, B):
            data, dest = self.chunk(n, 0x7A)
            for a in (0x8BCC, 0x8BFB):
                self.assertEqual(bytes(data[a - dest:a - dest + 3]), bytes.fromhex("20 09 a1"), (n, hex(a)))

    def test_the_humility_questions(self):
        """Disk B: Browning, Aristotle, Santayana and Slysam ask a boast
        ("Hast thou never lied?") and now count it, flag $FE as the pages
        that did (Sir Hrothgar, Flamis, Estro, Diane, Slim, Silver John)."""
        flagged = {}
        for i in range(256):
            raw = self.disk(B)[(i + 1) * 256:(i + 2) * 256]
            flagged[rm.alnum(rm.talk_decode(raw)["name"])] = raw[0xFE]
        for name in ("BROWNING", "ARISTOTLE", "SANTAYANA", "SLYSAM", "SIRHROTHGAR", "FLAMIS",
                     "ESTRO", "DIANE", "SLIM", "SILVERJOHN"):
            self.assertEqual(flagged[name], 1, name)
        orig = sum(self.disks[B].data[(i + 1) * 256 + 0xFE] for i in range(256))
        new = sum(self.disk(B)[(i + 1) * 256 + 0xFE] for i in range(256))
        self.assertEqual(new, orig + 4)

    def test_every_ladder_meets_one(self):
        """The eight dungeons (chunks $8C-$93, D; eight levels of 8 x 8): a
        ladder down ($20, $30) has a ladder up ($10, $30) below it, and the
        other way round -- the Abyss's altars ($B0) lead down too (elsewhere
        $B0 is not a way down).  Wrong (chunk $8F) had three that did not,
        Covetous ($90) one: level 6's down at (3, 3) over level 7's floor."""
        bad = []
        for c in range(0x8C, 0x94):
            d, dest = self.chunk(D, c)
            self.assertEqual(dest, 0xE800)
            for lv in range(7):
                for q in range(64):
                    a, b = d[lv * 64 + q] & 0xF0, d[(lv + 1) * 64 + q] & 0xF0
                    down = (0x20, 0x30, 0xB0) if c == 0x93 else (0x20, 0x30)
                    if (a in down) != (b in (0x10, 0x30)):
                        bad.append((c, lv + 1, q % 8, q // 8))
        self.assertEqual(bad, [])

    def test_serpents_holds_healer_can_be_talked_to(self):
        """Record $19 (B, block 352): the healer's row there is $12."""
        self.assertEqual(self.disk(B)[352 * 256 + 0x1D], 0x12)
        self.assertEqual(self.disks[B].data[352 * 256 + 0x1D], 0x0C)

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_no_bridge_trolls_while_flying(self):
        """$62B0, the turn's tile effects in Britannia on a bridge ($48 =
        $17) with the dice saying trolls ($084E & 7 = 0): "BRIDGE
        TROLLS!" and on to combat ($6EA3) on foot, but flying ($74 < 0) on to
        $62EA, which returns."""
        for flying, want in ((0x00, 0x6EA3), (0xFF, None)):
            with self.subTest(flying=flying):
                s = self.sim(A, 0x5B)                  # (u4fix.s is in its tail)
                s.mem[0x1B], s.mem[0x48], s.mem[0x74] = 1, 0x17, flying
                hit = []
                s.traps[0x084E] = lambda sim: setattr(sim.mpu, "a", 0)
                self.primm_text(s, [])
                s.traps[0x6EA3] = self.stop(hit)
                s.call(0x62B0)
                self.assertEqual(bool(hit), want is not None)

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_the_ankh_is_drawn_after_attacking_a_townsperson(self):
        """$472E: the third virtue lost ($8472), then the status ($0845)."""
        s = self.sim(A, 0x5B)
        ff, _f = rm.helpers("u4ff")
        s.mem[0xFF00:0xFF00 + len(ff)] = list(ff)
        calls = []
        for a in (0x8472, 0x0845):
            s.traps[a] = lambda sim, a=a: calls.append((a, sim.mpu.a, sim.mpu.y))
        s.mem[0x0400:0x0407] = [0xA0, 0x05, 0xA9, 0x03, 0x4C, 0x2E, 0x47]   # LDY #5 / LDA #3 / JMP $472E
        s.traps[0x4731] = self.stop([])
        s.call(0x0400)
        self.assertEqual([c[0] for c in calls], [0x8472, 0x0845])
        self.assertEqual(calls[0][1:], (3, 5))

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_a_dropped_chest_says_nothing(self):
        """$767B, a townsperson's chest in slot X: its conversation ($ACE0,X)
        cleared, on to $76D6."""
        s = self.sim(A, 0x5B)
        ff, _f = rm.helpers("u4ff")
        s.mem[0xFF00:0xFF00 + len(ff)] = list(ff)
        s.mem[0xACE0:0xAD00] = [0x07] * 32
        hit = []
        s.traps[0x76D6] = self.stop(hit)
        s.mpu.x = 5
        s.mem[0x0400:0x0403] = [0x4C, 0x7B, 0x76]
        s.call(0x0400)
        self.assertEqual(len(hit), 1)
        self.assertEqual(list(s.mem[0xACE0:0xAD00]), [0x07] * 5 + [0] + [0x07] * 26)

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_dismounting_takes_a_free_slot(self):
        """X-it's slot ($5C36 -> u4ff.s fx_free_slot, X at $5C4A): the
        highest free one -- from 8 up in Britannia (below are its monsters),
        from 0 up in a town; with none, a random one of 16-31 as before."""
        for mode, free, want in ((1, [3, 9], 9), (1, [3], "random"), (2, [3], 3), (2, [0], 0),
                                 (2, [3, 12], 12), (2, [], "random")):
            with self.subTest(mode=mode, free=free):
                s = self.sim(A, 0x5B)
                ff, _f = rm.helpers("u4ff")
                s.mem[0xFF00:0xFF00 + len(ff)] = list(ff)
                s.mem[0x1B] = mode
                s.mem[0xAC60:0xAC80] = [0 if i in free else 0x5A for i in range(32)]
                s.mem[0xAD5F] = 0                       # past the table: never taken
                s.traps[0x084E] = lambda sim: setattr(sim.mpu, "a", 0x2D)
                hit = []
                s.traps[0x5C4A] = lambda sim: hit.append(sim.mpu.x) or self.stop([])(sim)
                s.call(0x5C36)
                self.assertEqual(hit, [0x1D if want == "random" else want])

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_board_finds_the_transport_in_any_slot(self):
        """Board ($480B, A = the tile under the party): a horse in slot 3
        at the party's square is taken ($AC60,X and $AC00,X cleared), as one
        in slot 20 is; none there, nothing taken."""
        for slot in (3, 20, None):
            with self.subTest(slot=slot):
                s = self.sim(A, 0x5B)
                s.mem[0x10], s.mem[0x11], s.mem[0x48] = 9, 7, 0x14
                s.mem[0xAC00:0xAC80] = [0x5A] * 0x80
                if slot is not None:
                    s.mem[0xAC20 + slot], s.mem[0xAC40 + slot] = 9, 7
                    s.mem[0xAC60 + slot] = 0x15
                s.mpu.a = 0x14
                s.call(0x480B)
                tiles = list(s.mem[0xAC60:0xAC80])
                if slot is None:
                    self.assertEqual(tiles, [0x5A] * 32)
                else:
                    self.assertEqual((tiles[slot], s.mem[0xAC00 + slot]), (0, 0))
                    self.assertEqual(tiles.count(0), 1)
                self.assertEqual(s.mem[0x1E], 0x14)

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_katrina_gives_one_reason(self):
        """The talk code's reason not to join (chunk $78), its last two
        cases at $8D5F (X = 1 there: humility; 2: experience): "humble"
        alone, where it ran on into "EXPERIENCED"; "experienced" as it was."""
        for x, want in ((1, ["humble"]), (2, ["experienced"])):
            with self.subTest(x=x):
                s = self.sim(B, 0x78)
                ff, _f = rm.helpers("u4ff")
                s.mem[0xFF00:0xFF00 + len(ff)] = list(ff)
                text = []
                self.primm_text(s, text)
                s.mpu.x = x
                s.call(0x8D5F)
                self.assertEqual([t.lower() for t in text], want)
                self.assertEqual(text[0], want[0], "in the talk code's case")

    def test_creation_enables_interrupts_only_after_the_raster_irq_is_off(self):
        """Both of $51's IRQ restores: the CLI comes after the raster IRQ is
        disabled in $D01A (and, in the first, acknowledged in $D019) --
        before, a raster IRQ pending then went to a handler that did not
        acknowledge it, and the machine hung in character creation."""
        data, dest = self.chunk(A, 0x51)
        for start, end in ((0x67F5, 0x6803), (0x681E, 0x682F)):
            seg = bytes(data[start - dest:end - dest + 1])
            cli = seg.index(0x58)
            self.assertLess(seg.index(bytes([0x8D, 0x1A, 0xD0])), cli, hex(start))
            self.assertEqual(seg.count(0x58), 1)

    # -- the colour peer, EXIT?, the keyboard -----------------------------

    def test_the_colour_peer(self):
        """Chunk $77: the kit's peer_surface on B and C (one and the same
        copy before), peer_underworld on D, the rest of the chunk as it was."""
        for source, disks in rm.PEER:
            code = rm.kit_overlay(source, "src/patchedgame/peer.cfg")
            for n in disks:
                with self.subTest(disk=n):
                    got, dest = self.chunk(n, 0x77)
                    orig, _ = self.original_chunk(n, 0x77)
                    self.assertEqual(dest, 0x9000)
                    self.assertEqual(bytes(got[:len(code)]), code)
                    self.assertEqual(bytes(got[len(code):]), bytes(orig[len(code):]))
                    self.assertNotEqual(bytes(got), bytes(orig))

    @staticmethod
    def primm(sim):
        """$0821: print the inline string -- here, step over it."""
        sp = sim.mpu.sp
        ret = sim.mem[0x101 + sp] | sim.mem[0x102 + sp] << 8
        a = ret + 1
        text = []
        while sim.mem[a]:
            text.append(sim.mem[a] & 0x7F)
            a += 1
        sim.printed.append(bytes(text).decode())
        sim.mem[0x101 + sp], sim.mem[0x102 + sp] = a & 0xFF, a >> 8    # RTS: the byte after

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_exit_is_asked_at_a_towns_edge(self):
        """A step in town mode ($42E1 north, $43EF south, $44B9 west, $4591
        east): inside the map, on without a word; off it, "EXIT?" -- Y goes
        on (and the original's leaving follows), anything else takes the
        step back to its caller."""
        steps = ((0x42E1, 0x11, 0, -1), (0x43EF, 0x11, 0x1F, +1),
                 (0x44B9, 0x10, 0, -1), (0x4591, 0x10, 0x1F, +1))
        for site, zp, edge, d in steps:
            for pos, key, want in ((5, None, "on"), (edge, 0xD9, "on"), (edge, 0xCE, "back"),
                                   (edge, 0x00, "back")):
                with self.subTest(at=hex(site), pos=pos, key=key):
                    s = self.sim(A, 0x5B)
                    s.printed, hit = [], []
                    s.mem[zp] = pos
                    # the caller: JSR into the step, which is then entered at the site
                    s.mem[0x0400:0x0406] = [0x20, 0x04, 0x04, 0x60, 0x4C, site & 0xFF]
                    s.mem[0x0406] = site >> 8
                    s.traps[0x0821] = self.primm
                    def key_in(sim, key=key):
                        sim.mpu.a = key or 0
                        sim.mpu.p = (sim.mpu.p & ~0x82) | (0x02 if not key else 0x80)
                    s.traps[0x8398] = key_in
                    s.traps[site + 4] = lambda sim: hit.append("on")
                    s.traps[0x0403] = lambda sim: hit.append("back")
                    s.call(0x0400)
                    self.assertEqual(hit[:1], [want])
                    self.assertEqual(s.printed, [] if pos != edge else ["EXIT? "])
                    self.assertEqual(s.mem[zp], (pos + d) & 0xFF if want == "on" else pos)

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_the_key_read_takes_one_key_and_keeps_the_rest(self):
        data, dest = self.chunk(A, 0x4F)
        o = 0x1580 - dest
        _code, kb = rm.helpers("u4key")
        self.assertEqual(bytes(data[o:o + 7]), bytes([0x20, kb["kb_get"] & 0xFF, kb["kb_get"] >> 8,
                                                      0x09, 0x80, 0xC9, 0x80]))
        self.assertEqual(data[0x159D - dest], 0x2C, "the queue is still emptied")
        s = self.sim(A, 0x4F)
        s.mem[0x0277:0x027A] = list(b"ABC")
        s.mem[0xC6] = 3
        s.call(kb["kb_get"])
        self.assertEqual(s.mpu.a, ord("A"))
        self.assertEqual((s.mem[0xC6], bytes(s.mem[0x0277:0x0279])), (2, b"BC"))
        s.call(kb["kb_get"])
        self.assertEqual((s.mpu.a, s.mem[0xC6], s.mem[0x0277]), (ord("B"), 1, ord("C")))

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_the_text_scroll_does_what_the_original_did(self):
        """SUBS' text-window scroll ($160E, u4scroll.s) on random screen RAM
        and bitmap, against the original's code on the same memory: every
        byte outside the code and the scroll's scratch ($3D/$3E, $7C/$7D) is
        the same, and it is a good deal faster."""
        import random
        index = [c for c in range(0x40, 0xA0)
                 if u4.chunk_entry(u4.kernel_image(self.disks[1]), c)[2] <= 0xE000 <
                 u4.chunk_entry(u4.kernel_image(self.disks[1]), c)[2]
                 + u4.chunk_entry(u4.kernel_image(self.disks[1]), c)[1] * 256]
        self.assertEqual(len(index), 1)
        tables, tdest = self.original_chunk(A, index[0])
        code_new, cdest = self.chunk(A, 0x4F)
        code_old, _ = self.original_chunk(A, 0x4F)
        self.assertNotEqual(bytes(code_new[0x160E - cdest:0x1687 - cdest]),
                            bytes(code_old[0x160E - cdest:0x1687 - cdest]))

        def run(code, seed):
            s = Sim(bytes(code), cdest, {})
            rnd = random.Random(seed)
            s.mem[tdest:tdest + len(tables)] = list(tables)
            s.mem[0x0400:0x0800] = [rnd.randrange(256) for _ in range(0x400)]
            s.mem[0x2000:0x4000] = [rnd.randrange(256) for _ in range(0x2000)]
            s.mem[0x0000:0x0100] = [rnd.randrange(256) for _ in range(0x100)]
            s.mem[0x0100:0x0200] = [0] * 0x100
            before = s.mpu.processorCycles
            s.call(0x160E)
            return list(s.mem), s.mpu.processorCycles - before

        keep = [i for i in range(0x10000) if not cdest <= i < cdest + len(code_new)
                and i not in (0x3D, 0x3E, 0x7C, 0x7D) and not 0x0100 <= i < 0x0200]
        for seed in range(6):
            with self.subTest(seed=seed):
                new, cn = run(code_new, seed)
                old, co = run(code_old, seed)
                bad = [hex(i) for i in keep if new[i] != old[i]]
                self.assertEqual(bad[:8], [])
                self.assertLess(cn, co * 0.65, (cn, co))

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_the_town_view_buffer_is_what_it_was(self):
        """SUBS' $0C0B (u4view.s) on random maps and positions, edges of the
        32 x 32 map and 8-bit wrap-around included, against the original's code:
        the 121-tile buffer at $AE80, the registers and every byte of zero page
        but the cells' scratch ($44/$45, $7C/$7D) are the same, from $0F90
        (stubbed) to $0CD0 (a RTS here)."""
        import random
        code_new, dest = self.chunk(A, 0x4F)
        code_old, _ = self.original_chunk(A, 0x4F)

        def run(code, px, py, seed):
            s = Sim(bytes(code), dest, {})
            rnd = random.Random(seed)
            s.mem[0x0000:0x0100] = [rnd.randrange(256) for _ in range(0x100)]
            s.mem[0x0100:0x0200] = [0] * 0x100
            s.mem[0xE800:0xEC00] = [rnd.randrange(256) for _ in range(0x400)]
            s.mem[0xAE80:0xAF00] = [rnd.randrange(256) for _ in range(0x80)]
            s.mem[0x0F90] = 0x60
            s.mem[0x0CD0] = 0x60
            s.mem[0x10], s.mem[0x11] = px, py
            before = s.mpu.processorCycles
            s.call(0x0C0B)
            return s, s.mpu.processorCycles - before

        rnd = random.Random(7)
        edge = [0, 1, 4, 5, 6, 15, 26, 27, 28, 31, 32, 33, 36, 37, 250, 251, 252, 255]
        pos = [(rnd.randrange(256), rnd.randrange(256)) for _ in range(60)]
        pos += [(x, y) for x in edge for y in edge]
        faster, tn, to = 0, 0, 0
        for k, (x, y) in enumerate(pos):
            new, cn = run(code_new, x, y, k)
            old, co = run(code_old, x, y, k)
            same = [i for i in list(range(0xAE80, 0xAF00)) + list(range(0, 0x100))
                    if i not in (0x44, 0x45, 0x7C, 0x7D) and new.mem[i] != old.mem[i]]
            self.assertEqual(same[:4], [], (x, y))
            self.assertEqual((new.mpu.x, new.mpu.y), (old.mpu.x, old.mpu.y), (x, y))
            faster += cn < co
            tn, to = tn + cn, to + co
        self.assertEqual(faster, len(pos))         # never slower
        self.assertLess(tn, to * 0.6)

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_the_town_views_line_of_sight_is_what_it_was(self):
        """SUBS' $0D65-$0E6B (u4los.s) on random tile buffers with 0-80%
        opaque tiles ($06, $08, $49, $7E, $7F), against the original's code:
        the 121 tiles at $AE00 -- the tile where seen, $7E where not -- are
        the same, from $0D65 to $0E6C (a RTS here), and it is faster."""
        import random
        code_new, dest = self.chunk(A, 0x4F)
        code_old, _ = self.original_chunk(A, 0x4F)
        tiles = [0, 1, 2, 3, 4, 5, 0x3C, 0x20, 0x80, 0xFF]
        opaque = [6, 8, 0x49, 0x7E, 0x7F]

        def run(code, seed, p):
            s = Sim(bytes(code), dest, {})
            rnd = random.Random(seed)
            s.mem[0x0000:0x0100] = [rnd.randrange(256) for _ in range(0x100)]
            s.mem[0x0100:0x0200] = [0] * 0x100
            s.mem[0xAE80:0xAF00] = [rnd.choice(opaque) if rnd.random() < p else rnd.choice(tiles)
                                    for _ in range(0x80)]
            s.mem[0xAE00:0xAE80] = [rnd.randrange(256) for _ in range(0x80)]
            s.mem[0x0E6C] = 0x60
            before = s.mpu.processorCycles
            s.call(0x0D65)
            return s, s.mpu.processorCycles - before

        tn = to = 0
        for k in range(140):
            p = (0, 0.02, 0.05, 0.1, 0.2, 0.4, 0.8)[k % 7]
            new, cn = run(code_new, k, p)
            old, co = run(code_old, k, p)
            self.assertEqual(bytes(new.mem[0xAE00:0xAE79]), bytes(old.mem[0xAE00:0xAE79]), (k, p))
            if p <= 0.1:
                tn, to = tn + cn, to + co
        self.assertLess(tn, to * 0.8)

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_the_joystick(self):
        """Port 2 with the queue empty, at most every 5 jiffies ($A2):
        directions as @ / : ;, fire by the mode ($1B)."""
        _code, kb = rm.helpers("u4key")
        s = self.sim(A, 0x4F)
        s.mem[0xC6] = 0
        jiffy = [0]
        def read(port, mode=1, advance=5):
            jiffy[0] += advance
            s.mem[0xA2], s.mem[0xDC00], s.mem[0x1B] = jiffy[0] & 0xFF, port, mode
            s.call(kb["kb_get"])
            return s.mpu.a
        self.assertEqual(read(0xFF), 0)                 # nothing
        for port, key in ((0xFE, "@"), (0xFD, "/"), (0xFB, ":"), (0xF7, ";")):
            self.assertEqual(read(port), ord(key), hex(port))
        self.assertEqual(read(0xFE, advance=2), 0, "again within 5 jiffies")
        for mode, key in ((1, 0x45), (2, 0x54), (3, 0), (0x80, 0x41)):
            self.assertEqual(read(0xEF, mode), key, hex(mode))

    # -- u4a0.s at $A006: the active character, attacking non-monsters -----

    def a0(self):
        """u4a0.s at $A006, with u4ff.s at $FF00 (fx_attack goes on there)."""
        code, sym = rm.helpers("u4a0")
        sim = Sim(code, 0xA006, {})
        ff, _f = rm.helpers("u4ff")
        sim.mem[0xFF00:0xFF00 + len(ff)] = list(ff)
        return sim, sym

    def test_u4a0_is_a_boot_segment(self):
        code, _sym = rm.helpers("u4a0")
        found = [s for s in self.segments if s[2] == 0xA006]
        self.assertEqual(len(found), 1)
        off, length, _dest = found[0]                # (with the kernel and the tables)
        self.assertEqual(self.flash[off:off + len(code)], code)
        self.assertFalse(any(self.flash[off + len(code):off + 0xA100 - 0xA006]), "then zeros to $A100")

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_attacking_what_is_not_a_monster(self):
        """The foe's tile ($4733): sick -> beggar, water -> deep water, the
        Avatar's tile (a lord) -> knight, a horse facing east -> one facing
        west (u4ff.s fx_horse), anything else as it is; the check
        ($46E1): a chest cannot be attacked; the animation (SUBS $0B6D): the
        ankh and a camp fire keep still.  Hooked as stored."""
        _code, a = self.a0()
        data, dest = self.chunk(A, 0x5B)
        w = lambda x: bytes([0x20, x & 0xFF, x >> 8])
        self.assertEqual(bytes(data[0x4733 - dest:0x4736 - dest]), w(a["fx_attack"]))
        self.assertEqual(bytes(data[0x46E1 - dest:0x46E4 - dest]), w(a["fx_attackable"]))
        subs, sdest = self.chunk(A, 0x4F)
        self.assertEqual(bytes(subs[0x0B6D - sdest:0x0B70 - sdest]), w(a["fx_animate"]))
        for tile, foe, check in ((0x38, 0x58, 0x38), (0x02, 0x01, 0x02), (0x1F, 0x2A, 0x1F),
                                 (0x15, 0x14, 0x15), (0x14, 0x14, 0x14),
                                 (0x3C, 0x3C, 0x8C), (0x90, 0x90, 0x90)):
            with self.subTest(tile=hex(tile)):
                sim, _ = self.a0()
                sim.mem[0xAC60 + 3] = tile
                sim.mpu.x = 3
                sim.call(a["fx_attack"])
                self.assertEqual(sim.mpu.a, foe)
                sim.mpu.x = 3
                sim.call(a["fx_attackable"])
                self.assertEqual(sim.mpu.a, check)
        for tile, want in ((0x3D, 1), (0x4B, 1), (0x90, 0x77)):
            with self.subTest(animate=hex(tile)):
                sim, _ = self.a0()
                sim.mem[0xAD70 + 2] = 0x77
                sim.mpu.a, sim.mpu.x = tile, 2
                sim.call(a["fx_animate"])
                self.assertEqual(sim.mpu.a, want)

    def primm_text(self, sim, text):
        """A trap for $0821: the text inline after the JSR is skipped."""
        def trap(s):
            lo = s.mem[0x100 + ((s.mpu.sp + 1) & 0xFF)]
            hi = s.mem[0x100 + ((s.mpu.sp + 2) & 0xFF)]
            a = (hi << 8 | lo) + 1
            out = bytearray()
            while s.mem[a]:
                out.append(s.mem[a] & 0x7F)
                a += 1
            text.append(out.decode("latin1"))
            s.mem[0x100 + ((s.mpu.sp + 1) & 0xFF)] = a & 0xFF      # RTS lands after the 0
            s.mem[0x100 + ((s.mpu.sp + 2) & 0xFF)] = a >> 8
        sim.traps[0x0821] = trap

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_the_active_character(self):
        """Combat's digit ($7131, the command combat did not know): 1-8 up to
        the party's size picks one if awake ("3 ACTIVE"), 0 or more than the
        party is the party again ("PARTY MODE"), anything else "WHAT?".  Its
        rounds start with it; a turn not its own is skipped; asleep or gone,
        the party again.  Hooked as stored."""
        _code, a = self.a0()
        data, dest = self.chunk(A, 0x5B)
        w = lambda x: bytes([x & 0xFF, x >> 8])
        self.assertEqual(bytes(data[0x7097 - dest:0x7099 - dest]), w(a["ac_start"]))
        self.assertEqual(bytes(data[0x709D - dest:0x70A1 - dest]), b"\x20" + w(a["ac_turn"]) + b"\xea")
        self.assertEqual(bytes(data[0x70C2 - dest:0x70C5 - dest]), b"\x20" + w(a["ac_check"]))
        self.assertEqual(bytes(data[0x7131 - dest:0x7133 - dest]), w(a["ac_key"]))

        def machine(awake=True):
            sim, _ = self.a0()
            text, hit = [], []
            self.primm_text(sim, text)
            sim.traps[0x0824] = lambda s: text.append(chr(s.mpu.a & 0x7F))
            def check_awake(s):                         # 0 and Z: awake
                s.mpu.a = 0 if awake else 1
                s.mpu.p = (s.mpu.p & ~0x02) | (0x02 if awake else 0)
            sim.traps[0x7DAF] = check_awake
            for t in (0x621E, 0x4112, 0x714E, 0x084B, 0xA112):
                sim.traps[t] = lambda s, t=t: hit.append(t)
            sim.mem[0x1F] = 4                           # a party of four
            for i in range(4):
                sim.mem[0xADA0 + i] = 0x20              # all in the fight
            # a caller for ac_check, which drops its return when it skips
            sim.mem[0x0340:0x0344] = [0x20, a["ac_check"] & 0xFF, a["ac_check"] >> 8, 0x60]
            return sim, text, hit
        for key, want, char, words in ((0xB3, 0x621E, 3, "3 ACTIVE"), (0xB0, 0x621E, 0, "PARTY MODE"),
                                       (0xB5, 0x621E, 0, "PARTY MODE"), (0xC1, 0x4112, 0, "")):
            with self.subTest(key=hex(key)):
                sim, text, hit = machine()
                sim.mpu.a = key
                sim.call(a["ac_key"])
                self.assertEqual(hit, [want])
                self.assertEqual(sim.mem[a["ac_char"]], char)
                self.assertEqual("".join(text).strip(), words)
        # a round with 3 chosen: it starts with 3; player 2's turn is skipped,
        # 3's is played; 3 asleep, the party again
        sim, text, hit = machine()
        sim.mem[a["ac_char"]] = 3
        sim.call(a["ac_turn"])
        self.assertEqual((sim.mpu.a, sim.mem[0x54]), (3, 3))
        sim.mem[0x54] = 2
        sim.call(0x0340)
        self.assertEqual(hit, [0x714E], "not its turn: skipped")
        hit.clear()
        sim.mem[0x54] = 3
        sim.call(0x0340)
        self.assertEqual(hit, [0x084B], "its turn")
        sim.mem[0xADA0 + 2] = 0x38                      # asleep
        sim.call(a["ac_turn"])
        self.assertEqual((sim.mem[0x54], sim.mem[a["ac_char"]]), (1, 0))
        sim, text, hit = machine()
        sim.mem[a["ac_char"]] = 5
        sim.call(a["ac_start"])
        self.assertEqual((sim.mem[a["ac_char"]], hit), (0, [0xA112]), "a new fight: the party")

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_x_wins_a_fight(self):
        """Combat's X (its letter table, $77C8, "WHAT?" before): with the
        launcher's X (pw_on) every foe goes and the turn ends, and the game's
        own check after a turn ($7514) then finds none and goes to "VICTORY!"
        ($75FF); without it "WHAT?" and the foes stay.  Hooked as stored."""
        _code, a = self.a0()
        data, dest = self.chunk(A, 0x5B)
        self.assertEqual(bytes(data[0x77C8 - dest:0x77CA - dest]), bytes([a["pw_win"] & 0xFF, a["pw_win"] >> 8]))
        for on, want in ((0, 0x4112), (1, 0x621E)):
            with self.subTest(pw_on=on):
                code, _ = rm.helpers("u4a0")
                sim = Sim(code, 0xA006, {})
                sim.mem[dest:dest + len(data)] = list(data)
                hit = []
                for t in (0x4112, 0x621E, 0x75FF):
                    sim.traps[t] = lambda s, t=t: hit.append(t)
                sim.mem[0x02A7] = on
                foes = [0, 0x90, 0, 0, 0xA4] + [0] * 10 + [0x80]
                sim.mem[0xAD50:0xAD60] = foes
                sim.call(a["pw_win"])
                self.assertEqual(hit, [want])
                self.assertEqual(list(sim.mem[0xAD50:0xAD60]), [0] * 16 if on else foes)
                # the end of the turn: a caller for $7514, which drops it on a victory
                hit.clear()
                sim.mem[0x1B] = 0x80                    # a fight on the surface
                sim.mem[0xADA0] = 0x20                  # a player in it
                sim.mem[0x0340:0x0344] = [0x20, 0x14, 0x75, 0x60]
                sim.call(0x0340)
                self.assertEqual(hit, [0x75FF] if on else [])

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_quit_and_save_in_a_dungeon(self):
        """u4ff.s at $FF00, hooked at $582F (Quit outside Britannia) and $405C
        (the load): in a dungeon ($1B = 3) Quit asks for the save disk, saves
        chunks $7F, $80 and record $1A, and asks for the dungeon's again;
        elsewhere "NOT HERE!" still.  A load in a dungeon goes on there (its
        code, level and music) and into the main loop; on the surface the
        balloon as saved and A = 0, as the fix in place did."""
        code, f = rm.helpers("u4ff")
        found = [s for s in self.segments if s[2] == 0xFF00]
        self.assertEqual(len(found), 1)
        self.assertEqual(self.flash[found[0][0]:found[0][0] + found[0][1]], code)
        data, dest = self.chunk(A, 0x5B)
        self.assertEqual(bytes(data[0x582F - dest:0x5831 - dest]), bytes([f["dg_save"] & 0xFF, f["dg_save"] >> 8]))
        self.assertEqual(bytes(data[0x405C - dest:0x4062 - dest]),
                         bytes([0x20, f["dg_load"] & 0xFF, f["dg_load"] >> 8, 0xEA, 0xEA, 0xEA]))

        def machine(mode):
            sim = Sim(code, 0xFF00, {})
            sim.mem[0x1B] = mode
            calls = []
            sim.traps[0x0842] = lambda s: calls.append(("disk", s.mpu.a))
            sim.traps[0xA100] = lambda s: calls.append(("io", s.mpu.a, s.mpu.x))
            for a in (0x0845, 0x50AD, 0xAF20, 0x621E, 0x4178):
                sim.traps[a] = lambda s, a=a: calls.append((hex(a), s.mpu.a))
            return sim, calls
        sim, calls = machine(3)
        sim.call(f["dg_save"])
        self.assertEqual(calls, [("disk", 2), ("io", 0xD3, 0x7F), ("io", 0xD3, 0x80), ("io", 0xD3, 0x1A),
                                 ("disk", 4), ("0x621e", 4)])
        for mode in (1, 2):
            sim, calls = machine(mode)
            sim.call(f["dg_save"])
            self.assertEqual([c[0] for c in calls], ["0x4178"], f"mode {mode}: NOT HERE!")
        sim, calls = machine(3)
        sim.mem[0x0340:0x0344] = [0x20, f["dg_load"] & 0xFF, f["dg_load"] >> 8, 0x60]
        sim.call(0x0340)                            # (it drops its caller)
        self.assertEqual(calls, [("disk", 4), ("io", 0xCC, 0x95), ("0x845", 0xCC), ("0x50ad", 0xCC),
                                 ("0xaf20", 0xC4), ("0x621e", 0xC4)])
        self.assertEqual((sim.mem[0x74], sim.mem[0x75], sim.mem[0x4D]), (0, 0, 0xFF))
        for flying in (0, 1):
            sim, calls = machine(1)
            sim.mem[0x1D], sim.mem[0x74] = flying, 0x55
            sim.call(f["dg_load"])
            self.assertEqual((calls, sim.mem[0x74], sim.mpu.a), ([], flying, 0))

    def pw_sim(self, keys, waits=()):
        """Game main (chunk $5B) with u4pw.s in pages 2-3; keys for $8398
        (read and echoed) and $0800 (read) in turn."""
        code, pw = rm.helpers("u4pw")
        sim = self.sim(A, 0x5B)
        sim.mem[0x02A7:0x02A7 + len(code)] = list(code)
        hit, ks, ws = [], list(keys), list(waits)

        def key(s, q):
            k = q.pop(0) if q else 0
            s.mpu.a = k
            s.mpu.p = (s.mpu.p & ~0x82) | (0x80 if k & 0x80 else 0) | (0 if k else 0x02)
        sim.traps[0x8398] = lambda s: key(s, ks)
        sim.traps[0x0800] = lambda s: key(s, ws)
        self.primm_text(sim, [])
        sim.traps[0x0821] = (lambda old: (lambda s: (hit.append(0x0821), old(s))))(sim.traps[0x0821])
        for a in (0x0803, 0x0824, 0x621E, 0x4112, 0x4139, 0x4178):
            sim.traps[a] = lambda s, a=a: hit.append(a)
        return sim, pw, hit

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_teleport_and_transport(self):
        """u4pw.s, hooked always at T ($59CE) and B on nothing ($47AC): the
        option off (pw_on 0), Talk and "WHAT?" as they were; on, in
        Britannia on foot, T then T 3 goes to the third towne, T then C with
        letters to a latitude and longitude, B then H/S/B to a horse, a ship,
        a balloon."""
        data, dest = self.chunk(A, 0x5B)
        _c, pw = rm.helpers("u4pw")
        _f, ff = rm.helpers("u4ff")
        w = lambda a: bytes([a & 0xFF, a >> 8])
        self.assertEqual(bytes(data[0x59CE - dest:0x59D1 - dest]), b"\x20" + w(pw["pw_teleport"]))
        self.assertEqual(bytes(data[0x47AC - dest:0x47AE - dest]), w(pw["pw_board"]))
        self.assertEqual(bytes(data[0x404D - dest:0x4050 - dest]), b"\x4c" + w(ff["ff_nogame"]))
        # off: T is Talk -- the print, with "Talk-" as its return address --
        # and B "WHAT?"
        sim, pw, hit = self.pw_sim([])
        sim.mem[0x1B] = 1
        seen = []

        def talk(s):                    # where the print would read its text from
            lo = s.mem[0x100 + ((s.mpu.sp + 1) & 0xFF)]
            hi = s.mem[0x100 + ((s.mpu.sp + 2) & 0xFF)]
            seen.append((hi << 8 | lo) + 1)
            s.mpu.sp = (s.mpu.sp + 2) & 0xFF        # and end the call there
        sim.traps[0x0821] = talk
        sim.mem[0xC000:0xC004] = [0x20, 0xCE, 0x59, 0x60]
        sim.call(0xC000)
        self.assertEqual(seen, [0x59D1])
        self.assertEqual(bytes(sim.mem[0x59D1:0x59D6]), bytes(ord(c) | 0x80 for c in "Talk-"))
        sim, pw, hit = self.pw_sim([])
        sim.call(pw["pw_board"])
        self.assertEqual(hit, [0x4112])
        # on: (T, the command, read by the game), T(owne), 3
        sim, pw, hit = self.pw_sim([0xD4, 0xB3])
        sim.mem[pw["pw_on"]], sim.mem[0x1B], sim.mem[0x1E] = 1, 1, 0x1F
        sim.mem[0xAC00:0xAD00] = [0x55] * 256
        sim.mem[0xC000:0xC004] = [0x20, 0xCE, 0x59, 0x60]      # T's JSR (clear of u4pw.s)
        sim.call(0xC000)
        self.assertEqual((sim.mem[0x10], sim.mem[0x11]), (sim.mem[0x519E + 2], sim.mem[0x51BE + 2]))
        want = bytearray([0x55] * 256)
        for table in (0x00, 0x60):                  # map_status, object_tile: slots 0-7
            want[table:table + 8] = bytes(8)
        self.assertEqual(bytes(sim.mem[0xAC00:0xAD00]), bytes(want),
                         "the monsters gone, transports and chests (slots 8-31) kept")
        self.assertIn(0x0803, hit)
        # C, B C (latitude $12), D E (longitude $34)
        sim, pw, hit = self.pw_sim([0xC3], waits=[0xC2, 0xC3, 0xC4, 0xC5])
        sim.mem[pw["pw_on"]], sim.mem[0x1B], sim.mem[0x1E] = 1, 1, 0x1F
        sim.mem[0xC000:0xC004] = [0x20, 0xCE, 0x59, 0x60]
        sim.call(0xC000)
        self.assertEqual((sim.mem[0x11], sim.mem[0x10]), (0x12, 0x34))
        # on a ship: "only on foot"
        sim, pw, hit = self.pw_sim([])
        sim.mem[pw["pw_on"]], sim.mem[0x1B], sim.mem[0x1E] = 1, 1, 0x10
        sim.mem[0xC000:0xC004] = [0x20, 0xCE, 0x59, 0x60]
        sim.call(0xC000)
        self.assertEqual(hit, [0x4139])
        # B: H, B; S beside deep water
        for key, want in ((0xC8, 0x14), (0xC2, 0x18), (0xD3, 0x10)):
            sim, pw, hit = self.pw_sim([key])
            sim.mem[pw["pw_on"]], sim.mem[0x1A], sim.mem[0x1E] = 1, 0, 0x1F
            sim.mem[0x49:0x4D] = [0x05, 0x01, 0x05, 0x05]           # deep water south
            sim.call(pw["pw_board"])
            self.assertEqual(sim.mem[0x1E], want, hex(key))
            if key == 0xC2:
                self.assertEqual((sim.mem[0x1D], sim.mem[0x74]), (0xFF, 0xFF), "flying")

    @unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
    def test_no_saved_game_goes_back_to_the_title(self):
        """ff_nogame ($404D): a wait of 100 frames on line $FB, then disk 1
        and 'R' chunk $50 -- where it was JMP $404D, a hang.  The title's
        music is taken off the interrupt chain first ($A116 back from the
        $ECC2 its init kept), silent: the title loads it again over itself
        (else a crash once the title is up)."""
        from py65.memory import ObservableMemory
        code, ff = rm.helpers("u4ff")
        sim = Sim(code, 0xFF00, {})
        om = ObservableMemory(subject=sim.mem)
        line = [0]

        def d012(_a):
            line[0] = (line[0] + 1) & 0xFF
            return line[0]
        om.subscribe_to_read([0xD012], d012)
        sim.mpu.memory = sim.mem = om
        calls = []
        sim.traps[0x0842] = lambda s: calls.append(("disk", s.mpu.a))
        sim.traps[0xA100] = lambda s: calls.append(
            ("io", s.mpu.a, s.mpu.x, s.mem[0xA116] | s.mem[0xA117] << 8, s.mem[0xD418]))
        for hooked, want in ((0xEC89, 0xA6AC), (0xA6AC, 0xA6AC), (0x1234, 0x1234)):
            calls.clear()
            sim.mem[0x1B] = 1
            sim.mem[0xA116], sim.mem[0xA117] = hooked & 0xFF, hooked >> 8
            sim.mem[0xECC2], sim.mem[0xECC3] = 0xAC, 0xA6
            sim.mem[0xD418] = 0x08
            sim.call(ff["ff_nogame"])
            self.assertEqual(calls, [("disk", 1), ("io", 0xD2, 0x50, want,
                                                   0 if hooked == 0xEC89 else 8)])
            self.assertEqual(sim.mem[0x1B], 0)
            self.assertEqual(sim.mpu.p & 0x04, 0, "interrupts left off")

    def test_the_helpers_are_out_of_everyones_way(self):
        """$5B's tail holds them, and nothing loads there but chunks that
        reload $5B; the rest of the tail is cleared."""
        data, dest = self.chunk(A, 0x5B)
        code, fx = rm.helpers()
        o = rm.FX_ORG - dest
        self.assertEqual(bytes(data[o:o + len(code)]), code)
        self.assertEqual(bytes(data[o + len(code):rm.FX_END - dest]),
                         bytes(rm.FX_END - rm.FX_ORG - len(code)))


if __name__ == "__main__":
    unittest.main()
