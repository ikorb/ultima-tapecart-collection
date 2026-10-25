# Testing under emulation

The host tests (`make test`) cover most of the code without an emulator: py65 runs the
real 6502 code against models of the cart, a 1541, the VIC's badlines, an REU, an
EasyFlash. What needs a real machine model -- the games running, keys, the screen, the
tapecart protocol at its real timing -- is checked in VICE through the scripts in
`tools/vice/`. This document is about those: VICE's pitfalls, the monitor client, how to
drive each game, and what each harness checks.

**VICE 3.11 or later** is needed, or until its release a trunk build from r46288 on
(which still calls itself 3.10: VICE bumps the number just before a release): for the
monitor's `keymatrix` and `joystick` commands (r46288), which the harnesses use to press
keys; for the tapecart's LED commands (r46272) -- an older tapecart emulation does not
re-arm its receiver after an LED command, so the next command hangs (the log ends at
`received command 0x31`); and for the tapecart in snapshots (r46287). The harnesses run
`x64sc` (and `x128`) from `$PATH`.

Run every harness from the repository root as a module: `python -m tools.vice.<name>`.
Several need a built cart first (`make`).

## VICE gotchas

- **`-keybuf` and the monitor's `keybuf` need lower case**; upper case becomes Shift+key
  and types graphics characters. The monitor's `keybuf` takes its text **unquoted**;
  quoting it types the quote characters.
- **`-initbreak` fires on PC regardless of banking**, so a breakpoint in `$A000-$BFFF`
  also catches BASIC ROM during startup. Use a conditional breakpoint (`break <addr> if
  (@cpu:$01 & $03) != $03`), or bisect from RAM addresses.
- **`r a = af` sets nothing**: the monitor takes `af` as a register name, A keeps its
  value, and there is no error. Write `$af`.
- **A screenshot taken at a breakpoint can be half a frame**: the VIC has drawn the top of
  the new frame and the bottom of the old one. Run a frame or two before the shot, or
  compare RAM.
- **The monitor truncates an input line at about 256 characters**, so a `>` command with
  256 bytes on it silently writes only the first 85. `vice_mon.poke` writes 32 bytes per
  command. A harness that never filled a buffer makes a correct program look as though it
  corrupted it.
- **Reading memory back has two traps**, both of which make a correct transfer look
  corrupt from some arbitrary offset on: a single `m` over several KiB arrives in pieces
  and a naive drain stops early, returning a *short* buffer; and the ASCII column the
  monitor prints after the bytes gets parsed as data whenever it contains space-separated
  characters that look like hex (` ee ` for two 'e's), *inserting* a byte.
  `vice_mon.mem` dumps 256 bytes at a time, places each line by the address it carries,
  takes at most 16 tokens per line, and raises if a chunk comes back short. Before
  believing "the loader corrupts data past offset N", check the harness.
- **The `.tcrt` is written back only on a clean shutdown** (`-tapecartupdatetcrt`); a
  `-limitcycles` exit silently discards flash changes, which looks exactly like "the
  write never happened". The same holds for an EasyFlash `.crt` with
  `-easyflashcrtwrite`.
- **`-tapecartloglevel 2` prints every command the cart receives** and says when it
  leaves command mode. Reach for it first: a cart dropped out of command mode (the `$C0`
  and motor rules in the [overview](README.md)) shows there at once.
- **The memmap (`mmzap`, `mmsave "<file>" 0`) shows what RAM a game really uses**;
  `tools/vice/memmap.py` reads the BMP it writes. It has two limits. It only covers the
  paths the session exercised, so pair it with a static scan before calling anything
  free. And **it classifies `$D000-$DFFF` as I/O by address, whatever the banking**: a
  write to the RAM under the I/O registers is recorded as an I/O write, never as RAM, so
  "no RAM access at `$D000`" proves nothing. (Ultima V overwrites that RAM during its
  intro.)
- **The monitor's `bank` setting matters for `$D000-$DFFF`**: read it with `bank ram`, or
  you get the chips (or zeros, with I/O banked in).
