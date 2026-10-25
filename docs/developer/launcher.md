# The launcher: menu, per-game page, options

The launcher is what the cart shows at power-on: the list of games and, for each, a page
with its saved game, its options, Journey Onward, export and import, and a reset. This
document covers how it is built and how it reaches the games. The power-on path into it
(the first stage) is in [saves.md](saves.md); the menu's place in memory in the
[overview](README.md).

## The pieces and their memory

The launcher is **one PRG from `$4800`**, which the first stage loads at power-on
(`ultima/build.py` puts it together):

| Address | What |
|---|---|
| `$4800` | the font (bank 1) |
| `$5000` | the page, `asm/page.s` (with `page_text.s`, `page_xfer.s`, `page_u2l.s`, `page_u6x.s`, `page_u6t.s`), built by `ultima/launcher/launcher.py` after every game; it ends below `$8700` |
| `$8700` | the menu, `asm/menu.s` (`JMP start` first) |
| `REU_ORG` (`$9300`) | U6's REU line, `asm/page_reu.s`, a piece of its own |
| `XDATA` (`$9500`) | the export tables, up to `XDATA_END` (`$A000`) |
| `$A000` | the page's second piece (`page.s` `page_hi`: `page_file.s`), ending in `hi_magic`, the PRG's last bytes |

**Only the menu has to be where it is**: it runs the load loop while a game's segments
arrive, so it sits in the one window no game loads into (`$8700-$A0FF`; see `menu.s`
and the [overview](README.md)), and `tests/test_collection.py` checks it up to
`menu_end`. Everything else is the page's, done with before the first segment loads, so
it may be anywhere: nothing of a game is in memory while the launcher runs. The menu
banks BASIC out while the page runs (`run_page`: `$01 = $36`, back to `$37` after), so
`$A000-$BFFF` is RAM to the page. The REU line and the export tables fill the window
after the menu, and the second piece follows them at `$A000`, so the PRG has no gap to
store. acme emits the page as one blob; `launcher.py` cuts it into `build/page.bin` and
`build/page_hi.bin` and checks the hole between is empty.

Memory while the launcher runs: buffers `$0400-$07FF`, staging `$0800-$3FFF`, the screen
`$4400`, the font `$4800`, the page `$5000`, the rest as above. `REU_ORG` and `XDATA`
follow from the tables' size (`launcher.py`); `ultima/build.py` refuses a menu that runs
into either, and a launcher PRG that runs past the reserved area of flash (28 KiB:
`regions.RESERVED - regions.MENU_PRG`, so the PRG may reach about `$B7FF`); `page.s`
refuses a second piece past `$BFFF`. More of the page can go to the second piece by
moving its `!source` there.

## The game list

The menu reads the list from flash `$000000` (`ultima/build.py` writes it): a count,
then per game its name (16 bytes), its descriptor index -- which the page's per-game
tables go by, and which the page gets as `gid` -- and its descriptor's flash page, which
the menu loads the descriptor from. A game's place in the list is its key: 0 Akalabeth,
1-6 Ultima I-VI. Descriptor pages: `regions.desc_offset`.

## The per-game page

Picking a game in the menu runs the page first. It returns:

- **"back"** (carry set), with A = the list place to go to (the digits 0-6 on a page
  open that game's page), or `$FF` for the list;
- **"launch"**, with a **poke list**: a count, then address/value triples, 12 at most.
  The menu applies it after the game's segments are in and before the init stub runs.
  That is how an option reaches a driver, and how Journey Onward reaches a game.

What is game-specific is data from each game's build: `p["page"]` (the slot addresses the
info routine reads), `p["options"]` (which options the driver has, and where its options
byte is), `p["journey"]` and `p["xfer"]`. The menu itself stays game-agnostic.

**A game without saves** (Akalabeth) has no save region, so `launcher.py` gives it no
reset table (`rs_hi` 0), and the page shows neither a saved game nor "No saved game",
nor the blank row under it, and offers no R; without Journey Onward or export tables,
no J, E or I either: its commands are L and B.

