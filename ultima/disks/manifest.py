#!/usr/bin/env python3
"""The release manifest: what the build needs from the original disks, by hash.

Maintainer side.  Runs every game's build (`parts()`) against a set of
reference images with the D64 reader traced, and writes one entry per disk
(by its key, ultima/disks/keys.py) listing every sector the build read, how
it read it, and its hash -- never the bytes; a directory travels as fields
(the BAM's map, name and ID, each entry's type, start, name and size).

    ULTIMA_DISKS=<dir> python3 -m ultima.disks.manifest [out.json]

<dir> holds the reference images as <key>.d64, error maps included (they
tell the copy protection's unreadable sectors).  The default output is the
manifest the repository ships, ultima/disks/manifest.json.

How a sector was read decides how a user's image may supply it:

  file       read through the directory (D64.file/payload/chain) -- the unit
             is the file's content, matched by hash in any image, wherever
             it lies; the reference chain says where to put it back
  sector     read by position (raw blocks, U3's catalog, U4's whole disks) --
             matched by hash, preferably at the same track/sector
  dir        the directory and BAM chain of track 18: shipped as metadata
  prot       flagged unreadable in the reference's error map: the copy
             protection; the build patches its check out, so it is not needed
  seed:...   a unit the game writes: its base content is generated or rebuilt
             from a template on the same disks (SEEDS), not taken from the
             user's disk -- which may hold a saved game, offered as an import

Everything not a seed must match exactly: played world data (U3's SOSA, U6's
chunk files) is refused, with a diagnosis, by ultima/disks/scan.py.  Three
kinds of sector are matched after bytes are put in: a known variant
(FIXUPS, a hash of its own); U6's save area after a new character and U3
side B's label (RESETS: those fields with any content, then the reference's
hash); U3's played SOSA (ultima/disks/world.py: what play wrote, put back
from what the disk records, then the reference's hash).
"""
import collections
import hashlib
import importlib.util
import json
import os
import sys

from ultima import paths                             # noqa: E402
from ultima.disks.keys import DISKS as KEYS          # noqa: E402
from ultima.disks import d64 as d64mod                    # noqa: E402
from ultima.disks.d64 import D64                     # noqa: E402

GAMES = ["u0", "u1", "u2", "u3", "u4", "u5", "u6"]
VERSION = 1


def h(data):
    return hashlib.sha256(bytes(data)).hexdigest()[:32]


# ---- the units the games write, and their base content -----------------------
# Each rule makes the unit's base bytes from the reference disk set *without*
# copying game data into this file: a fill, a few bytes set, or a template that
# is itself a static unit on the disks given.  Where the base differs from
# the reference disk's bytes it says so (U5's are residue on the master).
# Evidence: the games' notes, "What play writes, and the pristine state".
U1, U2B, U3B, U4A, U4C, U5A, U5B = "u1", "u2b", "u3b", "u4a", "u4c", "u5-2a", "u5-2b"