- **A snapshot carries the tapecart whole.** `dump`/`undump` cut a turnaround from ~45 s
  to ~3 s (resume with `x64sc -autostart snap.vsf`, or `undump` into a running `x64sc`
  with the cart attached). The flash and the protocol's state (the mode, command mode
  included, the lines, the receivers) travel with it, so loads and saves work after a
  restore. A VICE without the tapecart in snapshots (before r46287) restores neither:
  after a restore every flash read returns `$FF`.
- **A watchpoint hit is `Stop on` in the monitor's output**, nothing else. The register
  header has a `STOPWATCH` column, so testing for "WATCH" matches every `r`.
- **VICE's bare `delete` drops watchpoints too** -- and tracepoints; `Vice.delbreaks()`
  is one, and the U5 helpers call it all the time. Delete a breakpoint by its number when
  others must stay, or set them again after each `delete` (`u5ef_check.py`), and list
  them with `bk` at the end to show they were there.
- **A tracepoint reports without stopping** (`trace store <range> if <cond>`): each hit
  arrives in the remote monitor's output as `#n (Trace store <addr>)` with the
  instruction, while the machine runs on. To see the hits that come during a harness's
  own waits, keep everything `_drain` returns. A condition reads the CPU port as
  `@cpu:$01`.
- **A `keymatrix` press can let the machine run on past what it starts.** Set the
  breakpoint *before* the press; one set after it may come too late
  (`Vice.ef_launch_u5`). And a `break` command's own reply says "Stop on exec": match a
  hit by its `#n (Stop on` form.
- **Hijacking the PC to run a test stub can land mid-transfer**, with interrupts off and
  the cart part-way through a command; the stub then hangs and looks like a driver bug.
  Park at a known-safe point first (the end of a load, a GETIN poll) before setting PC.
- **`chis` shows the CPU history**: the instructions that led to where the machine is
  stuck.

## `tools/vice/vice_mon.py`

`Vice` starts `x64sc` with a cart (or a PRG) and talks to its remote monitor:

- `cmd`, `run`, `go`, `pc`, `goto`, `run_to(addr)`, `brk`, `delbreaks`, `quit`, `kill`;
- `mem(start, end)` and `poke(addr, data)`, with the safeguards above;
- `shot(path)`: VICE's own `screenshot "<file>" 2` (PNG; without the format VICE writes
  a BMP). Use it rather than rendering `$0400`/`$2000` by hand: a hand renderer is wrong
  wherever a game uses a raster split or another bank, and is right often enough to be
  misleading. `vic_shot` is the variant for `x128`'s VIC;
- `screen()`, `dump`/`undump`;
- keys: `keys(text)` through the KERNAL's queue; `tap(key, frames, gap, shift)`,
  `type(text)` and `joystick(port, value, frames)` through the key matrix (below);
  `send_key_at(addr, key)` and `press(key)` deliver at a poll;
- helpers for particular games: `u6_journey_onward()`, `u6_save_keys(...)`,
  `ef_launch(key)` (below).

### Keys and joysticks

The monitor's `keymatrix ROW COL [+FRAMES|on|off]` presses a key in the emulated
keyboard matrix (row = the `$DC00` bit, column = the `$DC01` bit; `keymatrix restore`,
`keymatrix clear`), and `joystick PORT VALUE [+FRAMES]` a joystick (1/2/4/8 up, down,
left, right, `$10` fire; ports from 1). A `+` count is decimal frames, everything else
hex. This reaches every keyboard scan, a game's own included, without the host keyboard's
random delay. `Vice.MATRIX` is the matrix by row.