**Reset** is generic: `launcher.py` crunches every non-erased page that a *fresh* image
has in each game's save region into the launcher's own data region, and the page erases
the whole region (the settings page excepted) and writes those back. A U6 log that is all
`$FF` is no runs at all.

**7-9**, in the list or on a page, show a page for Ultima VII, VIII or IX: the name,
"This game was omitted due to limited cartridge memory.", and only B (Back). The menu
calls the page with A = `$80` + the number (`page.s` `not_here`); while it shows, `gid`
is that value and `keys` takes only the digits and Back, which go where they go from any
page. Not in the player's guide. Tested: `test_page.test_ultima_vii_to_ix_are_not_here`.

The menu's `MENU_AUTOKEY` builds skip the page and pick the game at that list place
(its key) at once (`tools/vice/menu_check.py`, `with_autokey`).

### Layout

From the top: the game's name (at column 1, the keys' column), the saved game (names, hit
points), the options, then the commands two to a row (L/J, E/I, R/B, the second at column
21) -- 24 rows at most, with
U4's full party of eight. The saved game's numbers are right-aligned (`nwid` in
`page_text.s`: a minimum width, spaces for the leading zeros dropped), so U1's and U2's
Food and U3-U6's slash before the maximum stand in one column: four digits for U1-U3's,
three for U4's (800 at most), U5's (240) and U6's (a byte). The rows from the blank one before the commands (`brow`) are
where a question goes: `p_area` clears them and puts the cursor there (Reset, export,
import, the C128 disk).

