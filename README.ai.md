# The Ultima Collection for the tapecart

Ultima I to VI for the Commodore 64 on one 2 MiB [tapecart](https://github.com/ikorb/tapecart),
and Akalabeth, the game before them. Every game loads from the cartridge: no disks, no
disk swapping, no waiting for a drive.
The games are the originals, with their disk access replaced by flash reads, their saved
games kept on the cart, and a few fixes and options added. A launcher lets you pick a
game, see its saved game, set its options, and export or import saves to and from disk.

As a side build, Ultima VI also runs alone on a 1 MiB EasyFlash ([docs/easyflash.md](docs/easyflash.md)),
whose launcher can also start the tapecart's Ultima V with its music.

**This repository contains no game data.** You build the cartridge image from images of
your own Ultima disks.

## What you need

- A tapecart with 2 MiB of flash, and the tapecart flash tool to write it.
- A C64 (or a C128; Ultima V also has a C128 mode). A disk drive only for exporting and
  importing saved games; an REU is used by Ultima VI if present.
- Disk images of the six games, of the fan version Ultima III Gold and of Akalabeth's C64
  conversion, in Genesis Project's release ([disks/README.md](disks/README.md)).
- To build: `make`, a C compiler, [acme](https://sourceforge.net/projects/acme-crossass/),
  [cc65](https://github.com/cc65/cc65) (`ca65`, `ld65`), Python 3 with
  [py65](https://github.com/mnaberez/py65). For the save editor: `tsc`, `bun`, `node`. To
  try the cart in an emulator: [VICE](https://vice-emu.sourceforge.io/) 3.11 or later.
  Builds on macOS and Linux (checked on Debian 13 and Fedora 44).

## Building

    git clone --recurse-submodules <this repository>
    cd <it>
    python3 -m venv .venv && .venv/bin/pip install py65
    # put your disk images into disks/
    make disks          # what was found, and what is missing
    make

The build makes three images in `build/`:

| Image | Use | Flash it with |
|---|---|---|
| `ultima-collection.tcrt` | a new cart (erases everything, saved games included) | the flash tool's **Write TCRT** |
| `ultima-collection-update.bin` | updating a cart that has the collection (keeps the saved games) | the flash tool's advanced **Write data file**, at offset 0 |
| `ultima6-ef.crt` | Ultima VI alone on a 1 MiB EasyFlash ([docs/easyflash.md](docs/easyflash.md)) | **EasyProg** |

`make import` also makes `build/ultima-collection-imported.tcrt`, with the saved games
found on your disks already in it. Power on with the cart in the tape port and load from
tape (`LOAD`, or Shift+RUN/STOP). `make play` starts the image in VICE.

More: [docs/guide.md](docs/guide.md) (playing), [docs/building.md](docs/building.md)
(all build targets, tests), [docs/changes/](docs/changes/) (what is different from the
originals, per game).

## Documentation

| | |
|---|---|
| [docs/guide.md](docs/guide.md) | the player's guide: the launcher, options, saves, export and import |
| [docs/changes/u0.md](docs/changes/u0.md) .. [u6.md](docs/changes/u6.md) | each game's changes on the cart, and where they come from (`u0`: Akalabeth) |
| [docs/save-format.md](docs/save-format.md) | the format of exported saved games |
| [docs/editor.md](docs/editor.md) | the save editor (`make editor`: one HTML page) |
| [docs/easyflash.md](docs/easyflash.md) | Ultima VI on an EasyFlash |
| [docs/building.md](docs/building.md) | building, testing, the tools |
| [docs/developer/](docs/developer/README.md) | how it works, for developers |
| [docs/reversing-notes/](docs/reversing-notes/) | what the original games do, as found by reverse engineering |

## Credits and licenses

This project is released into the public domain under [CC0 1.0](LICENSE). Parts of it come
from other projects, under their own licenses ([NOTICE.md](NOTICE.md)):

- the tapecart transfer code is based on the tapecart project's reference loader
  (Ingo Korb, BSD 2-clause);
- the [zx02](https://github.com/dmsc/zx02) compressor (MIT) and its decompressor;
- [Ultima IV Remastered](https://github.com/MagerValp/u4remastered) by Per Olofsson,
  code under the Apache License 2.0, built from its sources; its graphics (© Vanja Utne)
  are not in this repository;
- bug fixes found by Sean Gugler's
  [continuation of Ultima IV Remastered](https://github.com/sean-gugler/u4remastered),
  reimplemented;
- EasyFlash's [EAPI](https://gitlab.com/easyflash/eapi) for the EasyFlash build (zlib
  license);
- features ported from the fan version Ultima III Gold (MagerValp), whose disk you
  supply.

Ultima I-VI are © Origin Systems. Akalabeth is © Richard Garriott; its C64 conversion is
by Andrea Schincaglia (code), Antonello Molella (idea and testing) and David Vigh
(graphics), and the cart takes it from Genesis Project's release, whose trainer
(Wertstahl) becomes options on the cart. None of their code or data is in this
repository.