Games that take keys only at certain points need them **delivered at the poll**: break
where the game reads a key, then put the key into `$0277` with `$C6` = 1 (or wherever the
game's own queue is). U3, for one, flushes the keyboard queue all over its attract and
menu loops, and its `$B952` reads the *last* key queued (`$0276,x` with `x = $C6`) and
then flushes, so a burst loses all but one character. Resuming past such a breakpoint can
still race; scripted key delivery is not fully deterministic in every game.

## Driving the games

### Akalabeth

Akalabeth reads its keys through GETIN (`$FFE4`), and its INPUTs (the lucky number, the
level) through the KERNAL's line editor: `u0_check.py` types those through the key matrix
and the rest at the GETIN (`send_key_at`). Its state is in its BASIC variables, which the
harness reads from RAM: the scalars from VARTAB, the arrays from ARYTAB, in BASIC's
formats ([reversing-notes/u0.md](../reversing-notes/u0.md) names them).

### Ultima I

U1 reads the keyboard with interrupts off: ST's `$1ED5` calls `SCNKEY` and `GETIN`
itself, takes a key that is held down once (a direction repeats), and queues keys in a
queue of its own (`$4E-$55`). The harnesses press keys in the key matrix. `tools/vice/u1_town_check.py`
makes a character through it and plays; `u1_dungeon_check.py` does the same and goes
down a dungeon; `u1_powers_check.py` plays F7 and B and enters a town, a dungeon and a
castle with the page's S and X poked. `u1_view_check.py` plays outdoors (and in and out of
places, and a death) and checks the bitmap of every draw it stops at against the map
(`u1view.s`). `u1_step_bench.py` times a step outdoors, key to the moved view, or the pace
of a held direction key ([u1.md](u1.md)).

### Ultima II

`tools/vice/u2_powers_check.py` makes a player at `INTRO`'s title (C, 15 into each stat,
M 1 1, a name, Y -- which goes straight into the game) and plays. Every key goes straight
into `$38`, where `SUBS`' IRQ (`$4765`) puts the KERNAL's key with bit 7 set, and the next
key only once the game has taken it (`$4075` clears bit 7); through the KERNAL's queue
keys are lost at random, and a lost Y leaves no player. C is sent until "POINTS" is on
screen, Y until the record's write (`u2_blk_write`). Idle turns pass meanwhile: left in
warp, the player starves. The idle passes also scroll a command's text off the four text
rows before a script can read it, so see what a command did by a breakpoint or in RAM.
`u2_clamp_check.py` is built on it.

`menu_check.with_autokey(n)` builds a menu that picks list place n at once, which is the
game's key (Akalabeth 0, U2 2) -- not the descriptor index.

### Ultima III

`tools/vice/u3_drive.py`: `start(page_keys, opts_or)` launches U3 from a copy of the cart,
makes a fighter in slot 1 and forms a party of it, onto Sosaria; `key` delivers at
`$B80C` (`BOOT`'s menus, the peers' waits), `gkey` at the driver's `kb_take` (play).
Letters as ASCII capitals, F7 is `$88`. O(ther) asks "WHOSE ACTION-" first.
`u3_avoid_check.py` and `u3_map_check.py` are built on it, and `u3_step_bench.py`, which times a step on the
surface: it keeps the machine on Sosaria as a snapshot (`build/u3step.vsf`), reused
while it is newer than the cart. `start` makes the character in roster slot 1 of a copy
of `build/ultima-collection.tcrt` as it is, saves included, so it needs that slot empty:
a cart played in VICE with `-tapecartupdatetcrt` has to be built again first.

### Ultima IV

`tools/vice/u4_check.py` breaks at `u4_xfer_done` (the end of every `LOADBLK`) and
compares the destination -- read with `bsave` under `bank ram`, which is fast and sees
under the ROMs -- against the flash's block map.

- `--saved` seeds the image's save slots with the party of one `tests/test_page.py`
  seeds (`seed_u4`), so `j j` reaches the overworld.
- `--reuse` boots `build/auto.tcrt` as the previous run left it, which is how a save is
  read back.
- `--sweep` calls `LOADBLK` from a stub at `$0340` for every chunk and record on every
  disk (`--d011 1b` sets the display first; `--noguard` turns `TC_GUARD`'s check off in
  RAM, the control that has to fail). A sweep takes about 20 minutes, most of it monitor
  round trips. `--time` and `--irq` are variants.