SEEDS = {
    # (disk, file name) or (disk, (first block, count)) -> rule
    # file rules: "header" is the load address the file starts with, "len"
    # the bytes after it.  U1's RO is $2000 on the master (written by some
    # tool, its notes say); the cart ignores it, and $B000 is what the game
    # writes -- but the base keeps the master's, so a build is unchanged.
    (U1, "RO"): {"header": 0x2000, "fill": 0, "len": 64},
    (U2B, (D64.linear(35, 16), 1)): {"fill": 0},    # the player record
    (U3B, (327, 5)): {"fill": 0},                   # ROST
    (U3B, (332, 1)): {"fill": 0},                   # PLRS
    (U3B, (333, 1)): {"fill": 0, "set": {4: 0x08, 5: 0xFF}},   # PRTY
    (U3B, (312, 1)): {"fill": 0, "set": {0xFC: 0x02}},          # SOSM
    (U4C, (271, 2)): {"fill": 0},
    (U4C, (273, 2)): {"template": [U4A, 254, 2]},
    (U4C, (275, 1)): {"template": [U4A, 256, 1], "set": {0x0F: 0x00}},
    (U5A, "ROSTER"): {"header": 0x1000, "fill": 0, "len": 1025, "differs": "the master's residue"},
    (U5A, "PRTY.DATA"): {"header": 0xBC00, "fill": 0, "len": 48, "differs": "the master's residue"},
    (U5A, "LIST"): {"header": 0x4A00, "fill": 0, "len": 512, "differs": "the master's residue"},
    (U5A, "SLIST"): {"header": 0x4A00, "fill": 0, "len": 512, "differs": "the master's residue"},
    (U5A, "TLIST"): {"header": 0x4A00, "fill": 0, "len": 512, "differs": "the master's residue"},
    (U5B, "TLIST"): {"template_file": [U5B, "BLANK.ULIST"]},
}
for n in ("00", "10", "20", "30", "40"):
    SEEDS[(U2B, f"MON {n}")] = {"template_file": [U2B, f"MONX{n}"]}
    SEEDS[(U2B, f"MOB {n}")] = {"template_file": [U2B, f"MOBX{n}"]}


# ---- world data: written by the game, with no base to generate --------------
# Static units the scan must find pristine, which a played disk carries as
# part of its saved game (the import takes them along): U3's SOSA, the map of
# Sosaria (docs/developer/u3.md), put back by ultima/disks/world.py where the
# disk records what play wrote.  (U6's world is all of its Surface and
# Dungeon's files and save area; ultima/disks/importsave.py takes those whole.)
WORLD = {
    U3B: {f"{t}/{s}" for b in range(296, 312) for t, s in [D64.from_linear(b)]},
}


# ---- known variants of a static unit, and how they become the reference -------
# A sector the cart takes as the reference has it, but which some editions or
# dumps have otherwise: (disk, (t, s)) -> [(offset, theirs, ours, why)].  The
# manifest carries the variant's hash, computed from the reference sector with
# their bytes put in -- nothing of anyone's dump is copied here.
U4D = "u4d"
FIXUPS = {
    # Covetous, room 11, tile (7, 5): the 1986 dumps have a wall under a
    # monster, cutting the trigger's exit off; the Trilogy has floor, a bug
    # fix the cart always takes (docs/developer/u4.md)
    (U4D, (4, 13)): [(0xBE, 0x7F, 0x16, "Covetous room 11: the wall at (7, 5), the Trilogy's floor")],
}


# ---- what a new character writes, put back to the factory state -----------------
# U6's CREATE writes the Surface disk's save area (T6 S9-20, $5400-$5FFF in
# RAM) from its template and touches no object file, so a disk on which a
# character was made and never saved holds an unplayed world.  It differs
# from the factory state only in the fields below: they are taken with any
# content, the factory's bytes go back, and the sector must then match the
# reference's hash.  (disk, (t, s)) -> [(offset, the factory's bytes, why)]
U6A = "u6-1a"
U6_STATE = 0x5400                       # T6 S9
_U6_TABLES = bytearray(0xFF if i % 2 == 0 else 0x00 for i in range(80))
_U6_TABLES[0x23], _U6_TABLES[0x24] = 0x98, 0x00
U6_NEW_CHARACTER = [                    # (RAM address, the factory's bytes)
    (0x5700, b"\x20" * 9),              # the Avatar's name, blank
    (0x578C, b"\x12"),                  # strength
    (0x57A3, b"\x14"),                  # dexterity
    (0x57D1, b"\x16"),                  # intelligence
    (0x5844, b"\x2C"),                  # magic points
    (0x588B, b"\x00"),                  # sex
    (0x5FB0, bytes(_U6_TABLES)),        # five 16-byte tables
]
RESETS = collections.defaultdict(list)
for _addr, _bytes in U6_NEW_CHARACTER:
    RESETS[(U6A, (6, 9 + ((_addr - U6_STATE) >> 8)))].append(
        ((_addr - U6_STATE) & 0xFF, _bytes, "a new character, never saved: the factory state put back"))
