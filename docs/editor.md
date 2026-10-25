# The save editor

A save editor for Ultima I-VI that runs in a web browser on a PC. It edits the saved games
of the collection -- the files the launcher exports, the games' own disks, and the
cartridge image itself -- so that an edited game can go back onto the cart.

## Getting it

    make editor

builds `build/ultima-save-editor.html`: one HTML file, with everything in it. Open it
from disk in a browser; it needs no installation and no network, and nothing you open in
it leaves your computer. Building it needs `tsc` (TypeScript) and `bun`; the sources are in
`editor/` (TypeScript, no packages). `make editor-test` runs its tests with Node, and
`make editor-check` drives the built page in headless Chrome.

## What it opens

Drop a file on the page, or click to pick one:

- **The launcher's save file**, as an export with **E**, **F** writes it (`ULTIMA I SAVE`
  ... `ULTIMA VI SAVE`; the format is in [save-format.md](save-format.md)), copied off the
  disk as it is.
- **The same in a PC64 wrapper** (`.S00`, `.P00`).
- **A `.d64` disk image** holding one or more of those files; with several, it asks which.
- **The game's own disk with its save**, as the original game or the launcher's export
  with **E**, **D** wrote it: Ultima I, Ultima II's Player disk, Ultima III's Scenario
  disk, Ultima IV's Britannia disk, Ultima V's Britannia and Underworld disks, Ultima VI's
  Surface disk. The slots are read where the original game keeps them and written back in
  place; a file keeps its chain, its load address and anything after its data. Disks of
  other releases with other disk names are accepted, and the editor says so (the launcher
  itself refuses them).
- **The cartridge image**, `ultima-collection.tcrt`, for playing the collection in an
  emulator. Pick one of the six games; the edit goes straight into the image, exactly where
  the launcher's import would have put it, and only that game's save region is touched.
  VICE writes the cartridge's flash back to that file when it quits, so **quit VICE (or
  detach the cartridge) before opening the image, and attach it again after saving**.

The edited file comes out in the format it went in: a save file in its wrapper, a disk
image with its sectors rewritten, a cartridge image with its save region rewritten. Import
a save file or disk on the cart with **I**; a cartridge image needs no import.

## What it edits

Each game has its own pages: the characters, the inventory, the quest and the world, as
far as the game's save is understood. Everything else is kept byte for byte.

- **Undo and redo**, each step named (the Undo button's tooltip says what it undoes).
  A field nobody edits is never re-encoded.
- **Changes** lists every field an edit changed, before you save; one of them can be put
  back from there.
- **Bytes** shows the whole save in hex and edits it in place (click, two hex digits,
  arrows).
- **Helpers** that edit several fields as one step: heal and cure (Ultima III-VI; the
  dead stay dead), supplies filled (Ultima IV and V), Ultima VI's spellbook all or none,
  and All/None buttons on grids of like fields.
- **Ultima I's and III's rosters**: "Copy from…" above a character puts another
  roster place's character there (in Ultima III also a party member, as the game plays
  it), and **Delete** frees the place as the game's own terminate does. In Ultima I that
  only marks the seat free: the name and the character file stay until a character is
  made there. In Ultima III it clears the place. Ultima III's party is formed and
  dispersed in the game: a character in the party is neither deleted nor overwritten
  (disperse it first), and its roster copy is as it was when the party was formed.
- **Ultima VI's inventory**: an "Add an object" button (the first empty pack slot), and a
  Move menu per row (take off, ready, give to another party member, onto a stack of the
  same kind). Long lists such as Ultima VI's people have a filter. Lists of more than a
  couple of dozen choices (Ultima VI's objects, Ultima V's readied items) are searchable
  boxes: type to narrow them.

Left as bytes (shown on the Bytes page, not as fields): Ultima VI's chunk files and the
meaning of its NPC flags 1-7 (each conversation's own), Ultima V's object lists, Ultima
II's MOB and MON files, Ultima III's SOSA and SOSM. Positions are shown but not edited
where the game keeps more than one copy of them (Ultima V and VI).

Ultima VI's save file holds only what differs from the original disks, so some save-area
sectors may be missing from it. Their fields read as the original disk's; an edit there
adds the sector to the file, and undoing the edit takes it out again.

## Its warnings

- **Values beyond the game's own rules.** The editor allows any value the bytes can hold,
  but highlights one beyond what the game itself would set -- for example Ultima IV's
  attributes above 50 or maximum hit points above 100 x level, Ultima V's and VI's
  attributes above 30, levels outside 1-8, maximum hit points above 30 x level, Ultima
  VI's experience above 9999. A banner lists them, each with **Show** (to the field) and
  **Set to** (the nearest allowed value). The game may put such a value back on its own.
- **Consistency warnings** name what looks wrong in a save, with **Show** and, where there
  is one, a one-step fix.
- **Fields marked *ref*** come from other people's notes and have not been checked against
  the game's code; their tooltip names the source. Every other field was checked against
  the game's code, its own status screens, or the launcher's own reading of the save.
- **Unsaved changes**: the browser asks before leaving the page. Download the edited file
  before moving on.
- **A cartridge image is refused** when its saves are laid out for another build of the
  collection, or when it carries no layout stamp at all. A journal that a power cut left in
  the image is finished first, as the cart's first stage would, and the editor says so.
- **A save file is refused** when its magic, game, version, lengths or check bytes are
  wrong, or when it is cut short or too long, as the launcher's import would refuse it.

## Sources

The editor's field layouts come from this project's own disassembly and the launcher, and,
where marked *ref*, from:

- **C64UltimaEditor** by zoggins (a clone of Xenerkes Dragon's Ultima Savegame Editor, for
  the C64 versions of Ultima I-V), used as documentation only;
- the save editor of **Ultima IV Remastered** by Per Olofsson (MagerValp), and its symbol
  files;
- the save editor of **Ultima V Remastered** by Drunella, and the 2004 document on the C64
  version's save files that comes with it.
