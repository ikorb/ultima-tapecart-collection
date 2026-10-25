# Developer documentation

This is the overview for anyone working on the code of the Ultima Collection for the
tapecart: Ultima I-VI for the Commodore 64 on one 2 MiB tapecart, every game's disk I/O
replaced by reads from the cart's flash, and Akalabeth, which needs no disk at all once
its program is in RAM. It covers what holds for all of them. Each game has its own
document, and each shared subject has one too (see the index at the end).

Ultima I-VI are (c) Origin Systems / Lord British; Akalabeth (c) Richard Garriott, its C64
conversion by Andrea Schincaglia, Antonello Molella and David Vigh. Third-party parts keep their own
licenses: the tapecart project's reference code (which `asm/tclib.s` ports), zx02
(`external/zx02`), Ultima IV Remastered (`external/u4remastered`), EasyFlash's EAPI
(`external/eapi`), and the exomizer decruncher port in `ultima/sim/exodec.py`.

## The tapecart is a tape-port device

The tapecart plugs into the **tape port**. It is never memory-mapped: nothing of it shows
in the C64's address space, there is no ROM to bank in or out, and no game code has to
move out of the way of a cartridge window. (The reversing notes in
`docs/reversing-notes/` were written with a cartridge-port ROM in mind, and several of
them conclude that "every memory window is occupied" or that "`$01` banks the cart out".
None of that applies here.) U2's self-modifying inline filenames, for example, are no
obstacle: the driver reads the name wherever the game put it.

The cart talks through the processor port instead: `$00`/`$01` are the data path (the
tape's motor, sense and write lines). Four rules follow, and they hold everywhere.

1. **`$01` bit 5 (motor) stays 1.** With the motor active the cart drops back to
   streaming mode. U1, U2, U3, U4 and U6 never clear it. U5 does (`$01` = `$06` and
   `$00`), so its build changes two immediate operands in `temp.subs` (`$7685`, `$7690`).
2. **The DDR `$00` stays `$2F` between transfers.** tclib switches bits 3 and 4 itself
   while it talks to the cart.
3. **`$C0` is re-armed before every return to code that runs with interrupts on.** The
   KERNAL's IRQ clears `$C0` whenever sense is high, so setting it once at boot does not
   hold: after a later write the cart is busy with sense low, and the next IRQ starts the
   motor. `tc_leave` sets `$C0` = 1 on every exit.
4. **Command mode is entered once and held** for the whole session. Entering it costs
   about 70 ms.

## Architecture

### Power-on: first stage, launcher, game

The cart's loadinfo loads the **first stage** (`asm/boot.s`, a fixed 2 KiB from flash
`$000800`, run at `$1000`). It checks the save layout stamp, finishes any save journal a
power cut left behind, and loads the **launcher**: one PRG from `$4800` -- the font
(`$4800`), the per-game page (`asm/page.s`, `$5000`), the menu (`asm/menu.s`, `$8700`),
U6's REU line, the page's export tables up to `$A000` and the page's second piece from
there. Details:
[saves.md](saves.md) (first stage, stamp, journals) and [launcher.md](launcher.md).

**The menu's address is a constraint.** The menu is still running its load loop while a
game's segments arrive, so no segment of any game may overlap it. It sits at `$8700`
because segments of U2 and U5 load at `$C600` and `$2000`, and `$8700` is one of the few
windows left free across the games. `tests/test_collection.py` checks every segment of
every game against the menu's range, so a collision is a test failure rather than a
reset to BASIC. Only the menu has that constraint: the rest of the PRG is the page's,
done with before the first segment loads, so the page may be anywhere the launcher's
flash room reaches.

### The menu, descriptors and init stubs

The menu is game-agnostic. Flash holds a game list at `$000000` and one 256-byte
**descriptor** page per game from `$000100`: an entry address, a segment count, then per
segment its flash page, length, destination and flags (bit 0: stored zx02-crunched, with
its own length in the first two bytes). The menu loads the segments, applies the page's
poke list, and jumps to the entry address.

