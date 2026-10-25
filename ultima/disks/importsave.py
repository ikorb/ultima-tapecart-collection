#!/usr/bin/env python3
"""Put a saved game found on your disks into a built cart image.

    python -m ultima.disks.importsave CART.tcrt DIR_OR_IMAGE... [-o OUT] [--game u5 ...] [--pick IMAGE]
    (make import [PICK=<image>])

The cart's base state (what the page's Reset returns to) stays what the
build made; this only fills the save area, the way a player would by
importing from disk -- it *is* the page's own "import from disk", run on the
host (ultima/sim/pagesim.py: py65, the cart and a 1541 simulated), with your
disk images in the drive.  So every format -- the journalled slots, Ultima II's
and Ultima VI's logs -- is written by the same code as on a real C64.

Which disks: for each game, the images that are its save disk (most of the
disk's units in place, ultima/disks/scan.py's manifest) and hold a game -- their
save units differ from the base, and for Ultima V the roster names an
active game.  A game with two save disks (V: 2A and 2B, VI: Surface and
Dungeon) takes the base's stand-in for one that holds nothing.  When two
images hold different saves of one disk, nothing is imported for that game
and both are named; --pick IMAGE chooses.
"""
import argparse
import collections
import json
import os
import sys
from pathlib import Path

from ultima import paths                             # noqa: E402
from ultima.disks.keys import DISKS as KEY_LABELS    # noqa: E402
from ultima.disks.d64 import D64                     # noqa: E402
from ultima.flash.tcrt import TCRT                   # noqa: E402
from ultima.flash import regions                          # noqa: E402
from ultima.disks import scan                             # noqa: E402

SAVE_DISKS = {      # each game's save disks, in the order its import asks for them
    "u1": ["u1"], "u2": ["u2b"], "u3": ["u3b"], "u4": ["u4c"],
    "u5": ["u5-2a", "u5-2b"], "u6": ["u6-1a", "u6-1b"],
}
SAME_DISK = 0.9         # of a disk's telling units, at least this many in place


def units_of(entry):
    """The disk's telling static units: (kind, key, sha)."""
    out = []
    for name, f in entry["files"].items():
        if "seed" not in f and not f.get("prot") and not f.get("template"):
            out.append(("file", name, f["sha"]))
    for key, s in entry["sectors"].items():
        if s["kind"] == "sector" and not s.get("plain"):
            out.append(("sector", key, s["sha"]))
    return out


def is_disk(im, entry):
    """(is it this disk, how many of its telling units differ)."""
    us = units_of(entry)
    have = 0
    for kind, key, sha in us:
        if kind == "file":
            have += sha in im.files
        else:
            t, s = map(int, key.split("/"))
            have += im.sectors[D64.linear(t, s)] == sha
    return have >= SAME_DISK * len(us), len(us) - have


def beyond_the_save(im, entry):
    """What of the disk outside its save units this image lacks: files by
    content, on a disk with a directory (DOS moves files about as a game
    saves; a disk that has them all is this one); else sectors in place,
    but for track 18's BAM sector, which carries an edition's own name
    ("ULTIMA III-SCEN." for the 1984 Scenario disk)."""
    files = [(n, f) for n, f in entry["files"].items() if "seed" not in f and not f.get("prot")]
    if files:
        return [n for n, f in files if f["sha"] not in im.files]
    out = []
    for key, s in entry["sectors"].items():
        if s["kind"] == "sector" and not s.get("plain") and not s.get("world") and key != "18/0":
            t, sec = map(int, key.split("/"))
            if im.sectors[D64.linear(t, sec)] != s["sha"]:
                out.append(key)
    return out


def seed_view(d, entry):
    """What the game's save units hold on a disk (a D64), as the game reads
    them: a file's load address left out (the cart's import writes the
    game's own, as its LOAD ignores the file's)."""
    out = []
    for name, f in sorted(entry["files"].items()):
        if "seed" in f:
            try:
                out.append(d.file(name)[0][2:])
            except KeyError:
                out.append(None)
    for key, s in sorted(entry["sectors"].items()):
        if s["kind"] == "seed" and "file" not in s["seed"] or s.get("world"):
            t, sec = map(int, key.split("/"))
            out.append(d.sector(t, sec))
    return out


def holds_a_game(game, disk, im):
    """The page's own test of a saved game (asm/page.s, i_u1..i_u6), on the
    disk: what it would show as one is what is worth importing -- a disk
    whose party was wiped and whose world was left played is not."""
    d = im.d
    first = disk == SAVE_DISKS[game][0]
    try:
        if game == "u1":
            ro = d.file("RO")[0][2:]
            return any(ro[i] == 0xFF for i in range(0, min(len(ro), 64), 16))
        if game == "u2":
            return d.sector(35, 16)[0] >= 0xC1              # a name: bit 7 set
        if game == "u3":
            return 1 <= d.sector(*D64.from_linear(333))[1] <= 4     # PRTY: the party's size
        if game == "u4":
            return 1 <= d.sector(*D64.from_linear(275))[0x0F] <= 8   # the party's size
        if game == "u5" and first:
            roster = d.file("ROSTER")[0]
            return len(roster) > 2 and roster[2] != 0       # else "No active game!"
    except KeyError:
        return False
    return True                     # U5's 2B, U6: the other disk's data, or the world