The options are one table: `o_bits`, `o_pol` (X and G show "on" for the bit set), labels
`o_lo`/`o_hi`, X's per-game words `ox_lo`/`ox_hi`, bit 7's per-game words `o7_lo`/`o7_hi`
and its key `o7_key` (U4's W, U2's V, U1's S, Akalabeth's H), and a game's own words for
the others, `ow_lo`/`ow_hi` (Akalabeth's G and A); the items bit's key is per game too,
`oi_key` (M, Akalabeth's G). Values stand at column 31 (G's at 14). Drawing
keeps each line's row (`o_row`, from `$D6`), and a toggle rewrites only that value
through PLOT (`o_value`; each pair of values has the same length).

E (Export) is offered only with a saved game. The disks asked for are named as the games
name them: U2's "Player", U3's "Scenario".

### Ultima VI's REU line

Below the saved game on U6's page, after a blank line, in grey, one of: `REU: 512 KB, for loads and saves`;
`... for loads only` with `its verify command failed` under it; `REU: 128 KB, too small
to use`; nothing without an REU (an Action Replay's RAM at `$DF00` and an open bus count
as none).

The tests are the game's own (`ultima/games/u6/u6reu.s`, `reu_init`): the address
registers hold what is written, a stashed byte comes back, the size from where the banks
wrap (bank n := n for n = 1, 2, 4 .. 128 until bank 0 reads n; 256 KB is the least the
game takes), then the verify command on one page (its own code, to REU `$000000`): the
same bytes, its last byte different, its first. The game makes the same verify test and,
without a working verify, keeps the read cache and leaves the write cache off, so the
page and the game agree.

`page_reu.s` is assembled by `launcher.py` against the page's `pr`/`prdec16`
(`build/page_reu_syms.inc`); the page calls it for U6 only. The page runs with I/O in, so
its REU transfers start at once (command bit 4) and touch only RAM below `$D000`.

Tested: `tests/test_page_reu.py` (an REU model from 256 KB to 16 MB, a broken verify,
128 KB, an Action Replay, an open bus, none; only on U6's page; the lines within 40
columns; the game's init with and without a working verify). In VICE:
`tools/vice/page_reu_check.py`.

## Its look

**Ultima I's text font**, white and light grey on black, mixed case. The font is U1's own
(the first 1 KiB of `LO`, in ASCII order) rearranged by `launcher.font()` into the C64's
lower-case character set order, so `!pet` mixed-case strings and CHROUT show as written.
U1's `/` is a game symbol, so the build draws one to match; U1's `<`, `>` and `_` are
avoided in the texts (cancel is RUN/STOP; `<-` also works).

The VIC shows the ROM font wherever `$1000-$1FFF` is in bank 0, so the screen and font
live in **bank 1: screen `$4400`, font `$4800`**. The page's staging stays below the
screen (`im_read` checks; U6's `MAXSEC` is 20 and `ORIG` `$1C00`).

Shift+C= is blocked (`$0291` = `$80`), or the KERNAL would switch `$D018` onto the page's
data. U2's init stub sets MODE (`$0291`) bit 7 too, so Shift+C= does not flip U2's
character set either.

**Two brightnesses**: the keys in white, everything else light grey -- the list's digits
(`menu.s`), the page's option and command letters, the game's name on its page
(`page.s` `WHITE`/`GREY`, colour codes inside the strings, so no column moves). A question
below the page and a toggled value print in grey, the colour the page leaves.
`asm/page_text.s` holds the page's name and number printers; the EasyFlash launcher
includes it too. The host tests' `test_page.screen` leaves colour codes out of its
transcripts.

Before a game is loaded the menu takes the look down (`look_off`: bank 0, `$D018` `$15`,
screen `$0400` blank, `$0288`, `$0291`, the text colour `$0E`). The border stays black
through the loads and gets the KERNAL's colours right before the init stub runs, so every
game starts as it would from BASIC. Game names are shown as the games store them (U2-U4
in capitals).

### The logo

"Ultima" from Ultima V's C64 title (without its V, cyan over light blue) and under it
"TAPECART COLLECTION" in Ultima IV's letter tiles, in cyan, in screen rows 0-10.

**The picture is composed at build time from the games' data** by
`ultima/launcher/logo.py`; no copy of it is in the repository:

- U5's `U5.LOGO`, drawn into a bitmap by the title's own blitter (1A `STARTUP` `$91ED`,
  run in py65 as the attract sequence calls it), each cell in its `LOGO.COLORS`
  foreground, moved 5 cells right and 1 up, the V's cells left out;
- U4's letter tiles (disk A, chunk `$41`, tiles `$60-$79` for A-Z and `$7A` the space,
  16 x 16 each) -- the letters of its towns' signs, whose rule lines above and below join
  into a banner across 38 columns. U4's own P has an open bowl and a wide foot and reads
  as an L, so `logo.py` closes the bowl (three pixels) and narrows the foot (four).

`logo.py` turns the 320 x 88 picture into 137 characters and per-cell colours; no
sprites. The characters go into the font's **reverse half** (`$80-$FF`; the launcher
prints no reverse text) and `$61-$7F`, which only shifted-graphics PETSCII reaches and
U1's font leaves blank; never `$60`, which shifted space prints. 22 codes are spare.

The rows below the logo: the build banner on rows 13-14 (`ultima/build.py`
`banner_fragment`: "Version x", and a red second line when a debug switch made the image,
see [emulation.md](emulation.md)), a blank row, the games on rows 16-22, a blank row,
"Select a game" on row 24.

`tests/test_logo.py` draws the logo from the built image the way the VIC does and compares
it with the picture `logo.py` composes, which it also pins by hash. In VICE:
`tools/vice/page_look_check.py` (U4's longest page, F/X/G changing three rows, the Reset
question below the options) and `make run-menu`.

## Export and import

### To and from the games' own disks

`asm/page_xfer.s` (the drive layer, the prompts) with `ultima/launcher/xfer.py`; U6's
world: `asm/page_u6x.s`. Plain KERNAL serial I/O, drive 8 to 11.

Each game's build describes its saved game on disk (`p["xfer"]`): the disks in the order
to use them, each recognised by its BAM's disk name -- the Ultima Trilogy's, or another
edition's official one (U2 "U II-PLAYER DISK", Sierra's; U3 "ULTIMA III-SCEN.", the 1984
edition; U4 "BRITANNIA"); relabelled copies are refused. U6 is also checked by its disk
ID, which the game checks; U4 also by T1/S0 byte 0, its disk number (which also tells U4's
"BRITANNIA" from U5's). Per disk come the save slots: raw sectors (`U1`, `B-P` + `U2`) or
PRG files, read by name and written the way each game writes them (scratch, then save,
with the game's own load address).

- **An import reads and checks everything, from every disk, before the cart is
  touched**, so a failure or a cancel changes nothing. U6's import goes into the log's
  other half and makes it active with a header written last, as the compaction does,
  and logs only what differs from the originals.
- **U6's export** writes every chunk file (the log's newest, else the original) through a
  fresh chain from a pool the build worked out, then the save area, then a BAM that says
  exactly that: whatever copy of the disks it is given ends up consistent. About three
  and a half minutes to a real 1541, swaps excluded.

Rules of the 1541's DOS the page follows, each enforced by the host model
(`ultima/sim/fakedrive.py`, a 1541 behind the trapped KERNAL calls):

- **every channel is closed while a disk is asked for** -- with channels open, DOS may
  keep the old disk's BAM, and an export would undo itself;
- **`I0` goes out before the `#` buffer is opened** -- otherwise a 1541 answers 70, NO
  CHANNEL;
- **a failed OPEN leaves its logical file open** -- the next OPEN of it does nothing;
- **with no drive, CHKIN and CHKOUT fail** (carry set, A = 5) and leave the keyboard and
  screen as the channels; every CHKIN/CHKOUT goes to `d_gone` on carry ("Drive 8 is not
  there").

And one rule of tclib: the page counts in Y, never X, across `tc_sendbyte`/`tc_getbyte`;
the simulator's traps clobber X as the real routines may.

Tested: `tests/test_xfer.py` (U1-U5) and `tests/test_u6_xfer.py` round-trip every game on
the host. In VICE with true drive emulation, on copies of the disk images: every game out
and back byte-exact, a wrong disk refused with both sides untouched.

### To and from one file on any disk

`asm/page_file.s`. E and I ask "the game's own (D)isks, or a (F)ile on any disk?". One SEQ
file per game, `ULTIMA I SAVE` .. `ULTIMA VI SAVE`, compatible with nothing but itself:

- `UCSV`, the game's number (1-6), a version;
- for U1-U5: the slot count, then every slot of the game's xfer table as the disk export
  would write it (1, length, bytes; or 0, 0, 0 for an empty slot, which an import leaves
  erased);
- for U6: the write log's live chunk files (their logged pages, links included) and
  save-area sectors as records -- only what differs from the originals, 3-15 KiB where
  the disk export writes all 84 chunk files;
- two check bytes: a sum and a sum of sums.

An export scratches the old file first. An import checks the magic, the game, the
version, the slot count, each length against the table, the check bytes and the end of
the file before anything counts: U1-U5 stage it all and then write the cart as the disk
import does; U6 writes into the log's other half as it reads, and writes the header only
after the check, so a bad file leaves the log in use as it was. The save editor reads and
writes these files ([editor.md](editor.md)).

**The export tables** (the U1-U5 xfer tables and U6's world tables: chunk files, sector
pools, BAMs; about 2.6 KiB) sit at `XDATA`, after the menu (`build/xdata.bin`); only
`xf_lo`/`xf_hi` are in the page. They and the page's second piece (`page_file.s`) are
the end of the launcher's PRG, which ends in `hi_magic` ("UCSV"). A cart flashed with
only an update image over a build whose PRG was shorter may load neither, and E and I
say it "needs the full .tcrt image" (`x_there`, in the page's first piece, checked
before anything in the second runs). The EasyFlash launcher keeps its own check
(`efpage.s` `x_tables`, its tables ending in `x_magic`).

Tested: `tests/test_file_xfer.py` -- every game out and back (U6 a logged world, a played
one, into an existing log), an empty slot, a second export, a byte flipped anywhere, a
file cut short, one byte too many, not a save file, another game's file, no file, a PRG
of the name, no drive, neither D nor F, another drive. The host tests run the page from
the whole PRG as it is in flash (`test_page.launcher_prg`); `fakedrive.py` has SEQ files
and 64, FILE TYPE MISMATCH. In VICE with a 1541: `tools/vice/xfer_file_check.py` (keys
through the key matrix; `--drive 9 u4 u6`, `--drive 11 u1`, `--bounce u1 u6`): every
game's seeded save exported, each file byte for byte what the host model writes, and
imported into a fresh cart.

### Any drive, 8-11

Every disk prompt -- the original disks, the file, the C128 launcher -- says "in drive N",
and D there takes the next (8, 9, 10, 11, 8). The settings page keeps the choice at
`+$10` (0, as erased, is 8). The C128 launcher's instructions add `,U<n>` to the DLOAD
when the drive is not 8.

### Keys that bounce

Every (Y/N) question takes only Y or N (`yn_key`; RUN/STOP and `<-` are N); "(D)isks or
(F)ile?" takes only D, F, RUN/STOP and `<-`; and the key queue is emptied before "Done.
Press a key.", so a key that bounced during the transfer does not take the result away.
Tested by `test_file_xfer.test_only_y_or_n_answers` and `test_only_d_or_f_answers`. A D
that bounces at the drive prompt still steps two drives (it shows, and D again goes
round).

### Ultima VI: the Avatar from Ultima IV or V

T on U6's page (`asm/page_u6t.s`) puts the Avatar of a saved U4 or U5 game into a new
U6 game, by the PC version's rules. See [u6.md](u6.md).

## Journey Onward

J on the page, offered when a saved game exists, starts the game straight into the saved
game. Each game's build gives `p["journey"]`: pokes the menu applies before the init
stub, and/or bits the page ORs into the driver's options byte (`patches.JOURNEY`, never
stored) for patches applied as the code loads.

| Game | How |
|---|---|
| U1 | none: four characters, and the game asks which |
| U2 | `INTRO`'s title sequence at `$C093` jumps to `$CEBC`, the `<P>` path |
| U3 | `EXOD`'s sequence (`$826C`) is cut right after its display setup, which `BOOT` needs: `$827E` (`LDY #5 / JSR $8545`) becomes `JMP $8570`, the tail of the "any key" exit; `BOOT`'s demo view (`$116C`) and menu (`$1278` -> `$12A9`) are patched as `BOOT` loads. The U3 driver drops the bit once the menu patch is in (`u3_opt_once`), since `BOOT` comes back later in a session. |
| U4 | the title's logo sequence (`$6031`) jumps to a routine in chunk `$50`'s residue (`$71E0`, `build.py` `JOURNEY_AT`): the title's own set-up and music (`$676C-$67A1`) with the display off, colour RAM black, the display on, `JMP $6954`, the menu's J |
| U5 | `xyzzy`'s "J held" read at `$2109` becomes `LDA #$22` |
| U6 | the cold start's `LDA #$00 / BNE $C036` at `$C023` becomes `BEQ $C054`, the "load `game`" path, after the machine setup and music |

Also in U3: C at any of `EXOD`'s waits does not run `COPY`, the disk duplicator, which
cannot work without a drive (`$855E` `CMP #$C3` becomes `CMP #$00`).

Tested: `tests/test_page.py` (`test_every_game_s_journey_onward`); in VICE, J on the page
lands in the saved game for all five.

## The options

**The options are RAM patches with a signature** (`ultima/launcher/patches.py`,
`asm/patch.s`). Each driver carries `pt_apply`, a patch table and an options byte,
`pt_opts`, that the menu pokes. `pt_apply` runs after every load (U2: once, at `INTRO`'s
hand-over to `ULTIMA`, `$CED3` -> `u2_go`; U1: through `u1_done`, which sees RAM at
`$E000` because `OU` is cached there under the KERNAL).

A table entry: mask, address (2), n, the n original bytes, the n new ones; a zero mask
ends the table. **A patch is applied when its option is on and every original byte is in
place**, so it can only land in the code it was written for, whichever unit happens to be
loaded at that address, and a second call finds it applied and leaves it. The build proves
each signature appears in nothing else the game loads over that address
(`patches.check`; `check_floating` for U3's units, which load wherever the caller says;
U4 checks all its blocks at the address's page offset). What each patch does is in the
`OPTION_PATCHES` comments of each `ultima/games/<g>/build.py` and in the per-game
documents. `PT_LONG` is the variant for a table longer than 256 bytes (U4's).

**`PT_STREAM`** (U5, whose driver has no room for a table): the table is in the cart, and
`pt_apply` streams it through tclib after every named load (not after raw sector reads),
applying each entry as it passes, by the same rule, and only when an option is on.
`pt_where` (address, length) is filled in by `build.py`. The streamed applier is smaller
than the in-RAM one without its table. U5's table is 211 bytes, about 50 ms a named load
at 1 bit.

### The options byte

| Bit | Name | What |
|---|---|---|
| 0 | `FOOD` | no food used while walking (camping, and monsters that steal or eat food, still cost food) |
| 1 | `PASS` | no turn passes on an idle keyboard (U1-U4) |
| 2 | `JOURNEY` / `POWERS` | Journey Onward, this launch only, never stored (U1-U4); U5: F7 teleports, B brings a vehicle (its Journey Onward is a poke, so the bit is free there) |
| 3 | `TILES` | U4: Ultima IV Remastered's tile set (no RAM patch: the page pokes the driver's disk-A map pointer) |
| 4 | `TORCH` | igniting a torch does not use one up (U2-U5) |
| 5 | `ITEMS` | spells, keys and gems not used up: U3 (Ultima III Gold's trainers), U4 (Ultima IV Remastered's cheats), U5 (keys never break, View needs no gem, Cast needs no mixture and no MP) |
| 6 | `AVOID` | a monster's attack can be avoided ("AVOID?"): U4 (Remastered's cheat), U3 |
| 7 | `BALLOON` / `CLAMP` / `STEAL` | U4: the balloon steered, no drift; U2: counts stop at 99 and 9999; U1: no one steals |

The byte is full. Bit 7 means one thing in U4, another in U2 and a third in U1; no game
offers two of them, and the page's line for bit 7 has each game's own words and key
(`o7_lo`/`o7_hi`/`o7_key`): W does nothing on U2's and U1's pages, V nothing on U4's and
U1's, S nothing on U2's and U4's.

**Poke options** live only in the settings and the page, never in the options byte:
`POWERS` (the page's X: U4's T teleports, B brings a transport, X wins a fight; U3: Ultima
III Gold's in-game keys; U1 and U2: F1 tells the position, F7 teleports, B brings a
transport) and U2's counts. (U5's X, F7 teleports and B brings a vehicle, is
two patches, hooks into `u5powers.s` appended to `MAIN.OUT`: its bit is in U5's options byte, and `build.py` `caps()` adds it to
what `patches.caps()` reports.) The
page sends them as launch pokes (`pw_on`, `tr_on`, `cl_on` = `$80`) to hooks that are
always assembled in.

