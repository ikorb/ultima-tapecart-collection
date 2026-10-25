# Ultima III Gold (C64): what it changes

**Ultima III Gold** is a fan version of the C64 Ultima III: "cracked, trained and
enhanced by MagerValp, released at BFP 2007, music by Zabutom", as its scroll text says.
It comes on one disk. These notes describe what it changes against the original two
disks (`docs/reversing-notes/u3.md`). The findings come from unpacking the Gold disk and
comparing every module with the original. Measurements say so where they were made.

Addresses are C64 addresses. ULT3, SUBS, UPDT and SHP3 have the same addresses in both
versions, because Gold patches them in place. **Gold's BOOT is the original shifted down
by `$72` bytes** (from Gold `$1060` on), so for BOOT these notes give the *original*
address first.

## Summary

| Feature (Gold's own list) | Where |
|---|---|
| Faster tile plotting | UPDT's blitter, SUBS' glyph printer and animations, SHPS/TEXT/frames reordered, BOOT's title-menu map |
| Revamped save system | ULT3: automatic saves go to RAM under the KERNAL; only Q writes to disk |
| Delete key in name entry | BOOT, one byte |
| Buy more than one dagger | SHP3 (the weapon shop overlay), self-contained |
| Ask on location exit | ULT3's dispatcher and about 60 bytes in ULT3's unused tail |
| Select a default character (1-4, 0) | ULT3's dispatcher, 12 "which player?" call sites, about 90 bytes in the tail |
| Trainers (magic, food, torches, keys, gems, powder) | byte patches into ULT3, applied by BOOT per menu answer |
| Trainer keys (teleport, board, exit combat, Ambrosia) | ULT3 tail code and patches |
| Keyboard remapping | BOOT reads the KERNAL's key table and patches the direction-key compares |
| Fastloader, single disk side, compression, intro | the packaging |

Everything else is byte-identical to the original: all the map, monster and conversation
files, the combat maps, DDRW, END, OUTM, DNGM, SHNE, SHP0-2 and SHP4-7, MUSI, EXOD, DEMO,
DDAT, ROST and PLRS. The original's copy-protection check (BOOT `$1DF4`) and the INSERT
SCENARIO DISK prompt are gone.

**PRTY, SOSA and SOSM on the Gold disk hold a played state**: a party record at `$CD00`,
monsters in SOSM, 10 changed tiles in SOSA. The original disk's are blank.

## How the disk is built

A normal CBM directory of 87 files.

1. `ultima iii gold` (117 blocks) is an **exomizer self-extracting file**. Stage 1
   unpacks to `$0801-$CB63`, entry `$6D9F`: the title screen with two scrollers (it waits
   for Space by reading `$DC01` directly), then the trainer menu at `$759A`. Its seven
   Y/N answers are stored in **`$D000-$D006`, the VIC's sprite X registers**, which BOOT
   reads back later. Then it puts 13 bytes back at `$0801` and jumps to `$080D`, a second
   self-extractor.
2. Stage 2 unpacks to `$0801-$F7EC`, entry `$080D`. It installs a 2-bit serial fastloader
   (drive detection for 1541, 1570, 1571, 1581, CMD FD and CMD HD; "RAMLINK -
   UNSUPPORTED!"), reads the directory and fills a new catalog at `$B000` (6 bytes an
   entry: name and track/sector), then `JMP $8220`, the original intro's entry. EXOD is
   already at `$3000` and byte-identical.
3. The DOS module at `$B800` keeps the original jump table and `^D` parser, but the
   transfer is new: the loader client at `$BA95`/`$BB61`/`$BBEB` and an exomizer
   decruncher at `$BC7C`. The files named in a table at `$BAD9` (PLRS, PRTY, ROST, SOSA,
   SOSM) are stored raw; everything else is decrunched. A file's load address comes from
   the file.
4. SUBS, ULT3, TEXT, SHPS, DEMO and DDAT are not files. BOOT calls `$BE00`, which unpacks
   **five in-memory exomizer streams** (at `$BF30`, `$C446`, `$CCB7`, `$F4F9`, `$F58C`)
   with `$01` = `$34`. That is where the game image comes from.
5. Every data file is an `exomizer raw` stream (forward, `-P0`), except the five save
   files.

When unpacking stage 2 outside a C64, model the I/O banking: the self-extractor writes the
screen's last colour cell (`$DBE7`) while I/O is banked in, and stage 2 keeps packed data
in the RAM under it. A simulator that writes the RAM there corrupts ULT3 from `$6846` on.

## The faster tile plotting

The original stores tiles and font in an Apple-like layout and its blitter walks the map
view one bitmap row at a time with self-modified single-byte copies. Gold reorders the data
into C64 bitmap order and copies a whole tile, or a character, at once.

**The data is a pure permutation of the original bytes** (verified: every byte matches):

| Data | Original layout | Gold's layout |
|---|---|---|
| SHPS `$0800-$0FFF` | `$0800 + r*$80 + t*2 + b` | `$0800 + (r>=8)*$400 + t*16 + b*8 + (r&7)` |
| TEXT `$B400-$B7FF` | `$B400 + r*$80 + c` | `$B400 + c*8 + r` |
| SUBS `$4100-$42FF` (16 animation frames) | `$4100 + i*32 + r*2 + b` | `$4100 + (r>=8)*$100 + i*16 + b*8 + (r&7)` |

So Gold's data can be produced from the original disks.

**The code** (the ranges Gold replaced, all in place):

| Unit | Range | What |
|---|---|---|
| UPDT | `$CB01-$CBE7`, `$CC66-$CC93` | the map blitter: per tile two 16-byte copies (top half from `$0800 + t*16`, bottom from `+$400`) and its colour byte. `$CC66-$CC93` saves and restores `$73`/`$7E`/`$7F` (residue in the original) |
| SUBS | `$48CE-$491A` | the glyph printer: an 8-byte copy from `$B400 + c*8` |
| SUBS | `$491B-$4962`, `$4B74-$4B8E` | the water animation (at `$492E` in the original), scratch at `$0334-$0354`. The jump-table entry `$46D8` and the four calls at `$4A87-$4AA0` are retargeted (`$2E` -> `$1B`) |
| SUBS | `$4ABE-$4B27`, `$4B2F-$4B73`, `$4B9D-$4BF5` (NOPs to `$4C17`) | the other tile animations, at new offsets |
| SUBS | `$4ECF-$4EFF` | the cursor glyph animation, new font offsets |
| BOOT | original `$1369-$144A`, `$14A1-$14F1` | the title menu's map blitter and its animations (Gold `$12F7-$1406`, `$1447-$147E`); in Gold this is one routine where the original has a blitter, a frame routine and three animations, followed by the original's tile colour table |

**Measured** in a 6502 simulator, running the real code over each version's own memory
image, with SOSA as the map, at three party positions:

| | Original | Gold | |
|---|---|---|---|
| one map redraw (`JSR $CA00`, all of UPDT) | 191-201k cycles, about 194-204 ms PAL | 98-108k, about 100-110 ms | 1.9x |
| the blit alone (`$CB01` on) | about 156k | about 64k | 2.4x |
| one character (`JSR $48C5`) | about 710 cycles | about 310 | 2.3x |

The map view (22 x 22 cells) comes out **byte-identical** in both, at all three positions,
as does the glyph. The line-of-sight pass before the blit (34-44k cycles) is unchanged.
Both idle loops redraw continuously (see the original's notes), so the redraw time is the
animation frame time and the worst-case delay before a key is noticed: about 200 ms
becomes about 100 ms on the surface.

**Other readers of the old layout**: a byte-pattern scan of every code unit found only
what Gold changed, linear-scan noise, and the dead copy of the animation code in DDRW
(`$1CB2-$1CFF`; see the original's notes). The scan can miss computed pointers. That Gold
was play-tested is some evidence the list is complete.

## The save system

The original writes to disk on seven triggers (`docs/reversing-notes/u3.md`, "Saving").
Gold keeps only the first:

| Trigger | Original | Gold |
|---|---|---|
| Q, "Quit & save" (surface only) | `$647F`: SOSA, SOSM, PLRS, PRTY to disk | **still to disk** (through `$92A9`) |
| entering a town, castle or dungeon (`$5925`) | `$64AA`: all four | RAM cache |
| back on Sosaria (`$6DA1` load, `$6DB9` save) | load, then `$64BD` all four | restored from the cache (`$927B`), cached again |
| whirlpool to Ambrosia (`$764C`) | `$64BD` all four | cache |
| leaving Ambrosia (`$7726`/`$774D` load, `$777B` save) | load, then `$64E1` PLRS/PRTY | restore and cache; the second load becomes a short delay loop |
| a character dies (`$7076` -> `$70B4`) | `$64BD` or `$64E1` | cache |
| the whole party dies (`$70AD`) | as above | cache |

The cache lives **under the KERNAL**: SOSA `$1000-$1FFF` -> `$E000-$EFFF`, SOSM `$4F00` ->
`$F000`, PLRS `$4000` -> `$F100`, PRTY `$CD00` -> `$F200`. The routines are in ULT3's
unused tail: `$922F` caches SOSA/SOSM, `$9261` PLRS/PRTY, `$927B` restores SOSA/SOSM.
`$9292` would restore PLRS/PRTY, but nothing calls it (the Gold image and all unpacked
files scanned). `$6DA7` banks the RAM in (`SEI`, `$01` = `$35`), `$9243` out (`$01` = `$36`,
`CLI`). Both values keep `$01` bit 5 (the cassette motor) set.

The consequence, which Gold's feature list states: the disk only changes on Q. A death is
not final (reboot, and the last Q save is back), and anything since the last Q is
lost at power-off. In the original, entering any town was a save point.

## The smaller features

### Delete key (BOOT)

Name entry at original `$1B25` compares the key with `$AB` (`+`) to delete. Gold compares
with `$94` (DEL): **original BOOT `$1B2E`, `$AB` -> `$94`**. `+` then does not delete.

### Buying several daggers (SHP3, the weapon shop, `$9400`)

For item 0 only, the dagger, the shop asks "AMOUNT-" (through SUBS `$46EA`), pays once
per dagger through the original purchase routine and prints "BOUGHT n". `$9502` `ADC #1`
becomes `ADC $977D` (the count). That shifts the rest of the file by one byte, hence many
+1 operands. The new code is at `$977D-$97F6`, over the file's dead tail (residue of a disk
routine and "COMPONENTS" text in the original). It calls only the SUBS and DOS jump tables
(`$46C3`, `$46DE`, `$46EA`, `$B809`, `$B80F`), so **Gold's SHP3 can replace the original
whole**.

### Ask on location exit

The surface dispatcher's four direction keys go through `$6DAD` (north, in bytes the
save change freed) and `$93B2`/`$93BA`/`$93C2`. If the move would cross the map's edge (x
or y at 1 or `$3F`) and `$62` is positive (a town or castle; `$62` is 0 on Sosaria and
negative in Ambrosia and combat; dungeons have their own dispatcher), it prints "EXIT?"
and only Y moves on. Code: `$93B2-$93F0` and the dispatcher (`$50C2`, `$50C9`, `$50D0`,
`$50D7`).

