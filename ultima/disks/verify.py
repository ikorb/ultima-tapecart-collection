#!/usr/bin/env python3
"""Build every game from images the scanner assembled, and compare.

    ULTIMA_DISKS=<reference dir> python -m ultima.disks.verify [--exact] DIR_OR_IMAGE...

Maintainer side.  Scans the given images (ultima/disks/scan.py), assembles a
stand-in for every disk, runs each game's parts() once on the reference
images (<key>.d64 in ULTIMA_DISKS, as for the manifest) and once with D64
handed the stand-ins instead, and compares the two results: every byte the
game builds put out, by hash.

Known differences, which are the point (docs/developer/disks.md):
  u4  the protection track 6 on disk A: zeros, not the dump's noise
  u5  the save slots' base: the empty state, not the master's residue -- in
      the slots, and in the raw runs that span the save files' sectors, so
      the data after them and the addresses into it differ too

The runs on the reference disks (and with --exact, on the stand-ins with
the reference's bytes put back) make no cart: they are not held to the
flash regions (regions.unchecked), since the master's residue compresses
worse than the base.
"""
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

from ultima import paths                             # noqa: E402
from ultima.disks import d64 as d64mod                    # noqa: E402
from ultima.disks.d64 import D64                     # noqa: E402
from ultima.disks import scan                             # noqa: E402
from ultima.flash import regions                          # noqa: E402

GAMES = ["u0", "u1", "u2", "u3", "u4", "u5", "u6"]


def flatten(x, path="", out=None):
    """{path: hash} for every bytes-like leaf of a parts() result."""
    out = {} if out is None else out
    if isinstance(x, dict):
        for k, v in x.items():
            flatten(v, f"{path}/{k}", out)
    elif isinstance(x, (list, tuple)):
        for i, v in enumerate(x):
            flatten(v, f"{path}[{i}]", out)
    elif isinstance(x, (bytes, bytearray)):
        out[path] = hashlib.sha1(bytes(x)).hexdigest()
    elif isinstance(x, (int, str, float, bool)) or x is None:
        out[path] = repr(x)
    return out


def run_parts(game):
    return flatten(importlib.import_module(f"ultima.games.{game}.build").parts())


def reference_back(manifest, stand_ins):
    """--exact: the units the release changes on purpose -- the protection,
    the save units' base -- taken from the reference disks instead, so that
    any other difference shows."""
    for disk, img in stand_ins.items():
        ref = D64(paths.disk(disk))
        e = manifest["disks"][disk]
        for key, s in e["sectors"].items():
            if s["kind"] in ("prot", "seed"):
                t, sec = map(int, key.split("/"))
                o = D64.offset(t, sec)
                img[o:o + 256] = ref.data[o:o + 256]
        for f in e["files"].values():
            if "seed" in f or f.get("prot"):
                for t, sec in f["chain"]:
                    o = D64.offset(t, sec)
                    img[o:o + 256] = ref.data[o:o + 256]


EXACT = "--exact" in sys.argv


def main():
    if any(a.startswith("-") and a != "--exact" for a in sys.argv[1:]) or len(sys.argv) < 2:
        print(__doc__)
        return 2
    piles = [a for a in sys.argv[1:] if a != "--exact"]
    if not piles:
        raise SystemExit(__doc__)
    manifest = json.loads(Path(scan.DEFAULT_MANIFEST).read_text())
    images, _skipped = scan.gather(piles)
    resolution = scan.resolve(manifest, images)
    stand_ins = scan.assemble(manifest, resolution)
    if EXACT:
        reference_back(manifest, stand_ins)
    incomplete = [d for d in manifest["disks"] if d not in stand_ins]
    if incomplete:
        print("incomplete, not verified:", *incomplete, sep="\n  ")

    with regions.unchecked():
        before = {g: run_parts(g) for g in GAMES}

    orig_init = D64.__init__

    def init(d, path):
        key = os.path.basename(path)[:-4]
        if key in stand_ins:
            blob = bytes(stand_ins[key])

            d.path = path
            d.data = blob[:d64mod.DATA_LENGTH]
            d.errmap = b""                  # the release ships no error maps
            return
        orig_init(d, path)
    D64.__init__ = init
    try:
        if EXACT:
            with regions.unchecked():
                after = {g: run_parts(g) for g in GAMES}
        else:
            after = {g: run_parts(g) for g in GAMES}
    finally:
        D64.__init__ = orig_init

    for g in GAMES:
        a, b = before[g], after[g]
        diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        print(f"{g}: {'identical' if not diff else f'{len(diff)} of {len(a)} outputs differ'}")
        for k in diff[:8]:
            print(f"    {k}")


if __name__ == "__main__":
    main()
