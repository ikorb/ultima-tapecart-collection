# Your disk images

The repository contains no game data. Put images of your own Ultima disks in this
directory -- any file names, any number of them, in subdirectories if you like -- and run

    make disks

The build reads every image here, finds what it needs by content (a hash of every file and
every sector it uses, `ultima/disks/manifest.json`), reports per game what it found and
from which image, and explains what is missing. `make` runs this step by itself the first
time; run `make disks` again after adding images.

## Formats

- `.d64`, 35 or 40 tracks, with or without an error map
- `.g64` (decoded by the build, no tools needed)
- `.zip` archives of those, nested one level

Images may come from different dumps of the same disk: the build takes each piece from
wherever it finds it intact.

## What is needed

| Game | Disks |
|---|---|
| Akalabeth | Genesis Project's release of the C64 conversion ("Akalabeth - World of Doom +4", 2016; the disk is named "accept no limits"): its main file and `LIB` |
| Ultima I | the one disk |
| Ultima II | side A and side B (side A in the Origin / Ultima Trilogy edition; Sierra's 1984 side A is a different program and is refused) |
| Ultima III | side A (program) and side B (Scenario; the Trilogy's "PLAYER MASTER" or the 1984 "ULTIMA III-SCEN.", played or not) |
| Ultima III Gold | the one disk of the fan version, for the features the cart takes from it (played or not) |
| Ultima IV | disks A (program), B (towne), C (Britannia), D (underworld) |
| Ultima V | 1A, 1B, 2A, 2B, 3A, 3B, 4A, 4B |
| Ultima VI | 1A (surface), 1B (dungeon), 2A, 2B, 3A (populace A-C), 3B (game) |

## Played disks

A disk that has been played on holds a saved game. The cart's own starting state -- what a
new game and the launcher's Reset begin from -- is built without it, and is the same
whatever images you use: the save areas are generated, or rebuilt from parts of the disk
the game never writes.

Two games keep part of their world on the disk and change it as you play, so for these the
build needs a copy in the state the disk was shipped in:

- **Ultima III**: side B's Sosaria map (`SOSA`). A played side B is fine: the game records
  what it puts on the map (monsters, chests, parked horses and ships, the whirlpool, the
  moon gate), and the build takes it off again and checks the result.
- **Ultima VI**: disks 1A and 1B, the whole world.

If yours cannot be used, `make disks` names the disk and the reason. Any unplayed dump
does, including one combined from several partial dumps. An Ultima VI Surface disk on
which a character was created but the game never saved is unplayed too: the build takes
it, without the character.

## Bringing a saved game along

`make import` builds `build/ultima-collection-imported.tcrt`: the cart with the saved
games found on your disks put into its save area, by the same code the launcher runs when
you import a save from a disk on the C64. A disk counts when it is the game's save disk
and nothing on it but the saved game differs from the original. If a game has saves on
more than one image, nothing is imported for it until you choose one:

    make import PICK="the image's file name"