# U3's side B is matched by position, track 18 too; of its BAM sector the build
# takes the label, for export and import's disk check (ultima/games/u3/build.py).
# The 1984 edition's Scenario disk differs from the Trilogy's Player Master in
# the label alone ($90-$A9: name, ID, DOS type), and copies of it are relabelled:
# any label is taken, the Player Master's put back.
RESETS[(U3B, (18, 0))].append(
    (0x90, b"PLAYER MASTER" + b"\xa0" * 5 + b"64\xa02A" + b"\xa0" * 3,
     "another label (the 1984 Scenario disk's): the Player Master's put back"))
RESETS = dict(RESETS)


def reset_entry(disk, t, s, data):
    """A sector's "reset" in the manifest: offset -> the factory's byte, from
    RESETS, each checked against the reference sector `data`."""
    sets, why = {}, []
    for off, ours, reason in RESETS[(disk, (t, s))]:
        assert data[off:off + len(ours)] == ours, f"{disk} {t}/{s} +{off:#x} is not the reference's"
        sets.update((off + i, b) for i, b in enumerate(ours))
        why += [reason] if reason not in why else []
    return {"set": sets, "why": "; ".join(why)}


# ---- tracing the builds --------------------------------------------------------
class Trace:
    def __init__(self):
        self.reads = collections.defaultdict(set)          # disk -> {(t, s)}
        self.filereads = collections.defaultdict(set)      # disk -> {(t, s)} via chain
        self.rawreads = collections.defaultdict(set)       # disk -> {(t, s)} not via chain
        self.files = collections.defaultdict(set)          # disk -> {start (t, s)}
        self.whole = set()                                 # disks a build took .data of
        self.chain_depth = 0
        self.dir_depth = 0
        self.inside = 0                                    # in a D64 method

    def install(self):
        trace = self

        def rel(d):
            """The disk's key: a stand-in is <key>.d64 (paths.disk)."""
            return os.path.basename(d.path)[:-4]

        def internal(fn):
            def wrapped(d, *a, **k):
                trace.inside += 1
                try:
                    return fn(d, *a, **k)
                finally:
                    trace.inside -= 1
            return wrapped

        orig_sector, orig_chain = D64.sector, D64.chain

        def sector(d, t, s):
            key = rel(d)
            trace.reads[key].add((t, s))
            if trace.chain_depth:
                trace.filereads[key].add((t, s))
            elif not trace.dir_depth:
                trace.rawreads[key].add((t, s))
            return orig_sector(d, t, s)

        def chain(d, t, s):
            trace.files[rel(d)].add((t, s))
            trace.chain_depth += 1
            try:
                return orig_chain(d, t, s)
            finally:
                trace.chain_depth -= 1

        orig_directory = D64.directory

        def directory(d):
            trace.dir_depth += 1
            try:
                return orig_directory(d)
            finally:
                trace.dir_depth -= 1
        D64.directory = directory
        for name in ("__init__", "directory", "file", "payload", "error", "bad_sectors"):
            setattr(D64, name, internal(getattr(D64, name)))
        D64.sector, D64.chain = internal(sector), internal(chain)

        # d.data outside D64's own methods: a build slicing the whole disk
        def get_data(d):
            if not trace.inside:
                trace.whole.add(rel(d))
            return d._data

        def set_data(d, value):
            d._data = value
        D64.data = property(get_data, set_data)


def trace_builds():
    """The reads of every game's build on the reference disks: no cart, so the
    flash regions are not checked (regions.unchecked)."""
    from ultima.flash import regions
    t = Trace()
    t.install()
    with regions.unchecked():
        for g in GAMES:
            importlib.import_module(f"ultima.games.{g}.build").parts()
            print(f"  traced {g}", file=sys.stderr)
    return t