**Akalabeth's options are all pokes** and it has no options byte: F, G, A and H
(`FOOD`, `ITEMS` with its key G, `AVOID` and bit 7 with its key H) poke 100 into the trainer's flags
`$03FC-$03FF`, which the game reads ([u0.md](u0.md)). G's and A's lines have its own
words, "Gold spent when buying" and "Attacks can miss": `page.s` `ow_lo`/`ow_hi` point
a game at a list of words per option, 0 for the default (only Akalabeth has one); H's
are bit 7's per-game words.

Some sites, as examples of the kind of patch (the full lists are in each `build.py`):

- **Torches**: U2 `$79AF` and U3 `$5F86` (`SBC #$01` -> `#$00` in a BCD decrement), U4
  `$5516` (`JSR $8450`, "use up item 8", -> `SEC / NOP / NOP`, the Remastered kit's
  cheat), U5 five sites that decrement the torch count at `$1186` (`MAIN.OUT` on 2A and 2B,
  2B's `STARTUP`, `MAIN.TWN`, `MAIN.DNG`; the `STA` of each becomes a `BIT`).
- **U5's ITEMS** (`KEY_SITES`, `GEM_SITES`, `CAST_SITES` in its `build.py`): Jimmy's
  "Key broke!" decrement in several files, `STA` -> `BIT`; View's gem; Cast's
  `$A7AC LDA $1240,Y` made a `JMP` past the mixture check, and the cost's store into
  the `SBC #` operand a `BIT`, so it stays 0. The level check stays.
- **U4's X in combat** (`ultima/games/u4/u4a0.s` `pw_win`, hooked in combat's letter
  table at `$77C8`): the 16 foes' tiles (`$AD50`) cleared and the turn ended (`$621E`),
  so the game's own check after a turn (`$7514`) finds none and goes to its victory
  (`$75FF`). In a dungeon room the party walks out.
