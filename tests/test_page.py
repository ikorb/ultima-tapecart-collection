"""The launcher's per-game page (asm/page.s), on the host.

The page runs in py65 against the collection's real flash image, with the
KERNAL's CHROUT, GETIN and SCNKEY trapped: what it prints is the screen, and
the keys come from a list.  The saved games are real ones where there are
any -- Ultima I's scratched characters still on its disk, a played Ultima IV
from build/u4_saved.tcrt, Ultima V's saves in 5/with-save, Ultima VI's played
Surface disk -- and made up from the analysed record layouts where there are
not (II, III).

Skipped without py65 (the repository's .venv has it).
"""
import os
from ultima import paths
import re
import unittest
from pathlib import Path

try:
    from ultima.sim.sim6502 import Sim
except ImportError:
    Sim = None

from ultima.disks.d64 import D64
from ultima.flash.tcrt import TCRT
from ultima.launcher.u6log import Log
from ultima.sim.screenmodel import Screen
from ultima.launcher import u2log
from ultima.launcher import launcher
from ultima.flash import regions

IMAGE = os.path.join(paths.BUILD, "ultima-collection.tcrt")
NAMES = launcher.ORDER                      # descriptor index order
SAVING = [g for g in NAMES if regions.save_region(g)[1]]    # not Akalabeth
KEY_B, KEY_R, KEY_Y, KEY_L, KEY_J = (ord(c) for c in "BRYLJ")


from ultima.sim.pagesim import COLOURS, screen, launcher_prg, page_syms     # noqa: E402,F401


def slot(flash, base, data, blocks=False):
    """A slot as the drivers write one: A5 5A and the length (U3: the block
    count and a zero), the data a page on."""
    flash[base:base + 0x1000] = b"\xff" * 0x1000
    n = (len(data) + 255) // 256 if blocks else len(data)
    flash[base:base + 4] = bytes([0xA5, 0x5A, n & 0xFF, 0 if blocks else n >> 8])
    flash[base + 0x100:base + 0x100 + len(data)] = data


# -- saved games -----------------------------------------------------------
def seed_u1(flash, s):
    """Four in the roster, three with a character record (the first has none)."""
    ro = bytearray(64)
    for i, name in enumerate((b"Anselm", b"Brenda", b"Tertio", b"Dabba")):
        ro[16 * i] = 0xFF                           # in use
        ro[16 * i + 3:16 * i + 3 + len(name)] = name
    slot(flash, s["U1_RO"], bytes(ro))
    for i, (name, sex, race, cls, hp, food) in enumerate(((b"Brenda", 1, 2, 3, 150, 200),
                                                           (b"Tertio", 0, 1, 1, 1234, 9999),
                                                           (b"Dabba", 0, 3, 4, 7, 35))):
        p = bytearray(458)                          # the editor's u1.ts has the layout
        p[0:2] = b"\xca\x01"
        p[0x4A] = sex
        p[0x4B:0x4B + len(name)] = name
        p[0x59:0x5B] = hp.to_bytes(2, "little")     # hit points
        for o in range(0x5B, 0x67, 2):              # strength .. intelligence
            p[o:o + 2] = (20).to_bytes(2, "little")
        p[0x69], p[0x6B] = race, cls
        p[0x78:0x7A] = food.to_bytes(2, "little")   # food
        slot(flash, s["U1_P0"] + (i + 1) * 0x1000, bytes(p))
    return ["Anselm          (no data)", "Brenda          HP  150  Food  200",
            "Tertio          HP 1234  Food 9999", "Dabba           HP    7  Food   35"]


def seed_u2(flash, s):
    rec = bytearray(256)
    rec[0:6] = bytes(c | 0x80 for c in b"HAWKWI")
    rec[0x1B:0x1F] = bytes([0x04, 0x21, 0x03, 0x99])
    # a played log: an older record, then this one, in its second half
    old = bytearray(rec)
    old[0x1B:0x1D] = bytes([0x01, 0x00])
    u2log.write(flash, s["U2_LOG"], [(0, bytes(old)), (0, bytes(rec))], half=1, gen=7)
    return ["HAWKWI          HP  421  Food  399"]


def seed_u3(flash, s):
    prty, plrs = bytearray(256), bytearray(256)
    prty[1] = 3
    for i, (n, hp, mx, st) in enumerate(((b"IOLO", 0x0150, 0x0150, 0xC7),
                                         (b"SHAMINO", 0x0042, 0x0275, 0xD0),
                                         (b"DUPRE", 0x1234, 0x2500, 0xC7))):
        r = plrs[i * 64:(i + 1) * 64]
        r[:len(n)] = bytes(c | 0x80 for c in n)
        r[0x11] = st
        r[0x1A:0x1E] = bytes([hp >> 8, hp & 0xFF, mx >> 8, mx & 0xFF])
        plrs[i * 64:(i + 1) * 64] = r
    slot(flash, s["U3_PRTY"], bytes(prty), blocks=True)
    slot(flash, s["U3_PLRS"], bytes(plrs), blocks=True)
    return ["IOLO            G  HP  150/150", "SHAMINO         P  HP   42/275",
            "DUPRE           G  HP 1234/2500"]


