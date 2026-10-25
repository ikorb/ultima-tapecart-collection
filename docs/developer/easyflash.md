# Ultima VI on EasyFlash

A side build beside the tapecart collection: Ultima VI alone on a 1 MiB EasyFlash
cartridge (`make ef` -> `build/ultima6-ef.crt`). It is not a replacement for the tapecart
build, which stays the main product. The code is in `ultima/ef/`.

The game's own changes are shared: both builds carry the same fixes and speed patches, and
what differs is the storage, the drivers and the launcher. Shared sources serve the
EasyFlash build only through defaults that leave the tapecart image unchanged.

EAPI, EasyFlash's flash-writing interface, comes from the `external/eapi` submodule
(EasyFlash's EAPI drivers, (c) Thomas 'skoe' Giesel). The build assembles
`eapi-am29f040.s` (the driver for the AM29F040, which VICE emulates) into its place in
bank 0. **A flashing tool such as EasyProg replaces it with the driver for the cart's own
hardware**, and some carts carry an EAPI whose source is not available, so the build
relies only on EAPI's documented contract (the EasyFlash programmer's reference), never on
one driver's internals.

```sh
make ef                  # build/ultima6-ef.crt (EF_JOURNEY=1 python -m ultima.ef.build: straight into play)
make play-ef             # x64sc -cartcrt ... -easyflashcrtwrite (written back on a clean exit only)
python -m ultima.ef.efcrt keep-log OLD.crt NEW.crt OUT.crt   # carry a saved game into a new build's .crt
```

## Shape

- **The game's changes** come from `ultima/games/u6/build.py`'s `patched_game(disks,
  irq_ora=False)`: every fix and speed patch, the init moved out of `game`. `irq_ora`
  must be False here: the tapecart build's `ORA #$05` keeps `$01` as it was, but on the
  EasyFlash an IRQ that arrives with the cart mapped in (`$01` = `$37`) has to hide it,
  which the original `LDA #$35` does. The relocated init ends in a `JMP` to its own end,
  so the EasyFlash build appends `u6.INIT_TAIL` (`JMP $03FC`).