def as_the_page_wants(data, described):
    """A copy of a disk the scan has identified by its contents, with the BAM
    name (and ID) the page checks for: other editions and relabelled dumps
    carry other names ("ULTIMA III-SCEN." for the 1984 Scenario disk, which
    the Trilogy calls "PLAYER MASTER").  Only the copy in the simulated drive
    changes."""
    data = bytearray(data)
    o = D64.offset(18, 0)
    data[o + 0x90:o + 0xA0] = bytes.fromhex(described["bam_name"])
    if described["check_id"]:
        data[o + 0xA2:o + 0xA4] = bytes.fromhex(described["id"])
    return bytes(data)


def page_accepts(im, described):
    """The page's own check of a disk (build/xfer.json): its BAM's name, and
    for Ultima VI its ID too."""
    bam = im.d.sector(18, 0)
    if bytes(bam[0x90:0xA0]).hex() != described["bam_name"]:
        return False
    return not described["check_id"] or bytes(bam[0xA2:0xA4]).hex() == described["id"]


def candidates(manifest, images, stand_ins, xfer=None):
    """{game: {disk: [image]}} -- the images holding a game that the page
    would take for that disk."""
    if xfer is None:
        xfer = json.loads(Path(os.path.join(paths.BUILD, "xfer.json")).read_text())
    out = collections.defaultdict(dict)
    for game, disks in SAVE_DISKS.items():
        assert len(xfer[game]) == len(disks), f"{game}: the page asks for {len(xfer[game])} disks"
        for disk, described in zip(disks, xfer[game]):
            entry = manifest["disks"][disk]
            base = seed_view(D64.from_bytes(bytes(stand_ins[disk][:174848])), entry) if disk in stand_ins else None
            found = []
            for im in images:
                same, differ = is_disk(im, entry)
                if not same:
                    continue
                if game == "u6":
                    played = differ > 0         # its world is its save
                elif beyond_the_save(im, entry):
                    continue                    # another edition, or changed beyond its save
                else:
                    played = seed_view(im.d, entry) != base
                if played and holds_a_game(game, disk, im):
                    found.append(im)
            # one save per disk: the same bytes from several images is one save
            distinct = {}
            for im in found:
                key = tuple(bytes(x) if x is not None else None for x in seed_view(im.d, entry)) \
                    if game != "u6" else im.d.data
                distinct.setdefault(key, im)
            out[game][disk] = list(distinct.values())
    return out


def choose(cands, picks):
    """{game: [image or None per save disk]} for the games with one save to take;
    {game: reason} for those left alone."""
    chosen, left = {}, {}
    for game, per_disk in cands.items():
        if not any(per_disk.values()):
            continue
        sel = []
        for disk, ims in per_disk.items():
            picked = [im for im in ims if im.path in picks or os.path.basename(im.path) in picks]
            if picked:
                sel.append(picked[0])
            elif len(ims) == 1:
                sel.append(ims[0])
            elif not ims:
                sel.append(None)
            else:
                left[game] = f"{KEY_LABELS[disk]}: several saves -- " + \
                    ", ".join(os.path.basename(im.path) for im in ims) + " (choose one: make import PICK=<name>, or --pick)"
                break
        else:
            chosen[game] = sel
    return chosen, left


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cart")
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--manifest", default=scan.DEFAULT_MANIFEST)

    ap.add_argument("--game", action="append", help="only these games (u1..u6)")
    ap.add_argument("--pick", action="append", default=[], help="the image to take a save from")
    ap.add_argument("-o", "--out", help="write here instead of over CART")
    a = ap.parse_args()

    from ultima.sim import pagesim                      # py65: only needed here
    manifest = json.loads(Path(a.manifest).read_text())
    images, _skipped = scan.gather(a.paths)
    stand_ins = scan.assemble(manifest, scan.resolve(manifest, images))
    chosen, left = choose(candidates(manifest, images, stand_ins), set(a.pick))
    img = TCRT.read(a.cart)
    flash = bytearray(img.flash.ljust(regions.FLASH_SIZE, b"\xff"))
    for game in sorted(set(chosen) | set(left)):
        if a.game and game not in a.game:
            continue
        if game in left:
            print(f"{game}: not imported -- {left[game]}")
            continue
        disks = []
        xfer = json.loads(Path(os.path.join(paths.BUILD, "xfer.json")).read_text())
        for disk, im, described in zip(SAVE_DISKS[game], chosen[game], xfer[game]):
            if im is not None:
                if not page_accepts(im, described):
                    print(f"{game}: {os.path.basename(im.path)} is named "
                          f"{bytes(im.d.sector(18, 0)[0x90:0xA0]).rstrip(bytes([0xA0])).decode('latin1')!r}; "
                          f"handed to the page as {bytes.fromhex(described['bam_name']).rstrip(bytes([0xA0])).decode('latin1')!r}")
                disks.append(as_the_page_wants(im.d.data, described))
            elif disk in stand_ins:
                disks.append(bytes(stand_ins[disk][:174848]))
            else:
                break
        else:
            flash, text, done = pagesim.import_from_disks(flash, game, disks)
            srcs = ", ".join(os.path.basename(im.path) for im in chosen[game] if im is not None)
            if done:
                print(f"{game}: imported from {srcs}")
            else:
                print(f"{game}: the import failed ({srcs}):\n" + text[-300:])
            continue
        print(f"{game}: not imported -- a save disk is missing from the images")
    img.flash = bytes(flash)            # the whole 2 MiB: the saves are at its top
    img.write(a.out or a.cart, trim=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