Movement is `@` `:` `;` `/` (north, west, east, south). Key delivery through the queue is
racy: the same key script walks differently from run to run.

`u4_combat_check.py` puts an object (`$AC00`/`$AC60` tile, `$AC20`/`$AC40` position)
beside the party at game main, runs Attack (`$46BB`) from `$408F` with the direction
queued, and delivers keys at combat's read `$70EB`. `u4_dungeon_check.py` saves in a
dungeon and loads back into it; `u4_nmi_check.py [--nohold]` checks the NMI hold.
`u4_stack_check.py` reads SP from the monitor's register dump (`r`) at the main loop's
key read, `cmd_done` and combat's read, and around three moongate jumps run from a stub
in the BASIC input buffer (`$0240`) with `r pc =`; its control pokes the original
`JMP $621E` back at `$86CA`.

### Ultima V

U5 needs `tools/vice/u5_drive.py`, for three reasons:

- Its **attract sequence reloads `startup` every cycle**, so any patch made before the menu
  is on screen is wiped. Anchor on `$854D`, the menu's poll, which runs once each time
  the menu appears.
- Its **main menu times out** after about a second of warp: `$9176` counts `$9152` down
  and then drops the return addresses and jumps back to the attract loop. NOP the `DEC`
  at `$917B` and the menu waits.
- Its **key read is a routine, not a KERNAL call.** `$4C4E` -> `$5BDF` reads the joystick
  port `$DC00` when `$4CAE` is zero and calls GETIN only when it is not (text entry at
  `$685C` increments it for that reason). Replacing the read at `$9190` with `LDA #$00 /
  NOP` makes it a poll that always says "no key", and a key is delivered by writing its
  code to `$9191`. The codes carry bit 7 (`$5C26` does `ORA #$80`); the menu takes `$BB`
  down, `$C0` up, `$A0` select, and `$C1`-`$CF` (A-O) play songs 1-15 through `$6C40`.

**Undo both patches after `menu_pick`**, before character creation: its name prompt polls
through the same `$9190` read. Put back `20 4E 4C` at `$9190` and `CE 52 91` at `$917B`;
keys poked into `$0277`/`$C6` are then taken. After creation, `STARTUP` plays the title
and does not come back to the menu under the harness: `reset 0` and `boot_to_menu()`
again -- the cart keeps the new character -- and `menu_pick(0)` is Journey Onward.

More about U5 in VICE:

- **U5 moves the party with the joystick.** `$5BDF` reads `$DC00`, never the keyboard
  queue, in play. `u5_drive.py`'s `joystick_patch()` repoints that `LDA $DC00` at `$0334`
  and `push()` writes directions there; the key matrix's `joystick` command works too.
  Commands (`O`, `Q`, `Y`) come from the queue. The way out of the starting hut: south
  x3, `O` + south, south until "Dost thou wish to leave?", `Y`.
