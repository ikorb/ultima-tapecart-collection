"""The EasyFlash build of Ultima VI (ef/, a side quest beside the tapecart
collection): its flash map and CRT, and its real 6502 code -- the drivers in
ROM, their RAM primitives, the boot's init, EAPI -- run in py65 on a model
of a C64 with an EasyFlash (efsim.py), against the image the build made.

Skipped without py65 (the repository's .venv has it).
"""
import importlib.util
import os
from ultima import paths
import unittest

try:
    from tests.efsim import EFSim
    from ultima.sim.sim6502 import PowerCut
except ImportError:
    EFSim = None

# A side quest: `make test` runs these only once the EF image has been built
# (make ef), and never without EAPI's sources (external/eapi).
if not os.path.exists(os.path.join(paths.BUILD, "ultima6-ef.crt")) or \
        not os.path.exists(os.path.join(paths.EXTERNAL, "eapi", "eapi-am29f040.s")):
    raise unittest.SkipTest("the EasyFlash build is not made (make ef)")


from ultima.ef import efregions as R               # noqa: E402
from ultima.ef import efcrt                        # noqa: E402
from ultima.launcher import u6log                        # noqa: E402

_spec = importlib.util.find_spec("ultima.ef.build")
efb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(efb)
u6 = efb.u6

CMD = 0xC000            # command strings (free in these tests)
DEST = 0x4000           # where results land
GAME_SLOT_END = R.GAME_SLOT + R.EAPI_SIZE
EF_LOGDIR, EF_DIRCOUNT, EF_LOGDATA = 0xDF00, 0xDF03, 0xDF05
EF_OPEN, EF_ACT, EF_GEN = 0xDF08, 0xDF1A, 0xDF1B
STATE_LEN = 0x50                    # $DF00-$DF4F: efvars.inc's EF_STATE_END
SPIN_BM, SPIN_SC = 0xE000 + 23 * 320 + 23 * 8, 0xCC00 + 23 * 40 + 23

_built = {}


def built():
    if "p" not in _built:
        _built["p"] = efb.build()
    return _built["p"]


def a24(a):
    return bytes([a & 0xFF, (a >> 8) & 0xFF, a >> 16])


def chain(p, tag, name):
    d = p["disks"][tag]
    for n, _t, t, s, _b in d.directory():
        if n == name:
            return p["patched"].get((tag, name), d.chain(t, s)[0])
    raise KeyError(name)


class TestEFLayout(unittest.TestCase):
    """The flash map and the CRT (no CPU needed)."""

    def test_the_log_never_moves(self):
        # a save moved is a save lost: a new build is flashed over an old one
        self.assertEqual((R.LOG_LO, R.LOG_MID, R.LOG_HI), (0x0C0000, 0x0E0000, 0x100000))
        self.assertEqual(list(R.LOG_BANKS), list(range(48, 64)))

    def test_the_data_stays_below_the_log(self):
        self.assertLessEqual(built()["cursor"], R.LOG_LO)

    def test_eapi_name_and_vectors_in_bank_0(self):
        f = built()["flash"]
        self.assertEqual(bytes(f[R.EAPI_LIN:R.EAPI_LIN + 4]), b"eapi")
        self.assertEqual(bytes(f[R.NAME_LIN:R.NAME_LIN + 8]), bytes.fromhex("65662d6e414d453a"))
        vec = R.lin(0, 1, 0x1FFA)
        reset = f[vec + 2] | f[vec + 3] << 8
        self.assertEqual(reset, R.STUB_CPU, "the reset vector is the stub")

    def test_the_crt_round_trips_without_the_log(self):
        path = os.path.join(paths.BUILD, "ef", "test.crt")
        f = bytearray(built()["flash"])
        f[R.LOG_LO + 5] = 0x00                      # something in the log ...
        efcrt.write(path, f, "Ultima VI", skip_banks=R.LOG_BANKS)
        back, name = efcrt.read(path)
        self.assertEqual(name, "Ultima VI")
        self.assertEqual(bytes(back[:R.LOG_LO]), bytes(f[:R.LOG_LO]))
        self.assertEqual(bytes(back[R.LOG_LO:]), b"\xff" * (R.LOG_HI - R.LOG_LO))  # ... never in the CRT

    def test_the_static_directory_is_sorted_in_both_driver_banks(self):
        p = built()
        f = p["flash"]
        n = len(p["entries"])
        for bank in (R.GAME_DRV_BANK, R.BOOT_DRV_BANK):
            d = R.lin(bank, 1)
            keys = [bytes(f[d + 20 * i:d + 20 * i + 12]) for i in range(n)]
            self.assertEqual(keys, sorted(keys))
            self.assertEqual(len(set(keys)), n)