- **The flash map**, `ultima/ef/efregions.py` (pinned by `tests/test_ef.py`): linear
  24-bit addresses in EAPI's "lhlh" order (bank n's ROML at n x `$4000`, its ROMH at
  + `$2000`; with the cart in 16K mode an address shows at `$8000 | (a & $3FFF)` in bank
  `a >> 14`).

  | Bank | What |
  |---|---|
  | 0 | the start code at `$8000`, the launcher from `$8100` on into ROMH; EAPI at ROMH `$1800` (00:1:1800); the cart's name at `$1B00`; the Ultimax reset stub (`efstub.s`) and vectors |
  | 1 | the in-game driver (ROML), the sorted static directory (ROMH) |
  | 2 | the boot driver (ROML), the static directory again (ROMH) |
  | 3- | the game's data: Game-disk files and chunk files raw, conversations zx02, the raw sector pages, the block maps |
  | the next two | with Ultima V's disks: Ultima V's music (the player, its songs, the 2-bit receive, the stage), then its boot segments as the tapecart holds them, the patches and `efu5.s` ([below](#ultima-v-from-the-tapecart-the-5)); 42 and 43 in the current build |
  | 48-63 | **the write log**: two halves of 128 KiB, each one ROML and one ROMH 64 KiB sector |

  **The log banks are left out of the CRT**, so a new build flashed over an old one with
  a tool that leaves unwritten sectors alone (EasyProg does) keeps the saved game. A cart
  that loads `.crt` files from a card keeps the log in the `.crt` file, so a new build
  starts without it; `efcrt.py keep-log` copies it across. **A save moved is a save
  lost**: `LOG_LO`/`LOG_MID`/`LOG_HI` never move.
- **The drivers run from ROM** (`efdrv.s`, assembled once per context, `EF_GAME` and
  `EF_BOOT`): parsing, block maps, both directories (the static one by binary search),
  the log. A context's RAM holds only what has to be RAM: the trampoline at the old entry
  points, the IRQ shim, a copy loop (`k_run`, at `$01` = `$33` so stores reach the RAM
  under I/O and under the ROMs), a key compare, zx02 and its input, and EAPI's callers.
  `game`'s are in its old disk code (`$2823`, `$2989-$2B4D`) and the REU cache's room
  (`$132E`); the boot's in `$C16B-$C3FF` and `$C578-$C7FF`; the ending's loader
  (`efend.s`) is self-contained, with its three files' places built in.
- **The state that outlives a call is in the cart's RAM at `$DF00`** (`efvars.inc`): the
  log's position, the write session, the active half and its generation. The programmer's
  reference leaves `$DF00-$DF7F` to the application (EAPI has `$DF80-$DFFF`). The boot's
  init (`efinit.s`, at `$1000`) scans the log and writes it there.
- **Commands must be in RAM the driver sees**: while it runs, `$8000-$BFFF` is the cart
  and `$E000+` the KERNAL. Every command string the game sends is in `$0200-$7FFF` or
  `$C000-$CFFF`; tests must put theirs there too.

## The launcher: `efpage.s`

`efstart.s` (bank 0, `$8000`) copies it from `$8100` -- bank 0's ROML on into ROMH, up to
EAPI at `$B800` -- to `$5000` and jumps there, the KERNAL initialised by the stub. Like the
tapecart's page: **L** (launch: the game's title and menu), **J** (Journey Onward), **E**
and **I** (export and import: the game's disks, a file, or the tapecart's collection),
**R** (reset: a new, empty log), and in a build with Ultima V's disks **5** (Ultima V
from the tapecart, below). The saved game is shown as the tapecart's page shows it,
the party with hit points, and **J and E are offered only with one**: the log holding the
save area's sectors 12 and 13. A world never saved has only the build's save area, which
the game's own menu answers with "Create a Character first". The page also shows the
cart's EAPI by its version string (offset 4).

