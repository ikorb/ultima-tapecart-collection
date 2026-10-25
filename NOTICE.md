# Notices

The Ultima Collection for the tapecart is dedicated to the public domain under CC0 1.0
([LICENSE](LICENSE)), except for the parts below, which come from other projects and keep
their licenses. Their license texts are in [LICENSES/](LICENSES/).

## In this repository

| Files | Derived from | License |
|---|---|---|
| `asm/tclib.s` | the tapecart project's C64 code (`src-c64/blockwrite.s`, `getbyte_fast.s`, `tapecartif.c`), Copyright (C) 2013-2017 Ingo Korb; altered: rewritten for acme, no zero page, banking derived at run time, the LED around transfers | BSD 2-clause: [LICENSES/BSD-2-Clause-tapecart.txt](LICENSES/BSD-2-Clause-tapecart.txt) |
| `asm/zx02a.s`, `asm/zx02s.s` | zx02's 6502 decompressor (`6502/zx02-optim.asm`), (c) 2022 DMSC; altered: input pulled from a tapecart stream, `zx02a.s` without zero page | MIT: [LICENSES/MIT-zx02.txt](LICENSES/MIT-zx02.txt) |
| `ultima/sim/exodec.py` | exomizer's `src/exodec.c`, Copyright (c) 2002-2005 Magnus Lind; altered: a reduced Python port (one protocol, no logging), used only to read the Ultima III Gold disk | zlib: [LICENSES/Zlib-exomizer.txt](LICENSES/Zlib-exomizer.txt) |
| `ultima/games/u4/tiles.py`; `binpatch()` and `cards()` in `ultima/games/u4/tileset.py`; `binpatch_case()` in `ultima/games/u4/remastered.py` | Ultima IV Remastered's tools `gen_tiles.py`, `gen_font.py`, `gen_cards.py`, `binpatch.py`, (c) 2006-2015 Per Olofsson; altered: ported to Python 3, reduced to what the build uses | Apache License 2.0: [LICENSES/Apache-2.0.txt](LICENSES/Apache-2.0.txt) |

## Submodules (`external/`)

Used at build time, unmodified, each with its own license file:

- `external/u4remastered` -- [Ultima IV Remastered](https://github.com/MagerValp/u4remastered).
  "The code is (c) 2006-2015 Per Olofsson, and is available under an Apache 2.0 license.
  The new graphics are (c) 2015 Vanja Utne." The build assembles parts of its code and
  converts its graphics into the cartridge image you build; neither is in this repository.
- `external/zx02` -- [zx02](https://github.com/dmsc/zx02), Copyright (c) 2020 Daniel
  Serpell, MIT (and, for the parts derived from ZX0, Copyright (c) 2021 Einar Saukas, BSD
  3-clause). The build compiles its compressor.
- `external/eapi` -- [EAPI](https://gitlab.com/easyflash/eapi), (c) 2009-2010 Thomas
  'skoe' Giesel, zlib-style license. Assembled into the EasyFlash build.
- `external/c64ultimaeditor` -- [C64UltimaEditor](https://github.com/zoggins/C64UltimaEditor)
  by zoggins; it carries no license file. Not checked out by default and not used by any
  build: the save editor's tests read its sample save disks when it is there.

## Acknowledgements

- **Ultima III Gold**, "cracked, trained and enhanced by MagerValp, released at BFP 2007,
  music by Zabutom": several of its changes are reimplemented for the cart
  ([docs/changes/u3.md](docs/changes/u3.md)); its disk is read from your images.
- **Ultima IV Remastered's continuation** by Sean Gugler
  ([github.com/sean-gugler/u4remastered](https://github.com/sean-gugler/u4remastered),
  versions 2.3.0-2.4.1, Apache 2.0 as Ultima IV Remastered), and its wiki's analysis of
  them: the bugs it found in the original, fixed on the cart as patches of your disks'
  bytes ([docs/changes/u4.md](docs/changes/u4.md)). None of its code is in this
  repository or used by the build.
- **Ultima V Remastered** by Drunella (Apache 2.0) -- its save editor and its map tools --
  and Marc Winterrowd's "Ultima 5 File Formats (C64 version)" (2004), which it carries:
  sources of the save editor's field layout for Ultima V and of `make maps`' Ultima V
  layout and dungeon legend (its codes and abbreviations as in its `tools/dungeonbuilder.py`).
- **C64UltimaEditor** (zoggins), a clone of Xenerkes Dragon's Ultima Savegame Editor: its
  notes are a source of the save editor's layouts for Ultima II and III.
- The tapecart by Ingo Korb (idea by enthusi): the hardware this runs on, and its
  protocol documentation.

- **Akalabeth: World of Doom** (c) 1980 Richard Garriott; the C64 conversion (2016) by
  Andrea Schincaglia (code and conversion), Antonello Molella (idea and testing) and
  David Vigh (graphics), in Genesis Project's release (compiling and trainers: Wertstahl;
  linking: L.A.Style), read from your disk image: the build unpacks it with the release's
  own decruncher, run on the host, and its trainer's flags become the launcher's options
  ([docs/changes/u0.md](docs/changes/u0.md)).

Ultima I-VI are (c) Origin Systems. No part of the games is in this repository.
