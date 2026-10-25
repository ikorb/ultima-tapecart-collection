# Ultima IV Remastered: what it changes, and how

**Ultima IV Remastered** is Per Olofsson's (MagerValp's) remastered C64 port of Ultima IV.
Its code is (c) 2006-2015 Per Olofsson under the Apache 2.0 license. Its new graphics are
(c) 2015 Vanja Utne, and its crack intro music is (c) 2015 Johan Samuelson. The original
game is (c) 1985 Origin Systems, Inc. These notes analyse its source kit, v2.2.1
(github.com/MagerValp/u4remastered, the submodule `external/u4remastered`), against the
original four disks. The original game is described in `docs/reversing-notes/u4.md`, and
what the cart takes from Remastered in `docs/developer/u4.md`.

The analysis is static: disassembly of both versions and test assemblies of the kit's
units with ca65/ld65. Where a claim was later checked in VICE or on the cart, it says so.
Addresses are those of the original unit unless marked otherwise. Chunk and record
numbers are the kernel's. Disks are A (Program), B (Towne), C (Britannia) and D
(Underworld).

## How the kit is built

- **It patches the same release as the Trilogy disks.** All 25 of its binpatches match
  those disks byte for byte. Its file ids are exactly the kernel's chunk and record
  tables (all 116 units cross-checked), so every change maps onto "these
  blocks of this disk".
- It extracts each file from the original disks by chunk or record number. It applies
  `patches/*.binpatch` (match, replace, insert, truncate), reassembles whole overlays
  from `src/patchedgame/*.s`, and patches game main (chunk `$5B`) in RAM at startup
  (`src/gamemain/patchmain.s`).
- Its own loaders (an IFFL fastloader for a 1541, an EasyFlash version) keep code and
  data in their resident RAM: `$A000-$A0FF`, `$A600`, `$A800`/`$A900`, `$0200`, page 3,
  `$F200`/`$F300`, `$FF00`, `$D000`, `$DF00`. Several features depend on that RAM, so
  they are tied to the loader. Most gameplay changes are not.
- `u4init.s` sets up the machine (stack, SID, drive detection, a small bank helper at
  `$D000`), detects a SuperCPU and patches delays for it, installs the keyboard and
  joystick fix, and goes straight to the menu (`$6016`), skipping the title chain.
  `preload.s` links SUBS, the title, menu, music control, the driver and the first song
  into the loader PRG.

## Bug fixes

