"""The launcher's game options: each driver's pt_apply and patch table
(asm/patch.s, patches.py), run on the host against the game's own code.

For each game the unit that carries a patch is put where the game loads it,
the options byte is set as the menu's poke would set it, and the driver's
real pt_apply runs: the bytes change exactly when the option is on, a second
call changes nothing, and other code at the same address is left alone.

Skipped without py65 (the repository's .venv has it).
"""
import importlib.util
import os
import unittest
from pathlib import Path

try:
    from ultima.sim.sim6502 import Sim
except ImportError:
    Sim = None

from ultima.disks.d64 import D64
from ultima.launcher import patches
from ultima import paths

BUILD = paths.BUILD


def load(game):
    spec = importlib.util.find_spec(f"ultima.games.{game}.build")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def symbols(path):
    import re
    return {m.group(1): int(m.group(2), 16) for m in
            re.finditer(r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path(path).read_text())}


class OptionsCase(unittest.TestCase):
    """A driver image, its symbols, and the units its patches are for."""

    def apply(self, sim, opts):
        sim.mem[self.sym["pt_opts"]] = opts
        sim.call(self.sym["pt_apply"])

    def check_game(self, make_sim, patch_list, units, foreign):
        """make_sim(): a fresh Sim with the driver in place.  units: {what:
        (load address, bytes)} -- the code each patch is for; units that
        share a load address are tried one at a time.  foreign: (load
        address, bytes) of something else that loads over them."""
        distinct = {(a, d) for a, d in units.values()}
        for addr, data in sorted(distinct):
            here = [p for p in patch_list if units[p.what] == (addr, data)]
            # food, pass, journey, torch, items, avoid, balloon: alone and together
            for opts in (0, 1, 2, 3, 4, 7, 0x10, 0x11, 0x13, 0x17, 0x20, 0x40, 0x80,
                         0x60, 0xE0, 0xF7):
                with self.subTest(unit=f"${addr:04x}", opts=opts):
                    sim = make_sim()
                    sim.mem[addr:addr + len(data)] = list(data)
                    before = bytes(sim.mem)
                    self.apply(sim, opts)
                    after = bytes(sim.mem)
                    self.apply(sim, opts)
                    again = bytes(sim.mem)
                    self.assertEqual({i for i in range(0x10000)
                                      if again[i] != after[i] and not self.scratch(i)}, set(),
                                     "a second call changed something")
                    want = set()
                    for p in here:
                        self.assertEqual(before[p.addr:p.addr + len(p.orig)], p.orig,
                                         f"{p.what}: not in the unit")
                        if opts & p.option:
                            self.assertEqual(after[p.addr:p.addr + len(p.new)], p.new, p.what)
                            want |= {p.addr + i for i in range(len(p.new))
                                     if p.new[i] != p.orig[i]}
                    changed = {i for i in range(0x10000)
                               if before[i] != after[i] and not self.scratch(i)}
                    changed.discard(self.sym["pt_opts"])
                    self.assertEqual(changed, want)
        # something else at the same place is left alone
        sim = make_sim()
        addr, data = foreign
        sim.mem[addr:addr + len(data)] = list(data)
        before = bytes(sim.mem[addr:addr + len(data)])
        self.apply(sim, 0xFF)
        self.assertEqual(bytes(sim.mem[addr:addr + len(data)]), before)

    def scratch(self, a):
        """The applier's own variables and self-modified operands, and the
        stack (the call's return address)."""
        return 0x100 <= a < 0x200 or any(n in self.sym and self.sym[n] <= a <= self.sym[n] + 2
                                         for n in ("pa_on", "pa_n", "pa_x", "pa_rd", "pa_wr", "pa_tb"))


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestU4Options(OptionsCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load("u4")
        d = D64(paths.disk("u4a"))
        cls.disk = bytes(d.data)
        cls.mod.resolve_options(cls.disk)
        cls.mod.build_driver()
        cls.sym = symbols(os.path.join(BUILD, "u4drv.sym"))
        cls.blob = Path(os.path.join(BUILD, "u4drv.bin")).read_bytes()

    def block(self, b):
        return self.disk[b * 256:(b + 1) * 256]

    def test_the_patches_land_in_chunk_5b(self):
        # each patch's block (chunk $5B's, or the title's, block 221 at $6000)
        # loaded at its own page
        addr = {p.what: p.addr for p in self.mod.OPTION_PATCHES}
        units = {what: (addr[what] & 0xFF00, self.block(b))
                 for what, b in self.mod.OPTION_BLOCKS.items()}
        self.check_game(lambda: Sim(self.blob, 0xA45E, self.sym),
                        self.mod.OPTION_PATCHES, units,
                        (0x6200, self.block(36)))

    def test_the_options_byte_is_what_the_page_pokes(self):
        p = self.mod.parts()
        self.assertEqual(p["options"]["addr"], self.sym["pt_opts"])
        self.assertEqual(p["options"]["caps"], patches.FOOD | patches.PASS | patches.TORCH | patches.TILES
                         | patches.ITEMS | patches.AVOID | patches.BALLOON | patches.POWERS)


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestU3Options(OptionsCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load("u3")
        cls.p = cls.mod.parts()
        cls.sym = symbols(os.path.join(BUILD, "u3drv.sym"))
        cls.blob = Path(os.path.join(BUILD, "u3drv.bin")).read_bytes()

    def test_the_patches_land_in_ult3(self):
        ult3 = self.p["unit_data"]["ULT3"]
        boot = self.p["unit_data"]["BOOT"]
        units = {p.what: ((0x1000, boot) if p.option == patches.JOURNEY else (0x5000, ult3))
                 for p in self.mod.OPTION_PATCHES}
        self.check_game(lambda: Sim(self.blob, self.mod.DRIVER_ADDR, self.sym),
                        self.mod.OPTION_PATCHES, units,
                        (0x5000, self.p["unit_data"]["EXOD"][:0x4000]))

    def test_the_options_byte_is_what_the_page_pokes(self):
        self.assertEqual(self.p["options"]["addr"], self.sym["pt_opts"])
        self.assertEqual(self.p["options"]["caps"],
                         patches.FOOD | patches.PASS | patches.TORCH | patches.ITEMS | patches.POWERS
                         | patches.AVOID)
        # Gold's trainer keys are a poke of the driver's flag, not the byte's bit
        self.assertEqual(self.p["options"]["pokes"], {patches.POWERS: [(self.sym["tr_on"], 0x80)]})

    def test_journey_onward_is_for_one_launch(self):
        """Once BOOT's menu has the patch the bit goes, so BOOT loaded again
        later in the session (it is) shows its menu as it should."""
        sim = Sim(self.blob, self.mod.DRIVER_ADDR, self.sym)
        boot = self.p["unit_data"]["BOOT"]
        sim.mem[0x1000:0x1000 + len(boot)] = list(boot)
        sim.mem[self.sym["pt_opts"]] = patches.JOURNEY | patches.FOOD
        sim.call(self.sym["pt_apply"])
        sim.call(self.sym["u3_opt_once"])
        self.assertEqual(bytes(sim.mem[0x1278:0x127B]), bytes([0x4C, 0xA9, 0x12]))
        self.assertEqual(sim.mem[self.sym["pt_opts"]], patches.FOOD)
        sim.mem[0x1000:0x1000 + len(boot)] = list(boot)          # BOOT again
        sim.call(self.sym["pt_apply"])
        self.assertEqual(bytes(sim.mem[0x1278:0x127B]), bytes([0x20, 0x11, 0x47]))


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestU2Options(OptionsCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load("u2")
        cls.p = cls.mod.parts()
        cls.sym = symbols(os.path.join(BUILD, "u2drv.sym"))
        cls.blob = Path(os.path.join(BUILD, "u2drv.bin")).read_bytes()

    def test_the_patches_land_in_ultima(self):
        units = {p.what: (0x5000, self.p["ultima"]) for p in self.mod.OPTION_PATCHES}
        self.check_game(lambda: Sim(self.blob, 0xB100, self.sym),
                        self.mod.OPTION_PATCHES, units,
                        (0x5000, bytes(range(256)) * 64))

    def test_intro_goes_to_ultima_through_the_options(self):
        """INTRO's JMP $5000 is repointed at u2_go, which applies the
        options and then does the JMP $5000."""
        intro = self.p["intro"]
        self.assertIn(intro, [b for _o, b in self.p["blobs"]], "not what is in flash")
        go = self.sym["u2_go"]
        self.assertEqual(intro[self.mod.INTRO_GO - 0xC000:][:3], bytes([0x4C, go & 0xFF, go >> 8]))
        sim = Sim(self.blob, 0xB100, self.sym)
        self.assertEqual(bytes(sim.mem[go:go + 6]),
                         bytes([0x20, self.sym["pt_apply"] & 0xFF, self.sym["pt_apply"] >> 8,
                                0x4C, 0x00, 0x50]))

    def test_the_options_byte_is_what_the_page_pokes(self):
        self.assertEqual(self.p["options"]["addr"], self.sym["pt_opts"])
        self.assertEqual(self.p["options"]["caps"],
                         patches.FOOD | patches.PASS | patches.TORCH | patches.POWERS | patches.CLAMP)
        # F7 and B, and counts that stop at 99, are pokes of the driver's
        # flags, not the byte's bits
        self.assertEqual(self.p["options"]["pokes"], {patches.POWERS: [(self.sym["pw_on"], 0x80)],
                                                      patches.CLAMP: [(self.sym["cl_on"], 0x80)]})


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestU1Options(OptionsCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load("u1")
        cls.p = cls.mod.parts()
        cls.sym = symbols(os.path.join(BUILD, "u1drv.sym"))
        cls.blob = Path(os.path.join(BUILD, "u1drv.bin")).read_bytes()

    def test_the_patches_land_in_mi_and_the_overlays(self):
        loaded = {n: (a, d) for n, a, d in self.p["loaded"]}
        units = {p.what: loaded[next(iter(self.mod.OPTION_UNITS[p.what]))]
                 for p in self.mod.OPTION_PATCHES}
        self.check_game(lambda: Sim(self.blob, 0xC000, self.sym),
                        self.mod.OPTION_PATCHES, units, loaded["GE"])

    def test_every_load_goes_through_the_options(self):
        """u1_load's two exits (crunched and raw) both end in u1_done, which
        applies the options (here DN's PASS) and puts $01 back."""
        sim = Sim(self.blob, 0xC000, self.sym)
        done = self.sym["u1_done"]
        jmp = bytes([0x4C, done & 0xFF, done >> 8])
        body = bytes(sim.mem[self.sym["u1_load"]:self.sym["u1_err"]])
        self.assertEqual(body.count(jmp), 2)
        dn = next(d for n, a, d in self.p["loaded"] if n == "DN")
        sim.mem[0x8C9E:0x8C9E + len(dn)] = list(dn)
        sim.mem[0x01] = 0x37
        sim.mem[self.sym["pt_opts"]] = patches.PASS
        sim.call(done)              # (py65 has no banking: this shows the
                                    # patch lands and $01 comes back)
        self.assertEqual(sim.mem[0x01], 0x37)
        self.assertEqual(bytes(sim.mem[0x912C + 2:0x912C + 5]), bytes.fromhex("eaf0f8"))

    def test_the_options_byte_is_what_the_page_pokes(self):
        self.assertEqual(self.p["options"]["addr"], self.sym["pt_opts"])
        self.assertEqual(self.p["options"]["caps"],
                         patches.FOOD | patches.PASS | patches.STEAL | patches.POWERS)
        # F7 and B are a poke of the driver's flag, not the byte's bit
        self.assertEqual(self.p["options"]["pokes"], {patches.POWERS: [(self.sym["pw_on"], 0x80)]})


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestU5Options(OptionsCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load("u5")
        cls.p = cls.mod.parts()
        cls.sym = symbols(os.path.join(BUILD, "u5drv.sym"))
        cls.blob = Path(os.path.join(BUILD, "u5drv.bin")).read_bytes()
        d = D64(paths.disk("u5-1a"))
        raw = d.file("MAIN.SUBS")[0]
        cls.subs = (raw[0] | raw[1] << 8, bytes(raw[2:]))
        cls.origin = cls.mod.HOLES[0][0]    # the blob starts at the lowest hole

    def make_sim(self):
        """The driver with its table in a cart (PT_STREAM): the flash as
        built, pt_where filled in as build.py fills it."""
        from ultima.flash.layout import image_from
        from ultima.flash import regions
        sim = Sim(self.blob, self.origin, self.sym)
        sim.attach_cart(image_from(self.p["blobs"], regions.FLASH_SIZE))
        at, n = self.p["pt_at"], len(self.p["pt_table"])
        w = self.sym["pt_where"]
        sim.mem[w:w + 5] = [at & 0xFF, (at >> 8) & 0xFF, at >> 16, n & 0xFF, n >> 8]
        return sim

    def scratch(self, a):
        """The streamed applier also runs tclib: its variables and patched
        operands (in the driver and the holes), zero page, the stack."""
        return a < 0x200 or 0x7700 <= a < 0x7B00 or 0x6C49 <= a < 0x6F4D

    def body(self, disk, name):
        tag = {t: n for n, t in self.mod.TAGS.items()}[disk]
        key = next(k for k in self.p["bodies"] if k[0] == tag and k[1].upper() == name)
        return self.p["loads"][key], bytes(self.p["bodies"][key])

    def test_the_patches_land(self):
        """Food in MAIN.SUBS; the five torch sites in their files; and the
        table the driver streams is patches.py's."""
        self.assertEqual(self.p["pt_table"], patches.table(self.mod.OPTION_PATCHES))
        units = {"food": self.subs}
        for where, _addr, name in self.mod.TORCH_SITES:
            units[f"torch: {name} {where}"] = self.body("3A" if where == "3A-4B" else where, name)
        first = lambda where: self.mod._site_disks(where)[0]
        for where, addr, name in self.mod.KEY_SITES:
            units[f"items: key {name} {addr:04x}"] = self.body(first(where), name)
        for where, _addr, name in self.mod.GEM_SITES:
            units[f"items: gem {name} {where}"] = self.body(first(where), name)
        for where, _mix, _cost, name in self.mod.CAST_SITES:
            for what in ("mixture", "MP"):
                units[f"items: {what} {name}"] = self.body(first(where), name)
        for n in self.mod.TELE:
            for what in ("F7", "B"):
                units[f"powers: {what} MAIN.OUT {self.mod.TAGS[n]}"] = self.body(self.mod.TAGS[n], "MAIN.OUT")
        self.assertEqual(set(units), {p.what for p in self.mod.OPTION_PATCHES})
        self.check_game(self.make_sim, self.mod.OPTION_PATCHES, units,
                        (0x4C00, bytes(range(256)) * 32))

    def loaded(self, disk, name, opts):
        load, body = self.body(disk, name)
        sim = self.make_sim()
        sim.mem[load:load + len(body)] = list(body)
        sim.mem[self.sym["pt_opts"]] = opts
        sim.call(self.sym["pt_apply"])
        return sim

    @staticmethod
    def stop_at(sim, *addrs):
        """Run until one of addrs is reached (by a jump or branch, the
        caller's frame on the stack): that one is returned."""
        seen = []
        for a in addrs:
            sim.traps[a] = lambda s, a=a: seen.append(a)
        return seen

    def test_a_key_does_not_break_nor_a_gem_get_used(self):
        """Jimmy's "Key broke!" (S, the chests) and View (MAIN.OUT on 2A),
        run: with the option the count stays."""
        for opts, keys, gems in ((0, 0x02, 0x06), (patches.ITEMS, 0x03, 0x07)):
            sim = self.loaded("2A", "S", opts)
            sim.mem[0x1184] = 0x03
            sim.call(0xAF98)                        # SED ... STA $1184 / CLD / RTS
            self.assertEqual(sim.mem[0x1184], keys)
            sim = self.loaded("2A", "MAIN.OUT", opts)
            sim.mem[0x1185] = 0x07
            self.stop_at(sim, 0x90BD)               # after the CLD
            sim.call(0x9097)                        # View's LDA $1185 / BNE
            self.assertEqual(sim.mem[0x1185], gems)

    def test_a_spell_needs_no_mixture_nor_mp(self):
        """Cast (C and OC), from the mixture's check: the original wants a
        mixture and the MP and uses both up; with the option neither, and the
        level check still applies."""
        for disk, name, delta in (("1B", "C", 0), ("2B", "OC", 4)):
            mix, cost_at = 0xA7AC + delta, 0xA7E6 + delta
            char, circle = 0xA892 + delta, 0xA893 + delta
            none, low, failed, cast = (a + delta for a in (0xA7B1, 0xA7EA, 0xA7FC, 0xA826))
            for opts, mixture, mp, level, want, mixture_after, mp_after in (
                    (0, 0x00, 0x05, 1, none, 0x00, 0x05),
                    (0, 0x03, 0x01, 1, low, 0x02, 0x01),
                    (0, 0x03, 0x05, 1, cast, 0x02, 0x03),
                    (0, 0x03, 0x05, 0, failed, 0x02, 0x03),
                    (patches.ITEMS, 0x00, 0x00, 1, cast, 0x00, 0x00),
                    (patches.ITEMS, 0x03, 0x05, 1, cast, 0x03, 0x05),
                    (patches.ITEMS, 0x00, 0x00, 0, failed, 0x00, 0x00)):
                with self.subTest(name=name, opts=opts, mixture=mixture, mp=mp, level=level):
                    sim = self.loaded(disk, name, opts)
                    seen = self.stop_at(sim, none, low, failed, cast)
                    sim.traps[0x4C54] = lambda s: setattr(s.mpu, "a", 0x02)     # the cost
                    sim.mem[0x1240] = mixture               # spell 0, circle 1
                    sim.mem[char] = 0x00                    # the caster's record
                    sim.mem[0x1087] = mp
                    sim.mem[0x108E] = level
                    sim.mpu.y = 0
                    sim.call(mix)
                    self.assertEqual(seen, [want])
                    self.assertEqual((sim.mem[0x1240], sim.mem[0x1087]), (mixture_after, mp_after))
                    self.assertEqual(sim.mem[circle], 0 if want == none else 1)
                    self.assertEqual(sim.mem[cost_at], 0x02 if not opts and want != none else 0x00)

    def test_a_torch_lights_but_is_not_used_up(self):
        """MAIN.DNG's torch, run: with the option, $1186 stays."""
        load, body = self.body("1B", "MAIN.DNG")
        for opts, left in ((0x00, 0x04), (patches.TORCH, 0x05)):
            sim = self.make_sim()
            sim.mem[load:load + len(body)] = list(body)
            sim.mem[self.sym["pt_opts"]] = opts
            sim.call(self.sym["pt_apply"])
            sim.mem[0x1186] = 0x05
            # sed / sec / sbc #$01 / sta-or-bit $1186 / cld, then stop
            at = 0x8B53 - 4
            self.assertEqual(bytes(sim.mem[at:at + 8]),
                             bytes.fromhex("f838e901") + bytes([0x2C if opts else 0x8D]) + b"\x86\x11\xd8")
            sim.mem[at + 8] = 0x60                  # RTS instead of its JMP
            sim.mpu.a = 0x05
            sim.call(at)
            self.assertEqual(sim.mem[0x1186], left)

    def test_every_load_goes_through_the_options(self):
        sim = Sim(self.blob, self.origin, self.sym)
        a = self.sym["pt_apply"]
        body = bytes(sim.mem[self.sym["u5_load"]:self.sym["u5_ld_done"]])
        self.assertIn(bytes([0x20, a & 0xFF, a >> 8]), body)

    def test_the_options_byte_is_what_the_page_pokes(self):
        self.assertEqual(self.p["options"]["addr"], self.sym["pt_opts"])
        self.assertEqual(self.p["options"]["caps"],
                         patches.FOOD | patches.TORCH | patches.ITEMS | patches.POWERS)

    def powers(self, disk, opts, site, a, key, typed, shape=0x1C):
        """MAIN.OUT from one of the hooks ("hook": the answer to an unknown
        key, $8275, 2B $826B; "board": Board's "What?", $86E5, 2B $86DB)
        with A = `a` (Board's object under the party), the raw key in $82D6
        ($82CC), the party's shape `shape` and `typed` coming from $4C15:
        what was printed, where it ended ("turn" or "loop"), and the state
        after, as a dict."""
        n = {t: k for k, t in self.mod.TAGS.items()}[disk]
        t = self.mod.TELE[n]
        # the defines as build.py takes them, from the files before the append
        d = self.mod.tele_sites({
            (k, "MAIN.OUT"): [0x8000, bytearray(self.body(self.mod.TAGS[k], "MAIN.OUT")[1][:u["TELE"] - 0x8000])]
            for k, u in self.mod.TELE.items()})[n]
        sim = self.loaded(disk, "MAIN.OUT", opts)
        out = {"text": "", "end": None, "entry": False}
        keys = iter(typed)

        def inline(s):                  # $4C00: the string after the JSR, returns past it
            sp = s.mpu.sp
            at = (s.mem[0x101 + sp] | s.mem[0x102 + sp] << 8) + 1
            while s.mem[at]:
                out["text"] += chr(s.mem[at] & 0x7F) if s.mem[at] != 0x8D else "|"
                at += 1
            s.mem[0x101 + sp], s.mem[0x102 + sp] = at & 0xFF, at >> 8

        def end(what):
            def h(s):
                out["end"] = what
                s.mpu.sp = 0xFD         # back to call()'s own return
            return h
        sim.traps[0x4C00] = inline
        sim.traps[0x4C15] = lambda s: setattr(s.mpu, "a", next(keys))
        sim.traps[0x4C06] = lambda s: None
        sim.traps[0x4C09] = lambda s: out.__setitem__("text", out["text"] + str(s.mpu.a & 15))
        sim.traps[0x8003] = lambda s: out.__setitem__("entry", True)
        sim.traps[d["TURN"]] = end("turn")
        sim.traps[d["LOOP"]] = end("loop")
        sim.mem[d["KEY"]] = key
        sim.mem[0x2D], sim.mem[0x2E] = 45, 62
        sim.mem[d["HEADING"]], sim.mem[d["SAILING"]] = 0xBA, 0x80
        sim.mem[0x0C], sim.mem[0x17], sim.mem[0x4AC0], sim.mem[0x80] = shape, 0, 0x00, 0
        sim.traps[0x4C03] = lambda s: out.__setitem__("text", out["text"] + (
            "|" if s.mpu.a == 0x8D else chr(s.mpu.a & 0x7F)))
        sim.traps[0x6C46] = lambda s: out.__setitem__("song", s.mpu.a)
        sim.mpu.a = a
        sim.call(t[site])
        return dict(out, pos=(sim.mem[0x2D], sim.mem[0x2E]), ship=(sim.mem[d["HEADING"]], sim.mem[d["SAILING"]]),
                    shape=sim.mem[0x0C], skiffs=sim.mem[0x17], hull=sim.mem[0x4AC0], redraw=sim.mem[0x80])

    def teleport(self, disk, opts, key, typed):
        """powers() from the unknown key's hook: (what was printed, where it
        ended, $2D/$2E, whether $8003 ran, the heading and sailing bytes)."""
        r = self.powers(disk, opts, "hook", 0, key, typed)
        return r["text"], r["end"], r["pos"], r["entry"], r["ship"]

    def test_f7_teleports(self):
        """u5powers.s behind the hook, run: F7 and X, Y in decimal (RETURN, or
        three digits); given up on anything else or above 255, without a turn;
        any other key, or the option off, "What?" as before."""
        D = lambda text: [0xB0 + int(c) if c.isdigit() else 0x0D if c == "|" else 0xC1 for c in text]
        F7, EQ, P = 0x88, 0xBD, patches.POWERS
        for disk in ("2A", "2B"):
            for opts, key, typed, want in (
                    (P, F7, "58|43|", ("Teleport|X-58 Y-43", "turn", (58, 43), True, (0, 0))),
                    (P, F7, "2550|", ("Teleport|X-255 Y-0", "turn", (255, 0), True, (0, 0))),
                    (P, F7, "7|200", ("Teleport|X-7 Y-200", "turn", (7, 200), True, (0, 0))),
                    (P, F7, "256", ("Teleport|X-25", "loop", (45, 62), False, (0xBA, 0x80))),
                    (P, F7, "|", ("Teleport|X-", "loop", (45, 62), False, (0xBA, 0x80))),
                    (P, F7, "1A", ("Teleport|X-1", "loop", (45, 62), False, (0xBA, 0x80))),
                    (P, F7, "12|9A", ("Teleport|X-12 Y-9", "loop", (45, 62), False, (0xBA, 0x80))),
                    (P, EQ, "", ("What?|", "turn", (45, 62), False, (0xBA, 0x80))),
                    (0, F7, "", ("What?|", "turn", (45, 62), False, (0xBA, 0x80)))):
                with self.subTest(disk=disk, opts=opts, key=key, typed=typed):
                    self.assertEqual(self.teleport(disk, opts, key, D(typed)), want)

    def test_board_with_nothing_to_board_brings_a_vehicle(self):
        """u5powers.s behind Board's "What?", run: on foot with no object
        under the party, H/C/S/K puts the party in a horse, on a carpet, in a
        ship (hull 99, two skiffs) or a skiff, the turn ended and the objects
        redrawn; another key gives up without a turn.  An object that is no
        vehicle, a party not on foot, or the option off: "What?" as before."""
        P, menu = patches.POWERS, "|H)orse C)arpet|S)hip sK)iff?|"
        for disk in ("2A", "2B"):
            for opts, a, shape, key, want in (
                    (P, 0, 0x1C, "H", dict(text=menu + "Horse|", end="turn", shape=0x12, skiffs=0, hull=0, redraw=1)),
                    (P, 0, 0x1D, "C", dict(text=menu + "Carpet|", end="turn", shape=0x15, skiffs=0, hull=0, redraw=1)),
                    (P, 0, 0x1C, "S", dict(text=menu + "Ship|", end="turn", shape=0x25, skiffs=2, hull=0x99,
                                           redraw=1, song=3)),
                    (P, 0, 0x1C, "K", dict(text=menu + "Skiff|", end="turn", shape=0x29, skiffs=0, hull=0,
                                           redraw=1, song=3)),
                    (P, 0, 0x1C, "X", dict(text=menu, end="loop", shape=0x1C, redraw=0)),
                    (P, 0x30, 0x1C, "", dict(text="What?|", end="turn", shape=0x1C, redraw=0)),
                    (P, 0, 0x12, "", dict(text="What?|", end="turn", shape=0x12, redraw=0)),
                    (0, 0, 0x1C, "", dict(text="What?|", end="turn", shape=0x1C, redraw=0))):
                with self.subTest(disk=disk, opts=opts, a=a, shape=shape, key=key):
                    r = self.powers(disk, opts, "board", a, 0xC2, [0x80 | ord(c) for c in key], shape)
                    self.assertEqual({k: r[k] for k in want}, want)
                    self.assertEqual(r.get("song"), want.get("song"))


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestApplier(unittest.TestCase):
    """asm/patch.s on its own, with a made-up table."""

    def test_a_patch_needs_its_option_and_every_original_byte(self):
        pl = [patches.Patch(patches.FOOD, 0x5000, b"\x01\x02\x03", b"\x01\xAA\x03", "a"),
              patches.Patch(patches.PASS, 0x5010, b"\x04", b"\xBB", "b")]
        src = os.path.join(BUILD, "test_patch_wrap.s")
        with open(src, "w") as fh:
            fh.write('        * = $2000\n!source "patch.s"\n'
                     "pt_opts: !byte 0\npa_on: !byte 0\npa_n: !byte 0\npa_x: !byte 0\n")
            fh.write(patches.asm("PT_TAB", pl))
        import subprocess
        out, sym = os.path.join(BUILD, "test_patch.bin"), os.path.join(BUILD, "test_patch.sym")
        subprocess.run(["acme", "-f", "plain", "-I", paths.ASM,
                        "-o", out, "-l", sym, src], check=True)
        s = symbols(sym)
        for opts, mem, want in ((3, b"\x01\x02\x03", b"\x01\xAA\x03"),
                                (2, b"\x01\x02\x03", b"\x01\x02\x03"),
                                (3, b"\x01\x02\x04", b"\x01\x02\x04")):
            sim = Sim(Path(out).read_bytes(), 0x2000, s)
            sim.mem[0x5000:0x5003] = list(mem)
            sim.mem[0x5010] = 0x04
            sim.mem[s["pt_opts"]] = opts
            sim.call(s["pt_apply"])
            self.assertEqual(bytes(sim.mem[0x5000:0x5003]), want)
            self.assertEqual(sim.mem[0x5010], 0xBB if opts & 2 else 0x04)


if __name__ == "__main__":
    unittest.main()