- **Breaking at `$F142` (the KERNAL's GETIN) catches nothing in play.** U5 runs at `$01` =
  `$00` -- all RAM -- with its own copies of the routines under ROM. It works only during
  the early attract, before the banking changes.
- **U5's `$0380-$03FF` is live code** (an IRQ handler). A memmap of 120 steps of
  overworld play, a fight included, shows `$0335-$037F` and `$0200-$0276` untouched;
  `u5_wander.py` and `u5_sweep.py` put their stubs there. The joystick byte at `$0334`
  sits just below.
- **A cart seeded with a saved game** reaches the in-game paths without typing a name:
  `U5_SAVE_FROM=<dir> python -m ultima.build build/u5dbg.tcrt`, where `<dir>` holds the
  saved Britannia and Underworld disks as `u5-2a.d64` and `u5-2b.d64` (the save slots are
  filled from them). Debug only: **such an image says so** -- the launcher banner's second
  line reads "DEBUG, do not flash: U5 seed" in red, and the build ends with a warning
  (`ultima/build.py` `DEBUG_SWITCHES`; add any new debug switch there). `U5_NO_FAST`
  (banner "slow") leaves U5's speed patches out, for before/after comparisons.
- `u5_sweep.py [--ar | --c128 | --ef] [--sprites] [--menu]` (after a `U5_SAVE_FROM` build;
  `--menu` and `--ef` park at the main menu on the cart as built instead): calls `$6C00`
  and `$6C24` from a stub at `$0335` and compares the results with the disks; also loads
  every file carrying an option patch with the options on. `--c128` boots the launcher
  from `build/u5c128.d64` (`make build/u5c128.d64`, which `make play128` also makes) and
  stops without it.
- `u5_powers_check.py`: the launcher's X, F7 teleports and B brings a vehicle, on the
  cart as built with `build/fixture_u5created.tcrt`'s save region: out of the hut, `=`
  still "What?", B H and B S, each left with X and boarded again by the game's own Board,
  F7 to (58, 43), three ways of giving up, a save; then Journey Onward there, F7 and B
  "What?" with the option off, E into Yew. "What?" is seen as the `JMP` after it being
  reached (the text is drawn into the bitmap, not into screen RAM). B on a square with a
  vehicle on it boards that one: the ship's B is a step away from the horse X left.
- `u5_efoff_check.py`: the tapecart's own Ultima V with the EasyFlash plugged in, under both
  of VICE's EasyFlash jumper settings (`-easyflashjumper`, `+easyflashjumper`; the cart's
  `$DF00` RAM reads back in both): no AR found, the game runs.
- `u5ef_check.py`: Ultima V from the Ultima VI EasyFlash's 5 (`make cart ef`), both carts
  plugged in; tracepoints on every store to `$DE00-$DFFF` made with I/O in and the cart's
  window out, through the title's music, character creation and its save, Journey Onward,
  Britannia and a save. `Vice.ef_launch_u5()` gets a script to the init stub.
- `u5_wander.py` walks Britannia with a raw-read log, a miss counter and a data-read watchpoint on the holes.
  `u5_save_check.py` checks a `ROSTER` save through the journal. `u5_step_bench.py`
  times one step in cycles (its images come from `tools/vice/fixtures.py`).

### Ultima VI

- **Start with `Vice.u6_journey_onward()`.** It passes over stops until `A9 00 D0 0F` is
  at `$C023` -- the boot program is loaded -- and patches the cold start there. The cart's
  first stage also runs at `$1000`, where the init stub is, so stopping at `$1000` alone
  may come before the boot program is loaded, and the patch is lost under it. Every U6
  script uses the helper.
- **U6's direction keys** (`+ - £ / @ ↑ / : ; =`) need taps of about 2 frames, and Return
  at a target or item prompt about 3 (the cart's build latches taps and reads Return as
  fire: see [u6.md](u6.md)).
- **Saving, typed: `Vice.u6_save_keys`.** It waits for the save prompt (`$3E6C`), lets
  Shift go -- a Y while Shift is still held is Shift-Y, which the prompt ignores -- arms
  the save's breakpoint, then presses Y, and tries Shift-S again if no prompt came (the
  save command wants the modifier state `$48` = 1 when the key is read). A blind Y left in
  the game's key queue answers the next prompt before a breakpoint is armed.
- Harnesses: `u6_compact_check.py [worst]` (a save into a nearly full log, timed),
  `u6_keep_check.py` (the on-demand part kept in its sprite half), `u6_reu_check.py`,
  `u6_reu_d400_check.py`, `u6_wcache_check.py` (the REU and its caches),
  `u6_shift_bench.py [cart|disk|both|ef]` (a map-window shift timed on the cart, on the
  original disks, on the EasyFlash), `u6_colours_check.py` (the view's colours, for the
  maps), `u6_session.py` (a session of the *original* game from disks, with the memmap
  recording), `ram_audit.py` (the evidence for RAM the game does not use).

### The EasyFlash build