- **E and I are the tapecart page's own code, included unchanged**: `asm/page_xfer.s`,
  `asm/page_u6x.s`, `asm/page_file.s`. What they take from `page.s` is re-made in
  `efpage.s` (`pr`, `getkey`, `fread_to`, `write_page`, `u6_find_log` by the
  EasyFlash's header-only rule, ...); the other games' parts assemble against stubs and
  are never reached. `ultima/ef/build.py` `page_data()` writes `efpage_data.s` (U6's disk
  table from `xfer.py`, `u6x_*` from `ultima/games/u6/build.py` `xfer_world`, the save area's
  pages from the EasyFlash's block map).
- **`eflib.s` is tclib's names over the EasyFlash**: `tc_read`; `tc_write` through EAPI
  (`WriteFlashInc` runs on across chips and banks as the linear address does);
  `tc_erase_block` -- the page erases a log half in 4 KiB steps, the EasyFlash has 64 KiB
  sectors, so the block at a half's base erases both of the half's sectors and the rest
  do nothing; and `tc_enter/sendbyte/getbyte/leave`, which answer the tapecart's
  `DIR_SETPARAMS` and `DIR_LOOKUP` from the flash (a linear scan, the first match). EAPI
  lives at `$C000` for the launcher's whole run, CIA 2's NMI latched with `$0318` at an
  RTI. Every call masks interrupts and maps the cart for itself; between calls the cart
  is off.
- **A write that fails stops all writing** (`el_werr`): every later write and erase is
  refused until the page has said "A write to the cartridge failed". An import that fails
  half way never writes its header nor erases the old half, so the old game stays.
- **Its look**: the keys white, the rest light grey, in **Ultima VI's own text-box font**
  (the intro's and the ending's, 3B `ICHARS`, stored inverted), inverted and arranged by
  the tapecart launcher's `launcher.font()`, 2 KiB in the data area, read to `$4800` at
  start.
- The drive number is not kept across power-ons (the settings would cost a 64 KiB
  erase).
- Memory: `$0400-$07FF` the transfer code's buffers, `$0800-$2FFF` buffers, the screen
  `$4400` (VIC bank 1, the font at `$4800`), the code `$5000-$8668` (`eflib` first; it
  must end below `$8000`, since it maps the cart), the tapecart's tclib at `$9000-$9299`
  while T or 5 is used, EAPI at `$C000`, `efu5.s` at `$C300` once 5 is picked. J and L read `efinit` to `$1000`, J writes Journey
  Onward's pokes into its table, then IOINIT/RESTOR/CINT and the jump with the cart in,
  `$01` = `$37`, interrupts masked. The reads from the cart's data area go by 7-byte rows
  (`rd7`: `tc_addr`, `tc_len`, `tc_dest`): the font, `efinit`, `eftc.s`, the tapecart's
  settings and `efu5.s`.

### To and from the tapecart

With both carts plugged in, **E T** writes this cart's world into the tapecart
collection's U6 log, and **I T** reads it back. Both logs hold the same kind of entries
and both builds the same originals, so a key neither log has is the original on both, and
the copy (`tx_copy`) is the disk import's loop with the source cart's log in the drive's
place: each chunk file and save-area sector the source has logged (its newest, with
links), compared with this cart's original, and logged into the destination's other half
if it differs; `x6_commit` last (the header, then the old half erased). A copy cut short
leaves the destination's world as it was. The tapecart's own static data and layout are
never needed.

- **`eftc.s`**: a second tclib (command mode, 1 bit, the LED), assembled at `TCX_ORG`
  `$9000` behind a jump table, kept in the data area and read in when T is picked.
  `eflib.s` with `EFLIB_TC`: `el_dev` bit 7 makes every `tc_*` name the tapecart's.
  `dev_ef`/`dev_tc` also put the cart's log addresses into `u6_tops` and `page_u6x`'s
  `u6_bases`; `draw` calls `dev_ef`, so every way back ends on this cart.
- **What is checked first** (`tx_open`): command mode entered at every T (no tapecart:
  "none answers"); the tapecart's settings page must say "UCFG" and this build's
  `regions.LAYOUT` (the first stage's stamp, [saves.md](saves.md)), so its U6 log is
  where `ultima/flash/regions.py` says. An import also wants a saved game there, so an
  empty tapecart cannot wipe this cart's world. Nothing is written before the Y.
- Measured in VICE: a small world (4 chunk files, 4 sectors) 6.6 s out, 8.2 s in; a
  played session of 29 keys 10.2 s out. 1-bit writes cost ~140k cycles a page, so a world
  with every chunk file live (~220 pages) would take ~35 s out (inferred).

## Ultima V from the tapecart: the 5

With both carts plugged in, **5** starts the tapecart's Ultima V with its music and 2-bit
reads from this cart, as an Action Replay gives them ([u5.md](u5.md), "Music on a C64,
from the Ultima VI EasyFlash"). The build has it only when Ultima V's disks are there
too: `u5_part` runs Ultima V's own build (`ultima/games/u5/build.py`, into
`build/ef/u5`, so a cart build beside it does not race it) and `build_efmusic`; without
the disks the page has no 5 (`efpage.s` `!ifdef U5L_SRC`).

- **Two banks**, the next free ones: the music's (the jump table at `$8000`, the player
  and its 15 songs, the receive, the stage after them; 11.6 KiB), and one with the four
  boot segments as the tapecart holds them (xyzzy, `temp.subs`, the driver, the init
  stub; 4.9 KiB), the patch list after them (a count, an address, the new bytes; 0
  ends), and `efu5.s` itself.
- **`efu5.s`**, read to `$C300` (after EAPI's slot) and called after `tx_open` has
  answered: command mode, "UCFG" and `LAYOUT`. In order, through `eftc.s`'s `tc_read`
  (a row each): U5's byte of the tapecart's settings, U5's descriptor page (compared
  with this build's), the first two bytes of U5's journal (anything but `$FF $FF`:
  refused, as `asm/boot.s` `jn_one` would act on it), the four segments one after
  another into `$0800` (the transfer buffers, RAM whatever `$01` says, clear of every
  segment's place). Those are compared byte for byte with the copy in the bank, the cart
  mapped for each read (the compare after unmapping it: an `LDX` in between would change
  Z). A refusal prints why and returns C set; nothing has been changed. Then the line
  "Cheats:" with the page's keys (F U M X) or "none", and from there on the launcher is
  overwritten: the segments to their places, the patches (the cart in for the list,
  every target below `$8000`), the options byte to `pt_opts`, IOINIT/RESTOR/CINT, `BIT
  $DD0D` (the NMI latch), `$C024` = 0 (the C128 test in `xyzzy`: EAPI's bytes are
  there), the music's bank into `$DE00`, the cart off, `JMP $0200`.
- **What it refuses**: no tapecart ("none answers"), another save layout ("has no Ultima
  collection", `tx_open`'s), another build's descriptor or segments ("the tapecart
  holds another build's. Flash both carts from the same build."), a save cut short
  ("Start the tapecart on its own once to finish it.").
- The 5 never writes to the tapecart; the game's saves go to its slots through its
  journal, as from the tapecart's own menu.

## Journey Onward's screen, and the music at a reset

- `$C054`'s `JSR $C074` stops the opening's raster split, which leaves the VIC on bank 2
  -- the picture's bitmap `$A000` and colours `$8C00` -- while the next loads land there.
  From disk the first loads take seconds and the picture stays; from the EasyFlash they
  take a frame and would show as garbage. `ub_journey` (`efboot.s`, the `$C054` call
  patched to it) does the setup and turns the display off; `game`'s own split turns it
  on. The launcher's J takes the same way in.
- Character creation's world reset makes two 64 KiB erases, which hold interrupts off
  inside EAPI for a second or more each. `d_reset` sets the SID's volume to 0 first;
  THEME's player writes `$D418` every frame it plays, so the music comes back on the first
  frame after. Only at boot: in play, the game's own sounds may not rewrite the volume.

## The interrupts: the KERNAL's vectors are game code

- **`game`'s `$0314` is `4C 64 31` and `$0317` `4C 09 1E`**: entries of its jump table
  (`$022D-$038E`). The cart is visible only with HIRAM set, which banks the KERNAL in
  too, and the KERNAL's IRQ entry is `JMP ($0314)` -- `$644C`, the tiles. So the
  trampoline points `$0314` at a shim (`PLA TAY PLA TAX PLA`, then the game's own handler
  from the RAM `$FFFE`) for as long as the cart is in, and puts the jump table back on the
  way out. No file on the Game disk calls those two entries; only code overlays do, from
  the main loop (a byte scan of every file of 3B and every sector of 1A/1B).
- **A load into page 3 overwrites the shim's pointer** -- every program the boot loads to
  `$0200` (`OPENING`, `CREATE`, `INTRO`, `GAME`). `fl_read` flags a run whose destination
  touches page 3, and `k_run` copies it with interrupts off: the program's bytes for
  `$0314`/`$0315` are kept as what the way out restores, and the shim goes back in.
- **NMI**: `e_init` latches CIA 2's NMI (one timer underflow, never acknowledged) before
  `EAPIInit`, at `$01` = `$35`, so that one NMI goes to the context's RTI. Nothing can
  raise another while EAPI's Ultimax windows are open (their vectors would come from
  whatever bank is selected). The cold start's `BIT $DD0D` releases the latch; it is set
  again before every EAPI use.

## EAPI's home: borrowed, three pages at a time

EAPI has to be in RAM (page aligned, `$0200-$7FFF` or `$C000-$CFFF`) only while it runs.
So `e_begin` copies it from 00:1:1800 into the context's slot and calls `EAPIInit` (every
time -- allowed; Ultima IV Remastered does the same), and `e_end` copies the slot's own
bytes back from flash:

- in play, **TILES `$6200-$64FF`** (tiles 16-39), back from the `TILES` file. The in-game
  memmaps write only the animated tiles there (`$6100-$611F`, `$65E0`) or reload `TILES`
  whole. A static walk of every instruction reachable from the IRQ (`$1F26`, the raster
  chain, `$208D`, `$20FE`, `$214E`, `$28CE`, `$0A97`, `$0ACC`: 347 instructions) names
  nothing there and has no indirect access;
- at boot (character creation's writes), **`$5800-$5AFF` inside `CREATE`**, back from
  `CREATE`'s file: untouched in the creation memmap, named by no instruction that ran;
  `CREATE`'s IRQ, the resident IRQ and the music player name nothing there.

## The log: what differs from the tapecart's

The log format is the tapecart build's (see [u6.md](u6.md)); the differences:

- **A half is valid only with a header** (`efinit.s` topslot: all 20 bytes, `$FE "LOG"`,
  zeros, generation and complement, zeros). The log banks are not in the CRT, so they may
  hold whatever the cart held before, and random data must not pass for a log. **No valid
  half** (a new cart, or one that held something else): `efinit` has the boot driver make
  one (`d_new`: half 0 erased, header generation 1) before the cold start, and the world
  counts as reset for that boot. `efsave.py`'s import writes a header.
- **Compaction is in the game only, when a save finds no room** (`d_pack`, from
  `d_append`, inside the write that needed the page; EAPI is in already). There is no
  boot compaction. The other half is erased (two sectors), the newest version of every
  key copied, the open session's pages after them, the header last; **the old half is not
  erased afterwards** -- the generation decides, and the next compaction erases it as its
  target. An entry is live if its key has not been copied yet: a 140-bit map in the
  cart's RAM (`P_SEEN`) for every key the game logs, the new directory searched for any
  other. Buffers: the idle sprite half (`$D800`/`$DC00` by `$27` bit 4), page 0 a compared
  or held page, page 1 the copies. A spinner turns in the cursor's cell after the prompt
  `>` (row 23, column 23).
- **The access light**, as the tapecart's: `u6_cmd` turns the frame cell below the cursor
  white while the driver runs (`efres.s`).
- **Unchanged pages are skipped, by an exact compare** (`d_same_s`, `d_same`, `k_eq` at
  `$01` = `$34`), never a checksum. A save-area sector equal to its newest version (the
  log's, else the block map's) is not written. A chunk file's pages are held back while
  each equals the same page of the file's newest version (`d_old`: logged pages with
  links compared whole, or the build's raw file compared as the drive would give it).
  The first page that differs writes the held ones first (`d_flush`), so the entry's
  pages stay in a row. A file equal to its last version gets no entry; a session closed
  early writes what it held. At most `MAXHOLD` (10) pages are held (the largest chunk
  file has 9).
- **The intro and the menu take Space or fire** (`$0C22` in `OPENING` reads keyboard
  column 4 and joystick 2's fire), Return in the menu and the name.

## Speed

Measured in VICE (x64sc, PAL), against the tapecart build:

| | tapecart | EasyFlash |
|---|---|---|
| map-window shift (`tools/vice/u6_shift_bench.py ef`) | 8.49 s | **2.6 s** steady (save 1.95, load and draw 0.65); the first after a boot 4.8 s |
| a step on the map | ~205-275k cycles | the same (CPU bound) |
| a step at a chunk boundary | 452-463k | 290-340k |
| a sector read, 256 bytes | ~90k | 5.5k |
| a 64-byte chunk read | ~28k | 2.4k |
| a conversation (zx02), T005 / T100 | 1-2 s | 0.67 / 0.28 s |
| a page written | ~140k | ~110k (~65k of it EAPI's, ~28k EAPI in and out of its slot) |
| a page compared and skipped | -- | ~10.9k |
| a save into a full log, typical / worst | -- | shift 9.5 s (~5 s compaction) / 23.2 s (~18 s) |

VICE's EAPI costs ~98k cycles a page written where EasySDK's costs ~65k in py65; a real
AM29F040 adds its program time (~14 us a byte, polled) and ~1 s (up to 8) per sector
erase. On an EasyFlash 3 a compaction takes about 3 s of spinner, then 2-3 s more of cart
accesses for the rest of the shift.

## Hardware

The build runs on real hardware: an EasyFlash 3, an EasyFlash-compatible cart with an
EAPI of its own, and a 1541 Ultimate. Flashing with EasyProg keeps the saved game.

**The screen flickers during flash writes**: on the EasyFlash 3 two cells below the
prompt, on the 1541 Ultimate line-like artifacts across the screen. *Inferred, not
verified*: EAPI writes each flash byte in Ultimax mode (four short windows a byte in
EasySDK's driver), and in Ultimax mode the VIC reads ROMH for `$3000-$3FFF` of its bank --
in the game's bank 3, `$F000-$FFFF`, the bitmap's lower part -- so each window shows a few
bytes of ROM wherever the raster is. VICE shows it too (`export.ultimax_phi1`). It is
EAPI's doing and cosmetic; reads (16K mode, which the VIC never sees) do not flicker.

**Limitation**: a write that fails for good in play (EAPI reports an error: a worn or
protected sector) makes the game retry forever, with the access light on and no message.
The launcher stops and says so; the game does not.

## Tests

- **`tests/efsim.py`**: a C64 with an EasyFlash for py65 -- the PLA (every `$01` x
  cartridge mode), `$DE00`/`$DE02`, the cart's RAM at `$DF00`, two AM29F040s at the
  command level so EasyFlash's real EAPI runs, power cuts (`cut_after`). Or
  `eapi="contract"`: the jump table trapped and answered by the documented contract
  alone, leaving the bank and `$DE02` as another driver might -- a check that nothing
  relies on one driver's internals.
- **`tests/test_ef.py`**: the flash map, the drivers, the log, compaction, power cuts, the
  access light (lit at every read, both EAPIs).
- **`tests/test_ef_u5.py`**: the 5 on the launcher with the built collection on the
  tapecart: the segments in place with the patches, the options byte for several settings
  ("Cheats: ..."), `$C024`, the bank and `$DE02`, the tapecart untouched; refused without
  a tapecart, with another layout, another descriptor, any segment's byte changed, and a
  journal begun; and a build without Ultima V's disks has no 5. The music itself:
  `tests/test_u5_efmusic.py` ([u5.md](u5.md)).
- **`tests/test_ef_xfer.py`**: the launcher, with the real EAPI and by contract: L/J, the
  party and "No saved game", the font, export and import to disks, a file and the
  tapecart (both directions, the newest of a key, nothing equal to the original copied,
  no tapecart, another layout, no stamp, no saved game, N, power cuts through an export,
  a cell that will not program), a cancelled import, a bad file, reset. `tests/test_u6_xfer.py`
  checks the tapecart page exporting to disks what this cart wrote.
- **In VICE**: `tools/vice/u6ef_compact_check.py [worst] [image]` (a save into a full log,
  read back after; `image` writes only the seeded image, `build/ef/u6efcompact.crt`, for a
  real cart), `tools/vice/u6ef_xfer_check.py [file] [disks] [tapecart] [play]` (export and
  import with a true-drive 1541, and with VICE's tapecart emulation: the `.tcrt` VICE
  writes back is the host model's byte for byte, and the tapecart then boots into Journey
  Onward with the played save area), `tools/vice/u6_shift_bench.py ef`.
  `Vice.ef_launch("j")` gets a script past the launcher ([emulation.md](emulation.md)).
  Ultima V from the 5: `tools/vice/u5_sweep.py --ef` (160 transfers against the disks,
  2-bit), `tools/vice/u5ef_check.py` (the music, creation, Journey Onward, Britannia,
  saves, and no store of the game's into the cart's I/O); `Vice.ef_launch_u5()` stops
  at the init stub.
