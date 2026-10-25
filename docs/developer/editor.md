# The save editor

A save editor for the PC, for the saved games the cart's launcher exports, the games' own
disks, and the cart image itself. It is one HTML file that works offline from disk:
`make editor` -> `build/ultima-save-editor.html`. This document covers its structure,
its sources of truth and its tests; how to use it is in the player's guide.

## Build

TypeScript with no npm packages (vanilla DOM), checked by `tsc` (`editor/tsconfig.json`),
bundled by `bun` (`editor/build.ts`: the script and the CSS inlined into one page, nothing
fetched from anywhere). Node runs the `.ts` files directly for the tests and the command
line; `editor/node.d.ts` declares the parts of Node's API that are used, so nothing is
installed.

```sh
make editor          # tsc -p editor, then bun editor/build.ts build/ultima-save-editor.html
make editor-test     # the fixtures (below), tsc, then node --test editor/tests/*.test.ts
make editor-check    # the built page in headless Chrome (editor/browser_check.ts)
node editor/cli.ts show FILE                 # every field: id, value, where
node editor/cli.ts set FILE OUT id=value...  # edit and write OUT, in the same wrapper
```

`cli.ts` takes the same files as the page; a `.d64` holding several save files takes
`--file="ULTIMA IV SAVE"`, a cart image `--game=1..6`.

## Structure

`editor/src/`:

| Path | What |
|---|---|
| `main.ts`, `ui/app.ts`, `ui/dom.ts`, `ui/style.css` | the page |
| `ui/combo.ts` | the searchable box for enums of more than 24 choices (U6's objects, U5's readied slots) |
| `container/open.ts` | recognises a file and opens the save in it; `serialise` writes it back in the wrapper it came in |
| `container/ucsv.ts` | the launcher's save file (`UCSV`, slot records, check bytes: [launcher.md](launcher.md)) |
| `container/pc64.ts` | the PC64 wrapper (`C64File`, NUL, 16-byte name, NUL, record size: `.S00`/`.P00`) |
| `container/d64.ts` | a `.d64`: one or several save files (a pick) |
| `container/gamedisks.ts` | the games' own disks: which disk is which (its BAM name; U6 also its ID; U4 also its disk number) and where each slot of the save file lives -- whole sectors, or a PRG file without its load address |
| `container/tcrt.ts`, `container/cart.ts` | the cart image (below) |
| `games/model.ts` | the engine: areas over the slots, encodings, records, enums, flags, warnings, actions, undo |
| `games/u1.ts` .. `u6.ts` | each game's fields, as declarative tables |
| `games/u6names.ts` | U6's object and NPC names and the object types that stack -- generated from your disks by `editor/gen_data.py` (`make editor` runs it), not in the repository |
| `games/u6original.ts` | U6's save area as the original Surface disk has it -- generated the same way |

### The containers

- **The launcher's save file**, plain or in a PC64 wrapper, or on a `.d64`.
- **The games' own disks**: slots read where the originals keep them and written back in
  place; a file keeps its chain, its load address and the bytes after its data. (U1's
  `RO` file's load address on the original disk is `$2000`, not the `$B000` the game
  writes: PRG headers on these disks are not to be trusted.) Other releases' disk names
  are accepted and the page says so: "U II-PLAYER DISK" and "ULTIMA III-SCEN." (which the
  launcher takes too), and the U4 disk of C64UltimaEditor's samples, named "U4 DISK C"
  padded with NULs and with T1/S0 byte 0 = 0, which the launcher refuses. `gamedisks.ts` holds the same tables as the build's xfer
  descriptions (`build/xfer.json`); `editor/tests/gamedisks.test.ts` compares them.
- **U1's roster seats may have no file**: RO and P0-P3 are optional (`optionalSlotArea`).
  A missing one reads as absent; the first edit -- a character copied into the seat --
  adds the slot, and an undo that leaves it all zero takes it out again. The disk
  container then writes a new file, the cart a new slot.
- **U6's file holds only what differs from the original disks**, so save-area sectors may
  be missing from it. They read as the original disk's (`u6original.ts`), and an edit
  there adds the sector to the file (an undo that restores it takes it out again).
- **The cart itself, `.tcrt`** (for playing the collection in an emulator; VICE writes the
  flash back into the image on exit with `-tapecartupdatetcrt`). `tcrt.ts` is the
  container: a content shorter than 2 MiB is erased beyond its end, and it is written
  back no shorter than it was. `cart.ts` reads the six games' saves the way the page's
  file export reads them (`f_out`, `f6_out`) and writes them the way its file import
  does (`im_write` per changed slot for U1/U3/U4/U5; U2's and U6's logs: a new half
  holding the whole save, its generation one more, the old half's directory or the whole
  old half erased). Only the opened game's region is touched. **The slot table comes
  from the cart**: the page's export tables at the end of the launcher's PRG, found by
  each disk's BAM name and checked against `gamedisks.ts` (U2's seeds live in the game
  data and move from build to build). The rest is the save layout, pinned to the
  settings page's stamp: `LAYOUT` 1; another stamp, or none, is refused. A journal a
  power cut left is finished first, as the first stage does, and the page says so.