# ---- classifying -----------------------------------------------------------------
def dir_chain(d):
    """Track-18 sectors of the BAM and the directory chain, if the disk has one."""
    out = {(18, 0)}
    t, s = 18, 1
    while t == 18 and (t, s) not in out and s < 19:
        out.add((t, s))
        blk = D64.sector(d, t, s)
        t, s = blk[0], blk[1]
    return out


def file_index(d):
    """start (t, s) -> (name, [(t, s), ...]) for every directory entry."""
    out = {}
    try:
        entries = d.directory()
    except ValueError:
        return out
    for name, _typ, t, s, _blocks in entries:
        chain, seen = [], set()
        while t and 1 <= t <= 35 and (t, s) not in seen:
            seen.add((t, s))
            chain.append((t, s))
            try:
                blk = D64.sector(d, t, s)
            except ValueError:
                break
            t, s = blk[0], blk[1]
        out[chain[0] if chain else (t, s)] = (name, chain)
    return out


def meta(d):
    """A disk's directory as fields, to rebuild a standard CBM track 18 from:
    the BAM's allocation map, disk name and ID, and each directory sector's
    eight entries (type, start, name, blocks).  Nothing else of track 18 --
    what was there in unused bytes, scratched entries -- is kept."""
    bam = D64.sector(d, 18, 0)
    sectors = []
    t, s = bam[0], bam[1]
    seen = set()
    while t == 18 and (t, s) not in seen:
        seen.add((t, s))
        blk = D64.sector(d, t, s)
        entries = []
        for e in range(8):
            ent = blk[e * 32:(e + 1) * 32]
            if ent[2] & 0x80:
                entries.append({"slot": e, "type": ent[2], "start": [ent[3], ent[4]],
                                "name": bytes(ent[5:21]).hex(), "blocks": ent[30] | ent[31] << 8})
        sectors.append({"at": [t, s], "entries": entries})
        t, s = blk[0], blk[1]
    return {"dos": bam[2], "bam": bytes(bam[4:0x90]).hex(), "name": bytes(bam[0x90:0xA0]).hex(),
            "id": bytes(bam[0xA2:0xA4]).hex(), "dostype": bytes(bam[0xA5:0xA7]).hex(),
            "dir": sectors}


def has_directory(d):
    """A real CBM directory: 18/0 points at 18/x and the entries parse."""
    bam = D64.sector(d, 18, 0)
    if bam[0] != 18 or bam[2] not in (0x41, 0x00):
        return False
    try:
        return bool(d.directory())
    except ValueError:
        return False


def seed_rules(disk):
    return {k[1]: v for k, v in SEEDS.items() if k[0] == disk}