`Vice.ef_launch("j")` gets past the EasyFlash launcher (Journey Onward; on a world never
saved, where the launcher offers no J, it presses L and pokes the same at `$C00C`), or
`ef_launch("l")`. The intro and the game's menu then take Space. See
[easyflash.md](easyflash.md).

## Harnesses by subject

| Script | What it checks |
|---|---|
| `run_vice.py` | runs a PRG with a tapecart attached until it parks at a label, prints the screen (`make run-u1test`, `make run-u3test`) |
| `menu_check.py [n addr]` | the cart boots from streaming mode and the menu comes up; with arguments, auto-picks game n and checks it reaches an address (`make run-menu`) |
| `boot_check.py` | a game image with a standalone launcher reaches a given address |
| `first_stage_check.py` | the first stage: power-on, a wrong layout stamp, a planted journal |
| `unit_check.py u1\|u2\|u3 [--time] [--plain]` | every read-only unit through the driver's own routine, compared with flash, with YSCROLL stepping and sprites on every fifth unit; 15-40 minutes a game |
| `u4_check.py` | every U4 block transfer against the flash |
| `u4_stack_check.py` | U4's command-level stack, moongate jumps included |
| `page_look_check.py`, `page_reu_check.py` | the page as the KERNAL draws it; U6's REU line |
| `xfer_file_check.py` | export to a file and import from it, with a true-drive 1541 |
| `editor_vice_check.py [--tcrt]`, `editor_game_check.py GAME SAVE` | a save edited by the save editor, imported and played; each field against the game's own status screens |
| `u0_check.py` | Akalabeth from the menu, with and without its options: no LOAD at all, the instructions' pages as text, a character, a walk to a dungeon (gold and food used or not), its ladder |
| `u1_town_check.py` | U1's screen against what the map renderer draws |
| `u1_dungeon_check.py` | U1's dungeon levels as `DN` builds them against the map renderer's |
| `u1_view_check.py` | U1's outdoor view drawn only where it changed: each checked draw's bitmap against the map |
| `u1_step_bench.py`, `u2_step_bench.py`, `u3_step_bench.py`, `u5_step_bench.py` | a step's cycles, with the profiler; U1's and U2's also a held key's pace |
| `u1_powers_check.py`, `u2_powers_check.py`, `u2_clamp_check.py`, `u3_avoid_check.py`, `u3_map_check.py`, `u4_combat_check.py` | the options and cheats in play |
| `u6ef_compact_check.py`, `u6ef_xfer_check.py` | the EasyFlash build's compaction, export and import |
| `u5ef_check.py` | Ultima V from the EasyFlash's 5: its music, play, saves, no store into the cart's I/O |
| `u5_efoff_check.py` | the tapecart's Ultima V with an EasyFlash plugged in: not taken for an Action Replay |
| `memmap.py` | reads VICE's memmap BMP |

## Fixtures

Some host tests run on RAM captured from a running game. They live in `tests/data`, which
is not shipped (it is RAM of the games); **`make fixtures`** (`tools/vice/fixtures.py
[u3] [u4] [u5] [u6]`) regenerates them from the cart your disks build -- no saved game
needed. The tests that use a fixture skip without it.

| Fixture | Captured | Used by |
|---|---|---|
| `u3_screen.bin` | U3 in play on Sosaria, a party of one, screen RAM | `test_u3_peer` |
| `u4_title_frame.bin` | U4 with Remastered's tile set, the title view's second frame after the dissolve (break at `$6B83`): bitmap and screen RAM | `test_u4_tileset` |
| `u5_britannia.bin`, `u5_town.bin` | U5: a character made, let out of the hut south of Yew; the same character in Yew at noon | `test_u5_fast` |
| `u6_castle_0.bin`, `u6_castle_21.bin` | U6: Journey Onward from the cart's base, in Lord British's castle, after 0 and 21 turns walking south, with `game`'s original bytes put back where the speed patches go | `test_u6_fast`, `test_u6_init`, `test_u6_chunk` |

`fixtures.py` also writes the cart images `u5_step_bench.py` uses.
