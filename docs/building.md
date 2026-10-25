# Building

## Tools

| Tool | For |
|---|---|
| `make`, a C compiler (`cc`) | everything; the compiler builds the zx02 compressor from `external/zx02` |
| [acme](https://sourceforge.net/projects/acme-crossass/) 0.97 | the 6502 code: drivers, launcher, patches (Debian/Ubuntu: package `acme`; where there is none, e.g. Fedora, build it from its SourceForge repository: `make -C src`) |
| [cc65](https://github.com/cc65/cc65) (`ca65`, `ld65`) | Ultima IV Remastered's units, assembled from `external/u4remastered` |
| Python 3 and [py65](https://github.com/mnaberez/py65) | the build itself; py65 runs 6502 code on the host (the Ultima III Gold and Akalabeth unpacks, the launcher's import, the logo, many tests) |
| `tsc`, `bun`, `node` | the save editor only (no npm packages); its tests need node 22.18 or later, which runs TypeScript as it is, and are skipped with an older one |
| [VICE](https://vice-emu.sourceforge.io/) 3.11 or later (`x64sc`, `x128`, `c1541`) | `make play`, `make play128`, `make play-ef`, the checks in `tools/vice/`, `make fixtures` |

Checked on macOS, Debian 13 and Fedora 44: the same disks give the same images, byte for
byte, on each.

The Makefile uses `.venv/bin/python` when a virtual environment is there:

    python3 -m venv .venv && .venv/bin/pip install py65

Three things in VICE are expected in release 3.11, and are in its trunk from r46288 on
(a trunk build still calls itself 3.10 until the release): a fix to its tapecart
emulation (with an older VICE a transfer hangs right after the cart's first LED command),
the tapecart in snapshots, and the `keymatrix` monitor command the checks use to press
keys.

The submodules are needed for every build:

    git submodule update --init

| Submodule | What it gives |
|---|---|
| `external/zx02` | the compressor every packed unit goes through |
| `external/u4remastered` | Ultima IV Remastered's sources and graphics, built into the cart |
| `external/eapi` | the EasyFlash flash driver, for `make ef` |

One more is not checked out unless asked for (`update = none`): `external/c64ultimaeditor`,
[C64UltimaEditor](https://github.com/zoggins/C64UltimaEditor)'s sample save disks, which
the save editor's tests also read when they are there (no build needs them):

    git submodule update --init --checkout external/c64ultimaeditor

## The disks

Put your images into `disks/` ([disks/README.md](../disks/README.md)), then:

    make disks

It reports every game, which image each disk came from, and what is missing or unusable
and why, and writes one stand-in per disk to `build/disks/`. Everything else reads only the
stand-ins. Set `ULTIMA_DISKS` to read stand-ins from another directory. How the matching
works: [developer/disks.md](developer/disks.md).

## Targets

| Target | Output |
|---|---|
| `make` | both carts: `make cart` and `make ef` |
| `make all` | both carts, the editor, the maps and the dialogue |
| `make cart` | `build/ultima-collection.tcrt`, the full image, and `build/ultima-collection-update.bin`, the update image that keeps the saves |
| `make import [PICK=<image>]` | `build/ultima-collection-imported.tcrt`: the full image with the saved games found on your disks |
| `make ef` | `build/ultima6-ef.crt`, Ultima VI on a 1 MiB EasyFlash ([easyflash.md](easyflash.md)) |
| `make build/ultimaN.tcrt` | one game alone, as some tests and checks use it |
| `make editor` | `build/ultima-save-editor.html` ([editor.md](editor.md)) |
| `make maps` | every game's maps as PNG files in `build/maps/` |
| `make dialogue` | every game's conversations and texts in `build/dialogue/` |
| `make play`, `make play128`, `make play-ef` | the image in VICE (`play128`: Ultima V's C128 mode in `x128`) |
| `make test` | the host tests, then the editor's |
| `make fixtures` | the RAM images in `tests/data` that some tests need, captured in VICE |
| `make run-menu`, `make run-u1test`, `make run-u3test` | checks in VICE: every game starts from the menu; Ultima I's and III's saves round-trip |
| `make clean` | removes `build/` |

The version shown on the launcher is `VERSION` in the Makefile (`make VERSION=1.1`). A
build is reproducible: the same disks (in any form the scanner accepts) and the same
sources give the same image, byte for byte.

## Tests

`make test` runs the Python tests (`python -m unittest discover -s tests -t .`) and, with
node 22.18 or later, the editor's. They need no emulator: they check the built images, run the
game's and the launcher's code in py65, and simulate the cart, the drive and the flash.
Tests that run 6502 code skip without py65; the few that need a ROM image (the C64's or
the C128's KERNAL) take VICE's -- next to `x64sc`/`x128` on `$PATH`, in the usual install
places, or under `$VICE_ROMS` -- and skip without it (`ultima/sim/roms.py`).

Some tests run original and patched game routines over whole-RAM images captured in
VICE. These are made from your disks, not shipped: `make fixtures` captures them
(`tools/vice/fixtures.py`, about fifteen minutes), and the tests skip until they exist.

The VICE-based checks in `tools/vice/` start an emulator and drive a game through the
monitor; run them from the repository root as `python -m tools.vice.<name>` (each one's
docstring says what it checks). [developer/emulation.md](developer/emulation.md) has the
details.

## The manifest

`ultima/disks/manifest.json` lists, by hash, every file and sector the build reads from
each disk. It is generated from a set of reference images named by their keys
(`u1.d64`, `u2a.d64` .. `u6-3b.d64`, `u3gold.d64`):

    ULTIMA_DISKS=<that directory> python -m ultima.disks.manifest

    ULTIMA_DISKS=<that directory> python -m ultima.disks.verify [--exact] <pile of images>

builds every game from the reference images and from the stand-ins assembled from the
pile, and compares the results ([developer/disks.md](developer/disks.md)).