### The fields

Per game, declarative tables (`games/u1.ts` .. `u6.ts`) over the engine in `model.ts`:
areas over the slots, BCD with the high digits first, the games' four name encodings,
enums, flags. Undo and redo are byte patches, so a field nobody edits is never
re-encoded.

**Each field is tagged with its source**: `verified` (the launcher page, the U6 transfer's
research, this project's own disassembly, or the game's own status screens) or
`reference` (another editor or document, not checked against the game's code), and the
page marks reference fields with a badge whose tooltip names the source. The reference
sources:

- **C64UltimaEditor** (by zoggins), a C# editor for U1-U4: its offsets and notes, used as
  documentation;
- **Ultima IV Remastered**'s own save editor (by Per Olofsson (MagerValp)), which edits
  exactly U4's five save blocks;
- **Ultima V Remastered**'s editor (by Drunella; its `roster_t`), and a 2004 document of
  U5's C64 save format.

Where a source and the game's code disagree, the code wins, and the field says so. Some
results of checking the fields against the games' code:

- U3's hit points are `+$1A` and their maximum `+$1C` (`ULT3`'s heal at `$6FCF` adds to
  the first and caps it at the second); C64UltimaEditor's code has them swapped, its
  notes do not.
- U1's `+$82`/`+$83` is a random seed, not a checksum (`GE` `$25BA`/`$25C0`; `SP` copies
  it to `$FC`/`$FD`).
- U5's `ROSTER` inventory starts at `+$180` (food); its readied-equipment byte is 1 + the
  item's place in armour, weapons, rings, amulets (0 none).
- U6's dungeon chunk files are `DAA`-`DED` (five levels).
- U6's clock is BCD (`$0525`: `$03` minutes, `$04` hours, `$05` day 1-28, `$06` month
  1-12, `$07`/`$08` the year, low byte first).
- U6's conditions, invisibility, level (the **low nibble** of `$57BA`), NPC flags (bit 0
  "met"), **the spellbook as NPC flags 203-210** (circle c, bit i), karma (`$09`, kept to
  99) and the quest flag (`$0B`) were followed from the game's own cheat menu's script
  into its Talk overlay's statement and function tables, to the bytes. Its inventory is
  32 slots a party place: 0-23 the pack, 24-31 worn (neck/cloak, head, body, weapon hand,
  shield hand, ring, ring, feet), status/object/quantity/quality at
  `$5400`/`$54C0`/`$5580`/`$5640`.
- U1's readied spell/weapon/armour are `+$0C`/`+$0D`/`+$0E`, its vehicles counted at
  `$8213` + vehicle, its coins in copper pence; U2's readied weapon/armour/spell are
  `+$2B`/`+$2C`/`+$2D`; U3's cards and marks are `+$0E` bit by bit, `PRTY` `+3`/`+4` the
  party's position and `+$0A`..`+$0D` the moves.

Left as bytes: U6's chunk files and NPC flags 1-7 (each conversation's own meaning), U5's
object lists, U2's `MOB`/`MON`, U3's `SOSA`/`SOSM`. Positions are shown but not edited
where the game keeps more than one copy (U5, U6).

**Limits are the bytes'**; the game's own rule is a field's `rule` (U4 attributes 50, max
HP 100 x level; U5/U6 attributes 30, levels 1-8, max HP 30 x level; U6 experience 9999). A
value beyond it is allowed but highlighted, with a warning that the game may put it back.

### The page's helpers

- **Actions**: buttons that edit several fields as one undo step (`Action` on a tab or
  section: heal and cure in U3-U6 -- the dead stay dead --, U4/U5's supplies filled, U6's
  spellbook all or none); grids of like fields get All/None or All N/All 0
  (`bulkValues`, unless `bulk: false`).