The entry address points at the game's **init stub**, `asm/init_<g>.s`, loaded as an
ordinary segment: at `$0200` for U2-U5, `$C700` for U1, `$1000` for U6, `$0334` for
Akalabeth. The stub
reproduces the machine setup of the game's original boot code and jumps into the game.
U1's and U5's stubs also carry their driver's `tc_init` (`TC_INIT_ELSEWHERE`, below).
Adding a game needs no change to the menu.

### The launcher page

Picking a game runs the page first: the saved game, the game's options, Journey Onward,
export and import, reset. It answers "back" or "launch"; with "launch" comes a **poke
list** that the menu applies after the game's segments are in and before the init stub
runs. That is how an option reaches a driver. The options are RAM patches with a
signature (`ultima/launcher/patches.py`, `asm/patch.s`), applied only where every
original byte is in place. All of it: [launcher.md](launcher.md).

### Loads

tclib reads at 1 bit or 2 bits per handshake. On hardware the 2-bit read runs at about
8.5 KB/s; the 1-bit read was measured at about 2.8 KB/s with a receive of ~35 cycles a
bit, and tclib's receive takes 24 cycles a bit (not timed on hardware). **`TC_GUARD`** is
the 2-bit read with the screen on: it waits out badlines before each byte and falls back
to 1 bit while a sprite is enabled. U1-U4 load everything through it, raw or crunched;
U5 uses it only with an Action Replay or in C128 mode; U6 reads at 1 bit (interrupts on
during loads, sprites in the game view) except during its boot's compaction.
**`TC_NMI_HOLD`** keeps a RESTORE from jumping through RAM during a transfer (U2, U3; U4
has its own hold). Every compressed unit is zx02. Details: [transfer.md](transfer.md).

### tclib

`asm/tclib.s` is the shared tapecart library, assembled into each game at whatever
address that game has free. Its byte transfers are ports of the tapecart project's
reference code (`src-c64`, and the protocol as its `doc/ProgRef.md` describes it). It
differs from that code deliberately in three ways:

- **Banking is derived at runtime.** The reference routines hardcode `$01` values, which
  also pin the banking bits; the six games have six banking disciplines. `tc_init`
  (`asm/tcinit.s`) derives every port and DDR value from the caller's `$00`/`$01`, and
  transfers run in all-RAM banking, which also lets a load land under I/O or ROM.
- **The LED shows activity.** The cart lights its LED on entering command mode, and
  command mode is held all session, so it would glow throughout. `tc_enter` sends
  `LED_ON` and `tc_leave` `LED_OFF`, so it is lit while data moves. `TC_SCREEN_LED` also
  lights a screen cell (U6). The cost is about 23 bytes per copy of tclib and a few
  hundred cycles per operation; both routines keep X, Y and the carry. `tc_cmdmode`
  leaves through `tc_leave_quiet`, because a cart that failed to enter command mode must
  not be sent anything. `TC_NO_LED` leaves the LED commands out (the first stage).
- **No zero page at all.** Parameters live in the library's own RAM and the transfer
  loops use self-modified absolute addressing. There is no run of zero page free across
  all six games (U3's engine, for one, uses `$F7`/`$F8` heavily), so the only safe
  answer is to need none. It is also a cycle per byte faster than `(zp),y`.

The decoder U1-U3, the menu and U6 use, `asm/zx02a.s`, needs no zero page either: its two
`(zp),y` pointers are self-modified operands. U4's and U5's `asm/zx02s.s` saves and
restores four zero-page bytes, which is only safe with interrupts off, as they are there.

**When game state is subtly wrong after a load, suspect corruption first**, before
hunting for a missing patch: a library that touches a game's zero page or RAM produces
exactly that symptom.

### Per-game shape

Each game has:

- `ultima/games/<g>/build.py`: extract from the disks, patch, lay out; it exposes
  `parts()`, which `ultima/build.py` merges into the cart;
- `ultima/games/<g>/<g>drv.s`: the driver that replaces the game's disk routines (not
  Akalabeth, which has none);