def build_manifest(trace):
    # what the builds read, frozen: reading the disks below goes through the
    # traced D64 too, and must not count as a build's reads
    import copy
    trace = copy.copy(trace)
    for name in ("reads", "filereads", "rawreads", "files"):
        setattr(trace, name, {k: set(v) for k, v in getattr(trace, name).items()})
    trace.whole = set(trace.whole)
    for name in ("reads", "filereads", "rawreads", "files"):
        setattr(trace, name, collections.defaultdict(set, getattr(trace, name)))
    disks = {}
    for disk in sorted(set(trace.reads) | trace.whole):
        if disk not in KEYS:
            continue
        d = D64(paths.disk(disk))
        reads = set(trace.reads[disk])
        if disk in trace.whole:
            reads |= {D64.from_linear(b) for b in range(d64mod.TOTAL_SECTORS)}
        directory = dir_chain(d) if has_directory(d) else set()
        # Track 18 is the game's data where a build reads a sector of it that
        # is not the directory's (U6's Surface and Dungeon: their block maps
        # take all of it): then its directory sectors are data too, matched
        # like any other.  Elsewhere they are rebuilt from "meta".
        t18_data = any(t == 18 and (t, s) not in directory for t, s in trace.rawreads[disk])
        index = file_index(d) if directory else {}
        rules = seed_rules(disk)
        by_name = {name: chain for name, chain in index.values()}

        files = {}
        for start in sorted(trace.files[disk]):
            if start not in index:
                continue
            name, chain = index[start]
            if any(x not in trace.filereads[disk] for x in chain):
                continue
            content, ok = d.chain(*start)
            files[name] = {"sha": h(content), "len": len(content), "chain": chain}
            if not ok:          # crosses an unreadable sector: the protection's
                files[name]["prot"] = True
            if name in rules:
                files[name]["seed"] = rules[name]
        # a sector also read raw (or the whole disk taken) is a positional
        # unit too, all 256 bytes of it: the tail after a file's end counts
        raw = set(trace.rawreads[disk])
        if disk in trace.whole:
            raw |= reads
        in_files = {x for f in files.values() for x in map(tuple, f["chain"])} - raw
        seeded = {}
        for name, f in files.items():           # a seeded file's sectors, raw-read too
            if "seed" in f:
                for x in map(tuple, f["chain"]):
                    seeded[x] = {"file": name}
        for key, rule in rules.items():
            if isinstance(key, tuple):
                first, count = key
                for b in range(first, first + count):
                    seeded[D64.from_linear(b)] = dict(rule, block=b - first, of=key)

        sectors = {}
        for t, s in sorted(reads):
            if (t, s) in in_files and (t, s) not in seeded:
                continue
            data = D64.sector(d, t, s)
            if (t, s) in directory and not t18_data:
                kind = "dir"
            elif d.error(t, s) != d64mod.ERROR_OK:
                kind = "prot"
            elif (t, s) in seeded:
                kind = "seed"
            else:
                kind = "sector"
            entry = {"sha": h(data), "kind": kind}
            if len(set(data)) <= 2:     # a fill: in any image, says nothing of which disk
                entry["plain"] = True
            if f"{t}/{s}" in WORLD.get(disk, ()):
                entry["world"] = True
            if (disk, (t, s)) in FIXUPS:
                theirs = bytearray(data)
                sets, why = {}, []
                for off, their, our, reason in FIXUPS[(disk, (t, s))]:
                    assert data[off] == our, f"{disk} {t}/{s} +{off:#x} is not the reference's"
                    theirs[off] = their
                    sets[off] = our
                    why.append(reason)
                entry["alt"] = [{"sha": h(theirs), "set": sets, "why": "; ".join(why)}]
            if (disk, (t, s)) in RESETS:
                entry["reset"] = reset_entry(disk, t, s, data)
            if kind == "seed":
                entry["seed"] = seeded[(t, s)]
            sectors[f"{t}/{s}"] = entry
        missing = [n for n in rules if isinstance(n, str) and n not in files]
        if missing:
            raise SystemExit(f"{disk}: seed rules for files the build did not read: {missing}")
        disks[disk] = {"files": files, "sectors": sectors,
                       "meta": None if t18_data or not directory else meta(d),
                       "whole": disk in trace.whole,
                       "templates": sorted({n for r in rules.values()
                                            for n in [r.get("template_file", [None, None])[1]] if n})}
        for name in disks[disk]["templates"]:
            if name not in files:
                content, _ok = d.file(name)
                files[name] = {"sha": h(content), "len": len(content),
                               "chain": by_name[name], "template": True}
    return {"version": VERSION, "disks": disks}


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                             "manifest.json")

    m = build_manifest(trace_builds())
    with open(out, "w") as fh:
        json.dump(m, fh, indent=1, default=lambda o: sorted(o) if isinstance(o, set) else o)
    for disk, e in m["disks"].items():
        kinds = collections.Counter(s["kind"] for s in e["sectors"].values())
        print(f"{disk}: {len(e['files'])} files, " +
              ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    print(f"-> {out} ({os.path.getsize(out) // 1024} KiB)")


if __name__ == "__main__":
    main()