@unittest.skipIf(EFSim is None, "py65 is not installed (use the repository's .venv)")
class GameSim(unittest.TestCase):
    """`game` with its EF driver, as the boot leaves it: the cart off, $01 =
    $34, the log's state in the cart's RAM."""
    eapi = "real"

    def setUp(self):
        self.p = built()
        self.sim = EFSim(self.p["flash"], eapi=self.eapi)
        if self.eapi == "contract":
            self.sim.contract_init_at(R.GAME_SLOT)
        self.setUp_ram()

    def setUp_ram(self):
        m = self.sim.mem
        game = self.p["game"]
        m.ram[0x0200:0x0200 + len(game)] = game
        tiles = chain(self.p, "3B", "TILES")[2:]
        m.ram[0x6000:0x6000 + len(tiles)] = tiles
        m.ram[0xFFFE], m.ram[0xFFFF] = 0x26, 0x1F
        m.ram[0], m.ram[1] = 0x2F, 0x34
        m.control = 0x04
        self.empty_log()

    def empty_log(self, half=0):
        m = self.sim.mem
        top, base = (R.LOG_MID, R.LOG_LO) if half == 0 else (R.LOG_HI, R.LOG_MID)
        m.efram[0:STATE_LEN] = bytes(STATE_LEN)
        m.efram[0:3] = a24(top)
        m.efram[5:8] = a24(base)
        m.efram[0x1A] = 3 * half

    def state(self):
        st = self.sim.mem.efram
        return dict(logdir=st[0] | st[1] << 8 | st[2] << 16, count=st[3] | st[4] << 8,
                    logdata=st[5] | st[6] << 8 | st[7] << 16, act=st[0x1A], gen=st[0x1B] | st[0x1C] << 8)

    def use_log(self, log, count, gen, half=0):
        """The cart's state as efinit would leave it for a log laid down by u6log."""
        m = self.sim.mem
        m.efram[0:STATE_LEN] = bytes(STATE_LEN)
        m.efram[0:3] = a24(log.dir)
        m.efram[3:5] = bytes([count & 0xFF, count >> 8])
        m.efram[5:8] = a24(log.data)
        m.efram[0x1A] = 3 * half
        m.efram[0x1B:0x1D] = bytes([gen & 0xFF, gen >> 8])

    def save_session(self, name, pages, close=True):
        """`!NAME`, its sectors with `&`, then (close) a load by name, which
        ends the session as the game's next command would."""
        c = self.cmd(b"!" + name.encode() + b"\x80" + bytes([0x00, 0x30]))
        self.assertEqual(c, 0)
        t, s = self.ram(0x3000, 2)
        self.assertEqual((t, s), self.p["starts"][name])
        for pg in pages:
            self.sim.mem.ram[0xD600:0xD700] = pg            # the save builds them under I/O
            self.assertEqual(self.cmd(bytes([0x26, 1, 0, 0, 0, 0x00, 0xD6]), "1A"), 0)
        if close:
            self.assertEqual(self.cmd(b"/T005\x80" + bytes([0x00, 0x70])), 0)

    def disk_pages(self, name):
        """A chunk file's sectors as on its disk, links and all."""
        tag = "1A" if name.startswith("S") else "1B"
        d = self.p["disks"][tag]
        t, s = self.p["starts"][name]
        out = []
        while True:
            sec = bytes(d.sector(t, s))
            out.append(sec)
            if sec[0] == 0:
                return out
            t, s = sec[0], sec[1]

    def load(self, name):
        self.sim.mem.ram[0x4000:0x5400] = bytes(0x1400)
        self.assertEqual(self.cmd(b"/" + name.encode() + b"\x80" + bytes([0x00, 0x40])), 0)
        return self.ram(0x4000, 0x1400)

    def cmd(self, cmd, disk=None):
        sim = self.sim
        if disk is not None:
            sim.mpu.x = {"1A": 0, "1B": 2}[disk]
            sim.call(0x2823)
        sim.mem.ram[CMD:CMD + len(cmd)] = cmd
        sim.mpu.x, sim.mpu.y = CMD & 0xFF, CMD >> 8
        sim.call(0x29BE)
        self.assertEqual(sim.mem.ram[1], 0x34, "$01 as the original loader left it")
        self.assertEqual(sim.mem.control, 0x04, "the cart out of sight")
        self.assertEqual(bytes(sim.mem.ram[0x0314:0x0316]),
                         bytes(self.p["game"][0x0314 - 0x0200:0x0316 - 0x0200]), "($0314) put back")
        return sim.mpu.p & 1

    def ram(self, addr, n):
        return bytes(self.sim.mem.ram[addr:addr + n])

    def logview(self):
        m = self.sim.mem
        f = m.flash()
        logdir = m.efram[0] | m.efram[1] << 8 | m.efram[2] << 16
        n = m.efram[3] | m.efram[4] << 8
        return u6log.view(f, logdir, n)