- **U3's AVOID** (`ultima/games/u3/u3avoid.s` in the decoder segment, `AVOID_HOOKS`):
  the two places `ULT3` starts a fight the party did not choose -- a monster stepping
  onto it (`$78D5 JMP $5249`, from the monsters' turn `$78AF`) and a dungeon's random
  encounter (`$8E01`). The question is Ultima III Gold's EXIT? routine (`$46C3`, `$4711`).
- **U2's powers** (`ultima/games/u2/u2powers.s` in `SUBS`' dead block I/O at `$4E6A`,
  `pw_on` in the driver, `POWER_HOOKS`): an unknown non-letter in `ULTIMA`'s command loop
  (`$5233 JMP $6702`) -- F1 prints `POSITION X-30 Y-31` and goes back to the prompt
  (`$50E7`) with no turn passed, F7 asks X and Y, two digits each up to 63, and sets
  `$02`/`$03`; Board on foot with nothing to board (`$72CD JSR $4006`) offers horse,
  frigate or plane (tiles `$22`/`$24`/`$26` set at `$13`). All three only on the surface
  (`$8E14` = 0). No rocket: a launch is the way between Earth and
  the planets.
- **U1's powers** (`ultima/games/u1/u1powers.s`, in a segment of its own at `$CE01` with
  the options' table, `POWER_HOOKS`): OU's command loop (`$8D31 JSR $85FD`) -- F1 prints
  the position, F7 asks a land (0-3) and X and Y, and enters the land as a step off its
  edge does (`$983D`);
  Board with nothing to board (`$9082 JSR $83F6`) offers horse, cart, raft, frigate or
  aircar. Outdoors only. U1's STEAL is three patches of the options byte: the bard's and
  the jester's thefts (TW `$A457`, CA `$9D88`) and the dungeon thief's (DN `$9E81`).
