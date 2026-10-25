#!/usr/bin/env python3
"""Find what the build needs in a pile of disk images.

    python3 -m ultima.disks.scan [--write build/disks] DIR_OR_IMAGE...   (make disks)

Names do not matter and neither does which image a unit comes from: every
unit the manifest lists (ultima/disks/manifest.py) is looked up by hash in every

image given -- a file by its content wherever it lies, a sector preferably at
its own track/sector.  Each reference disk is then complete, or the report
says which units are missing and what the closest image has instead.

assemble() builds, for every complete reference disk (and the disks its
save templates are on), an image the game builds can read in its place: the units where the reference had them, the
directory from the manifest, the games' save units at their base content
(generated or from a template), zeros elsewhere.
"""
import argparse
import collections
import glob
import hashlib
import json
import os
import sys

from ultima.disks.d64 import D64, TOTAL_SECTORS, DATA_LENGTH     # noqa: E402
from ultima.disks.keys import DISKS as KEY_LABELS, GAMES as KEY_GAMES, game_of   # noqa: E402

from ultima.disks import images, world                                # noqa: E402
import zipfile                                      # noqa: E402
from pathlib import Path

GAME_NAMES = KEY_GAMES
DEFAULT_MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "manifest.json")

# What a mismatch most likely means, where it is known.  Keyed by disk;
# each entry: (file names or "t/s" sectors or None for any, message).
HINTS = {
    "u3b": [
        ({f"{t}/{s}" for b in range(296, 312) for t, s in [D64.from_linear(b)]},
         "SOSA, the map of Sosaria, differs even with what play leaves on it put back "
         "(monsters, chests, craft, the whirlpool, the moon gate): this Player Master's "
         "map has been changed in a way the disk does not record. A fresh, unplayed copy "
         "is needed."),
    ],
    "u6-1a": [
        (None, "the world differs: this disk has been played and saved (Ultima VI "
               "keeps its world on the Surface and Dungeon disks and never resets "
               "it; a character made on it and never saved is fine). "
               "A fresh, unplayed copy is needed."),
    ],
    "u6-1b": [
        (None, "the world differs: this disk has been played. A fresh, unplayed "
               "copy is needed."),
    ],
    "u2a": [
        ({"INTRO", "ULT"}, "INTRO is not a file on this disk: Sierra's 1984 edition "
                           "packs it into its boot file and differs from Origin's. "
                           "The cart needs the Origin (Ultima Trilogy) side A; side B "
                           "from either edition works."),
    ],
}


def h(data):
    return hashlib.sha256(bytes(data)).hexdigest()[:32]


def reset(sector, rule):
    """A sector with a rule's bytes put in (the manifest's "alt" and "reset")."""
    out = bytearray(sector)
    for off, val in rule["set"].items():
        out[int(off)] = val
    return bytes(out)


# ---- the images -----------------------------------------------------------------
class Image:
    def __init__(self, label, data, errmap=b""):
        self.path = label
        self.d = D64.from_bytes(data, errmap, label)
        self.sectors = [h(self.d.data[i * 256:(i + 1) * 256]) for i in range(TOTAL_SECTORS)]
        self.files = {}                         # content hash -> name
        self.by_name = {}                       # name -> content
        try:
            for name, _typ, t, s, _b in self.d.directory():
                try:
                    data, _ok = self.d.chain(t, s)
                except ValueError:
                    continue
                self.files.setdefault(h(data), name)
                self.by_name.setdefault(name, data)
        except ValueError:
            pass


def gather(paths):
    """Every disk image under the given paths: .d64 (35 or 40 tracks, with or
    without an error map), .g64, and zips of them (ultima/disks/images.py)."""
    found, skipped = [], []
    for p in paths:
        cands = sorted(glob.glob(os.path.join(p, "**", "*"), recursive=True)) if os.path.isdir(p) else [p]
        for c in cands:
            if not os.path.isfile(c):
                continue
            try:
                got = images.read(c)
            except (ValueError, OSError, zipfile.BadZipFile):
                got = None
            if got:
                for label, data, errmap in got:
                    found.append(Image(os.path.join(os.path.dirname(c), label), data, errmap))
            elif c.lower().endswith(images.EXTENSIONS + (".nib", ".d71", ".d81")):
                skipped.append(c)
    return found, skipped