class TestEFDriverReads(GameSim):
    def test_sector_reads_whole_and_partial(self):
        checked = 0
        for tag in ("1A", "1B"):
            d = self.p["disks"][tag]
            infile = u6.file_sectors(d)
            for t in (1, 5, 6, 18, 20, 26, 33, 35):
                for s in (0, 4, 9, 16):
                    if s >= u6.SECTORS[t] or (t, s) in infile or (t, s) == (u6.EXP_TRACK, u6.EXP_SECTOR):
                        continue
                    if t == u6.END_TRACK and s in u6.END_SECTORS:
                        continue
                    want = bytes(d.sector(t, s))
                    for off, cnt in ((0, 0), (64, 64), (34, 222)):
                        self.sim.mem.ram[DEST:DEST + 257] = b"\xa5" * 257
                        c = self.cmd(bytes([0x5E, t, s, off, cnt, DEST & 0xFF, DEST >> 8]), tag)
                        n = cnt or 256
                        self.assertEqual(c, 0)
                        self.assertEqual(self.ram(DEST, n), want[off:off + n], f"{tag} T{t} S{s} +{off} x{n}")
                        self.assertEqual(self.sim.mem.ram[DEST + n], 0xA5, "the read ran past its count")
                        checked += 1
        self.assertGreater(checked, 50)

    def test_a_read_under_io(self):
        # overlay $34 and the chunk reads land in $D400-$D7FF, under I/O
        want = bytes(self.p["disks"]["1A"].sector(19, 8))
        self.assertEqual(self.cmd(bytes([0x5E, 19, 8, 0, 0, 0x00, 0xD4]), "1A"), 0)
        self.assertEqual(self.ram(0xD400, 256), want)

    def test_loads_by_name(self):
        for tag, name in (("2A", "T005"), ("3A", "T201"), ("2B", "T100"), ("1A", "SCC"),
                          ("1B", "DAA"), ("1A", "SDC"), ("3A", "T191")):
            want = chain(self.p, tag, name)
            c = self.cmd(b"/" + name.encode() + b"\x80" + bytes([DEST & 0xFF, DEST >> 8]))
            self.assertEqual(c, 0, name)
            self.assertEqual(self.ram(DEST, len(want)), want, name)

    def test_percent_names_drop_the_prg_header(self):
        want = chain(self.p, "3B", "COLORS")[2:]
        self.assertEqual(self.cmd(b"%COLORS\xff" + bytes([DEST & 0xFF, DEST >> 8])), 0)
        self.assertEqual(self.ram(DEST, len(want)), want)

    def test_a_chain_of_names(self):
        a, b = chain(self.p, "2A", "T005"), chain(self.p, "2A", "T018")
        cmd = b"/T005\x00" + bytes([0x00, 0x40]) + b"/T018\x80" + bytes([0x00, 0x60])
        self.assertEqual(self.cmd(cmd), 0)
        self.assertEqual(self.ram(0x4000, len(a)), a)
        self.assertEqual(self.ram(0x6000, len(b)), b)

    def test_a_missing_name_fails(self):
        self.assertEqual(self.cmd(b"/NOPE\x80\x00\x40"), 1)

