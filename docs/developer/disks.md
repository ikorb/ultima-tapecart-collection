# The disks: your own images, found by hash

The repository ships no disk images and no data taken from them. Users put their own
images into `disks/` -- any names, any number, any mix of editions and dumps -- and the
build finds what it needs there by content, refusing with a reason what it cannot use.
This document is how that works: the manifest, the scan, the stand-ins the games build
from, the pristine base layer, save import, and verification. The code is in
`ultima/disks/`.

## The principles

- **Inputs by content, unit by unit.** A file is matched by its content wherever it lies;
  a sector the build reads by position is matched by its hash, at the same track and
  sector if possible. Units may come from different images.
- **A pristine base layer.** The cart's base state -- and so what the page's Reset returns
  to -- is the same whatever images it was built from. A game's save units are generated,
  or rebuilt from a template on the same disks that the game never writes; none is
  copied from your disk. A saved game found on your disks can be imported on
  top (`make import`, below).
- **Played world data is put back where the disk records it, else refused**, with a
  diagnosis. U3's `SOSA` (the map of Sosaria) and U6's world (all of the Surface and
  Dungeon disks' chunk files and save area) have no template, and the games never reset
  them. U3 records under every square it writes what was there (below); U6 does not, so
  apart from a new U6 character (below) a played U6 world needs a fresh, unplayed copy.
- **U2: only the Origin (Ultima Trilogy) side A.** Sierra's 1984 side A packs `INTRO`
  into its boot file and differs from Origin's; the scanner names it. Side B is the same
  in both.
- **U3 side B: either edition, any label.** The 1984 Scenario disk is the Trilogy's
  Player Master but for the label in its BAM (`$90-$A9`: "ULTIMA III-SCEN.", ID "U3"; a
  relabelled copy says "ULTIMA III"). Side B is matched by position, track 18 too, so
  `manifest.RESETS` takes the label with any content and puts the Player Master's back,
  as for a new U6 character (below). The cart's export and import know both names.
- **Known variants are fixed up to the reference** (`manifest.FIXUPS`): a sector may also
  be accepted in another known form, whose hash the manifest computes from the reference
  with the other bytes put in, and the scanner writes the reference's bytes back. There
  is one: Ultima IV disk D (Underworld), Covetous room 11, tile (7, 5) -- a wall under a
  monster in the 1986 dumps, cutting the trigger's exit off; floor on the Trilogy. The cart
  always gets the floor ([u4.md](u4.md)).
- **A played Sosaria is put back** (`ultima/disks/world.py`): each SOSM monster's
  under-tile, a chest's terrain from its low bits, grass under a parked horse and the moon
  gate's other squares, water under a parked frigate and the whirlpool, the gate on its
  unplayed square ([u3.md](u3.md), the reversing notes' "The pristine state"). The sectors
  must then match the reference's hashes, so the rules only decide which disks are taken,
  never what the cart gets; a change the disk does not record (a chest on mountains) is
  refused.
- **A new U6 character is put back** (`manifest.RESETS`): `CREATE` writes the Surface
  disk's save area (T6 S9-20) from its template and no object file, so a disk on which a
  character was made and never saved holds an unplayed world. Its save area differs from
  the factory state only in what creation fills in -- the Avatar's name (`$5700`), strength,
  dexterity, intelligence, magic points, sex (`$588B`) and the five tables at `$5FB0`.
  Those bytes are taken with any content and the factory's put back (the manifest's
  `"reset"` on 1A's T6 S12, S13 and S20); the sector must then match the reference's
  hash, so the stand-in is the unplayed disk's. Any other difference in the state (a
  position, the time) is a saved game, refused as played.

Which units each game writes, and their base, are in the per-game documents. In short:
U1, U2, U4 and U5 need nothing pristine from your save disks; U3 needs `SOSA`, unplayed or
put back; U6 its world.

## The disks, by key

`ultima/disks/keys.py` names every disk the build needs, by a key; the stand-in for each
is `build/disks/<key>.d64`.

| Keys | Disks |
|---|---|
| `u0` | Akalabeth: Genesis Project's release of the C64 conversion ("accept no limits") |
| `u1` | Ultima I |
| `u2a`, `u2b` | Ultima II, side A (program and galactic), side B (player master) |
| `u3a`, `u3b` | Ultima III, side A (program), side B (player master) |
| `u3gold` | Ultima III Gold |
| `u4a` .. `u4d` | Ultima IV, disks A (program), B (towne), C (Britannia), D (underworld) |
| `u5-1a` .. `u5-4b` | Ultima V, 1A (program), 1B (dungeon), 2A (Britannia), 2B (underworld), 3A (towne), 3B (dwelling), 4A (castle), 4B (keep) |
| `u6-1a` .. `u6-3b` | Ultima VI, 1A (surface), 1B (dungeon), 2A-3A (populace A-C), 3B (game) |

The labels follow the Ultima Trilogy releases, which the manifest was made from; other
editions' disks are found by content. Akalabeth's is one release, the one the build
unpacks (`ultima/games/u0/build.py`); it needs that release's main file and `LIB`, not
the pictures.

`ultima/paths.py` decides where the stand-ins are: `build/disks`, or the directory in
**`ULTIMA_DISKS`** when it is set (the tests, a reference set). `paths.require_disks()`
stops a build with the list of what is missing and what to do.

## What a user runs

```sh
make disks                     # scan disks/, write the stand-ins, report
make                           # the cart (runs the scan first if it has not completed)
make import [PICK=<image>]     # the cart with the saved games found in disks/:
                               #   build/ultima-collection-imported.tcrt
```

`make disks` is `python -m ultima.disks.scan --write build/disks disks`. It writes
`build/disks/.complete` when every disk is complete, which the cart's rule depends on; run
it again after adding images.

## The pieces

### The manifest: `ultima/disks/manifest.py`, `manifest.json`

What the build needs from the original disks, by hash. It runs every game's `parts()`
with the D64 reader traced and records, per reference disk, every sector the build read
and how:

| Kind | Read | How a user's image may supply it |
|---|---|---|
| `file` | through the directory (`D64.file`/`payload`/`chain`) | the file's content, matched by hash in any image, wherever it lies; the reference chain says where to put it back |
| `sector` | by position (raw blocks, U3's catalog, U4's whole disks) | matched by hash, preferably at the same track/sector |
| `dir` | the track-18 directory and BAM chain | shipped as fields, not sectors |
| `prot` | flagged unreadable in the reference's error map, or a file crossing such a sector: the copy protection | not needed; the build patches the check out |
| `seed:...` | a unit the game writes | its base is generated (`SEEDS`), not taken from your disk |

Hashes only, never bytes. **Track 18 travels as fields** (`meta`): the BAM's allocation
map, disk name and ID, DOS type, and each directory entry's type, start, name and size.
The builds use nothing else of track 18 -- names and starts to find files, name and ID for
export and import's disk check, the allocation map for U5's and U6's block maps -- and the
rest of it is rebuilt as a standard DOS writes it. The exception is U6's Surface and
Dungeon, whose block maps take all of track 18 as game data: there it is matched like any
other sector. **No error maps** are needed: images with or without one are read alike.

`SEEDS` gives each save unit's base rule: a fill, a few bytes set, or a template that is
itself a static unit on your disks (U4's party from disk A, U2's `MON n`/`MOB n` from
`MONXn`/`MOBXn`). Where the base differs from the reference disk's bytes the rule says so
(U5's save files: the empty state, not the master's residue). `WORLD` lists the static
units that must be pristine and travel with a saved game (U3's `SOSA`).

**Regenerating the manifest** needs a set of reference images: with `ULTIMA_DISKS` pointing at a
directory of reference images named `<key>.d64` (error maps included -- they tell the copy
protection's unreadable sectors),

```sh
ULTIMA_DISKS=<dir> python -m ultima.disks.manifest [out.json]
```

writes `ultima/disks/manifest.json` (the default output). Do it whenever a game's build
starts reading something new from a disk. The error maps are what makes a protection
unit `prot`: U1's `PR` on track 6, U4 disk A's track 6 -- without them those are taken
for files and sectors every user's disk would have to match. The traced builds run on
the reference disks, whose save units hold the master's residue where a cart has the
seeds' base (U5 stores the save files' sectors in its raw runs, and residue compresses
worse), so they are not held to the flash regions (`regions.unchecked()`); only a build
from stand-ins makes a cart. `verify.py`'s runs on the references do the same.

### The scan: `ultima/disks/scan.py`

Indexes every image under the given paths, resolves the manifest against them (a world
sector also from what `world.py` puts back, reported as "fixed"), reports per
game, and diagnoses what is missing: a known cause (`HINTS`: a `SOSA` changed beyond what
`world.py` puts back, a played U6 world, Sierra's U2 side A), else the closest image and what it lacks. `assemble()` builds a
stand-in for every complete disk: the units where the reference had them, a file into the
reference chain with its links, a standard track 18 from the manifest's fields, the seeds
at their base, zeros elsewhere. The stand-ins are rewritten only when they change, so
`make` sees what is new.

Mixing disks is allowed: two played Surface dumps whose changes do not overlap complete
each other, since unit by unit everything is still the pristine hash. The U6 hint says
"played and saved" for any difference on Surface or Dungeon that is not a new character;
a damaged dump would get the same words.

### What the scanner reads: `ultima/disks/images.py`

- `.d64`: 35 or 40 tracks, with or without an error map;
- `.g64`: GCR decoded here (syncs, headers, data blocks, checksums). A sector that does
  not read gets its DOS error code (20, 22 or 23), as a protection track's do;
- `.zip` archives holding either, nested once.

`.nib` is not read.

### Ultima III Gold: `ultima/games/u3/goldunpack.py`

Ultima III Gold's disk is packed, and is unpacked on the host without VICE or the
exomizer binary: its data files by `ultima/sim/exodec.py`, a Python port of exomizer's raw
decruncher (exomizer is (c) Magnus Lind, zlib license); its two self-extracting stages
and `$BE00`'s five in-memory streams by Gold's own code in py65. The model must send
writes to `$D000-$DFFF` to the chips while `$01` has I/O in, or the self-extractor's busy
cell (`$DBE7`) corrupts `ULT3`. `ultima/games/u3/gold.py` reads the Gold disk through it.
Gold's five save files (`goldunpack.SAVES`) are never read, so they are not in the
manifest and a played Gold disk serves as well as a fresh one; the stand-in's directory
still lists them, over zeroed sectors.
This is why the U3 build needs py65.

### Ultima IV Remastered

The kit is the `external/u4remastered` submodule (Ultima IV Remastered by Per Olofsson
(MagerValp), code (c) 2006-2015 Per Olofsson, Apache 2.0; new graphics (c) 2015 Vanja
Utne). The build reads it and assembles the parts it takes with ca65/ld65; nothing derived
from it is stored in the repository. See [u4.md](u4.md).

### Importing a saved game: `ultima/disks/importsave.py`

`make import [PICK=<image>]` builds the cart if needed and runs

```sh
python -m ultima.disks.importsave build/ultima-collection.tcrt disks \
    -o build/ultima-collection-imported.tcrt [--pick IMAGE]
```

so the plain image stays pristine. It puts a saved game found in the images into the
cart's save area **by the page's own "import from disk", run on the host**
(`ultima/sim/pagesim.py`: py65, the cart, a simulated 1541 with your images in the
drive). Every save format -- journalled slots, U2's and U6's logs -- is written by the same
code as a player's import on a C64. The base, and so Reset, is untouched.

A disk counts when:

- it is its game's save disk by content (most of the disk's telling units in place), and
  nothing outside its save differs (its files by content, or its sectors bar track 18's
  BAM sector);
- the page's own test sees a game on it: U1 a used roster slot, U2 a named record, U3 a
  party in `PRTY`, U4 a party in block 275, U5 an active roster, U6 a played world or a
  new character (the cart then starts with that character, the world unplayed).

The save disks, in the order the import asks for them: U1 the disk, U2 side B, U3 side B,
U4 disk C, U5 2A and 2B, U6 Surface and Dungeon. A game with two save disks takes the
base's stand-in for one that holds nothing. Another official edition's disk name is
written over in the copy the simulated drive gets (the scan has identified the disk by
content). When two images hold different saves of the same disk, nothing is imported for
that game and both are named: `PICK=<image>` (`--pick`) chooses. `--game u5` limits the
import to one game. **World data** (U3's `SOSA`, U6's world) must be pristine for the
base and is part of a save for the import.

### Verifying: `ultima/disks/verify.py`

```sh
ULTIMA_DISKS=<reference dir> python -m ultima.disks.verify [--exact] DIR_OR_IMAGE...
```

A check of the whole scheme, for developers: it scans the given images, assembles the stand-ins, runs each game's
`parts()` once on the reference images and once with the stand-ins handed to the D64
reader instead, and compares every byte the builds put out, by hash. `--exact` puts the
reference's bytes back into the seeds and the protection, so every game must come out
identical. Without it the known differences are the point: U4's protection track 6 on
disk A (zeros, not the dump's noise) and U5's save base (the empty state, not the
master's residue).

Akalabeth's manifest entry was made from its one disk and added to the others' (its
files are read through the directory; nothing of its disk is written). Checked: from the
reference disks, `--exact`, all six Ultimas identical; without it, U1-U4
and U6 identical and U5 differing only by its save base. A pile of several hundred images
scans in under a second, every game complete (U4's disk D through its fixup), and
`--exact` from it gives all six games identical to the build from the reference disks.
A `.g64` written by VICE's `c1541` reads back identical to its `.d64`, all 683 sectors.

## Tests

`tests/test_release.py`: the games' sector ranges and files, raw files staying raw, a file
round trip, the seed rules, the fixup and the resets holding on the reference, a new U6
character put back (and one more byte of state refused), U5's base being no game,
`.g64` and nested zips, the page's own test of a saved game, another edition's name handed
over as the page's, a U4 game going in.