# ---- resolving -------------------------------------------------------------------
def index(images):
    sec_at = collections.defaultdict(list)      # (pos, hash) -> [(image, pos)]
    sec_any = collections.defaultdict(list)     # hash -> [(image, pos)]
    files = collections.defaultdict(list)       # hash -> [(image, name)]
    for im in images:
        for i, s in enumerate(im.sectors):
            sec_at[(i, s)].append((im, i))
            sec_any[s].append((im, i))
        for s, name in im.files.items():
            files[s].append((im, name))
    return sec_at, sec_any, files


def resolve(manifest, images):
    """Per reference disk: where each unit comes from, and what is missing.
    Each disk prefers one image -- the one holding most of it in place -- so
    that an empty sector does not come from some other game's disk."""
    sec_at, sec_any, files = index(images)
    result = {}
    for disk, e in manifest["disks"].items():
        units = []
        put_back = {}                               # image -> {block: rule}, world.put_back
        for name, f in e["files"].items():
            if "seed" not in f and not f.get("prot"):
                units.append((("file", name), files.get(f["sha"], []), len(f["chain"])))
        for key, s in e["sectors"].items():
            if s["kind"] == "sector":
                t, sec = map(int, key.split("/"))
                pos = D64.linear(t, sec)
                srcs = sec_at.get((pos, s["sha"]), []) + sec_any.get(s["sha"], [])
                for alt in s.get("alt", []):        # a known variant, fixed up
                    srcs += [(im, p, alt) for im, p in
                             sec_at.get((pos, alt["sha"]), []) + sec_any.get(alt["sha"], [])]
                if "reset" in s:                    # fields put back, then the reference's hash
                    srcs += [(im, pos, s["reset"]) for im in images
                             if (im, pos) not in srcs and h(reset(im.d.data[pos * 256:(pos + 1) * 256],
                                                                  s["reset"])) == s["sha"]]
                if s.get("world"):                  # what play wrote, put back from the disk's records
                    for im in images:
                        if im not in put_back:
                            put_back[im] = world.put_back(disk, im.d.data)
                        rule = put_back[im].get(pos)
                        if rule and h(reset(im.d.data[pos * 256:(pos + 1) * 256], rule)) == s["sha"]:
                            srcs.append((im, pos, rule))
                units.append((("sector", key), srcs, 0 if s.get("plain") else 1))
        votes = collections.Counter()
        for _key, srcs, weight in units:
            for im in {x[0] for x in srcs}:
                votes[im.path] += weight
        closest = max(votes, key=lambda p: (votes[p], p)) if votes else None
        got, missing = {}, []
        for key, srcs, _weight in units:
            if not srcs:
                missing.append(key)
                continue
            mine = [x for x in srcs if x[0].path == closest]
            exact = [x for x in mine or srcs if len(x) == 2]    # the reference's own first
            got[key] = (exact or mine or srcs)[0]
        telling = [k for k, srcs, w in units if w]
        found = sum(1 for k, srcs, w in units if w and srcs)
        result[disk] = {"got": got, "missing": missing, "closest": closest,
                        "present": found >= len(telling) / 2}
    return result


def diagnose(disk, entry, res, images):
    """A sentence or two per missing group, from HINTS or from the closest image."""
    if not res["missing"]:
        return []
    if not res["present"]:
        return ["not found: none of the images is this disk"]
    names = {k for kind, k in res["missing"]}
    out = []
    for keys, msg in HINTS.get(disk, []):
        if keys is None or names & keys:
            out.append(msg)
    if out:
        return out
    im = next((i for i in images if i.path == res["closest"]), None)
    nfile = sum(1 for kind, _ in res["missing"] if kind == "file")
    nsec = len(res["missing"]) - nfile
    detail = []
    for kind, k in res["missing"][:6]:
        if kind == "file":
            theirs = im.by_name.get(k) if im else None
            detail.append(f"{k} ({'not on it' if theirs is None else 'differs'})")
        else:
            detail.append(k)
    more = " ..." if len(res["missing"]) > 6 else ""
    where = f" -- the closest image is {os.path.basename(res['closest'])}" if res["closest"] else \
        " -- no image has anything of it"
    out.append(f"{nfile} files and {nsec} sectors not found{where}: {', '.join(detail)}{more}")
    return out