### Default character (keys 0-4)

Keys 1-4 on the surface store the player (`$934B`) and print "<name> ACTIVE"; 0 clears it
("NO ONE ACTIVE"). Dispatcher `$50DA` -> `$92F0`. Twelve of the 23 `JSR $6F04` ("which
player?") call sites become `JSR $933A`, which uses the default unless `$62` = `$80`
(combat). Hooked: cast, search a chest, torch, join gold, negate time, the other command,
both gem prompts, steal, transact, unlock, ztats. Still asking: heal, cure, resurrect and
recall targets, shrines, trading, modify order, fountains, walls.

### Trainers

BOOT's `$1D82` (Gold address) walks seven patch lists (pointers at `$1E28`/`$1E2F`, records
`length, address, bytes`; the lists at `$1E36-$1E6D`) and applies the ones answered Y:

| Option | Patch (ULT3) | Effect |
|---|---|---|
| Unlimited Magic | `$5355` `JMP $5368`; `$53E3` `JMP $5418` | fighters, thieves and barbarians may cast both schools (casters keep theirs); no MP check or cost |
| Unlimited Food | `$7463` `RTS` | the food routine does nothing (`$73D1` is its only caller) |
| Unlimited Torches | `$5F53` `JMP $5F8D` | a torch lights without asking whose and without using one |
| Unlimited Keys | `$6823` `JMP $684C` | doors unlock without a key |
| Unlimited Gems | `$6404` `JMP $6419`; `$8D94` `JMP $8DA9` | peer without a gem (surface and dungeon) |
| Unlimited Powder | `$51DB` (the command letter table's N) and `$8122` (combat) -> `$6122` | negate time without powder |
| Ingame keys | `$52B0`, `$50E5`, `$801F`, `$61DA`, and tail code `$934C-$93AF`, `$93F1-$93FA`, `$64A2` | see below |

**The ingame keys:**

- **B** on an empty square asks S/H: board a frigate or mount a horse (`$934C`).
- **X** in combat goes straight to "VICTORY!" (`$834E`, through `$93F1`).
- **O**(ther), **AMBROSIA**: the whirlpool sequence (`$756B`; it says "and your ship" on
  foot too). Gold's feature list calls this "Yell", but the hook is in the Other
  command's word check ("CMD:", where EVOCARE is). That check knows a word by its last
  letter and length only, so any 8-letter word ending in A does it. The hook overwrites
  the 18 bytes of "NO EFFECT!", so a word that does nothing prints "FAILED!".
  The sequence is the whirlpool's, made for a frigate on the whirlpool's tile: on
  Sosaria it clears the party's square to water (`$762B`: `JSR $4708 / LDA #$00 /
  STA ($7E),Y`, meant for the tile `$30`), keeps the square in `$63`/`$64`, and on the way
  back puts the party there as a frigate (`$7777`: `LDA #$16 / STA $60`). Said on land,
  the square becomes water and the party comes back on a frigate on it; said on a
  castle or town (the party stands on its tile after leaving it), the castle or town is
  gone. A frigate on land also changes the map: X-it (`$6951`) writes the frigate's tile
  `$2C` on any square below `$05` (water, grass), and Board (`$52D0`) writes water where
  the frigate stood. The B key does it at once: S goes to Board's `$52D0` (`$9367`),
  water at the party's square, H to `$52B2` (`$9372`), grass, whatever the square was.
  The teleport on a frigate leaves a frigate wherever it lands. (The cart keeps the
  map whole: `docs/developer/u3.md`, "Trainer stubs".)
- **Teleport** asks X and Y (`$9375`). It refuses only 100 and up (`CMP #$64` at `$93AF`,
  after the BCD-to-binary conversion at `$7027`), so 64-99 put the party off the 64 x 64
  map. The handler fires on key code `$88`, which the stock KERNAL's key table gives for
  **F7**. Gold's screen says "T", but T is Transact and its table entry is unchanged.

### Keyboard remapping

BOOT `$1D9F` (Gold address) reads the KERNAL's unshifted key table at `$EBAE`, `$EBAF`,
`$EBB3`, `$EBB8` (the matrix positions of `:` `@` `;` `/`) and writes those codes into the
direction compares of the surface (`$50BF`-`$50D4`), the direction prompt
(`$7BA5`-`$7BB5`), combat (`$8022`-`$8032`) and the dungeon (`$8B78`-`$8B8D`). With a US
KERNAL nothing changes. With a KERNAL that puts other characters on those keys, the same
physical keys keep working. These addresses fit Gold's reshuffled dispatcher, which also
drops the original's duplicate `CMP #$C0`. In the original layout the surface operands
are `$50BF`/`$50C6`/`$50CD`/`$50D4`/`$50DB`.

## Space and memory

- **ULT3's tail.** Gold's new ULT3 code is all in `$922F-$93FA`. The original's code ends
  at `$922E` (a table at `$921F-$922E` is referenced), and `$922F-$93FF` is BASIC residue
  (monster-name strings) with no absolute reference into it in the original image.
- **Memory Gold uses** beyond the original's: `$E000-$F2FF` under the KERNAL (the save
  cache) and `$0334-$0354` (animation scratch). Gold does not use `$C500-$C9FF` at run
  time: its packed data is left there after boot and never read again.

## What the cart takes from it

The cart takes the faster tile plotting, the save system, "EXIT?", the default
character, the delete key, the dagger shop, the magic/keys/gems/powder trainers (as a
launcher option) and the ingame keys (as another), with two differences in the last.
The details are in `docs/changes/u3.md` and `docs/developer/u3.md`.