class TestEFDriverWrites(GameSim):
    def test_a_save_session_reads_back(self):
        sector = lambda link, fill: bytes(link) + bytes([fill]) * 254
        pages = [sector((1, 2), 0x11), sector((1, 3), 0x22), sector((0, 101), 0x33)]
        self.save_session("SCC", pages, close=False)
        state = bytes(range(256))           # (the save area's S9 closes the session)
        self.sim.mem.ram[0x5400:0x5500] = state
        self.assertEqual(self.cmd(bytes([0x26, 6, 9, 0, 0, 0x00, 0x54]), "1A"), 0)
        # the load by name now finds the logged copy, links stripped
        want = b"\x11" * 254 + b"\x22" * 254 + b"\x33" * 100
        self.assertEqual(self.cmd(b"/SCC\x80" + bytes([0x00, 0x40])), 0)
        self.assertEqual(self.ram(0x4000, len(want)), want)
        # and the save area's sector its newest copy
        self.assertEqual(self.cmd(bytes([0x5E, 6, 9, 0, 0, 0x00, 0x48]), "1A"), 0)
        self.assertEqual(self.ram(0x4800, 256), state)
        view = self.logview()
        self.assertEqual(set(view), {b"/SCC".ljust(12, b"\0"), bytes([1, 0, 6, 9]).ljust(12, b"\0")})

    def test_a_second_save_wins(self):
        for fill in (0x41, 0x42):
            self.sim.mem.ram[0x5400:0x5500] = bytes([fill]) * 256
            self.assertEqual(self.cmd(bytes([0x26, 6, 10, 0, 0, 0x00, 0x54]), "1A"), 0)
        self.assertEqual(self.cmd(bytes([0x5E, 6, 10, 0, 0, 0x00, 0x48]), "1A"), 0)
        self.assertEqual(self.ram(0x4800, 256), b"\x42" * 256)

    def test_eapis_slot_is_put_back(self):
        before = self.ram(0x6000, 0x800)
        self.sim.mem.ram[0x5400:0x5500] = b"\x99" * 256
        self.assertEqual(self.cmd(bytes([0x26, 6, 11, 0, 0, 0x00, 0x54]), "1A"), 0)
        self.assertEqual(self.ram(0x6000, 0x800), before, "the tiles under EAPI's slot are back")

    def test_the_access_light_is_lit_only_while_the_driver_runs(self):
        """efres.s's trampoline: the frame cell below the cursor (row 24, col
        23) is white ($81) at every read from the cart -- the driver's code,
        its data, EAPI's flash -- and the frame's $89 again after."""
        cell = 0xCC00 + 24 * 40 + 23
        m = self.sim.mem
        m.ram[cell] = 0x89
        seen = []

        class Watched(type(m)):
            def __getitem__(self, addr):
                if not isinstance(addr, slice) and self.region(addr) in ("roml", "romh"):
                    seen.append(self.ram[cell])
                return super().__getitem__(addr)
        m.__class__ = Watched
        m.ram[0x5400:0x5500] = b"\x99" * 256
        for cmd, disk in ((bytes([0x5E, 18, 0, 0, 0, 0x00, 0x50]), "1A"),
                          (b"/T005\x80\x00\x40", None),
                          (bytes([0x26, 6, 11, 0, 0, 0x00, 0x54]), "1A")):
            with self.subTest(cmd=cmd[:1]):
                del seen[:]
                self.assertEqual(self.cmd(cmd, disk), 0)
                self.assertGreater(len(seen), 100)
                self.assertEqual(set(seen), {0x81}, "not lit while the cart was read")
                self.assertEqual(m.ram[cell], 0x89, "not put back")

    def test_writes_land_only_in_the_log(self):
        before = bytes(self.sim.mem.flash())
        self.sim.mem.ram[0x5400:0x5500] = b"\x5a" * 256
        self.cmd(bytes([0x26, 6, 12, 0, 0, 0x00, 0x54]), "1A")
        after = self.sim.mem.flash()
        diff = [i for i in range(len(after)) if after[i] != before[i]]
        self.assertTrue(diff)
        self.assertTrue(all(R.LOG_LO <= i < R.LOG_MID for i in diff), "a write outside the log's half")

    def test_bam_writes_are_dropped(self):
        before = bytes(self.sim.mem.flash())
        self.assertEqual(self.cmd(bytes([0x26, 18, 0, 0, 0, 0x00, 0x54]), "1A"), 0)
        self.assertEqual(bytes(self.sim.mem.flash()), before)

    def test_a_full_log_is_compacted_not_refused(self):
        m = self.sim.mem
        m.efram[0:3] = a24(R.LOG_LO + 0x0200)       # the directory two pages above the data
        self.sim.mem.ram[0x5400:0x5500] = b"\x77" * 256
        self.assertEqual(self.cmd(bytes([0x26, 6, 9, 0, 0, 0x00, 0x54]), "1A"), 0)
        self.assertEqual(self.state()["act"], 3)
        self.assertEqual(self.logview(), {bytes([1, 0, 6, 9]).ljust(12, b"\0"): b"\x77" * 256})


class TestEFDriverWritesByContract(TestEFDriverWrites):
    """The same, with EAPI answered by its documented contract alone."""
    eapi = "contract"


def strip(pages):
    """What the drive gives for a chain: 254 bytes a sector, the last's to its link."""
    out = b""
    for pg in pages:
        out += pg[2:] if pg[0] else pg[2:pg[1] + 1]
    return out


def log_entry(flash, logdir, count, key):
    """The newest entry for key: (address, pages or 0, flags)."""
    key = key.ljust(12, b"\0")
    for i in range(count):
        e = flash[logdir + 20 * i:logdir + 20 * (i + 1)]
        if bytes(e[:12]) == key:
            return e[12] | e[13] << 8 | e[14] << 16, e[15] | e[16] << 8, e[17]
    return None