def seed_u4(flash, s):
    """A party of one, on the base slots (disk C's blocks 271-275): block
    275's party size 1, the first roster record named, in good health."""
    d = D64(paths.disk("u4c"))
    base = regions.save_base("u4")
    for i in range(5):
        flash[base + i * 0x1000:base + i * 0x1000 + 256] = d.sector(*D64.from_linear(271 + i))
    flash[s["U4_ZP"] + 0x0F] = 1
    ro = s["U4_ROSTER"]
    flash[ro:ro + 16] = bytes(c | 0x80 for c in b"AVATAR").ljust(16, b"\0")
    flash[ro + 0x12] = ord("G") | 0x80
    flash[ro + 0x13:ro + 0x16] = bytes([0x19, 0x22, 0x25])           # STR DEX INT, BCD
    flash[ro + 0x18:ro + 0x1C] = bytes([0x02, 0x00, 0x02, 0x00])     # 200 of 200, BCD
    flash[ro + 0x1C:ro + 0x1E] = bytes([0x01, 0x25])                 # experience 125, BCD
    return ["AVATAR          G  HP 200/200"]


def seed_u5(flash, s):
    """The game's own BLANK.ROSTER (1A) -- British, Shamino and Iolo in the
    party, as character creation starts it -- with the first renamed."""
    roster = bytearray(D64(paths.disk("u5-1a")).payload("BLANK.ROSTER")[0])
    roster[0:8] = bytes(c | 0x80 for c in b"teste") + b"r\0\0"     # bit 7 but on the last letter
    roster[0x80 + 4:0x80 + 7] = bytes([0x20, 0x23, 0x18])          # STR DEX INT, BCD (blank's
                                                                    # 150 experience, level 2 stay)
    slot(flash, s["U5_ROSTER"], bytes(roster))
    return ["tester          G  HP  60/60", "Shamino         G  HP   5/60",
            "Iolo            G  HP  90/90"]


def u6_save_area():
    """{sector: bytes} of 1A's save area (T6 S9-20) as a saved game holds
    it: as 1A ships it -- the party of four the game starts with -- the
    Avatar named."""
    d = D64(paths.disk("u6-1a"))
    out = {}
    for sc in range(9, 21):
        sector = bytearray(d.sector(6, sc))
        if sc == 12:            # slot 0's name, at S12 +$7D's offset
            at = sector[0x7D]
            sector[at:at + 7] = b"T" + bytes(c - 0x60 for c in b"ester") + b"\0"
        out[sc] = bytes(sector)
    return out


def seed_u6(flash, s):
    """u6_save_area(), logged as a save would."""
    log = Log(flash, s["U6_LO"], s["U6_MID"])
    for sc, sector in u6_save_area().items():
        log.append(bytes([1, 0, 6, sc]), [sector], False)

    return ["Tester          HP  90/90", "Dupre           HP  90/90",
            "Shamino         HP  90/90", "Iolo            HP  90/90"]



def seed_u4_full(flash, s):
    """Ultima IV's longest page: eight in the party, the Avatar's name as
    long as the record holds."""
    seed_u4(flash, s)
    flash[s["U4_ZP"] + 0x0F] = 8
    ro = s["U4_ROSTER"]
    rec = bytes(flash[ro:ro + 32])
    names = (b"AVATARNAMELONGX", b"IOLO", b"SHAMINO", b"MARIAH", b"GEOFFREY",
             b"JAANA", b"JULIA", b"KATRINA")
    for i, n in enumerate(names):
        flash[ro + 32 * i:ro + 32 * i + 32] = n.ljust(16, b"\0") + rec[16:]
    return [f"{n.decode():16}G  HP 200/200" for n in names]