- `asm/init_<g>.s`: the init stub.

| Game | Seam | Driver lives at | Notes |
|---|---|---|---|
| U1 | `$C480`/`$C483`/`$C486`/`$C489` | `$C000-$C47F` (the original fastloader's place), entry table at `$C480` | reuses the original's memcpy at `$C4FD`; decoder at `$C600` |
| U2 | `SUBS` vectors `$408D`/`$4090`/`$40AB`/`$40AE` | `$B100-$BF47` (above the map cache) + the save log's code at `$D000-$D363` (under I/O) | by filename; the save is a raw block (T35/S16), not a file |
| U3 | `$BA48` `dos_transfer` | `$BC00-$BFFF` + `$C500-$C73F` (decoder, patcher, `tcguard.s`) | one unit per catalog entry; the catalog is rewritten to flash pages at build time |
| U4 | `$A45E` block transfer: the driver starts there | `$A45E-$A588` resident + `$D000-$D531` under I/O | every block through a per-disk block map; each distinct page zx02-crunched |
| U5 | all seven disk slots at `$6C00` | `$7700-$7AB5` + four dead routines in `temp.subs` | by name through the cart's DIR_LOOKUP; zx02 at 1 bit; raw sectors through per-disk block maps |
| U6 | `$C16B` (resident loader) and `$29BE` (`game`'s loader), one command protocol | boot: `$C16B-$C3D6` + `$C578-$C7C8`; game: `$2823-$28CB` + `$2989-$2B4D`, plus 1 KiB fetched into the idle sprite half | |
| Akalabeth | none: its two loads are patched out of the program, `LIB` is a segment | -- | a compiled BASIC program, unpacked from Genesis Project's file in py65 at build time; the trainer's flags are the page's options |

The per-game documents have the details: [u0.md](u0.md) (Akalabeth), [u1.md](u1.md),
[u2.md](u2.md), [u3.md](u3.md), [u4.md](u4.md), [u5.md](u5.md), [u6.md](u6.md).

### Copy protection

U1, U2, U3 and U4 all check for a *read failure*. U3's check is in `BOOT`: it calls
`$1DF4` from `$103F`, which reads track 6 sector 8 -- all of track 6 is unreadable on the
original disk A -- and **hangs forever at `$1E42` if the read succeeds**. The build NOPs
that call, which is faithful: on an original the read fails and the routine returns
having done nothing. When adding a game or a disk, check whether its image carries an
error map or unreadable sectors before assuming there is no protection.

## The flash map

One file decides it: **`ultima/flash/regions.py`**. Nothing else holds an absolute flash
address.

- **The reserved area, `$000000-$007FFF`**: `$000000` the game list, `$0000F8` the
  launcher's locator (its flash address and length), `$000100`+ one descriptor page per
  game for U1-U6, `$000700` the C128 descriptor (U5), `$000800` the first stage (a fixed
  2 KiB), `$001000` the launcher's PRG, `$007F00` Akalabeth's descriptor.
  `ultima/build.py` refuses a launcher that runs into it (`regions.MENU_PRG_END`).
- **Game data** tiles upward from `$008000` in the order U1, U3, U2, U4, U5, U6,
  Akalabeth, then the launcher's region (each game's fresh save pages, which the page's
  Reset writes back). A data region is whole pages -- game data is only ever read, and
  an update image rewrites all of it -- sized to the game's extent plus about half a KiB
  (`regions.DATA`); `regions.check` stops the build when a game outgrows its region, and
  the sizes are raised there. What is left between the data and the saves is free
  (`regions.free()`, 2 KiB).
- **Every save region sits at a fixed address at the top of flash**, growing down: U1
  `$1F8000`, U3 `$1EC000`, U2 `$1E4000`, U4 `$1DE000`, U5 `$1D7000`, U6 `$197000`
  (256 KiB, its write log). Each fixed-slot region (U1, U3, U4, U5) ends in its journal.
  Only U6's region, the lowest, can grow, downward.
- **The launcher's settings page is `$1FF000`**, the top block of U1's region, above
  the save area like the saves (`regions.SETTINGS`). `regions.save_region()` is a game's
  region without it, which is what a reset erases.

**A save moved is a save lost.** A new build is meant to be flashed over an old one
without touching the save area (the update image, [saves.md](saves.md)), so the save
addresses never move; `tests/test_regions.py` pins them, the journals, the first stage
and the C128 page. **Raise `regions.LAYOUT` whenever a save moves or changes format**:
the first stage compares it with the stamp on the settings page and starts nothing on a
cart whose saves are laid out for another build.

## Gotchas

Each game's own pitfalls are in its document; VICE's are in [emulation.md](emulation.md).

### Assembler

- **ACME's `^` is the bank-byte operator, not XOR.** `and #<(F_WRITABLE ^ $ff)` silently
  assembles as `and #$00`, with no warning. Spell masks out in binary.
- **`!ifndef` treats a value of `0` as defined.** `TC_NO_CMDMODE = 0` still excludes the
  code.
- **ACME's `--` is its own anonymous label**, not "the `-` two back". A `jmp --` with no
  `--` defined is an error; use named labels for anything but the nearest.
- **ACME only warns when `* = ...` lands inside code already emitted** ("Segment starts
  inside another one, overwriting it"), and the build goes on. Every pinned `* =` needs
  an assertion in front of it that the code before it ends in time; U1's driver asserts
  `u1_pre_end <= $C480` before its entry table.
- **Check scripted edits.** A string replacement that matches nothing is a silent no-op.
  Use a regex and assert its match count.

### C64 and banking

- **Put the caller's I flag back on every driver exit.** `tc_enter` does `SEI` and
  `tc_leave` does not undo it -- it cannot know what the caller wants -- so every driver
  has to. U2, U3 and U4 carry a four-instruction wrapper for it; U1 masks interrupts for
  its whole run. A missing restore does not look like a failed load: the game runs and
  the screen updates, but anything timed off the interrupt stops and the KERNAL's
  keyboard scan never runs. A game that is "alive but deaf" is this.
- **No code may run from `$D000-$DFFF` while I/O is banked in.** The whole 4 KiB is I/O
  then, colour RAM and the CIAs included, so the next instruction fetch is garbage. Code
  that lives in the RAM under I/O (U4's resident part, U6's on-demand code) must not
  bank I/O in while it runs; U6's REU status read sits in its resident for this reason.
  A test model that only maps the registers it cares about does not catch this.
- **Force I/O visible with HIRAM+CHAREN (`ora #%00000110`), never LORAM.** LORAM banks
  BASIC ROM in over `$A000-$BFFF`, which is fatal for a driver living at `$BC00`.
- **`READ_FLASH_FAST` (the cart's 2-bit read without the guard) needs a quiet display.**
  Clearing DEN is not enough on its own: the VIC samples DEN during raster line `$30`, so
  a whole frame must pass. `tc_blank`/`tc_unblank` handle this (and sprites); keying the
  wait on raster line `$F8` avoids a test of `$D011` bit 8.

### Layout and build

- **Never copy a whole driver image over an overlay.** U1's `build.py` slices the
  assembler output at the `u1_drv_end` symbol, not at the image's length: the overlay
  replaces only the driver's range, and everything above it is original and load bearing
  -- the original's memcpy at `$C4FD` and the save start/end tables at `$C5E3`/`$C5EF`,
  which `build.py` reads back. Copying the whole image zero-fills those tables, and every
  save then writes zero bytes to offset zero.
- **The standalone launchers and the decoders must not overlap.** `asm/boot_u1.s` sits
  at `$9000` and `asm/boot_u3.s` at `$8700`, clear of the decoders. A launcher that loads
  a segment over itself fails in a way that looks like a bad segment, not a bad address.
- **The Makefile lists its inputs** (`PY_SRC`, `ASM_SRC`, `KIT_SRC`). A new source
  outside those patterns gives "Nothing to be done" and a stale image in VICE.
- **Byte patterns in a regex go through `re.escape`.** `$24` is `$`, an end anchor, so an
  unescaped search for `JSR $24EF` (`20 EF 24`) can never match. Any address containing
  `$24`, `$2A`, `$2B`, `$2E`, `$3F`, `$5B`, `$5C`, `$5E`, `$7B` or `$7C` is affected;
  `bytes.find` has no such trap.
- **A scan that finds nothing must prove it looked at something.** A file list that
  parsed to zero entries reports "no hits" just as confidently.

### Memory that looks free

- **A watchpoint or memmap covers only what the session did.** Before calling RAM free,
  scan every unit of the game statically *and* exercise every mode of the game: town,
  dungeon, space, combat, character creation. For example, U1's TW and CA overlays copy
  the settlement's map (three pages) to `$CB00-$CDFF` as they start, which no session
  that stays outdoors ever sees; anything placed there is wrecked by the first town.
  `tests/test_u1_build.py` (`TestU1Memory`) guards that range.
- **VICE's memmap classifies `$D000-$DFFF` as I/O by address**, whatever the banking, so
  "no RAM access under I/O" proves nothing (see [emulation.md](emulation.md)).
- **State a negative finding with its scope.** A search of a game's resident kernel says
  nothing about its overlays; say which files, sectors or code paths were scanned.

## Repository layout

| Path | What is there |
|---|---|
| `Makefile` | every target (below) |
| `ultima/build.py` | the whole cart: the games' `parts()`, the launcher, the first stage, the image and the update image |
| `ultima/flash/` | the flash map (`regions.py`), layout, the `.tcrt` container (`tcrt.py`), zx02 (`zx.py`), symbol export (`tcsyms.py`) |
| `ultima/disks/` | the D64 reader, your images (`.d64`, `.g64`, zips), the manifest, the scan, save import, verify: [disks.md](disks.md) |
| `ultima/games/u0` .. `u6` | each game's build and driver sources (`u0`: Akalabeth) |
| `ultima/launcher/` | the launcher's build (`launcher.py`), the logo (`logo.py`), the option patches (`patches.py`), export/import tables (`xfer.py`), the U2 and U6 log models (`u2log.py`, `u6log.py`) |
| `ultima/sim/` | host models: the 6502 (`sim6502.py`, on py65), a 1541 behind trapped KERNAL calls (`fakedrive.py`), the page on the host (`pagesim.py`), a screen (`screenmodel.py`), the C128 (`c128sim.py`), the Action Replay (`armodel.py`), a disassembler, the exomizer decruncher port |
| `ultima/ef/` | Ultima VI on a 1 MiB EasyFlash: [easyflash.md](easyflash.md) |
| `ultima/maps/`, `ultima/dialogue/` | maps as PNGs, dialogue as text: [maps.md](maps.md), [dialogue.md](dialogue.md) |
| `asm/` | shared 6502 sources: tclib and its parts, the decoders, the first stage, the menu, the page and its pieces, the init stubs, the journal, the patch applier, the standalone test launchers |
| `tests/` | the host tests (`python -m unittest`, py65); `tests/data` holds RAM fixtures made in VICE, not shipped |
| `tools/vice/` | the VICE harnesses and checks: [emulation.md](emulation.md) |
| `editor/` | the save editor for the PC: [editor.md](editor.md) |
| `external/` | submodules: `zx02`, `u4remastered`, `eapi` |
| `disks/` | where users put their own disk images (any names); nothing shipped |
| `build/` | everything the build writes, including the stand-in disks in `build/disks` |

## Build and test

```sh
make                      # make cart and make ef
make all                  # make cart, ef, editor, maps and dialogue
make cart                 # build/ultima-collection.tcrt and build/ultima-collection-update.bin
make import [PICK=<image>]  # also build/ultima-collection-imported.tcrt, with the saved
                          #   games found on the disks in disks/ (docs: disks.md)
make disks                # find what the build needs in disks/, report what is missing
make ef                   # Ultima VI on EasyFlash: build/ultima6-ef.crt
make test                 # the host tests, then the editor's tests (with node)
make editor               # the save editor: build/ultima-save-editor.html
make editor-test          # the editor's tests
make editor-check         # the built editor in headless Chrome
make maps                 # every game's maps as PNGs -> build/maps/<game>/
make dialogue             # every game's dialogue as text -> build/dialogue/<game>/
make fixtures             # the RAM fixtures in tests/data, captured in VICE
make play                 # the cart in VICE (x64sc)
make play128              # Ultima V in C128 mode (x128)
make play-ef              # the EasyFlash build in VICE
make run-u1test           # U1's save round trip, in VICE
make run-u3test           # U3's save round trip, all five writable entries, in VICE
make run-menu             # the menu comes up, and each game starts from it, in VICE
make clean
```

Tools: `acme`, `ca65`/`ld65` (cc65, for U4 Remastered's units), a C compiler (for zx02,
built into `build/tools`), `python3` with **py65** (a venv in `.venv` is used when it is
there: `python3 -m venv .venv && .venv/bin/pip install py65`), and for the editor `tsc`,
`bun` and `node`. The U3 build needs py65: Ultima III Gold's disk is unpacked by Gold's
own code running in py65. VICE (`x64sc`, `x128`, `c1541`) is needed for the `play` and
`run-*` targets and `make fixtures`; VICE 3.11 or later for the key-matrix monitor
commands the harnesses use and for the tapecart LED commands.

Timings measured in VICE are not cycle exact. Compare load times against each game's
*own* loader: U1, U5 and U6 ship 2-bit fastloaders, while U2, U3 and U4 load at stock
KERNAL speed.

## Conventions

- Addresses in 6502 style (`$BA48`), and say which binary or file a runtime address is
  in.
- Keep verified findings apart from inferences, and say which is which.
- Say what was searched, not what exists: a negative result is only as broad as the scan
  behind it.
- No game data in the repository. A patch's check of the original bytes may quote up to
  15 of them; a longer run is pinned by its length and hash (`ultima/pin.py`: a `Pin`
  compares equal to the one byte string it stands for). Where the build needs the bytes
  themselves, it takes them from the disk images and checks them against the pin
  (`Patch.resolve`, a function of the original as the new bytes). Data a tool needs
  whole is generated from the disks at build time (`editor/gen_data.py`).

## Index

| Document | Subject |
|---|---|
| [transfer.md](transfer.md) | how tclib reads: `TC_GUARD`, `TC_NMI_HOLD`, compression and the two zx02 decoders |
| [launcher.md](launcher.md) | the per-game page, its look and the logo, export and import, Journey Onward, the options, the credits screens |
| [saves.md](saves.md) | updating a flashed cart (first stage, layout stamp), journals, write logs |
| [emulation.md](emulation.md) | VICE's gotchas, `tools/vice/vice_mon.py`, keys and joysticks, every harness |
| [disks.md](disks.md) | your own disk images, found by hash: manifest, scan, stand-ins, import, verify |
| [maps.md](maps.md) | `make maps`, and how each game stores its maps |
| [dialogue.md](dialogue.md) | `make dialogue`, and how each game stores its text |
| [editor.md](editor.md) | the save editor's structure, tests and fixtures |
| [easyflash.md](easyflash.md) | Ultima VI alone on a 1 MiB EasyFlash |
| [u0.md](u0.md) .. [u6.md](u6.md) | each game's driver, storage, patches, saves and tests (`u0`: Akalabeth) |

Elsewhere: `docs/guide.md` is the player's guide; `docs/changes/u0.md` .. `u6.md` describe for players what differs from the
originals; `docs/reversing-notes/u0.md` .. `u6.md`, `u3-gold.md` and `u4-remastered.md`
describe the original games themselves.