class TestEFSkips(GameSim):
    """A save writes only what changed, by an exact compare (never a
    checksum): a save-area sector equal to its newest
    version, a chunk file equal page for page, cost nothing."""
    S9 = bytes([1, 0, 6, 9]).ljust(12, b"\0")
    SCC = b"/SCC".ljust(12, b"\0")

    def write_s9(self, data):
        self.sim.mem.ram[0x5400:0x5500] = data
        self.assertEqual(self.cmd(bytes([0x26, 6, 9, 0, 0, 0x00, 0x54]), "1A"), 0)

    def test_an_unchanged_save_area_sector_is_not_written(self):
        static = bytes(self.p["disks"]["1A"].sector(6, 9))
        before = bytes(self.sim.mem.flash())
        self.write_s9(static)
        self.assertEqual(bytes(self.sim.mem.flash()), before, "equal to the build's: no write")
        self.write_s9(b"\x31" * 256)
        self.assertEqual(self.logview(), {self.S9: b"\x31" * 256})
        before = bytes(self.sim.mem.flash())
        self.write_s9(b"\x31" * 256)
        self.assertEqual(bytes(self.sim.mem.flash()), before, "equal to the log's: no write")
        self.write_s9(static)                       # back as it was: that is a change
        self.assertEqual(self.logview(), {self.S9: static})
        self.write_s9(static[:255] + b"\x00")       # one byte, the last
        self.assertEqual(self.logview(), {self.S9: static[:255] + b"\x00"})

    def test_a_chunk_file_saved_unchanged_writes_nothing(self):
        for name in ("SCC", "SDC", "SAA", "DAB"):
            pages = self.disk_pages(name)
            before = bytes(self.sim.mem.flash())
            self.save_session(name, pages)
            self.assertEqual(bytes(self.sim.mem.flash()), before, name)
            self.assertEqual(self.load(name)[:len(strip(pages))], strip(pages))

    def test_a_change_in_the_last_page_writes_the_held_ones_first(self):
        pages = self.disk_pages("SCC")
        pages[-1] = pages[-1][:10] + b"\xEE" + pages[-1][11:]
        self.save_session("SCC", pages)
        m = self.sim.mem
        st = self.state()
        addr, n, flags = log_entry(m.flash(), st["logdir"], st["count"], b"/SCC")
        self.assertEqual((n, flags), (len(pages), 2))
        self.assertEqual(bytes(m.flash()[addr:addr + 256 * n]), b"".join(pages),
                         "the held pages come from the build's file with their own links")
        self.assertEqual(self.load("SCC")[:len(strip(pages))], strip(pages))

    def test_a_change_in_the_first_page(self):
        pages = self.disk_pages("SCC")
        pages[0] = pages[0][:2] + b"\x01" + pages[0][3:]
        self.save_session("SCC", pages)
        self.assertEqual(self.logview(), {self.SCC: b"".join(pages)})

    def test_a_logged_file_saved_again(self):
        pages = self.disk_pages("SDC")
        pages[4] = pages[4][:100] + b"\x5A" + pages[4][101:]
        self.save_session("SDC", pages)
        before = bytes(self.sim.mem.flash())
        self.save_session("SDC", pages)
        self.assertEqual(bytes(self.sim.mem.flash()), before, "equal to the log's version: no write")
        pages[7] = pages[7][:2] + b"\x5B" + pages[7][3:]
        self.save_session("SDC", pages)
        self.assertEqual(self.logview(), {b"/SDC".ljust(12, b"\0"): b"".join(pages)})
        self.assertEqual(self.load("SDC")[:len(strip(pages))], strip(pages))

    def test_a_file_that_grows_or_shrinks(self):
        pages = self.disk_pages("SCC")
        last = pages[-1]
        grown = pages[:-1] + [bytes([1, 7]) + last[2:], bytes([0, 40]) + b"\x77" * 254]
        self.save_session("SCC", grown)
        self.assertEqual(self.logview(), {self.SCC: b"".join(grown)})
        self.assertEqual(self.load("SCC")[:len(strip(grown))], strip(grown))
        shrunk = grown[:-3] + [bytes([0, 255]) + grown[-3][2:]]
        self.save_session("SCC", shrunk)
        self.assertEqual(self.logview(), {self.SCC: b"".join(shrunk)})
        self.assertEqual(self.load("SCC")[:len(strip(shrunk))], strip(shrunk))
        # the last page ends one byte early: data the same, its length not
        short = self.disk_pages("SCC")
        short[-1] = bytes([0, short[-1][1] - 1]) + short[-1][2:]
        self.save_session("SCC", short)
        self.assertEqual(self.logview(), {self.SCC: b"".join(short)})

    def test_more_pages_than_can_be_held(self):
        rng = __import__("random").Random(9)
        pages = [bytes([1, i + 1]) + rng.randbytes(254) for i in range(13)] + [bytes([0, 99]) + rng.randbytes(254)]
        self.save_session("SCC", pages)
        self.save_session("SCC", pages)             # unchanged, but more than MAXHOLD: written again
        self.assertEqual(self.logview(), {self.SCC: b"".join(pages)})
        self.assertEqual(self.load("SCC")[:len(strip(pages))], strip(pages))

    def test_a_session_that_ends_early_is_kept(self):
        # every page so far equal, but the session closes before the file's
        # last page: what was held is written, not dropped
        pages = self.disk_pages("SCC")[:3]
        self.save_session("SCC", pages)
        self.assertEqual(self.logview(), {self.SCC: b"".join(pages)})


    def test_power_cuts_while_held_pages_are_written(self):
        # the old file stays until the entry for the new one is complete
        pages = self.disk_pages("SDC")
        pages[-1] = pages[-1][:3] + bytes([pages[-1][3] ^ 0xFF]) + pages[-1][4:]
        start = bytes(self.sim.mem.flash())
        m = self.sim.mem
        m.changes = 0
        self.save_session("SDC", pages)
        total = m.changes
        self.assertGreater(total, 9 * 256)
        new = {b"/SDC".ljust(12, b"\0"): b"".join(pages)}
        for cut in sorted({1, 200, total // 2, total - 20, total - 1}):
            self.setUp()
            self.sim = sim = EFSim(start, eapi=self.eapi)
            if self.eapi == "contract":
                sim.contract_init_at(R.GAME_SLOT)
            self.setUp_ram()
            sim.mem.cut_after = cut
            with self.assertRaises(PowerCut, msg=f"a cut after {cut} of {total}"):
                self.save_session("SDC", pages)
            view = boot_log(sim.mem.flash())[0]
            self.assertIn(view, ({}, new), f"a cut after {cut} of {total} changes")

class TestEFSkipsByContract(TestEFSkips):
    eapi = "contract"


class TestEFCompaction(GameSim):
    """A save that finds the log full compacts it in place: the newest
    version of every key into the other half, the open session's pages
    after them, the header last.  The game never sees a failed write."""

    def full_log(self, until_free=3, seed=3):
        import random
        f = bytearray(self.p["flash"])
        log = u6log.Log(f, R.LOG_LO, R.LOG_MID)
        log.header(6)
        want = {}
        u6log.play(log, random.Random(seed), want, until_free=40)    # (a save is ~30 pages)
        while log.free() >= until_free:
            log.append(b"/SZZ", [b"\x01" * 256], True)
            want[b"/SZZ".ljust(12, b"\0")] = b"\x01" * 256
        count = (R.LOG_MID - log.dir) // 20
        self.sim = EFSim(f, eapi=self.eapi)
        if self.eapi == "contract":
            self.sim.contract_init_at(R.GAME_SLOT)
        m = self.sim.mem
        game = self.p["game"]
        m.ram[0x0200:0x0200 + len(game)] = game
        tiles = chain(self.p, "3B", "TILES")[2:]
        m.ram[0x6000:0x6000 + len(tiles)] = tiles
        m.ram[0xFFFE], m.ram[0xFFFF] = 0x26, 0x1F
        m.ram[0], m.ram[1] = 0x2F, 0x34
        m.control = 0x04
        self.use_log(log, count, 6)
        return log, want

    def test_a_save_into_a_full_log(self):
        log, want = self.full_log()
        m = self.sim.mem
        m.ram[SPIN_BM:SPIN_BM + 8] = bytes(range(1, 9))
        m.ram[SPIN_SC] = 0x3C
        tiles = self.ram(0x6000, 0x800)
        old_half = bytes(m.flash()[R.LOG_LO:R.LOG_MID])
        m.ram[0x5400:0x5500] = b"\x77" * 256
        self.assertEqual(self.cmd(bytes([0x26, 6, 9, 0, 0, 0x00, 0x54]), "1A"), 0)
        want[bytes([1, 0, 6, 9]).ljust(12, b"\0")] = b"\x77" * 256
        st = self.state()
        self.assertEqual((st["act"], st["gen"]), (3, 7))
        self.assertEqual(self.logview(), want)
        self.assertEqual(bytes(m.flash()[R.LOG_LO:R.LOG_MID]), old_half, "the old half stays as it was")
        self.assertEqual(self.ram(0x6000, 0x800), tiles)
        self.assertEqual(self.ram(SPIN_BM, 8), bytes(range(1, 9)), "the spinner's cell put back")
        self.assertEqual(m.ram[SPIN_SC], 0x3C)
        # and the next boot agrees
        self.assertEqual(boot_log(m.flash())[0], want)

    def test_compaction_in_the_middle_of_a_chunk_file(self):
        log, want = self.full_log(until_free=5)
        rng = __import__("random").Random(4)
        pages = [bytes([1, i + 1]) + rng.randbytes(254) for i in range(7)] + [bytes([0, 200]) + rng.randbytes(254)]
        self.save_session("SDC", pages)
        want[b"/SDC".ljust(12, b"\0")] = b"".join(pages)
        self.assertEqual(self.state()["act"], 3)
        self.assertEqual(self.logview(), want)
        self.assertEqual(self.load("SDC")[:len(strip(pages))], strip(pages))

    def test_compaction_while_pages_are_held(self):
        # the held pages' version moves with the compaction: it is looked up again
        log, want = self.full_log(until_free=5)
        f = self.sim.mem.flash()
        pages = self.disk_pages("SDC")
        changed = pages[:6] + [pages[6][:50] + b"\x00" + pages[6][51:]] + pages[7:]
        self.save_session("SDC", changed)
        want[b"/SDC".ljust(12, b"\0")] = b"".join(changed)
        self.assertEqual(self.state()["act"], 3)
        self.assertEqual(self.logview(), want)

    def test_power_cuts_through_a_compaction(self):
        log, want = self.full_log()
        start = bytes(self.sim.mem.flash())
        st0 = bytes(self.sim.mem.efram[:STATE_LEN])
        m = self.sim.mem
        m.changes = 0
        m.ram[0x5400:0x5500] = b"\x77" * 256
        self.assertEqual(self.cmd(bytes([0x26, 6, 9, 0, 0, 0x00, 0x54]), "1A"), 0)
        total = m.changes
        new = dict(want)
        new[bytes([1, 0, 6, 9]).ljust(12, b"\0")] = b"\x77" * 256
        for cut in sorted({0, 1, 2, 3, 300, total // 3, total // 2, total - 300, total - 21,
                           total - 20, total - 1}):
            sim = EFSim(start, eapi=self.eapi)
            if self.eapi == "contract":
                sim.contract_init_at(R.GAME_SLOT)
            self.sim = sim
            game = self.p["game"]
            sim.mem.ram[0x0200:0x0200 + len(game)] = game
            sim.mem.ram[0x6000:0x6000 + 0x4000] = chain(self.p, "3B", "TILES")[2:]
            sim.mem.ram[0xFFFE], sim.mem.ram[0xFFFF] = 0x26, 0x1F
            sim.mem.ram[0], sim.mem.ram[1] = 0x2F, 0x34
            sim.mem.control = 0x04
            sim.mem.efram[:STATE_LEN] = st0
            sim.mem.ram[0x5400:0x5500] = b"\x77" * 256
            sim.mem.cut_after = cut
            with self.assertRaises(PowerCut):
                sim.mem.ram[CMD:CMD + 7] = bytes([0x26, 6, 9, 0, 0, 0x00, 0x54])
                sim.mpu.x = 0
                sim.call(0x2823)
                sim.mpu.x, sim.mpu.y = CMD & 0xFF, CMD >> 8
                sim.call(0x29BE)
            view = boot_log(sim.mem.flash())[0]
            self.assertIn(view, (want, new), f"a cut after {cut} of {total} changes")


class TestEFCompactionByContract(TestEFCompaction):
    eapi = "contract"


def boot_log(flash):
    """(the log's view, efinit's state) as the next boot finds them."""
    p = built()
    sim = EFSim(flash)
    m = sim.mem
    m.ram[0x1000:0x1000 + len(p["init"])] = p["init"]
    m.control = 0x07
    sim.mpu.pc = 0x1000
    while sim.mpu.pc != 0xC00C:
        sim.mpu.step()
    st = m.efram
    logdir, count = st[0] | st[1] << 8 | st[2] << 16, st[3] | st[4] << 8
    return u6log.view(m.flash(), logdir, count), dict(act=st[0x1A], gen=st[0x1B] | st[0x1C] << 8)


@unittest.skipIf(EFSim is None, "py65 is not installed (use the repository's .venv)")
class TestEFInit(unittest.TestCase):
    """efinit.s: which half, its directory, the next free page -- the rules
    of asm/init_u6.s, on the EasyFlash's halves."""

    def run_init(self, flash):
        p = built()
        sim = EFSim(flash)
        m = sim.mem
        m.ram[0x1000:0x1000 + len(p["init"])] = p["init"]
        m.control = 0x07
        sim.traps[0xC00C] = lambda s: None          # the cold start: stop there
        sim.mpu.pc = 0x1000
        while sim.mpu.pc != 0xC00C:
            sim.mpu.step()
        st = m.efram
        return dict(logdir=st[0] | st[1] << 8 | st[2] << 16, count=st[3] | st[4] << 8,
                    logdata=st[5] | st[6] << 8 | st[7] << 16, act=st[0x1A], gen=st[0x1B] | st[0x1C] << 8,
                    sim=sim)

    def flash(self):
        return bytearray(built()["flash"])

    def test_a_fresh_cart(self):
        # no half has a header: half 0 gets a new log (the boot driver's `*`),
        # and character creation will not reset it again
        r = self.run_init(self.flash())
        self.assertEqual((r["logdir"], r["count"], r["logdata"], r["act"], r["gen"]),
                         (R.LOG_MID - 20, 1, R.LOG_LO, 0, 1))
        f = r["sim"].mem.flash()
        self.assertEqual(bytes(f[R.LOG_MID - 20:R.LOG_MID]),
                         b"\xfeLOG" + bytes(8) + bytes([1, 0, 0xFE, 0xFF]) + bytes(4))
        self.assertEqual(r["sim"].mem.efram[0x19], 1, "EF_FRESH: the world counts as reset")
        self.assertEqual(bytes(f[R.LOG_LO:R.LOG_MID - 20]), b"\xff" * (R.LOG_MID - 20 - R.LOG_LO))

    def test_whatever_the_cart_held_before_is_no_log(self):
        import random
        f = self.flash()
        rng = random.Random(5)
        f[R.LOG_LO:R.LOG_HI] = rng.randbytes(R.LOG_HI - R.LOG_LO)
        f[R.LOG_MID - 20] = 0x01                        # (the tapecart would take that as an entry)
        r = self.run_init(f)
        self.assertEqual((r["logdir"], r["count"], r["logdata"], r["act"], r["gen"]),
                         (R.LOG_MID - 20, 1, R.LOG_LO, 0, 1))
        f = r["sim"].mem.flash()
        self.assertEqual(bytes(f[R.LOG_LO:R.LOG_MID - 20]), b"\xff" * (R.LOG_MID - 20 - R.LOG_LO))

    def test_the_log_is_found(self):
        import random
        f = self.flash()
        log = u6log.Log(f, R.LOG_LO, R.LOG_MID)
        log.header(1)
        want = {}
        u6log.play(log, random.Random(3), want, until_free=300)
        r = self.run_init(f)
        self.assertEqual((r["logdir"], r["logdata"], r["act"]), (log.dir, log.data, 0))
        self.assertEqual(u6log.view(f, r["logdir"], r["count"]), want)
        p = built()
        self.assertEqual(bytes(r["sim"].mem.ram[0xC000:0xC400]), p["boot_image"])
        self.assertEqual(bytes(r["sim"].mem.ram[0xC578:0xC578 + len(p["boot_piece2"])]), p["boot_piece2"])

    def test_the_newer_half_wins(self):
        f = self.flash()
        a = u6log.Log(f, R.LOG_LO, R.LOG_MID)
        a.header(4)
        a.append(b"/SAA", [b"\x01" * 256], True)
        b = u6log.Log(f, R.LOG_MID, R.LOG_HI)
        b.header(5)
        b.append(b"/SAA", [b"\x02" * 256], True)
        r = self.run_init(f)
        self.assertEqual((r["act"], r["gen"], r["logdir"], r["logdata"]), (3, 5, b.dir, b.data))

    def test_pages_a_torn_save_left_are_skipped(self):
        f = self.flash()
        log = u6log.Log(f, R.LOG_LO, R.LOG_MID)
        log.header(1)
        log.append(b"/SAA", [b"\x01" * 256], True)
        f[log.data:log.data + 300] = b"\x00" * 300     # two pages written, no entry
        r = self.run_init(f)
        self.assertEqual(r["logdata"], log.data + 0x200)


@unittest.skipIf(EFSim is None, "py65 is not installed (use the repository's .venv)")
class TestEFBootDriver(unittest.TestCase):
    """The boot driver (efboot.s + efdrv.s EF_BOOT): character creation's
    first save-area write starts a new world in the other half."""

    def setUp(self):
        self.p = built()
        self.make(self.p["flash"])

    def make(self, flash):
        p = self.p
        self.sim = EFSim(flash)
        m = self.sim.mem
        m.ram[0xC000:0xC400] = p["boot_image"]
        m.ram[0xC578:0xC578 + len(p["boot_piece2"])] = p["boot_piece2"]
        create = chain(p, "3B", "CREATE")[2:]
        m.ram[0x0200:0x0200 + len(create)] = create
        m.ram[0xFFFE], m.ram[0xFFFF] = 0x2D, 0xC1
        m.ram[0], m.ram[1] = 0x2F, 0x35
        m.control = 0x04
        m.efram[0:0x1E] = bytes(0x1E)
        m.efram[0:3] = a24(R.LOG_MID)
        m.efram[5:8] = a24(R.LOG_LO)

    def cmd(self, cmd):
        sim = self.sim
        sim.mem.ram[0xC900:0xC900 + len(cmd)] = cmd   # (in RAM the driver sees: not $8000-$BFFF)
        sim.mpu.x, sim.mpu.y = 0x00, 0xC9
        sim.call(0xC16B)
        self.assertEqual(sim.mem.ram[1], 0x35)
        return sim.mpu.p & 1

    def test_creation_resets_the_world(self):
        f = bytearray(self.p["flash"])                 # an old world in half 0
        old = u6log.Log(f, R.LOG_LO, R.LOG_MID)
        old.append(b"/SAA", [b"\x01" * 256], True)
        self.make(f)
        m = self.sim.mem
        m.efram[0:3] = a24(old.dir)
        m.efram[3] = 1
        m.efram[5:8] = a24(old.data)
        before = bytes(m.ram[0x5800:0x5B00])
        self.assertEqual(self.cmd(b"#SU"), 0)
        m.ram[0x5400:0x5500] = b"\x66" * 256
        self.assertEqual(self.cmd(bytes([0x26, 6, 9, 0, 0, 0x00, 0x54])), 0)
        self.assertEqual(bytes(m.ram[0x5800:0x5B00]), before, "CREATE's bytes under EAPI's slot are back")
        st = m.efram
        self.assertEqual((st[0x1A], st[0x1B] | st[0x1C] << 8), (3, 1), "the other half, generation 1")
        logdir = st[0] | st[1] << 8 | st[2] << 16
        n = st[3] | st[4] << 8
        view = u6log.view(m.flash(), logdir, n)
        self.assertEqual(view, {bytes([1, 0, 6, 9]).ljust(12, b"\0"): b"\x66" * 256},
                         "the new world has the new save and nothing of the old")
        # a second write this boot does not reset again
        m.ram[0x5400:0x5500] = b"\x67" * 256
        self.assertEqual(self.cmd(bytes([0x26, 6, 9, 0, 0, 0x00, 0x54])), 0)
        self.assertEqual(st[0x1A], 3)

    def test_a_program_loaded_over_page_3(self):
        # %OPENING lands at $0200: ($0314) is the KERNAL's IRQ vector while the
        # cart is in, so the shim is put back after each run into page 3 -- and
        # what the load put there is what is left there afterwards
        want = chain(self.p, "3B", "OPENING")[2:]
        self.assertEqual(self.cmd(b"%OPENING\xff" + bytes([0x00, 0x02])), 0)
        self.assertEqual(bytes(self.sim.mem.ram[0x0200:0x0200 + len(want)]), want)

    def test_boot_reads(self):
        want = chain(self.p, "3B", "THEME")[2:]
        self.assertEqual(self.cmd(b"%THEME\xff\x00\x40"), 0)
        self.assertEqual(bytes(self.sim.mem.ram[0x4000:0x4000 + len(want)]), want)


if __name__ == "__main__":
    unittest.main()