- **U2's counts** (`ultima/games/u2/u2clamp.s` in the driver, `CLAMP_HOOKS`): the page
  shows "Counts wrap past 99/9999", on (the original) by default. What wraps and why:
  [u2.md](u2.md).

Tested: `tests/test_options.py` runs each driver's real `pt_apply` on the host (U5's ten
files through the streamed applier; Cast, a key break and View run in py65 both ways);
`tests/test_u4_remastered.py` (`pw_win` and the game's `$7514` after it);
`tests/test_u3_build.py` (both AVOID hooks); `tests/test_u1_build.py` (F7 and B in py65);
`tests/test_u2_build.py` (both power hooks,
keys fed through `$38`; every clamp hook on and off against the disk's `ULTIMA`);
`tests/test_page.py` (the page's lines, keys and pokes). In VICE:
`tools/vice/u5_sweep.py` (every file with a torch, ITEMS or POWERS site, the three
options on: each exactly the disk's plus its patches, on a C64, with an AR and in C128
mode), `u5_powers_check.py`, `u4_combat_check.py`, `u3_avoid_check.py`,
`u2_powers_check.py`, `u2_clamp_check.py`, `u1_powers_check.py`.

## The credits while the games load

U3's and U4's boot PRGs draw a title screen of credits straight into screen RAM and leave
it up while the game loads. The cart does not run those boot PRGs, so each one's painter
and text are a boot segment at their own address (U3 `$0825-$090F`, U4 `$0839-$095A`;
the routine reads its text there), their last `JMP` into the loads made an `RTS`. The init
stubs call them and hold about four seconds (200 frames on raster line `$FB`; a key ends
it, the CIA read directly with interrupts off, `$DC00` back to `$7F`) -- unless the
options byte has `JOURNEY`. Tested: each painter run in py65 (the lines in screen RAM,
white) and the stubs' tests.