- **Warnings** are `{text, id, fix}`: Show goes to the field (tab, record, focus, a
  flash), the fix is one step; the limits banner lists each value with Show and Set to
  (`withinRule`: the step's nearest multiple).
- **Records' own edits** (`RecordDef.menus` and `.actions`, shown above the record and on
  its empty card): U1's and U3's rosters copy a character from another place ("Copy
  from…") and delete one, as the game frees a place. U1: a seat is in use while RO `+0`
  is not zero (GE `$8E29`, `$9592`); a copy takes the seat's 16 RO bytes and the P file,
  a delete clears `+0` alone, as GE's terminate (`$8ED9`) does -- the name and the P file
  stay. Nothing in a P file names its seat (the seat is `$C4F8`). U3 (BOOT, the
  Scenario's "Party organization"): a place is used while its name's first byte is not
  zero; forming a party sets `+$10` to `$FF` (`$17A1`) and copies the records into PLRS,
  dispersing copies PLRS back and clears `+$10` (`$18AF`), and ULT3 never writes ROST,
  so a member's roster record is as it was when the party was formed. The party's PLRS
  records are offered as sources too; a copy clears `+$10`. A delete zeroes the 64 bytes,
  as Terminate does (`$1980`), and like Terminate (`$195A`) it is refused, as is a copy
  over it, while `+$10` is set. No record names its place (PRTY `+6`..`+9` do, from 1).
- Undo steps carry a label (the Undo button's tooltip names the change); the Changes tab
  puts one field back (`Doc.revert`); `Doc.edit` undoes its own writes when it throws.
- U6's inventory: a count beside each place, "Add an object" (the first empty pack slot,
  its list open), a Move menu per row (take off, ready -- status bit `$08` --, give to
  another place, onto a stack of the same kind and quality).
- The combo box narrows its list as one types (word starts first; `$1F`/`#31` by the byte;
  "empty" or Enter on an empty box the empty choice), and opens on typing, a click or
  Down, not on focus, since every edit re-renders and puts the focus back.
- Long record lists (U6's people) have a filter, and keep their own scroll position across
  re-renders, the selected record scrolled into view; the Bytes tab edits in place; Enter and
  Shift+Enter in a table move down and up a column; the window title marks unsaved
  changes; a page left with unsaved edits asks before navigating away.

## Tests

- **`editor/make_fixtures.py`** (run by `make editor-test` and `make editor-check`, needs
  py65 and the built cart) writes `build/editor-fixtures/`: each game's seeded save as
  the real page exports it (the page in py65 against the built cart, seeded as
  `tests/test_page.py` and `tests/test_u6_xfer.py` seed it) -- as `.seq`, as `.s00`, and
  on a `.d64` --, `cart.tcrt` with all six saves at once, and `layout.json`, the save
  layout the editor's cart code must match. With the opt-in submodule
  `external/c64ultimaeditor` checked out (`git submodule update --init --checkout
  external/c64ultimaeditor`), C64UltimaEditor's played save disks are added as further
  read fixtures (`zoggins_*`); without it, the tests and `make editor-check` skip them.
- **`editor/tests/*.test.ts`** (Node's runner): the containers against the page's own
  exports; every field against the seeds' known values and real saves' enums; every field
  edited and undone byte-exact; the games' own disks (an edit changes one sector);
  `cart.test.ts` (each game read from the cart equal to its `.seq`, an unedited write
  giving the same bytes, an edit staying in its region, the logs alternating, journals,
  stamps, `layout.json` against `ultima/flash/regions.py` and the page's symbols);
  `u6.test.ts` (the object names and the original save area against the disk);
  `actions.test.ts`, `roster.test.ts` (copy and delete, undo byte-exact), `combo.test.ts`, `gamedisks.test.ts`, `u4.test.ts`.
- **`tests/test_editor.py`** (py65, part of `make test`; skipped without node or py65):
  every game's seeded save exported by the real page, edited by `cli.ts`, imported into a
  fresh cart by the real page ("Done."), exported again -- the same bytes. On the cart: the
  same edits made by the editor on `cart.tcrt` leave the whole 2 MiB exactly as the page's
  import of the edited file does; planted journals are finished as the real first stage
  finishes them.
- **`make editor-check`** (`editor/browser_check.ts`) drives the built page in headless
  Chrome through the DevTools protocol, with a profile under `build/`: each fixture
  dropped on the page, every tab screenshotted (`build/editor-shots/`), a field edited,
  the download decoded (the edit there, nothing else changed); every helper on U6's file
  with real clicks and keys; U6's object box with real keys. Any exception or console
  error fails it. It expects Chrome at the macOS application path (`CHROME` in the
  script).
- **In VICE**: `tools/vice/editor_vice_check.py [--tcrt]` -- U4's seeded save edited (the
  Avatar's strength 25, gold 4321), imported through the page from a 1541 (or, with
  `--tcrt`, the cart image edited directly), Journey Onward: `$AA13`/`$AB13` hold the
  edits and Ztats shows them. `tools/vice/editor_game_check.py GAME SAVE` puts a distinct
  value into every field, imports the save through the page, launches the game and reads
  its status screens (U1-U5's Ztats pages); every value shown was where the table put it.
  What the screens do not show was checked in the code.
