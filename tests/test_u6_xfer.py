"""Ultima VI's world to and from its disks (asm/page_u6x.s), on the host.

As test_xfer.py: the page in py65, the KERNAL's I/O on fakedrive.FakeDrive
over copies of disks 1A and 1B, the cart on FakeCart.

  * an export writes every chunk file -- the log's newest, else the
    original -- and the save area, through chains whose sectors the BAM it
    writes marks used and nothing else does;
  * an import logs exactly the chunk files and save-area sectors that differ
    from the originals, into the log's other half, and makes it the one in
    use (read back the way the cart's DIR_LOOKUP reads it);
  * a world goes out and comes back unchanged.

Skipped without py65 (the repository's .venv has it).
"""
import os
import random
import unittest

try:
    from ultima.sim.sim6502 import Sim
except ImportError:
    Sim = None

from ultima.disks.d64 import D64, SECTORS_PER_TRACK
from ultima.sim.fakedrive import Disk
from ultima.flash.tcrt import TCRT
from ultima.launcher.u6log import Log, KEYLEN, E, view
from ultima.launcher import launcher
from ultima.flash import regions
from tests import test_page
from ultima.sim import pagesim
from ultima import paths

IMAGE = os.path.join(paths.BUILD, "ultima-collection.tcrt")
DISKS = {"1A": "u6-1a", "1B": "u6-1b"}
PLAYED = "played"           # original(tag, PLAYED): the disk as a played game leaves it
RET, Y, B, SPACE = 13, ord("Y"), ord("B"), 32


def original(tag, where=None):
    with open(paths.disk(DISKS[tag]), "rb") as fh:
        data = fh.read()[:174848]
    return played(tag, data) if where == PLAYED else data


def played(tag, data):
    """The disk as a played game leaves it, made from the pristine one: what
    a save writes changed -- five chunk files' first sectors (their data,
    not the links) and, on 1A, the save area as test_page.u6_save_area()
    has it (the starting party, the Avatar named) with two of the party
    hurt -- and nothing else, so the allocation is the original's.
    Deterministic."""
    out = bytearray(data)
    disk = Disk(bytes(data))
    rng = random.Random(f"played {tag}")
    long_files = [n for n in sorted(files_of(disk)) if len(chain_sectors(disk, n)) > 1]
    for name in rng.sample(long_files, 5):
        t, s = chain_sectors(disk, name)[0]
        o = D64.offset(t, s)
        for _ in range(12):
            out[o + 2 + rng.randrange(254)] ^= 1 + rng.randrange(255)
    if tag == "1A":
        for s, sector in played_save_area().items():
            o = D64.offset(6, s)
            out[o:o + 256] = sector
    return bytes(out)


def played_save_area():
    """{sector: bytes}: test_page's save area, Dupre and Shamino hurt (S12
    +$E8, one hit-point byte a slot) and Dupre's maximum up (S13 +0: slots
    1-14's) -- the party's two sectors, both of which the page reads."""
    area = dict(test_page.u6_save_area())
    s12, s13 = bytearray(area[12]), bytearray(area[13])
    s12[0xE8 + 1], s12[0xE8 + 2] = 61, 47
    s13[0] = 96
    area[12], area[13] = bytes(s12), bytes(s13)
    return area



def files_of(disk):
    """{name: content} of every file on a Disk, following its chain."""
    out = {}
    for t, s, o, e in disk.entries():
        if e[2] & 0x07:
            name = bytes(e[5:21]).rstrip(b"\xa0").decode("latin1")
            out[name] = disk.read_file(name.encode())
    return out


def chain_sectors(disk, name):
    hit = disk.find(name.encode())
    t, s, out = hit[3][3], hit[3][4], []
    while t:
        out.append((t, s))
        blk = disk.sector(t, s)
        t, s = blk[0], blk[1]
    return out


def contents(logged):
    """A log's entries as the game reads them: a chunk file's content with
    its sectors' links stripped (as the driver's b_unlink does), a sector's
    page."""
    got = {}
    for k, pages in logged.items():
        k = k.rstrip(b"\x00")
        if k[:1] == b"/":
            data, i = bytearray(), 0
            while True:
                pg = pages[i * 256:(i + 1) * 256]
                data += pg[2:] if pg[0] else pg[2:pg[1] + 1]
                i += 1
                if not pg[0]:
                    break
            got[k] = bytes(data)
        else:
            got[k.ljust(4, b"\x00")[:4]] = pages
    return got