| Fix | Where (original) | How |
|---|---|---|
| Stack leaks: attacked by a monster, bridge trolls, party dead | `$5B` `$670D`, `$62E8`, `$83E1` | each `JMP` operand points at a helper that does `PLA / PLA / JMP` the original target (`attacked_by_fix`, `bridge_trolls_fix`, `player_dead_fix`) |
| Main menu and creation start game main by JSR | `$50` `$6966`, `$6A27`; `$51` `$640B` | `JSR` -> `JMP` (1 byte each) |
| Ending: thrown out of the Abyss leaves two return addresses | `$7A` (D) `$8A52`; `$9A` `$90D8` | the Use overlay's `JSR $A100` (`R $9A`) becomes `JMP`, and the throw-out's `JMP $4009` goes through `$987F` = `PLA / PLA / JMP $4009` (residue). Only both halves together drop both addresses |
| Character creation hangs at random | `$51` `$67F5`, `$681E` | the `CLI` moves after the raster IRQ is disabled and acknowledged (one byte out, one in) |
| Shrine: 0 cycles counts as 256 | `$82` `$8907-$8918` | Z tested straight after `get_number` (which ends in `PLA`), then `CMP #$04`; same length |
| Shrine: one hint for 1, 2 and 3 cycles | `$82` `$8C00-$8C01` | `shrine_msg_per_cycle` `$18,0,0,0` -> `$18,0,1,2` (the kit's source comments it "Buggy original") |
| Destard rooms 12 and 14 (level 8), Hythloth rooms 7 and 9 (level 6): no start positions | disk D blocks 45, 47, 104, 106 | start positions added (all on floor tiles, checked against the drawn maps). Room 9 also gets a trigger, `16 98 05 04`: stepping on (9, 8) turns (0, 5) and (0, 4), west wall cells, into floor. The level numbers are the changelog's |
| Resurrection plays the previous area's music | `$5B` `$83DC` | `LDA #$01` -> `LDA #$C3`: song C, the castle music |
| DEL compared with `$88` | SUBS `$12F3`, `$130A`; `$7A` (D) `$8B08` | `$94` |
| B on a dungeon ladder boards a frigate | `$5B` `$47B1` | `board_ship_check_britannia`: outside Britannia (`$1A` != 0), drop the return and print "WHAT?" |
| Enter while flying the balloon | `$5B` `$4FDA` | `enter_balloon`: "WHAT?" when the transport is the balloon (`$18`). It tests the transport, not the flying flag `$74`, so a landed balloon cannot enter either |
| A saved game loses balloon flight | `$5B` `$405C` | inside `load_dungeon`: `$74` = the saved `$1D` instead of clearing both |
| Attacking static NPCs | `$5B` `$4733`, `$46E1`; SUBS `$0B6D` | `attack_fix` maps the foe's tile: sick or sleeping `$38` -> beggar `$58`, water `$02` -> deep water `$01`, the Avatar-tile NPC `$1F` (lords) -> knight `$2A`. `attack_creature_check` makes a chest `$3C` unattackable. `combat_animate_fix` treats the ankh `$3D` and camp fire `$4B` as asleep, so they do not animate |
| Typos | `$5B`: `WH0-`, `-GOLD!`, `THE ALTER ROOM`; `$7A` (D) `$8A24`: `THE ALTER / THYNE EYES` | same-length text |
| "Joshua courage -> canrage" (changelog 2.1) | none | not in the original; a case-insensitive search of every file and all 256 talk pages finds no "CANRAGE". Inferred: a typo the remaster introduced and then removed |

**The stack leaks** (checked here in disassembly). The main loop and every command end in
JMPs, and nothing resets S, so each leak is permanent. The kit's changelog calls the
result "crashes to the ready prompt". The mechanism is inferred: once the stack wraps,
the ROM IRQ entry's BRK test reads a stray bit 4 and goes to BASIC.

**Unfinished in the kit**: J at the title with no saved game. The original's `$404D JMP
$404D` hang becomes `JMP initiate_new_game` = `JMP *`, the same hang moved. The
commented-out code would request disk 1 and `R $50`.

## Conversations and maps

The kit's talk pages (`src/talk/talk.json`, built by `gen_talk.py`) use **a different page
format** for its rewritten talk overlay (chunk `$78`). Strings end at a clear bit 7 in
`$00-$F4`, which saves a byte per string. The keywords are four characters at `$F5`/`$F9`,
the trigger at `$FD`, humility at `$FE` and turns-away at `$FF`. The overlay's
`print_string` is rewritten for it, the "SPECIAL!" trigger (unused on every page) is
removed, a full stop is printed after the name, and "ON GUARD! FOOL!" becomes "En garde!
Fool!". Otherwise the talk code is the original's, with its strings recased. The new format
makes room for the kit's longer texts. In the original format, 9 of its 256 pages would
overflow by 1-3 bytes.

**Behaviour fixes** (triggers, keywords, map bytes):

| Where | Original | Kit |
|---|---|---|
| Britain map (chunk `$61`, disk B block 286 +`$ED`) | NPC 13 points at conversation 7 (Joe), and Thevel's page is unreachable | 6, Thevel |
| Thevel's page (disk B block 86 +`$FC`) | question after keyword 2 (MAGIC) | after keyword 1 (ORBS) |
| Serpent's Hold map (chunk `$5F`, disk B block 276 +`$FC/$FD`) | both gate guards (NPCs 28, 29) use conversation 1 (Sentri's) | 2, the gate guard's own, which is on the original disk |
| Michelle, Serpent's Hold | keyword 2 HEALER shadows HEALTH, so her question is never asked | VISIT |
| Water (Castle Britannia), Shamino (Skara Brae), Charm (Cove) | trigger 0: never asked | after keyword 2 ALTAR / TRUTH / AXIOM |
| Alkerion, Minoc | trigger 10, which does not exist | after keyword 2 STONE |
| Estro (Lycaeum), a beggar (Yew) | keywords REAS, SINED (the job says RESEARCH, SINNED) | RESE, SINNED |

Of the kit's 256 pages, 2387 fields differ from the original only in case. 86 pages have
other changes, mostly added full stops and articles. There are about a dozen wording and
spelling fixes as well. **Isaac in Skara Brae** has a conversation that no map references,
in either version (not investigated). The 15 pages still without a trigger all have the
placeholder question "A".

**The content fixes can be carried in the original format**, upper case, with the original
talk overlay (the analysis's port, which the cart's `talk_fixes()` reimplements). 22 pages
change, and 20 fit. The two that do not are cosmetic: Zorin's "SERPENT'S CASTLE" (+1 byte)
and Dupre's "A HANDSOME FIGHTER." (+3).

## Mixed case

**It needs no new font and no new output code.** The original font already has
lower-case glyphs, `console_out` masks bit 7, and the original already prints mixed case
in places. The kit's text changes are pure data.

- Its binpatches are almost all case changes: game main 184 lines (plus three typos),
  the new-game roster 8, mix reagents 11, the shops (`36d`-`376`) 884. Search, Use, Camp,
  the shrine and Lord British (55 + 22 strings) are reassembled overlays with recased
  strings. Lord British's overlays also drop the music stop before `R $87`/`R $88`,
  because the kit's loader plays music during loads. Chunk `$89` (Lord British at a
  resurrection) has no unit in the kit and stays in capitals.
- **The kit's new font changes 17 glyphs, none of them letters, digits or
  punctuation**: the frame and border pieces `$88-$97` (one pixel wider) and `$DF`. The
  font colour table at `$E2B0` changes 30 entries (`$80-$9F`, `$FC-$FF`: a blue frame
  and the cursor). It belongs with the graphics.
- **Name entry in mixed case** (chunk `$50` `$6DC8`, a 17-byte routine at `$71E0` in the
  residue): an unshifted letter is stored in lower case and a shifted one in capitals.
  Other code that reads the Avatar's name may assume capitals.
- Talk input is not lower-cased. Letters arrive as capitals and are compared with the
  keyword table in capitals, and `talk.json` keeps every keyword in capitals.

## Graphics

### Tile set and renderer

The kit's loader copies five routines over the original ones **at their original
addresses**: `drawview` (SUBS `$0E6C`, slot `$EA`), `gettileaddr` (`$148B`), `fillrand`
(`$14CC`), `animate_flags` (`$1504`), and the title's `drawview` (chunk `$50` `$6B83`, slot
`$EB`). The kit's `subs.s` still contains the *old* versions of all five. A port that
takes `subs.s` alone silently loses the colour.

- **Four colours a tile**: one per 8 x 8 cell from `tilecolors0..3` (upper left, upper
  right, lower left, lower right), where the original writes one byte to all four cells
  on black. `gen_tiles.py` makes the darker of a cell's two colours its background. The
  new set uses backgrounds 0, 1, 2, 4, 5, 6 and 9. 75 tiles have more than one cell
  colour. Table 1 differs from table 0 for 29 tiles, table 3 from table 2 for 17, and
  table 2 from table 0 for 68.
- **184 of 256 tiles are redrawn.** The format is the original's, and chunk `$41` keeps
  its 32 blocks.
- `drawview` is also faster: fixed bitmap and screen pointers instead of row lookups, and
  both halves in one unrolled loop. It uses zero page `$80-$83` as scratch (no code use
  in any original unit statically). `gettileaddr` shifts in A. `fillrand` masks the random
  field pixels with `AND #$55`. `animate_flags` works on the new tiles' flag offsets and
  would corrupt the original castle and ship tiles. `randfire` is unrolled in `subs.s`.
- Where the tables live: table 0 replaces the original's `$E1B0` (chunk `$4C`, followed by
  the new font colours at `$E2B0`). **Tables 1 and 2 are at `$A800`/`$A900`** (loader RAM)
  and **table 3 at `$F300`** (chunk `$55` truncated to `$EC00-$F1FF` by `155.binpatch`).
  `$F300` is read during play by the original game: a VICE memmap saw 209 reads in
  `$F302-$F3FD`. So the kit's placement depends on its loader and on not running that
  code. A port has to put tables 1-3 elsewhere.