def report(manifest, images, skipped, resolution):
    games = collections.defaultdict(list)
    for disk in manifest["disks"]:
        games[game_of(disk)].append(disk)
    ok_games = 0
    for g in sorted(games):
        disks = games[g]
        complete = all(not resolution[d]["missing"] for d in disks)
        ok_games += complete
        print(f"{GAME_NAMES[g]}: {'complete' if complete else 'INCOMPLETE'}")
        for d in disks:
            r = resolution[d]
            label = KEY_LABELS.get(d, d)
            srcs = sorted({os.path.basename(x[0].path) for x in r["got"].values()})
            fixed = sorted({x[2]["why"] for x in r["got"].values() if len(x) == 3})
            if not r["missing"]:
                print(f"   {label}: from {', '.join(srcs)}")
                for why in fixed:
                    print(f"      fixed: {why}")
            else:
                print(f"   {label}: missing {len(r['missing'])} units")
                for line in diagnose(d, manifest["disks"][d], r, images):
                    print(f"      {line}")
    print(f"\n{ok_games} of {len(games)} games complete, from {len(images)} images"
          + (f"; {len(skipped)} not read ({', '.join(os.path.basename(x) for x in skipped[:3])}"
             f"{' ...' if len(skipped) > 3 else ''}: not a .d64, .g64 or zip of them)" if skipped else ""))
    return ok_games == len(games)


# ---- assembling ------------------------------------------------------------------
def _seed_bytes(rule, length, images_by_disk, manifest):
    if "fill" in rule:
        out = bytearray([rule["fill"]]) * rule.get("len", length)
    elif "template" in rule:
        disk, first, count = rule["template"]
        img = images_by_disk[disk]
        out = bytearray(img[first * 256:(first + count) * 256])
    elif "template_file" in rule:
        disk, name = rule["template_file"]
        out = bytearray(_file_bytes(images_by_disk[disk], manifest["disks"][disk]["files"][name]))
    else:
        raise ValueError(f"no rule in {rule}")
    for k, v in rule.get("set", {}).items():
        out[int(k)] = v
    if "header" in rule:
        out = bytearray([rule["header"] & 0xFF, rule["header"] >> 8]) + out
    return out


def _file_bytes(img, f):
    out = bytearray()
    chain = [tuple(x) for x in f["chain"]]
    for i, (t, s) in enumerate(chain):
        o = D64.offset(t, s)
        last = i == len(chain) - 1
        n = (img[o + 1] - 1) if last else 254
        out += img[o + 2:o + 2 + n]
    return bytes(out)


def _put_file(img, chain, content):
    """content into the reference chain, with the chain's own links."""
    chain = [tuple(x) for x in chain]
    for i, (t, s) in enumerate(chain):
        o = D64.offset(t, s)
        part = content[i * 254:(i + 1) * 254]
        if i + 1 < len(chain):
            img[o], img[o + 1] = chain[i + 1]
        else:
            img[o], img[o + 1] = 0, len(part) + 1
        img[o + 2:o + 2 + len(part)] = part


def write_directory(img, m):
    """A standard CBM track 18 from the manifest's fields: the BAM (link to
    the first directory sector, DOS version, allocation map, name, ID, DOS
    type, $A0 where the DOS writes it) and the directory sectors where the
    reference had them, each entry's unused bytes zero."""
    o = D64.offset(18, 0)
    bam = bytearray(256)
    first = m["dir"][0]["at"] if m["dir"] else [0, 0xFF]
    bam[0], bam[1], bam[2] = first[0], first[1], m["dos"]
    bam[4:0x90] = bytes.fromhex(m["bam"])
    bam[0x90:0xAB] = b"\xa0" * (0xAB - 0x90)
    bam[0x90:0xA0] = bytes.fromhex(m["name"])
    bam[0xA2:0xA4] = bytes.fromhex(m["id"])
    bam[0xA5:0xA7] = bytes.fromhex(m["dostype"])
    img[o:o + 256] = bam
    for i, sec in enumerate(m["dir"]):
        blk = bytearray(256)
        if i + 1 < len(m["dir"]):
            blk[0], blk[1] = m["dir"][i + 1]["at"]
        else:
            blk[0], blk[1] = 0, 0xFF
        for ent in sec["entries"]:
            b = ent["slot"] * 32
            blk[b + 2] = ent["type"]
            blk[b + 3], blk[b + 4] = ent["start"]
            blk[b + 5:b + 21] = bytes.fromhex(ent["name"])
            blk[b + 30], blk[b + 31] = ent["blocks"] & 0xFF, ent["blocks"] >> 8
        o = D64.offset(*sec["at"])
        img[o:o + 256] = blk


