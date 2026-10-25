"""Verify the Ultima 4 cart image against the original disks.

Block addressing is preserved end to end, so the checks here are direct: a
linear block on disk N, looked up through that disk's block map in flash --
the same table the driver reads -- must be the original block, the five save
blocks must be redirected to their own erase blocks, and the three patches
(track-6 protection, disk-swap overlays, the spliced-in driver) must be
exactly where and what the build claims.
"""
import os
import subprocess
import sys
import unittest

from ultima.disks.d64 import D64
from ultima.flash.tcrt import TCRT
from ultima.flash import regions
from ultima.flash import zx

import importlib.util as _il
from ultima import paths


def _load_game(name):
    """Load games/<name>/build.py under a unique module name.

    Importing it as plain `build` makes the per-game test modules collide in
    sys.modules -- whichever runs first wins and the other silently tests the
    wrong game."""
    spec = _il.find_spec(f"ultima.games.{name}.build")
    mod = _il.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


u4 = _load_game("u4")

TCRT_PATH = os.path.join(paths.BUILD, "ultima4.tcrt")


class TestU4Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, "-m", "ultima.games.u4.build"],
                       check=True, stdout=subprocess.DEVNULL)
        cls.flash = TCRT.read(TCRT_PATH).flash
        cls.parts = u4.parts()
        cls.disks = {n: D64(name)
                     for n, (name, _label) in u4.DISKS.items()}
        desc = cls.flash[regions.desc_offset("u4"):regions.desc_offset("u4") + 64]
        cls.entry = desc[0] | desc[1] << 8
        cls.segments = []
        for i in range(desc[2]):
            o = 3 + 7 * i
            cls.segments.append((desc[o] << 8 | desc[o + 1] << 16,
                                 desc[o + 2] | desc[o + 3] << 8,
                                 desc[o + 4] | desc[o + 5] << 8))

    def expected_image(self, number):
        """The disk image as build.py should have stored it: the original,
        plus disk 1's three patches, plus Ultima IV Remastered's fixes
        (remastered.py; their content is tests/test_u4_remastered.py's)."""
        if not hasattr(self, "_remastered"):
            imgs = {n: bytearray(d.data) for n, d in self.disks.items()}
            imgs[1] = bytearray(self._disk1_patches(imgs[1]))    # (as build.py: these first)
            kernel = u4.kernel_image(self.disks[1])
            u4.remastered.apply(imgs, lambda c: u4.chunk_entry(kernel, c), u4.patch)
            type(self)._remastered = imgs
        return bytes(self._remastered[number])

    def _disk1_patches(self, img):
        img = bytearray(img)
        sym = u4.symbols(os.path.join(paths.BUILD, "u4drv.sym"))
        jmp = bytes([0x4C, sym["u4_setdisk"] & 0xFF, sym["u4_setdisk"] >> 8])
        for site in self.parts["sites"]:
            img[site:site + 3] = jmp
        start, _count, dest = u4.chunk_entry(u4.kernel_image(self.disks[1]), 0x50)
        prot = (start + (u4.PROT_ADDR - dest) // 256) * 256 + (u4.PROT_ADDR & 0xFF)
        img[prot:prot + len(u4.PROT_PATCH)] = u4.PROT_PATCH
        for addr, _want, new, _why in u4.MENU_PATCHES:
            o = self.parts["menu_at"] + addr - u4.MENU_AT
            img[o:o + len(new)] = new
        o = self.parts["journey_at"]
        stub = (u4.JOURNEY_BLANK + self.journey_body() + u4.JOURNEY_UNBLANK +
                bytes([0x4C, u4.JOURNEY_TO & 0xFF, u4.JOURNEY_TO >> 8]))
        img[o:o + len(stub)] = stub
        return bytes(img)

    def journey_body(self):
        """The title's $676C-$67A1 as disk A has it (pinned: JOURNEY_BODY)."""
        start, _count, dest = u4.chunk_entry(u4.kernel_image(self.disks[1]), 0x50)
        at = lambda a: (start + (a - dest) // 256) * 256 + (a & 0xFF)
        lo, hi = u4.JOURNEY_FROM
        return bytes(self.disks[1].data[at(lo):at(hi)])

    def test_journey_onward_skips_the_title(self):
        """The launcher's J: the title's logo sequence starts at $6031 with
        JSR $6092 -- the option patch's signature -- and the routine it jumps
        to is the title's own $676C-$67A1 (the set-up and the music), then
        the menu's J at $6954, in chunk $50's residue at $71E0."""
        start, count, dest = u4.chunk_entry(u4.kernel_image(self.disks[1]), 0x50)
        at = lambda a: (start + (a - dest) // 256) * 256 + (a & 0xFF)
        orig = self.disks[1].data
        lo, hi = u4.JOURNEY_FROM
        self.assertEqual(orig[at(lo):at(hi)], u4.JOURNEY_BODY)
        got = self.mapped(1)
        o = at(u4.JOURNEY_AT)
        self.assertEqual(o, self.parts["journey_at"])
        stub = u4.JOURNEY_BLANK + self.journey_body() + u4.JOURNEY_UNBLANK + bytes([0x4C, 0x54, 0x69])
        self.assertEqual(got[o:o + len(stub)], stub)
        p = [p for p in u4.OPTION_PATCHES if p.option == u4.patches.JOURNEY]
        self.assertEqual(len(p), 1)
        self.assertEqual(p[0].addr, 0x6031)
        self.assertEqual(orig[at(0x6031):at(0x6031) + 4], p[0].orig)
        self.assertEqual(p[0].new[:3], bytes([0x4C, u4.JOURNEY_AT & 0xFF, u4.JOURNEY_AT >> 8]))

    def mapped(self, number):
        """Disk `number` as the driver sees it: every block fetched through
        the block map as stored in flash, not as build.py remembers it."""
        out = bytearray()
        for block in range(u4.BLOCKS):
            addr, length = self.map_entry(number, block)
            if length == 0:
                out += self.flash[addr:addr + 256]
            else:
                page = zx.decode(self.flash[addr:addr + length])
                self.assertEqual(len(page), 256, f"disk {number} block {block}")
                out += page
        return bytes(out)

    def map_entry(self, number, block):
        o = self.parts["map_addr"][number] + 4 * block
        e = self.flash[o:o + 4]
        return e[0] | e[1] << 8 | e[2] << 16, e[3]

    def segment(self, dest):
        """What loads from dest on: the rest of the one segment holding it."""
        found = [s for s in self.segments if s[2] <= dest < s[2] + s[1]]
        self.assertEqual(len(found), 1, f"no single segment loads to {dest:#06x}")
        off, length, start = found[0]
        return self.flash[off + dest - start:off + length]

    # -- the block map ---------------------------------------------------

    def test_disk_numbers_come_from_block_zero(self):
        """The game's disk number is block 0 byte 0, not the disk letter and
        not the 1541 BAM id.  2 is Britannia (disk C) and 3 is Towne (B)."""
        for number, disk in self.disks.items():
            self.assertEqual(disk.sector(1, 0)[0], number)
        self.assertTrue(u4.DISKS[2][0].endswith("u4c.d64"), "disk 2 is Britannia (C)")
        self.assertTrue(u4.DISKS[3][0].endswith("u4b.d64"), "disk 3 is the towne disk (B)")


    def test_every_block_is_where_the_driver_will_look(self):
        """Every block of every disk, fetched through its block map, is the
        original block, and nothing but the documented patches differs."""
        for number in self.disks:
            want = self.expected_image(number)
            got = self.mapped(number)
            for block in range(u4.BLOCKS):
                if number == u4.SAVE_DISK and \
                        u4.SAVE_FIRST <= block < u4.SAVE_FIRST + u4.SAVE_COUNT:
                    continue                        # redirected, checked below
                self.assertEqual(got[block * 256:(block + 1) * 256],
                                 want[block * 256:(block + 1) * 256],
                                 f"disk {number} block {block}")

    def test_save_blocks_map_to_the_save_slots(self):
        for i in range(u4.SAVE_COUNT):
            addr, length = self.map_entry(u4.SAVE_DISK, u4.SAVE_FIRST + i)
            self.assertEqual(length, 0, "a save slot must be a raw page")
            self.assertEqual(addr, regions.save_base("u4") + i * u4.SAVE_SLOT)

    def test_every_page_is_stored_once_and_in_the_data_region(self):
        """Dedup is the whole point: no page content is stored twice, every
        entry outside the save blocks is a stream inside the data region,
        and no stream is longer than the 255 its length byte can say -- a
        page zx02 cannot shrink below that is stored raw (length 0)."""
        lo, hi = regions.data_base("u4"), self.parts["cursor"]
        seen = {}
        for number in list(self.disks) + [u4.TILESET]:     # (and the tile set's disk A)
            for block in range(u4.BLOCKS):
                if number == u4.SAVE_DISK and \
                        u4.SAVE_FIRST <= block < u4.SAVE_FIRST + u4.SAVE_COUNT:
                    continue
                addr, length = self.map_entry(number, block)
                if length == 0:
                    page = bytes(self.flash[addr:addr + 256])
                    self.assertGreater(len(zx.crunch(page)), 255, f"disk {number} block {block}")
                    length = 256
                else:
                    page = zx.decode(self.flash[addr:addr + length])
                self.assertTrue(lo <= addr and addr + length <= hi,
                                f"disk {number} block {block}")
                self.assertEqual(seen.setdefault(page, addr), addr, "a page is stored twice")
        self.assertEqual(len(seen), self.parts["pages"])

    def test_protection_check_is_dead(self):
        image = self.mapped(1)
        start, count, dest = u4.chunk_entry(u4.kernel_image(self.disks[1]), 0x50)
        off = (start + (u4.PROT_ADDR - dest) // 256) * 256 + (u4.PROT_ADDR & 0xFF)
        self.assertEqual(image[off:off + 5], u4.PROT_PATCH)

    def test_the_menu_has_no_number_of_drives(self):
        """The drives line is jumped over, "Return to the view" moves down a
        row into its place (the other two keep theirs), and N goes back to
        the key poll -- as the game will fetch the pages."""
        image = self.mapped(1)
        at = self.parts["menu_at"] - u4.MENU_AT      # flash image offset of address 0
        self.assertEqual(image[at + 0x67F5:at + 0x67F9], bytes([0xA2, 0x0B, 0xA0, 0x12]))
        self.assertEqual(image[at + 0x680F:at + 0x6812], bytes([0x4C, 0x29, 0x68]))
        self.assertEqual(image[at + 0x6829:at + 0x682D], bytes([0xA2, 0x0D, 0xA0, 0x13]))
        self.assertEqual(image[at + 0x683F:at + 0x6843], bytes([0xA2, 0x0B, 0xA0, 0x14]))
        self.assertEqual(image[at + 0x6891:at + 0x6894], bytes([0x4C, 0x58, 0x68]))

    def test_swap_overlays_all_jump_to_the_driver(self):
        image = self.mapped(1)
        self.assertEqual(len(self.parts["sites"]), u4.SWAP_SITES)
        for site in self.parts["sites"]:
            jmp = image[site:site + 3]
            self.assertEqual(jmp[0], 0x4C, "not a JMP")
            target = jmp[1] | jmp[2] << 8
            self.assertTrue(u4.GLUE_ADDR <= target < u4.GLUE_LIMIT,
                            f"{target:#06x} is not inside the driver glue")

    def test_no_swap_overlay_is_reachable(self):
        """The body of the routine stays -- only its entry is replaced -- so
        the check is that every copy is now entered through a JMP into the
        driver, and that no other disk carries one at all."""
        for number in self.disks:
            image = self.mapped(number)
            found = 0
            for m in u4.SWAP_BODY.finditer(image):
                found += 1
                # the entry is 2 or 9 bytes back depending on the variant,
                # and its JMP's last byte can overlap the body's first
                window = image[m.start() - 12:m.start() + 2]
                jumps = [i for i in range(12)
                         if window[i] == 0x4C
                         and u4.GLUE_ADDR <= window[i + 1] | window[i + 2] << 8 < u4.GLUE_LIMIT]
                self.assertTrue(jumps, f"disk {number} swap overlay at "
                                       f"{m.start():#07x} is still entered normally")
                self.assertNotIn(u4.SWAP_ENTRY, window[jumps[0]:],
                                 "the original STA $5E entry is still live")
            self.assertEqual(found, u4.SWAP_SITES if number == 1 else 0,
                             f"disk {number} carries {found} swap overlays")

    # -- saves -----------------------------------------------------------

    def test_save_slots_are_seeded_from_britannia(self):
        base = regions.save_base("u4")
        for i in range(u4.SAVE_COUNT):
            block = u4.SAVE_FIRST + i
            want = self.disks[u4.SAVE_DISK].data[block * 256:(block + 1) * 256]
            got = self.flash[base + i * u4.SAVE_SLOT:base + i * u4.SAVE_SLOT + 256]
            self.assertEqual(got, want, f"save slot {i} (block {block})")

    def test_each_save_slot_owns_a_whole_erase_block(self):
        self.assertEqual(u4.SAVE_SLOT, regions.ERASE_BLOCK)
        self.assertEqual(regions.save_base("u4") % regions.ERASE_BLOCK, 0)

    def test_a_fresh_cart_has_no_active_game(self):
        """Record $1A is 32 bytes from block 275 to $0010, and $001F is the
        saved-game flag.  Seeded from the factory disk it must read as 0, or
        Journey Onward would restore garbage instead of saying NO ACTIVE GAME."""
        base = regions.save_base("u4") + 4 * u4.SAVE_SLOT
        self.assertEqual(self.flash[base + (0x1F - 0x10)], 0x00)

    # -- the driver ------------------------------------------------------

    def test_glue_is_spliced_over_loadblk_and_stops_before_bankout(self):
        kernel = self.segment(u4.KERNEL_ADDR)[:u4.KERNEL_LEN]
        self.assertEqual(len(kernel), u4.KERNEL_LEN)
        self.assertEqual(kernel[:3], bytes([0x4C, 0x2E, 0xA1]))
        # the jump table entry for the block transfer still points at $A45E
        self.assertEqual(kernel[3:6], bytes([0x4C, 0x5E, 0xA4]))
        glue = self.parts["glue"]
        self.assertLessEqual(u4.GLUE_ADDR + glue, u4.GLUE_LIMIT)
        # from BANKOUT on the kernel is the original's, but for its IRQ
        # stubs: the entry goes to the driver's u4_irq, the way on to the
        # KERNAL keeps $01's bits 3-5 (the music through a load)
        original = u4.kernel_image(self.disks[1])
        sym = u4.symbols(os.path.join(paths.BUILD, "u4drv.sym"))
        want = bytearray(original)
        o = 0xA696 - u4.KERNEL_ADDR
        want[o:o + 3] = bytes([0x4C, sym["u4_irq"] & 0xFF, sym["u4_irq"] >> 8])
        o = 0xA6AC - u4.KERNEL_ADDR
        want[o:o + 11] = bytes.fromhex("a5 01 29 38 09 06 85 01 6c fe ff")
        o = u4.GLUE_LIMIT - u4.KERNEL_ADDR
        self.assertEqual(kernel[o:], bytes(want[o:]))

    def test_driver_flash_map_was_filled_in(self):
        """The placeholders in u4drv.s are $FFFF; a build that forgot to
        overwrite them would read from the far end of the flash."""
        kernel = self.segment(u4.KERNEL_ADDR)
        sym = u4.symbols(os.path.join(paths.BUILD, "u4drv.sym"))
        for i, number in enumerate(n for n in sorted(self.parts["map_addr"]) if n != u4.TILESET):
            addr = sum(kernel[sym[name] - u4.KERNEL_ADDR + i] << shift for name, shift in
                       (("u4_map_lo", 0), ("u4_map_mid", 8), ("u4_map_hi", 16)))
            self.assertEqual(addr, self.parts["map_addr"][number])
        o = sym["u4_savepage"] - u4.KERNEL_ADDR
        page = kernel[o] | kernel[o + 1] << 8
        self.assertEqual(page << 8, regions.save_base("u4"))

    def test_driver_starts_at_the_current_disk_being_disk_one(self):
        kernel = self.segment(u4.KERNEL_ADDR)
        sym = u4.symbols(os.path.join(paths.BUILD, "u4drv.sym"))
        self.assertEqual(kernel[sym["u4_disk"] - u4.KERNEL_ADDR], 1)

    def test_the_rest_of_the_driver_is_under_io(self):
        """The body, tclib and the decoder at $D000, inside the RAM under I/O
        (which no code of the game reaches: it only ever sets $01 to $35 or
        $36); the init stub enters through the resident u4_init, which banks
        it in."""
        lib = self.segment(u4.LIB_ADDR)
        self.assertEqual(u4.LIB_ADDR, 0xD000)
        self.assertLessEqual(u4.LIB_ADDR + len(lib), 0xE000)
        sym = u4.symbols(os.path.join(paths.BUILD, "u4drv.sym"))
        init = self.segment(u4.INIT_ADDR)
        self.assertIn(bytes([0x20, sym["u4_init"] & 0xFF, sym["u4_init"] >> 8]), init)
        self.assertTrue(u4.GLUE_ADDR <= sym["u4_init"] < u4.GLUE_LIMIT)
        for name in ("tc_init", "u4_run", "pt_apply", "zx_unpack"):
            self.assertGreaterEqual(sym[name], 0xD000, name)
        for name in ("u4_transfer", "u4_setdisk", "u4_map_lo", "pt_opts", "u4_disk"):
            self.assertLess(sym[name], u4.GLUE_LIMIT, name)

    def test_the_temporary_map_is_kept_in_ram(self):
        """Chunk $7E (block 271 of the save disk, written at every town or
        dungeon entry): a write goes to the driver's copy under the I/O and
        not to the flash, a read comes from the copy once there is one (from
        its slot before), and the next write of chunk $7F (block 272, a
        Quit & save) puts the copy into 271's slot first.  The real driver,
        as flashed, on a model cart."""
        try:
            from ultima.sim.sim6502 import Sim
        except ImportError:
            self.skipTest("py65 is not installed (use the repository's .venv)")
        sym = u4.symbols(os.path.join(paths.BUILD, "u4drv.sym"))
        from py65.memory import ObservableMemory
        sim = Sim(self.segment(u4.LIB_ADDR), u4.LIB_ADDR, sym)
        # u4_in waits for CIA 2's timer A to run out (the NMI hold): stopped
        om = ObservableMemory(subject=sim.mem)
        om.subscribe_to_read([0xDD0E], lambda a: 0x08)
        sim.mpu.memory = sim.mem = om
        kernel = self.segment(u4.KERNEL_ADDR)
        sim.mem[u4.KERNEL_ADDR:u4.KERNEL_ADDR + len(kernel)] = list(kernel)
        flash = bytearray(self.flash.ljust(regions.FLASH_SIZE, b"\xff"))
        cart = sim.attach_cart(flash)
        flash = cart.flash                          # (the cart's own copy)
        sim.mem[0x00], sim.mem[0x01] = 0x2F, 0x35
        sim.call(sym["u4_init"])
        sim.mem[sym["u4_disk"]] = 2
        slot = lambda i: regions.save_base("u4") + i * regions.ERASE_BLOCK

        def xfer(op, blk):
            sim.mem[0xA000:0xA006] = [op, 1, 0x00, 0xAC, blk & 0xFF, blk >> 8]
            n = len(cart.log)
            sim.call(sym["u4_transfer"])
            return cart.log[n:]
        seed = bytes(flash[slot(0):slot(0) + 256])
        log = xfer(1, 271)
        self.assertEqual(bytes(sim.mem[0xAC00:0xAD00]), seed, "no copy yet: its slot")
        self.assertTrue(any(e[0] == "read" for e in log))
        page = bytes((i * 7 + 3) & 0xFF for i in range(256))
        sim.mem[0xAC00:0xAD00] = list(page)
        log = xfer(2, 271)
        self.assertFalse([e for e in log if e[0] in ("erase", "write")], "no flash written")
        self.assertEqual(bytes(flash[slot(0):slot(0) + 256]), seed)
        sim.mem[0xAC00:0xAD00] = [0] * 256
        log = xfer(1, 271)
        self.assertEqual(bytes(sim.mem[0xAC00:0xAD00]), page, "read back from the copy")
        self.assertFalse([e for e in log if e[0] == "read"], "and not from the cart")
        quit_page = bytes((i * 11 + 5) & 0xFF for i in range(256))
        sim.mem[0xAC00:0xAD00] = list(quit_page)
        log = xfer(2, 272)
        # each slot through the journal (asm/journal.s): the copy and its
        # header there, the slot, then the journal erased
        jn = regions.journal("u4")[0]
        journaled = lambda i: [("erase", jn), ("write", jn + 0x100), ("write", jn),
                               ("erase", slot(i)), ("write", slot(i)), ("erase", jn)]
        self.assertEqual([(e[0], e[1]) for e in log if e[0] in ("erase", "write")],
                         journaled(0) + journaled(1))
        self.assertEqual({e[2] for e in log if e[0] == "write" and e[1] == jn}, {4}, "the header")
        self.assertEqual(bytes(flash[slot(0):slot(0) + 256]), page, "the copy in its slot")
        self.assertEqual(bytes(flash[slot(1):slot(1) + 256]), quit_page)
        log = xfer(2, 272)                          # a second save: the copy is in already
        self.assertEqual([(e[0], e[1]) for e in log if e[0] in ("erase", "write")], journaled(1))

    def u4_sim(self):
        """The driver and the kernel as flashed, on a model cart, u4_init run."""
        try:
            from ultima.sim.sim6502 import Sim
        except ImportError:
            self.skipTest("py65 is not installed (use the repository's .venv)")
        sym = u4.symbols(os.path.join(paths.BUILD, "u4drv.sym"))
        from py65.memory import ObservableMemory
        sim = Sim(self.segment(u4.LIB_ADDR), u4.LIB_ADDR, sym)
        om = ObservableMemory(subject=sim.mem)      # the NMI hold's timer: run out
        om.subscribe_to_read([0xDD0E], lambda a: 0x08)
        sim.mpu.memory = sim.mem = om
        high = self.segment(u4.A0_ORG)
        sim.mem[u4.A0_ORG:u4.A0_ORG + len(high)] = list(high)
        flash = bytearray(self.flash.ljust(regions.FLASH_SIZE, b"\xff"))
        sim.attach_cart(flash)
        sim.mem[0x00], sim.mem[0x01] = 0x2F, 0x35
        sim.call(sym["u4_init"])
        return sim, sym

    def test_the_music_plays_through_a_load(self):
        """A load with interrupts coming (u4drv.s u4_irqs, u4_irq): they are
        taken during it through the kernel's entry ($A696, RAM's $FFFE), the
        music's handler ($A116) sees I/O in with the interrupted $01's
        cassette bits, the way on to the KERNAL ($A6AC) keeps them too, $0314
        is the KERNAL's IRQ past its tape motor code meanwhile, and the
        interrupted code gets its $01 back -- and the blocks arrive as they do
        without interrupts.  With a handler of the game's own in $0314
        (character creation's) none is taken during the load."""
        MUSIC, BLOCKS = 0xC000, 6
        runs = {}
        for case in ("quiet", "irqs", "own"):
            sim, sym = self.u4_sim()
            sim.mem[sym["u4_disk"]] = 1
            sim.mem[0xFFFE], sim.mem[0xFFFF] = 0x96, 0xA6        # BANKOUT's
            sim.mem[0xA116], sim.mem[0xA117] = MUSIC & 0xFF, MUSIC >> 8
            sim.mem[MUSIC:MUSIC + 3] = [0x4C, 0xAC, 0xA6]       # the music: on to $A6AC
            kvec = 0xEA31 if case != "own" else 0x6840
            sim.mem[0x0314], sim.mem[0x0315] = kvec & 0xFF, kvec >> 8
            seen = {"taken": 0, "in_lib": 0, "bad": []}
            mpu, step = sim.mpu, sim.mpu.step
            kernal_jmp = 0xA6AC + 8
            stack = []

            def stepper():
                pc = mpu.pc
                if pc == MUSIC:
                    was = stack[-1]
                    if sim.mem[0x01] != (was & 0x38) | 0x05:
                        seen["bad"].append(("music", was, sim.mem[0x01]))
                elif pc == kernal_jmp:
                    was = stack.pop()
                    if sim.mem[0x01] != (was & 0x38) | 0x06:
                        seen["bad"].append(("kernal", was, sim.mem[0x01]))
                    k = sim.mem[0x0314] | sim.mem[0x0315] << 8
                    if k != sym["u4_kirq"]:
                        seen["bad"].append(("0314", k))
                    # the KERNAL's IRQ: its pushes and pulls cancel, then RTI
                    sp = mpu.sp
                    mpu.p = sim.mem[0x100 + ((sp + 1) & 0xFF)] | 0x30
                    mpu.pc = sim.mem[0x100 + ((sp + 2) & 0xFF)] | sim.mem[0x100 + ((sp + 3) & 0xFF)] << 8
                    mpu.sp = (sp + 3) & 0xFF
                    return
                if case != "quiet" and not mpu.p & 0x04 and sim.steps % 23 == 0 \
                        and pc not in sim.traps and not stack:
                    seen["taken"] += 1
                    seen["in_lib"] += pc >= u4.LIB_ADDR
                    stack.append(sim.mem[0x01])
                    ret = pc
                    for b in (ret >> 8, ret & 0xFF, (mpu.p & ~0x10) | 0x20):
                        sim.mem[0x100 + mpu.sp] = b
                        mpu.sp = (mpu.sp - 1) & 0xFF
                    mpu.p |= 0x04
                    mpu.pc = sim.mem[0xFFFE] | sim.mem[0xFFFF] << 8
                    return
                if pc == 0xA6B3:
                    seen["bad"].append(("old exit",))
                step()
            mpu.step = stepper
            sim.mem[0xA000:0xA006] = [1, BLOCKS, 0x00, 0x40, 100, 0]
            sim.mpu.p &= ~0x04                                  # the game's: interrupts on
            sim.call(sym["u4_transfer"])
            self.assertFalse(mpu.p & 0x04, f"{case}: the caller's I flag back")
            self.assertEqual(sim.mem[0x0314] | sim.mem[0x0315] << 8, kvec, case)
            self.assertEqual(sim.mem[0x01], 0x35, case)
            self.assertEqual(seen["bad"], [], case)
            runs[case] = (bytes(sim.mem[0x4000:0x4000 + BLOCKS * 256]), seen)
        self.assertEqual(runs["quiet"][0], self.mapped(1)[100 * 256:(100 + BLOCKS) * 256])
        self.assertEqual(runs["irqs"][0], runs["quiet"][0])
        self.assertEqual(runs["own"][0], runs["quiet"][0])
        self.assertGreater(runs["irqs"][1]["in_lib"], 100, "interrupts taken inside the load")
        self.assertEqual(runs["own"][1]["taken"], 0, "none with the game's own $0314")

    def test_the_credits_are_shown_but_not_on_journey_onward(self):
        """The boot PRG's own title screen ($0839, its end an RTS), run: the
        credits in screen RAM, white; the init stub calls it unless the
        options byte has JOURNEY."""
        credits = self.segment(u4.CREDITS_ADDR)
        self.assertEqual(credits[0x0840 - 0x0839], 0x60)
        try:
            from ultima.sim.sim6502 import Sim
        except ImportError:
            self.skipTest("py65 is not installed")
        sim = Sim(credits, 0x0839, {})
        sim.call(0x0839)
        row = lambda r: bytes(sim.mem[0x0400 + 40 * r:0x0428 + 40 * r])
        scr = lambda text: bytes((ord(c) - 0x40) if c >= "@" else ord(c) for c in text)
        self.assertIn(scr("ORIGIN SYSTEMS"), row(6))
        self.assertIn(scr("ULTIMA IV: QUEST OF THE AVATAR"), row(11))
        self.assertIn(scr("COPYRIGHT (C) 1985 ORIGIN SYSTEMS, INC."), row(22))
        self.assertEqual(sim.mem[0xD800 + 40 * 6 + 13], 1, "white")
        stub = self.segment(u4.INIT_ADDR)
        call = bytes([0x20, 0x39, 0x08])
        i = stub.find(call)
        self.assertGreater(i, 0, "JSR $0839")
        sym = u4.symbols(os.path.join(paths.BUILD, "u4drv.sym"))
        self.assertEqual(stub[i - 7:i - 2], bytes([0xAD, sym["pt_opts"] & 0xFF, sym["pt_opts"] >> 8,
                                                   0x29, 0x04]), "LDA pt_opts / AND #JOURNEY")

    def test_init_stub_stays_clear_of_the_text_colour(self):
        init = self.segment(u4.INIT_ADDR)
        self.assertLess(u4.INIT_ADDR + len(init), 0x0286)
        self.assertEqual(self.entry, u4.INIT_ADDR)


if __name__ == "__main__":
    unittest.main()