- Only the two renderers read `$E1B0` in the original. In the kit, the dungeon reads it
  too.
- Nothing outside SUBS jumps into the replaced routines' bodies. Every other reference
  found was data, checked by context.

### Dungeon view (chunk `$95`, disk D)

`dungeon.s` assembles to the same size as the original unit and fits its 16 blocks. Its
only new external references are colour RAM and the four colour tables.

- **Torch dimming**: the view's colour is `light_color[light_duration >> 3]`: dark grey
  below 8 turns of light, grey for 8-15, and light grey otherwise (the original draws
  white). Torch and Light set `$21` to 100.
- **The perspective is laid onto 8-pixel cells**, with walls at x = 0, `$20`, `$40`, `$50`
  and `$57` (the original's 7, `$23`, `$3F`, `$4D`, `$53`). Front walls and doors are
  filled as **byte rectangles** in the bitmap (dithered `$55`/`$AA` by facing direction)
  instead of Bresenham column by column. `set_pixel_column` walks the bitmap cell by cell.
- **Items and monsters in colour**: the four cell tables are written under the shape at
  each distance. Distance 0 is drawn at 3x (6 cells), where the original uses 4x. Distance
  3 is a 2:1 downsample. Distance 1 sits lower. Fields are coloured from `tilecolors0`
  and drawn around a monster standing in front of them.
- **It stands alone.** With all three extra tables pointed at `$E1B0`, it assembles to the
  same size and needs nothing outside the original memory map. Items and monsters then
  take the original single tile colour, and the speed, dimming and scaling are
  unchanged. The speed gain was not measured; the kit gives no figure.

### Peer at a gem (chunk `$77`)

- **Surface** (`peer_surface.s`; disks B and C carry the same page): a new `init_view`
  switches to **multicolour bitmap** (`$D016` = `$D8`), with colour RAM 6 and `$E5` as the
  cells' colours. The original's dither patterns (`$55`, `$AA`, `$FF`) then come out as
  blue water, green grass and white, with the pattern code untouched. `exit_view` restores
  `$D016` = `$C8`. The whole screen is multicolour while the map is up, so the side
  panel's hires text looks garbled.
- **Underworld** (`peer_underworld.s`, disk D): `plot_char` goes through `plot_color`,
  which colours each cell from a 15-entry table by tile type (ladders orange, chest
  yellow, orb light green, trap red, fountain light blue, field light red, walls and
  doors grey).
- No dependencies: a page swap.

### Character creation (chunks `$45-$4B`, `$51`, `$52`, `$9F`)

- **Pictures** (by Vanja Utne): `$45-$4A` and the recoloured abacus `$4B` are Koala
  pictures in the original layout (bitmap `$4000-$56FF`, screen `$5700`, colour RAM
  `$5A00`, which `$51`'s copy loop at `$6C1B` already copies). They are drop-in.
- **Cards**: the kit's cards (chunk `$52`, cut from two Koala pictures by `gen_cards.py`)
  use a third colour from colour RAM, one per card row, from chunk `$9F`'s
  `$480-$4FF` (junk in the original). They need `drawcard_d800`, which the kit puts at
  `$9D00-$9D48`. That makes `$9F` **six blocks instead of five**, so the kernel's count
  must change. Disk A block 296 is free: no disk A chunk uses it.
- **Creation code** (`charcreate.s` over `151.binpatch`): the moongate rises and sinks as
  two sprites (pointers to `$3F80`/`$3FC0`, colour 6) grown 3 bytes at a time, with the
  original's sound kept. The raster IRQ ends at `irq_continue` (`$96E6`), which makes
  the sprites shimmer and acknowledges `$D019`. `$6B71` calls `drawcard_d800`. `$6BF2`
  calls `imagefade`, a two-sided column wipe synced to the IRQ before each picture. The
  new code at `$96E6-$97F7` sits in residue. The moongate sound writes `$D07A`/`$D07B`
  (SuperCPU), which are harmless unused VIC mirrors on a stock C64. The unit is `$33F8`
  bytes and fits its 52 blocks. It uses only `$A109`, `$A100`, the KERNAL IRQ vector and
  `$3F80-$3FFF`.
- Crunched per page with zx02, the whole set costs about +23.7 KiB over the original
  (the pictures +20.3 KiB, cards +1.6, colours +0.8).

## New features

All in `src/trainer/trainerroutines.s`, hooked from `patchmain.s` or `u4init.s`. The hooks
and the original bytes were checked in disassembly of the original.

| Feature | Hooks | What it does |
|---|---|---|
| "Exit?" at a town's edge | `$5B` `$42E1`, `$43EF`, `$44B9`, `$4591` (the town-mode step's `DEC/INC` of a coordinate) -> `JSR ask_exit_* / NOP` | at the map's edge, asks "Exit? ". Anything but Y drops two return addresses and returns to `$4278`: the move is cancelled, and a turn still passes |
| Quit & save in a dungeon | `$582F` (operand of `JMP $4178`, "NOT HERE!") -> `quit_and_save_dungeon`; `$405C` -> `JSR load_dungeon` | save: disk 2, `S $7F` (plus a flush of its `$7E` cache), `S $80`, `S $1A`, disk 4. Load: if `$1B` = 3, disk 4, `L $95`, `$0845`, `JSR $50AD` (the level map), `$4D` = `$FF`, music `$C4`, the steps of a dungeon entry at `$5082-$50A7`. Towns stay "NOT HERE!" |
| Keyboard queue and joystick | SUBS `$1580` (`PHP / LDA $0277 / ORA #$80 / PLP`) -> `JSR fixed_getkey / ORA #$80 / CMP #$80`; `$159D` `JSR` -> `BIT` | takes one key off the KERNAL queue and moves the rest up, where the original takes one and throws the rest away. With no key, it reads joystick 2 (`$DC00`, at most every 5 jiffies of `$A2`): directions as `@ / : ;`, fire as E (Britannia), T (town) or A (combat), nothing in a dungeon. The four direction keys are copied at start from the KERNAL's key table (`$EBAE`-`$EBB8`), for other KERNALs' layouts |
| Active character in combat | `$7097` (`JSR $A112`), `$709D` (`LDA #1 / STA $54`), `$70C2` (`JSR $084B`), `$7131` (`JMP $4112`) | 1-8 picks a character to play alone, 0 the party; solo mode ends when that character leaves or sleeps. 177 bytes, kept at `$A04B-$A0FF` |
| Music during loads | the six `LDA #$00 / JSR $AF20` before a load (Descend, Klimb, Mix, Quit & save, Search, Use) -> `BIT` (`patch_music`) | with the stop skipped, the later `LDA #$01 / JSR $AF20` finds the song playing and does nothing. This only makes sense with a loader that keeps the IRQ running: the IFFL loader masks interrupts only inside each byte's handshake, and the EasyFlash loader brackets every byte with `SEI ... CLI` |
| Temporary map cache | `$5840` (`S $7F`) -> `j_save_7e_7f` | chunk `$7E` lives at `$DF00` (RAM under I/O) instead of on disk, loaded once at start and flushed after `S $7F`, saving a drive access (or an EasyFlash log entry) per location entry |
| Screen shake | `$85FD` | rewritten as a loop between `STA $D07A` / `STA $D07B` (SuperCPU) |

## Cheats (the trainer menu)

The kit's pre-game trainer screen has nine Yes/No lines. Its clear loop and its "all"
loop cover only eight flags (`ldx #7`), so the ninth (idle without pass, `$0128`) holds
whatever the stack page held.

| Cheat | Patch | Effect |
|---|---|---|
| Magic | `$48A1` `AC EF 48` -> `JMP $48DD` | skips the mixture and the MP check: every spell is castable, free |
| Food | `$6500` `85 58` -> `SEC / RTS` | no food consumed through `$6500`: walking (`$6275`) and gremlins (`$74D1`) |
| Torches | `$5518` `JSR $8450` -> `SEC / NOP / NOP` | Ignite lights a torch without using one |
| Keys | `$5551` `03` -> `0D` | Jimmy's branch goes straight to the unlock |
| Gems | `$57CD` -> `JMP $57D7` | Peer without a gem |
| Avoid combat | `$66FC` (operand of `JSR $8357`), `$62D7` (bridge trolls), `$6D15` (dungeon encounter) | "Avoid? " on every fight a monster starts. Y drops the caller's return and skips it. The dungeon helper prints its own "Attackd by" line |
| Control balloon | `$424E`, `$434F`, `$4428`, `$44F1` (operands of the "DRIFT ONLY!" `JMP $41F7`); SUBS `$0B15` `A5` -> `RTS` | the direction keys steer a flying balloon (landed: still "Drift only"), and the wind drift routine does nothing |
| In-game keys | `$59CE` (`JSR $0821`, "Talk-") -> `trainer_teleport`; `$47AC` (operand of `JMP $4112`, Board on nothing) -> `trainer_board` | in Britannia, T teleports to a (T)owne, (D)ungeon, (S)hrine, (L)ocation 1-8 (the game's own coordinate tables `$519A-$51D9`) or (C)oordinate (four letters A-P). It clears the object table and redraws (`$0803`). Elsewhere T is Talk. B on an empty tile asks H (horse `$14`), S (ship `$10`, which needs deep water beside) or B (balloon `$18`) |
| Idle without pass | `$4096` -> `JMP $408F`; `$70F0` -> `JMP $70EB` | the key read's timeout goes back to the read instead of "Pass" |

The kit also ships a separate save-game editor (`src/editor/`, a cc65 C program) for the
zero-page record `$1A` and chunk `$80`.

## Loader-only and not portable

- The IFFL fastloader and drive code, the single-disk packaging, the EasyFlash version and
  its save log, the crack intro, preloading, and the removed disk requests (SUBS `$1914`
  becomes `STA $5E / STA $51 / RTS`).
- **The ending's graphics at `$B000`**: the Codex pictures (chunk `$9B`) load to `$4000`
  in the original, over game main, so a throw-out reloads 80 blocks. The kit loads them
  over the tiles at `$B000` and reloads chunk `$41` (32 blocks) instead. This works around
  its 1541 build, which could not reload `$5B` ("codex hang"). The original works as is.
- `j_loadtitle` (`$A106`) is `JMP *`. No unit calls it.
- The SuperCPU hooks (`$D07A`/`$D07B`), applied when `bit $D0BC` finds one.
- The kit's IRQ stubs are the original's (`LDA #$36`/`#$35 / STA $01`). That is harmless
  for a serial drive, but they drop the cassette lines.

## Free RAM the kit relies on

The kit keeps code resident in RAM that the original game leaves alone. Static scans (all
units on all four disks, absolute operands only) agree for most of it:

| Range | Kit's use | Evidence in the original |
|---|---|---|
| `$A006-$A0FF` | loader tail, active character | nothing loads there; a VICE memmap of play saw no access |
| `$FF00-$FFF9` | board, dungeon save, SuperCPU | nothing loads there; every hit is a KERNAL `JSR` or data |
| `$86EF` on (chunk `$5B`) | the trainer's startup patcher (`$8700`, used once) | residue; the kit truncates `$5B` at `$86EF` (file offset `$46F1`) |
| `$0200-$0276`, `$02A7-$0313`, `$032C-$03FF` | trainer code | no plausible references; only creation touches page 3 (`$0314/$0315`) |
| `$F200-$F3FF` | colour table 3, other data | **not free**: the original reads `$F302-$F3FD` during play (VICE memmap) |
| `$D000-$DFFF` | the bank helper, tables, the temporary map at `$DF00` | unreachable to the original: it never banks I/O out |