@unittest.skipIf(Sim is None, "py65 is not installed (use the repository's .venv)")
class TestU6Xfer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fresh = bytes(TCRT.read(IMAGE).flash.ljust(regions.FLASH_SIZE, b"\xff"))
        cls.image = test_page.launcher_prg()
        cls.sym = launcher.symbols()
        cls.s = test_page.page_syms()
        cls.lo, cls.mid, cls.hi = cls.s["U6_LO"], cls.s["U6_MID"], cls.s["U6_HI"]
        cls.orig = {tag: Disk(original(tag)) for tag in DISKS}
        cls.orig_files = {tag: files_of(d) for tag, d in cls.orig.items()}

    def run_page(self, flash, keys, disk):
        return pagesim.run_page(flash, "u6", keys, disk, self.image, self.sym)

    def export(self, flash, d1a, d1b):
        cart, drv, disks, text = self.run_page(bytearray(flash),
                                               [ord("E"), ord("D"), Y, RET, ("swap", d1b), RET, SPACE, B], d1a)
        self.assertIn("Done.", text, text[-500:])
        self.assertEqual(bytes(cart.flash), bytes(flash), "an export changed the cart")
        return disks

    def imported(self, flash, d1a, d1b):
        cart, drv, disks, text = self.run_page(bytearray(flash),
                                               [ord("I"), ord("D"), Y, RET, ("swap", d1b), RET, SPACE, B], d1a)
        self.assertIn("Done.", text, text[-500:])
        return cart.flash, text

    def active(self, flash):
        """The log half the cart would use, and what it says."""
        halves = []
        for base, top in ((self.lo, self.mid), (self.mid, self.hi)):
            e = flash[top - E:top]
            if e[0] == 0xFF:
                continue
            gen = 0
            if e[0] == 0xFE:
                g, c = e[12] | e[13] << 8, e[14] | e[15] << 8
                self.assertEqual(g ^ c, 0xFFFF, "a torn header")
                gen = g
            n, d = 0, top
            while flash[d - E] != 0xFF:
                d -= E
                n += 1
            halves.append((gen, base, view(flash, d, n)))
        return max(halves) if halves else None

    def check_disk(self, disk, tag, want):
        """want: {name: content}.  The files hold it, their chains start where
        the directory says, and the BAM marks the chains used -- every sector
        of a file, and none twice."""
        got = files_of(disk)
        self.assertEqual(set(got), set(want))
        for name in want:
            self.assertEqual(got[name], want[name], f"{tag} {name}")
        used = []
        for name in want:
            used += chain_sectors(disk, name)
        self.assertEqual(len(used), len(set(used)), "two files share a sector")
        for t, s in used:
            self.assertFalse(disk.is_free(t, s), f"{tag} T{t}/S{s} is in a file but free")
        bam = disk.sector(18, 0)
        for t in range(1, 36):
            n = sum(1 for s in range(SECTORS_PER_TRACK[t]) if disk.is_free(t, s))
            self.assertEqual(bam[4 * t], n, f"{tag} track {t}'s free count")
        self.assertNotIn((5, 20), used if tag == "1A" else [], "1A T5 S20 is read raw")

    # -- tests ---------------------------------------------------------------
    def party_only(self):
        """A cart whose log holds a saved party and nothing of the world
        (test_page's seed: the save area of the played session) -- Export is
        only offered with a saved game."""
        flash = bytearray(self.fresh)
        test_page.SEEDS["u6"](flash, test_page.page_syms())
        return flash

    def test_an_export_of_an_unchanged_world_is_the_original(self):
        flash = self.party_only()
        d1a, d1b = self.export(flash, original("1A"), original("1B"))
        for tag, disk in (("1A", d1a), ("1B", d1b)):
            self.check_disk(disk, tag, self.orig_files[tag])
        saved = test_page.u6_save_area()
        for s in range(9, 21):
            self.assertEqual(bytes(d1a.sector(6, s)), saved[s])


    def test_there_is_no_export_without_a_saved_game(self):
        cart, drv, disks, text = self.run_page(bytearray(self.fresh), [ord("E"), B], original("1A"))
        self.assertNotIn("Export", text)
        self.assertEqual(bytes(cart.flash), bytes(self.fresh))

    def test_an_export_writes_the_logged_world(self):
        """A log with new versions of some chunk files and the save area:
        those go out, everything else as it was."""
        flash = bytearray(self.fresh)
        log = Log(flash, self.lo, self.mid)
        rng = random.Random(6)
        want = {t: dict(f) for t, f in self.orig_files.items()}
        for tag, names in (("1A", ["SCC", "SDD", "SAA"]), ("1B", ["DAA"])):
            for name in names:
                n = rng.randint(1, 7)
                content = rng.randbytes(254 * (n - 1) + rng.randint(1, 254))
                pages = []
                for i in range(n):
                    part = content[254 * i:254 * (i + 1)]
                    link = bytes([17, i]) if i + 1 < n else bytes([0, len(part) + 1])
                    pages.append((link + part).ljust(256, b"\x00"))
                log.append(b"/" + name.encode(), pages, True)
                want[tag][name] = content
        save = {s: rng.randbytes(256) for s in (9, 12, 13, 20)}
        for s, pg in save.items():
            log.append(bytes([1, 0, 6, s]), [pg], False)
        d1a, d1b = self.export(flash, original("1A"), original("1B"))
        self.check_disk(d1a, "1A", want["1A"])
        self.check_disk(d1b, "1B", want["1B"])
        for s in range(9, 21):
            self.assertEqual(bytes(d1a.sector(6, s)),
                             save.get(s, bytes(self.orig["1A"].sector(6, s))))

    def test_an_export_to_a_played_disk_makes_it_consistent(self):
        """The disks of a session played on the original (with its track 17
        leak) come back as the cart's world, BAM and all."""
        d1a, d1b = self.export(self.party_only(), original("1A", PLAYED), original("1B", PLAYED))
        self.check_disk(d1a, "1A", self.orig_files["1A"])
        self.check_disk(d1b, "1B", self.orig_files["1B"])

    def test_an_import_logs_what_differs(self):
        played = {tag: Disk(original(tag, PLAYED)) for tag in DISKS}
        flash, _text = self.imported(self.fresh, bytes(played["1A"].data), bytes(played["1B"].data))
        gen, base, logged = self.active(flash)
        want = {}
        for tag in DISKS:
            for name, content in files_of(played[tag]).items():
                if content != self.orig_files[tag][name]:
                    want[b"/" + name.encode()] = content
        for s in range(9, 21):
            if played["1A"].sector(6, s) != self.orig["1A"].sector(6, s):
                want[bytes([1, 0, 6, s])] = bytes(played["1A"].sector(6, s))
        self.assertTrue(want, "the played disks differ from the originals")
        got = contents(logged)
        self.assertEqual(set(got), set(want))
        for k in want:
            self.assertEqual(got[k], want[k], k)

    def test_an_import_replaces_the_log_and_keeps_it_on_failure(self):
        """Into the other half, the header last, the old half erased; an
        import cancelled on the second disk leaves the log as it was."""
        flash = bytearray(self.fresh)
        log = Log(flash, self.lo, self.mid)
        log.append(b"/SCC", [bytes([0, 5, 1, 2, 3, 4]).ljust(256, b"\x00")], True)
        before = self.active(flash)
        # cancelled
        cart, drv, _d, text = self.run_page(bytearray(flash),
                                            [ord("I"), ord("D"), Y, RET, 0x5F, B], original("1A", PLAYED))
        self.assertEqual(self.active(cart.flash), before)
        # done
        new, _text = self.imported(flash, original("1A", PLAYED), original("1B", PLAYED))
        gen, base, logged = self.active(new)
        self.assertEqual((gen, base), (1, self.mid))
        self.assertEqual(new[self.lo:self.mid], b"\xff" * (self.mid - self.lo))
        self.assertNotIn(b"/SCC".ljust(KEYLEN, b"\x00"), logged if
                         files_of(Disk(original("1A", PLAYED)))["SCC"] == self.orig_files["1A"]["SCC"]
                         else {})

    def test_a_world_goes_out_and_comes_back(self):
        played = {tag: original(tag, PLAYED) for tag in DISKS}
        flash, _t = self.imported(self.fresh, played["1A"], played["1B"])
        d1a, d1b = self.export(flash, original("1A"), original("1B"))
        # the exported disks hold the played world
        for tag, disk in (("1A", d1a), ("1B", d1b)):
            self.check_disk(disk, tag, files_of(Disk(played[tag])))
        again, _t = self.imported(self.fresh, bytes(d1a.data), bytes(d1b.data))
        # the same world: the same files (their chains, and so their link
        # bytes, are the export's own) and the same save area
        self.assertEqual(contents(self.active(again)[2]), contents(self.active(flash)[2]))


if __name__ == "__main__":
    unittest.main()