def _template_disks(e):
    """The disks a disk's save units take their base content from."""
    rules = [f["seed"] for f in e["files"].values() if "seed" in f]
    rules += [s["seed"] for s in e["sectors"].values() if s["kind"] == "seed"]
    return {r[k][0] for r in rules for k in ("template", "template_file") if k in r}


def assemble(manifest, resolution):
    """{reference disk: image bytes} for every complete disk whose templates'
    disks are complete too (U4's Britannia takes its save from the program
    disk)."""
    images = {}
    for disk, e in manifest["disks"].items():
        r = resolution[disk]
        if r["missing"]:
            continue
        img = bytearray(DATA_LENGTH)
        if e.get("meta"):
            write_directory(img, e["meta"])
        for (kind, key), (im, where, *fix) in r["got"].items():
            if kind == "sector":
                t, sec = map(int, key.split("/"))
                o = D64.offset(t, sec)
                data = im.d.data[where * 256:(where + 1) * 256]
                img[o:o + 256] = reset(data, fix[0]) if fix else data
            else:
                data, _ok = im.d.file(where)
                _put_file(img, e["files"][key]["chain"], data)
        images[disk] = img
    for disk, e in manifest["disks"].items():
        if disk in images and not _template_disks(e) <= images.keys():
            del images[disk]
    # the save units, once every template is in place
    for disk, e in manifest["disks"].items():
        if disk not in images:
            continue
        img = images[disk]
        for name, f in e["files"].items():
            if "seed" in f:
                _put_file(img, f["chain"], _seed_bytes(f["seed"], f["len"], images, manifest))
            elif f.get("prot"):         # what a read of it gives does not matter
                _put_file(img, f["chain"], bytes(f["len"]))
        done = set()
        for key, s in e["sectors"].items():
            if s["kind"] != "seed" or "file" in s["seed"]:
                continue                    # (a seeded file's sectors: written above)
            rule = s["seed"]
            of = tuple(rule["of"])
            if of in done:
                continue
            done.add(of)
            first, count = of
            data = _seed_bytes(rule, count * 256, images, manifest)
            data = bytes(data) + bytes(count * 256 - len(data))
            for b in range(count):
                t, sec = D64.from_linear(first + b)
                o = D64.offset(t, sec)
                img[o:o + 256] = data[b * 256:(b + 1) * 256]
    return images


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--manifest", default=DEFAULT_MANIFEST)
    ap.add_argument("--write", metavar="DIR", help="write a stand-in <key>.d64 for every disk "
                    "found complete, and DIR/.complete when all of them are")
    a = ap.parse_args()
    manifest = json.loads(Path(a.manifest).read_text())
    images, skipped = gather(a.paths)
    resolution = resolve(manifest, images)
    complete = report(manifest, images, skipped, resolution)
    if a.write:
        write_stand_ins(a.write, assemble(manifest, resolution), complete)
    return 0 if complete else 1


def write_stand_ins(where, stand_ins, complete):
    """The assembled disks as files the build reads (paths.disk), each
    rewritten only when it changes, so make sees what is new."""
    os.makedirs(where, exist_ok=True)
    marker = os.path.join(where, ".complete")
    for key, img in stand_ins.items():
        p = os.path.join(where, key + ".d64")
        if os.path.islink(p) or not os.path.exists(p) or Path(p).read_bytes() != bytes(img):
            if os.path.lexists(p):
                os.remove(p)
            with open(p, "wb") as fh:
                fh.write(bytes(img))
    if complete:
        Path(marker).write_text("every disk the build needs is here\n")
    elif os.path.exists(marker):
        os.remove(marker)



if __name__ == "__main__":
    sys.exit(main())