SEEDS = {"u1": seed_u1, "u2": seed_u2, "u3": seed_u3, "u4": seed_u4,
         "u5": seed_u5, "u6": seed_u6}


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestPage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fresh = bytes(TCRT.read(IMAGE).flash.ljust(regions.FLASH_SIZE, b"\xff"))
        cls.image = launcher_prg()
        cls.sym = launcher.symbols()
        cls.s = page_syms()

    def run_page(self, flash, game, keys):
        sim = Sim(self.image, launcher.FONT_ORG, self.sym)
        cart = sim.attach_cart(flash)
        out, ks = bytearray(), list(keys)

        def getin(s):
            if not ks:
                raise AssertionError("the page wants another key; screen:\n" + screen(out))
            k = ks.pop(0)
            s.mpu.a = k
            s.mpu.p = (s.mpu.p & ~0x82) | (0x80 if k & 0x80 else 0) | (0 if k else 0x02)
        scr = self.scr = Screen(sim.mem)

        def chrout(s):
            out.append(s.mpu.a)
            scr.put(s.mpu.a)
        sim.traps[0xFFD2] = chrout
        sim.traps[0xFFF0] = scr.plot
        sim.traps[0xFFE4] = getin
        sim.traps[0xFF9F] = lambda s: None
        sim.mem[0], sim.mem[1] = 0x2F, 0x37
        sim.mem[0x0300:0x0310] = list(b"ULTIMA X".ljust(16, b"\x00"))
        sim.mpu.a, sim.mpu.x, sim.mpu.y = regions.DESC_INDEX[game], 0x00, 0x03
        sim.call(launcher.PAGE_ORG)
        return sim, cart, screen(out)

    @staticmethod
    def saved(text):
        """The saved game's lines, between the name and the first blank
        line, on the last screen drawn ("No saved game" when none)."""
        last = text.split("<CLR>")[-1]
        body = last.split("\n\n")[1]
        return [line.strip() for line in body.split("\n") if line.strip()]

    def option(self, label):
        """An option's value as the screen shows it now (toggles rewrite
        it in place), at column 31 -- or 14 for G's."""
        for line in self.scr.lines():
            if label + ":" in line:
                col = 14 if label == "Graphics" else 31
                self.assertEqual(line[col - 1], " ", line)
                return line[col:]
        self.fail(f"no {label!r} on the screen:\n{self.scr.text()}")

    def test_a_digit_is_another_game_s_page(self):
        """0-6 on a page: back, with A = that game's place in the list, which
        is its key (the menu opens its page); B, <- and RUN/STOP: back with
        A = $FF."""
        for key in "01636":
            sim, _cart, _text = self.run_page(bytearray(self.fresh), "u4", [ord(key)])
            self.assertEqual((sim.mpu.p & 1, sim.mpu.a), (1, int(key)), key)
        sim, _cart, _text = self.run_page(bytearray(self.fresh), "u0", [ord("4")])
        self.assertEqual((sim.mpu.p & 1, sim.mpu.a), (1, 4))
        for key in (KEY_B, 0x5F, 0x03):
            sim, _cart, _text = self.run_page(bytearray(self.fresh), "u4", [key])
            self.assertEqual((sim.mpu.p & 1, sim.mpu.a), (1, 0xFF), key)

    def run_not_here(self, a, keys):
        """The page called as the menu calls it for 7-9: A = $80 + the
        number."""
        sim = Sim(self.image, launcher.FONT_ORG, self.sym)
        sim.attach_cart(bytearray(self.fresh))
        out, ks = bytearray(), list(keys)

        def getin(s):
            if not ks:
                raise AssertionError("the page wants another key; screen:\n" + screen(out))
            s.mpu.a = ks.pop(0)
            s.mpu.p &= ~0x02
        scr = self.scr = Screen(sim.mem)
        sim.traps[0xFFD2] = lambda s: (out.append(s.mpu.a), scr.put(s.mpu.a))
        sim.traps[0xFFF0] = scr.plot
        sim.traps[0xFFE4] = getin
        sim.traps[0xFF9F] = lambda s: None
        sim.mem[0], sim.mem[1] = 0x2F, 0x37
        sim.mpu.a, sim.mpu.x, sim.mpu.y = a, 0x00, 0x03
        sim.call(launcher.PAGE_ORG)
        return sim, screen(out)

    def test_ultima_vii_to_ix_are_not_here(self):
        """7-9, from the menu (A = $87-$89) or on a game's page: the
        game's name, why it is not on the cart, and Back -- which goes back
        as a page's does; the other keys of a page do nothing there."""
        for n, name in ((7, "Ultima VII"), (8, "Ultima VIII"), (9, "Ultima IX")):
            with self.subTest(n=n):
                sim, text = self.run_not_here(0x80 + n, [ord(k) for k in "LRJEIFX"] + [KEY_B])
                self.assertEqual((sim.mpu.p & 1, sim.mpu.a), (1, 0xFF))
                self.assertEqual(text.count("<CLR>"), 1)
                lines = self.scr.lines()
                self.assertEqual(lines[0].rstrip(), " " + name)
                self.assertIn("omitted due to limited", self.scr.text())
                self.assertIn(" B  Back", lines)
                self.assertNotIn("Launch", self.scr.text())
                self.assertEqual((self.scr.scrolls, self.scr.wraps), (0, 0), self.scr.text())
        # 0-6 there are that game's page; 7-9 the next of these
        sim, text = self.run_not_here(0x87, [ord("9"), ord("8"), ord("3")])
        self.assertEqual((sim.mpu.p & 1, sim.mpu.a), (1, 3))
        self.assertEqual(text.count("<CLR>"), 3)
        self.assertEqual(self.scr.lines()[0].rstrip(), " Ultima VIII")
        # from a game's page
        _sim, _cart, text = self.run_page(bytearray(self.fresh), "u4", [ord("7"), 0x03])
        self.assertEqual(self.scr.lines()[0].rstrip(), " Ultima VII")

    def test_the_torch_option_where_there_are_torches(self):
        """U2-U5: "U  Torches used up when lit", toggled by U and poked into
        the options byte at a launch; the other games have no such line."""
        from ultima.launcher import patches
        for g in NAMES:
            with self.subTest(game=g):
                sim, cart, text = self.run_page(bytearray(self.fresh), g, [ord("U"), KEY_L])
                has = g in ("u2", "u3", "u4", "u5")
                self.assertEqual("Torches used up when lit" in text, has)
                if has:
                    self.assertEqual(self.option("Torches used up when lit"), "off")
                    p = sim.mpu.x | sim.mpu.y << 8
                    pokes = {sim.mem[p + 1 + 3 * i] | sim.mem[p + 2 + 3 * i] << 8: sim.mem[p + 3 + 3 * i]
                             for i in range(sim.mem[p])}
                    self.assertTrue(pokes[launcher.opt_addr(g)] & patches.TORCH)

    def test_ultima_iv_export_says_when_saved_in_a_dungeon(self):
        """A game saved in a dungeon (record $1A's $1B = 3, the Remastered's
        Quit there) gets a note before the export: the original would start
        it on the surface.  One saved in Britannia does not."""
        for mode, note in ((1, False), (3, True)):
            with self.subTest(mode=mode):
                flash = bytearray(self.fresh)
                seed_u4(flash, self.s)
                at = regions.save_base("u4") + 4 * regions.ERASE_BLOCK + 0x1B - 0x10
                flash[at] = mode
                sim, cart, text = self.run_page(flash, "u4", [ord("E"), ord("D"), ord("N"), KEY_B])
                self.assertIn("Export: this overwrites", text)
                self.assertEqual("Saved in a dungeon" in text, note)

    def test_ultima_iv_powers_are_a_poke(self):
        """X on U4's page: "Teleport, transport, win: on", and the launch
        pokes the helpers' flag -- the options byte never gets the bit (it
        is JOURNEY's), nor the tile set's."""
        from ultima.launcher import patches
        sim, cart, text = self.run_page(bytearray(self.fresh), "u4", [ord("X"), KEY_L])
        self.assertEqual(self.option("Teleport, transport, win"), "on")
        p = sim.mpu.x | sim.mpu.y << 8
        pokes = {sim.mem[p + 1 + 3 * i] | sim.mem[p + 2 + 3 * i] << 8: sim.mem[p + 3 + 3 * i]
                 for i in range(sim.mem[p])}
        self.assertEqual(pokes.get(0x02A7), 1, "pw_on")
        self.assertFalse(pokes[launcher.opt_addr("u4")] & (patches.POWERS | patches.TILES))

    def test_ultima_iii_trainer_keys_are_a_poke(self):
        """X on U3's page: "Gold's trainer keys: on", and the launch pokes the
        driver's tr_on with $80 -- bit 2 of the options byte is JOURNEY's."""
        from ultima.launcher import patches
        import re
        sym = {m.group(1): int(m.group(2), 16) for m in re.finditer(
            r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path(os.path.join(paths.BUILD, "u3drv.sym")).read_text())}
        sim, cart, text = self.run_page(bytearray(self.fresh), "u3", [ord("X"), KEY_L])
        self.assertEqual(self.option("Gold's trainer keys"), "on")
        p = sim.mpu.x | sim.mpu.y << 8
        pokes = {sim.mem[p + 1 + 3 * i] | sim.mem[p + 2 + 3 * i] << 8: sim.mem[p + 3 + 3 * i]
                 for i in range(sim.mem[p])}
        self.assertEqual(pokes.get(sym["tr_on"]), 0x80, "tr_on")
        self.assertFalse(pokes[launcher.opt_addr("u3")] & patches.POWERS)
        # and off: no poke of it
        sim, cart, text = self.run_page(bytearray(self.fresh), "u3", [KEY_L])
        p = sim.mpu.x | sim.mpu.y << 8
        pokes = {sim.mem[p + 1 + 3 * i] | sim.mem[p + 2 + 3 * i] << 8: sim.mem[p + 3 + 3 * i]
                 for i in range(sim.mem[p])}
        self.assertNotIn(sym["tr_on"], pokes)

    def test_ultima_ii_powers_are_a_poke(self):
        """X on U2's page: "Locate, teleport, vehicle: on" (U1's line), and the launch
        pokes the driver's pw_on with $80; off, no poke of it."""
        from ultima.launcher import patches
        import re
        sym = {m.group(1): int(m.group(2), 16) for m in re.finditer(
            r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path(os.path.join(paths.BUILD, "u2drv.sym")).read_text())}
        for keys, on in (([ord("X"), KEY_L], True), ([KEY_L], False)):
            sim, cart, text = self.run_page(bytearray(self.fresh), "u2", keys)
            if on:
                self.assertEqual(self.option("Locate, teleport, vehicle"), "on")
            p = sim.mpu.x | sim.mpu.y << 8
            pokes = {sim.mem[p + 1 + 3 * i] | sim.mem[p + 2 + 3 * i] << 8: sim.mem[p + 3 + 3 * i]
                     for i in range(sim.mem[p])}
            self.assertEqual(pokes.get(sym["pw_on"]), 0x80 if on else None, "pw_on")
            self.assertFalse(pokes[launcher.opt_addr("u2")] & patches.POWERS)

    def test_ultima_v_powers_are_a_bit(self):
        """X on U5's page: "F7 teleport, B vehicle: on", and the launch puts POWERS into
        U5's options byte (its Journey Onward is a poke, so the bit is free
        there; the driver's pt_apply then hooks MAIN.OUT); off, it is not."""
        from ultima.launcher import patches
        for keys, on in (([ord("X"), KEY_L], True), ([KEY_L], False)):
            with self.subTest(on=on):
                sim, cart, text = self.run_page(bytearray(self.fresh), "u5", keys)
                self.assertEqual(self.option("F7 teleport, B vehicle"), "on" if on else "off")
                p = sim.mpu.x | sim.mpu.y << 8
                pokes = {sim.mem[p + 1 + 3 * i] | sim.mem[p + 2 + 3 * i] << 8: sim.mem[p + 3 + 3 * i]
                         for i in range(sim.mem[p])}
                self.assertEqual(bool(pokes[launcher.opt_addr("u5")] & patches.POWERS), on)

    def test_ultima_ii_counts_stop_at_99_is_a_poke(self):
        """V on U2's page: "Counts wrap past 99/9999: off", and the launch
        pokes the driver's cl_on with $80, never the options byte's bit 7;
        off, no poke of it.  Bit 7 is U4's balloon too: W does nothing on
        U2's page, V nothing on U4's, where W is still the balloon's."""
        from ultima.launcher import patches
        import re
        sym = {m.group(1): int(m.group(2), 16) for m in re.finditer(
            r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path(os.path.join(paths.BUILD, "u2drv.sym")).read_text())}

        def pokes_of(sim):
            p = sim.mpu.x | sim.mpu.y << 8
            return {sim.mem[p + 1 + 3 * i] | sim.mem[p + 2 + 3 * i] << 8: sim.mem[p + 3 + 3 * i]
                    for i in range(sim.mem[p])}
        for keys, on in (([ord("V"), KEY_L], True), ([KEY_L], False), ([ord("W"), KEY_L], False)):
            with self.subTest(keys=keys):
                sim, cart, text = self.run_page(bytearray(self.fresh), "u2", keys)
                self.assertEqual(self.option("Counts wrap past 99/9999"), "off" if on else "on")
                self.assertNotIn("Balloon", self.scr.text())
                pokes = pokes_of(sim)
                self.assertEqual(pokes.get(sym["cl_on"]), 0x80 if on else None, "cl_on")
                self.assertFalse(pokes[launcher.opt_addr("u2")] & patches.CLAMP)
        for key, balloon in (("W", "off"), ("V", "on")):
            with self.subTest(game="u4", key=key):
                sim, cart, text = self.run_page(bytearray(self.fresh), "u4", [ord(key), KEY_L])
                self.assertEqual(self.option("Balloon drifts with wind"), balloon)
                self.assertNotIn("Counts wrap", self.scr.text())
                self.assertEqual(bool(pokes_of(sim)[launcher.opt_addr("u4")] & patches.BALLOON),
                                 balloon == "off")

    def test_ultima_i_options(self):
        """U1's page: S ("NPCs can steal items: off") is bit 7 of the
        driver's options byte, X ("Locate, teleport, vehicle: on") a poke of
        its pw_on; V and W, bit 7's keys on U2's and U4's pages, do nothing
        here, and S does nothing on theirs."""
        from ultima.launcher import patches
        import re
        sym = {m.group(1): int(m.group(2), 16) for m in re.finditer(
            r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path(os.path.join(paths.BUILD, "u1drv.sym")).read_text())}

        def pokes_of(sim):
            p = sim.mpu.x | sim.mpu.y << 8
            return {sim.mem[p + 1 + 3 * i] | sim.mem[p + 2 + 3 * i] << 8: sim.mem[p + 3 + 3 * i]
                    for i in range(sim.mem[p])}
        for keys, steal, powers in (([KEY_L], True, False), ([ord("S"), KEY_L], False, False),
                                    ([ord("X"), KEY_L], True, True),
                                    ([ord("V"), ord("W"), KEY_L], True, False)):
            with self.subTest(keys=keys):
                sim, cart, text = self.run_page(bytearray(self.fresh), "u1", keys)
                self.assertEqual(self.option("NPCs can steal items"), "on" if steal else "off")
                self.assertEqual(self.option("Locate, teleport, vehicle"), "on" if powers else "off")
                pokes = pokes_of(sim)
                self.assertEqual(bool(pokes[launcher.opt_addr("u1")] & patches.STEAL), not steal)
                self.assertFalse(pokes[launcher.opt_addr("u1")] & patches.POWERS)
                self.assertEqual(pokes.get(sym["pw_on"]), 0x80 if powers else None, "pw_on")
        for g, line in (("u2", "Counts wrap past 99/9999"), ("u4", "Balloon drifts with wind")):
            with self.subTest(game=g):
                sim, cart, text = self.run_page(bytearray(self.fresh), g, [ord("S"), KEY_L])
                self.assertEqual(self.option(line), "on")
                self.assertNotIn("steal", self.scr.text())

    def test_new_options_reach_the_options_byte(self):
        """U5's M (spells, keys, gems) and U3's A ("AVOID?") are bits of the
        driver's options byte, poked at the launch."""
        from ultima.launcher import patches
        for g, key, bit, line in (("u5", "M", patches.ITEMS, "Magic and items used up"),
                                  ("u3", "A", patches.AVOID, "Attacks can't be avoided")):
            with self.subTest(game=g):
                sim, cart, text = self.run_page(bytearray(self.fresh), g, [ord(key), KEY_L])
                self.assertEqual(self.option(line), "off")
                p = sim.mpu.x | sim.mpu.y << 8
                pokes = {sim.mem[p + 1 + 3 * i] | sim.mem[p + 2 + 3 * i] << 8: sim.mem[p + 3 + 3 * i]
                         for i in range(sim.mem[p])}
                self.assertTrue(pokes[launcher.opt_addr(g)] & bit)

    LABELS = ("Food used while walking", "Turn passes when idle", "Torches used up when lit",
              "Magic and items used up", "Attacks can't be avoided", "Balloon drifts with wind",
              "Counts wrap past 99/9999", "NPCs can steal items",
              "Gold's trainer keys", "Teleport, transport, win",
              "Locate, teleport, vehicle", "F7 teleport, B vehicle",
              "Gold spent when buying", "Attacks can miss", "Monsters can hurt you",
              "Graphics")

    def test_every_page_fits_the_screen(self):
        """The longest page each game draws (Ultima IV: eight in the party)
        stays on the 25 rows with nothing scrolled off or wrapped, and so do
        its questions (Reset, Export), which go in
        the rows from the blank one before the commands."""
        for g in NAMES:
            seed = seed_u4_full if g == "u4" else SEEDS.get(g, lambda _f, _s: None)
            asks = [[KEY_R, ord("N")], [ord("E"), 0x03]] if g in SAVING else []
            for keys in [[]] + asks:
                with self.subTest(game=g, keys=keys):
                    flash = bytearray(self.fresh)
                    want = seed(flash, self.s)
                    _sim, _cart, text = self.run_page(flash, g, keys + [KEY_B])
                    self.assertEqual((self.scr.scrolls, self.scr.wraps), (0, 0), self.scr.text())
                    self.assertLessEqual(self.scr.row, 23)
                    if not keys and g in SAVING:
                        self.assertEqual(self.saved(text), want)

    def test_the_saved_game_s_numbers_line_up(self):
        """Hit points right-aligned, so Food (U1, U2) and the slash before
        the maximum (U3-U6) are in one column whatever the numbers' lengths;
        the name on top at the keys' column."""
        for g in SAVING:
            with self.subTest(game=g):
                flash = bytearray(self.fresh)
                SEEDS[g](flash, self.s)
                self.run_page(flash, g, [KEY_B])
                lines = self.scr.lines()
                self.assertRegex(lines[0], r"^ \S", "the name not at the keys' column")
                self.assertTrue(any(line.startswith(" L  Launch") for line in lines), lines)
                rows = [line for line in lines if " HP " in line]
                self.assertTrue(rows)
                mark = "Food" if g in ("u1", "u2") else "/"
                self.assertEqual(len({line.index(mark) for line in rows}), 1, rows)
                self.assertEqual(len({line.index("HP") for line in rows}), 1, rows)

    def test_options_line_up(self):
        """Every option's value in one column, with a space before it."""
        for g in NAMES:
            with self.subTest(game=g):
                self.run_page(bytearray(self.fresh), g, [KEY_B])
                for label in self.LABELS:
                    if label + ":" in self.scr.text():
                        self.assertIn(self.option(label).rstrip(), ("on", "off", "original"))

    def test_a_toggle_rewrites_only_its_value(self):
        """An option key does not redraw the page: one clear, and the value
        changed in place, the rest of the screen as it was."""
        _sim, _cart, text = self.run_page(bytearray(self.fresh), "u4", [KEY_B])
        before = self.scr.lines()
        for key, label, value in (("F", "Food used while walking", "off"), ("X", "Teleport, transport, win", "on"),
                                  ("G", "Graphics", "Remastered")):
            with self.subTest(key=key):
                _sim, _cart, text = self.run_page(bytearray(self.fresh), "u4", [ord(key), KEY_B])
                self.assertEqual(text.count("<CLR>"), 1)
                self.assertEqual(self.option(label), value)
                changed = [i for i, (a, b) in enumerate(zip(before, self.scr.lines())) if a != b]
                self.assertEqual(len(changed), 1, changed)

    def test_a_fresh_cart_has_no_saved_games(self):
        for g in SAVING:
            with self.subTest(game=g):
                sim, _cart, text = self.run_page(bytearray(self.fresh), g, [KEY_B])
                self.assertEqual(self.saved(text), ["No saved game"])
                self.assertEqual(sim.mpu.p & 1, 1, "B is not back to the list")

    def test_the_saved_game_is_shown(self):
        for g in SAVING:
            with self.subTest(game=g):
                flash = bytearray(self.fresh)
                want = SEEDS[g](flash, self.s)
                _sim, _cart, text = self.run_page(flash, g, [KEY_B])
                self.assertEqual(self.saved(text), want)

    def test_reset_writes_back_what_a_fresh_cart_holds(self):
        """... erasing the whole save region (U6: both log halves) and
        leaving the launcher's settings alone."""
        for g in SAVING:
            with self.subTest(game=g):
                flash = bytearray(self.fresh)
                SEEDS[g](flash, self.s)
                settings = b"UCFG\x03\x03\x03\x03\x03\x03"
                flash[regions.SETTINGS:regions.SETTINGS + len(settings)] = settings
                lo, hi = regions.save_region(g)
                self.assertNotEqual(flash[lo:hi], self.fresh[lo:hi])
                _sim, cart, text = self.run_page(flash, g, [KEY_R, KEY_Y, KEY_B])
                self.assertEqual(cart.flash[lo:hi], self.fresh[lo:hi])
                self.assertEqual(cart.flash[regions.SETTINGS:regions.SETTINGS + len(settings)],
                                 settings)
                self.assertEqual(self.saved(text), ["No saved game"])
                erases = {c[1] for c in cart.log if c[0] == "erase"}
                self.assertEqual(erases, set(range(lo, hi, regions.ERASE_BLOCK)))

    def test_reset_asks_first(self):
        flash = bytearray(self.fresh)
        SEEDS["u2"](flash, self.s)
        before = bytes(flash)
        _sim, cart, _text = self.run_page(flash, "u2", [KEY_R, ord("N"), KEY_B])
        self.assertEqual(bytes(cart.flash), before)
        self.assertFalse([c for c in cart.log if c[0] in ("erase", "write")])

    def test_launch_returns_no_pokes_without_options(self):
        """With every option as it was, a launch pokes only the driver's
        options byte, where there is one (Akalabeth's options are all
        pokes of its own, none when they are off)."""
        for g in NAMES:
            with self.subTest(game=g):
                sim, _cart, _text = self.run_page(bytearray(self.fresh), g, [KEY_L])
                self.assertEqual(sim.mpu.p & 1, 0)
                pokes = sim.mpu.x | sim.mpu.y << 8
                self.assertEqual(pokes, self.sym["pokes"])
                self.assertEqual(sim.mem[pokes], 1 if launcher.opt_addr(g) else 0)

    def test_an_option_toggles_persists_and_is_poked(self):
        """F and P flip their bit in the settings page, which is written to
        flash at once (it is outside every save region), and a launch pokes
        the game's options byte with it.  A game without the option ignores
        the key.  (Akalabeth has no options byte: test_akalabeth_s_page.)"""
        for g in NAMES:
            if not launcher.opt_addr(g):
                continue
            caps = launcher_caps(g)
            with self.subTest(game=g):
                flash = bytearray(self.fresh)
                sim, cart, text = self.run_page(flash, g, [ord("F"), ord("P"), KEY_L])
                want = caps & 3
                page = cart.flash[regions.SETTINGS:regions.SETTINGS + 256]
                if want:
                    self.assertEqual(page[:4], b"UCFG")
                    self.assertEqual(page[4 + regions.DESC_INDEX[g]], want)
                    self.assertEqual([page[4 + i] for i in range(len(NAMES))
                                      if i != regions.DESC_INDEX[g]], [0] * (len(NAMES) - 1))
                    p = sim.mpu.x | sim.mpu.y << 8
                    self.assertEqual(sim.mem[p], 1)
                    opt = launcher.opt_addr(g)
                    self.assertEqual((sim.mem[p + 1] | sim.mem[p + 2] << 8, sim.mem[p + 3]),
                                     (opt, want))
                    self.assertIn("off", self.scr.text())
                else:
                    self.assertEqual(page, self.fresh[regions.SETTINGS:regions.SETTINGS + 256])
                # the next time the page runs, it remembers
                if want:
                    _sim, _cart, text = self.run_page(bytearray(cart.flash), g, [KEY_B])
                    if caps & 1:
                        self.assertEqual(self.option("Food used while walking"), "off")
                    if caps & 2:
                        self.assertEqual(self.option("Turn passes when idle"), "off")

    def test_akalabeth_s_page(self):
        """No saved game, so neither its line nor R, E, I, J; the trainer's
        four flags as options, on (the game as it was) until toggled; a
        launch pokes 100 into the flag of each option turned off, into
        init_u0.s's segment, and the settings keep them."""
        from ultima.games.u0 import build as u0
        _sim, _cart, text = self.run_page(bytearray(self.fresh), "u0", [KEY_B])
        lines = [line.rstrip() for line in self.scr.lines() if line.strip()]
        self.assertEqual(lines, [" ultima x",                    # (run_page's name)
                                 " F  Food used while walking:   on",
                                 " G  Gold spent when buying:    on",
                                 " A  Attacks can miss:          on",
                                 " H  Monsters can hurt you:     on",
                                 " L  Launch the game",
                                 " B  Back"])
        self.assertNotIn("saved game", text)
        flash = bytearray(self.fresh)
        sim, cart, text = self.run_page(flash, "u0", [ord(k) for k in "RIEJTCXPUMW"] + [KEY_L])
        self.assertEqual(text.count("<CLR>"), 1, "a key that is not Akalabeth's did something")
        self.assertEqual((sim.mpu.p & 1, sim.mem[sim.mpu.x | sim.mpu.y << 8]), (0, 0))
        self.assertFalse([c for c in cart.log if c[0] in ("erase", "write")])
        flags = {"F": 0x03FF, "G": 0x03FE, "H": 0x03FD, "A": 0x03FC}
        self.assertEqual(flags, {k: u0.TRAINER[b] for k, b in
                                 (("F", 0x01), ("G", 0x20), ("H", 0x80), ("A", 0x40))})
        for keys in ("F", "GH", "FGAH"):
            with self.subTest(keys=keys):
                sim, cart, _text = self.run_page(bytearray(self.fresh), "u0",
                                                 [ord(k) for k in keys] + [KEY_L])
                p = sim.mpu.x | sim.mpu.y << 8
                got = {sim.mem[p + 1 + 3 * i] | sim.mem[p + 2 + 3 * i] << 8: sim.mem[p + 3 + 3 * i]
                       for i in range(sim.mem[p])}
                self.assertEqual(got, {flags[k]: 100 for k in keys})
                _sim, _cart, _text = self.run_page(bytearray(cart.flash), "u0", [KEY_B])
                for k, label in (("F", "Food used while walking"), ("G", "Gold spent when buying"),
                                 ("A", "Attacks can miss"), ("H", "Monsters can hurt you")):
                    self.assertEqual(self.option(label).rstrip(), "off" if k in keys else "on")

    def test_journey_onward_only_with_a_character(self):
        sim, _cart, text = self.run_page(bytearray(self.fresh), "u5", [KEY_J, KEY_B])
        self.assertNotIn("Journey", text)
        self.assertEqual(sim.mpu.p & 1, 1, "J launched with no character")
        flash = bytearray(self.fresh)
        seed_u5(flash, self.s)
        sim, _cart, text = self.run_page(flash, "u5", [KEY_J])
        self.assertIn(" J  Journey onward", text)
        self.assertEqual(sim.mpu.p & 1, 0)
        p = self.sym["pokes"]
        n = sim.mem[p]
        pokes = [(sim.mem[p + 1 + 3 * i] | sim.mem[p + 2 + 3 * i] << 8, sim.mem[p + 3 + 3 * i])
                 for i in range(n)]
        self.assertEqual(pokes[-2:], [(0x2109, 0xA9), (0x210A, 0x22)])  # LDA #'J'


    def test_every_game_s_journey_onward(self):
        """Every game with a way straight in: J is offered only with a saved
        game, and pokes exactly what its build asked for -- plus, where the
        driver patches as it loads, the JOURNEY bit in the options byte."""
        text = Path(os.path.join(paths.BUILD, "page_data.s")).read_text()
        row = lambda n: [int(v, 16) for v in re.search(rf"^{n}:\s+!byte (.*)$", text, re.M)
                         .group(1).replace("$", "").split(", ")]
        jo_or = row("jo_or")
        for g in NAMES:
            m = re.search(rf"^jo_{g}: !byte (.*)$", text, re.M)
            if not m:
                continue
            with self.subTest(game=g):
                table = [int(v, 16) for v in m.group(1).replace("$", "").split(", ")]
                want = [(table[1 + 3 * i] | table[2 + 3 * i] << 8, table[3 + 3 * i])
                        for i in range(table[0])]
                sim, _cart, text_ = self.run_page(bytearray(self.fresh), g, [KEY_J, KEY_B])
                self.assertNotIn("Journey", text_, "offered with no saved game")
                flash = bytearray(self.fresh)
                SEEDS[g](flash, self.s)
                sim, _cart, text_ = self.run_page(flash, g, [KEY_J])
                self.assertIn(" J  Journey onward", text_)
                self.assertEqual(sim.mpu.p & 1, 0)
                p = self.sym["pokes"]
                got = [(sim.mem[p + 1 + 3 * i] | sim.mem[p + 2 + 3 * i] << 8, sim.mem[p + 3 + 3 * i])
                       for i in range(sim.mem[p])]
                opt = launcher.opt_addr(g) if launcher_caps(g) else None
                if opt:
                    self.assertEqual(got[0], (opt, jo_or[regions.DESC_INDEX[g]]))
                    got = got[1:]
                self.assertEqual(got, want)


def launcher_caps(game):
    text = Path(os.path.join(paths.BUILD, "page_data.s")).read_text()
    caps = [int(v, 16) for v in re.search(r"^caps:\s+!byte (.*)$", text, re.M)
            .group(1).replace("$", "").split(", ")]
    return caps[regions.DESC_INDEX[game]]


if __name__ == "__main__":
    unittest.main()
