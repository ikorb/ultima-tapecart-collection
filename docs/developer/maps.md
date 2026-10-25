# Maps as PNGs

`make maps` draws every game's maps as PNGs into `build/maps/<game>/`, from your own
disks (or, for U3 and U4, from the units as the cart's build stores them). They are a
testing aid -- a wrong block map or a misplaced patch shows as a wrong picture -- and a
record of how each game stores its world. The code is in `ultima/maps/`; each script's
docstring has the details of its game's format, and each can be run alone as
`python -m ultima.maps.<script> [--out DIR] [what ...]`.

## The kit: `ultima/maps/mapkit.py`

PNGs written with zlib alone (no Pillow), the C64's palette, text in a game's own 8 x 8
font (U1's, the launcher's, where no other is at hand).

- **Every overworld marks its places one way**: `mark_places` (a yellow frame on the
  square and its key -- a number or letter -- beside it, outlined in black by
  `outlined` so it reads on snow), `with_legend` (key, name and x,y on the image's
  right), `write_places` (the same list as `<world>_places.txt`).
- **Text that would leave the canvas is an error** (`Canvas.text`); `mapkit.wrap` breaks
  long headers.

## Ultima I: `u1maps.py`

The four continents in the game's tiles, every place numbered and named, the towns and
castles (`towns/`, `castles/`, `settlements.txt`) and the dungeons. Files are named by
what is in them: a continent by its lands (`OU` `$9DC2` prints "You are in the lands of"
and `MI`'s name at `$7BDA` for the continent), a town or castle layout by the four places
that use it, a dungeon by its place's number and name.

- **The world is in `GE`** (character creation) at file offset `$959`, not in `MA`, whose
  bytes are graphics. `GE` puts it at `$D000`; `OU` copies those 13 pages to `$B000`
  outdoors (`$8C9E`) and back (`$9279`). Four offsets, one a continent (`$81E4` & 3),
  each to run-length bytes (count = the top five bits, tile = the low three, stored x 2;
  `$9840`), decoded into 64 x 64 at `$6400`. Kinds: 0 water, 1 grass, 2 forest, 3
  mountains, 4 castle, 5 landmark, 6 town, 7 dungeon. `MI`'s 84 places (`$7C18` y with
  the continent in bits 6-7, `$7C6C` x, names from `$7CC0`, the last letter's bit 7 set)
  each land on their own kind.
- U1 draws into a bitmap (`$D011` `$37`; `$2000` and `$4000` are its two bitmaps).
  **The tiles are `ST`'s first 2 KiB**, `$0C00-$13FF`: the view renderer (`ST` `$1C8A`,
  19 x 9 around the party; tile v = (map byte & `$7E`) / 2, monsters `$20-$58`
  alternating by a table at `$B700`) copies 32 bytes from `$0C00` + 32v -- the first 16
  the upper two cells, the next 16 the lower two -- and puts `$1500`,v in both cells'
  screen RAM. `ST` animates four tiles in place (`$1DB5`).
- **Towns and castles**: `TW` and `CA` load `TC` (`$4000`) and `MA` (`$C700`, their glyph
  set) and copy layout n from `TC`'s ten pointers to `$CB00` -- `$4000` + 2n the 2
  castles, `$4004` + 2n the 8 towns; the place's number in its continent picks n, so
  each layout serves one place a continent. A layout is 18 rows of 38 glyphs, printed
  through `MI` `$83D7`, then 16 people (`$CDAC` type, bit 7 none; `$CDBC` x; `$CDCC` y).
  The glyphs are `MA` swapped in over the text font at `$0800`, glyph g at `$0800` + 8g,
  its colour from `TW`'s table at `$A887` (`CA`'s `$A22B`). People are drawn after the
  font is swapped back, so a person of type t is glyph `$AD98`,t (`CA` `$A21D`,t) of the
  **text font**.
- **Dungeons** (`dungeons/NN_name.png`, `dungeons.txt`; 36 of them, 10 levels of 11 x 11): `DN`
  builds a level whenever the party enters it (`$8FAA`, on Enter and every Klimb) at
  `$B407`, with a generator of its own (`$A760`) **seeded from the dungeon and the level
  alone** -- place index (`$8262`) x 8 ^ x (`$81E8`) ^ level (`$A873`), and y (`$81E9`)
  x 4 ^ continent (`$81E4`) -- so a dungeon's levels are the same in every game. Only
  whether a chest's square holds a chest or a coffin (`$906D`) and the monsters (the
  high nibble of open squares, `$9F4E`) come from `ST`'s generator. The square values
  and the steps are in the script's docstring. `$A773`'s fill turns the table's
  trapdoors into secret doors, so a level starts without any. **`$A760` leaves N from
  its `LDX`** (the old first byte), not from the value it returns, and the chests'
  `BMI` at `$9062` tests that.
- U1's key queue is its own: `$4E`-`$55`, `$56` the count, filled by `$1E08`.

Checked against the game's screen in VICE (`tools/vice/u1_town_check.py`, keys through
the key matrix): a new character on continent 0, the map at `$6400` all 4096 squares as
decoded, the view 680 of 680 cells as `ST`'s tiles (animation frames allowed), Britain and
Lord British's castle each 684 of 684 cells as drawn here, people included. The
dungeons: `tests/test_u1_dungeons.py` runs `DN`'s generator under py65 for all 360 levels
(both chest-or-coffin outcomes) against `u1maps.Dungeons`; `tools/vice/u1_dungeon_check.py`
walks a new character into the Dungeon of Montor and Klimbs down to level 10 and back to
9 -- each level at `$B407` 121 of 121 squares as drawn (the low nibble), the seed's inputs
the place's.

## Ultima II: `u2maps.py`

Every `MAP` file of both disks (the Player disk's are Earth's, the Program + Galactic
disk's the planets'; `MAP xy`: x = `$8E13` the era or planet, y = `$8E14` the kind of
place), each named by what it is, with `maps.txt`.

- **Enter** (`ULTIMA` `$75D3`) goes by the tile alone, never the position: 5 village ->
  `MAP n1`, 6 town -> n2, 8 castle -> n3, 7 tower -> n4, 9 dungeon -> n5, 10 a sign. The
  surfaces key each square by that digit, with a legend.
- Earth's **time door** is placed at run time, every 8 turns on the next of four squares
  per era (`ULTIMA` `$6CA5`); door k leads to era k, or k+1 if k is not below the current
  one (`$6C08`).
- **Towers and dungeons** (16 levels of 16 x 16): `$80` wall, `$10` ladder up (Klimb
  `$79F5`), `$20` down (Descend `$75BE`), `$30` both, `$40` chest (Get `$78C9`), `$C0` door
  (drawn on the wall face, `$979C`; Advance passes, Retreat does not), `$E0` the same plus
  Descend works on it (meaning not known); entry at (5, 5) on level 1; in a dungeon Klimb
  goes to the level before, in a tower the other way. Monsters (the low 3 bits) and traps
  (rolled per step) are run time.
- Several files are byte for byte the same map (Player `MAP 15/25/35/45`; galactic
  `MAP 85` is `MAP 82`).
- U2's view is character mode: tile t is `SHAPES`' characters 4t-4t+3 (left column t*32,
  right t*32+16), hires, one colour a tile (`SUBS` `$4AC9`) on light green; map byte =
  tile x 4; `MON`: x `+$00`, y `+$20`, tile `+$60`.

## Ultima III: `u3maps.py`

From the units `ultima/games/u3/build.py` `parts()` stores (Gold's changes included).
`SHPS` (Gold's bitmap-order permutation undone) coloured by `UPDT`'s table (one screen-RAM
byte a tile); map byte = tile x 4.

- Sosaria with `SOSM`'s monsters (`ULT3`'s table at `$4F00`: tile, x `+$40`, y `+$60`) and
  the 19 entrances (`ULT3` `$77E5`/`$77F8`: entry n is `MAP` + n, A-L towns and castles,
  M-S dungeons), named from the towns' signs through `ultima/dialogue/u3talk.py`; the moon
  gate and the Great Snake by their tiles.
- Ambrosia, its four shrines by their tiles (which is which was not looked into).
- **Files are named by unit and place**: `towns/mapc_britain.png`,
  `dungeons/mapq_perinian_depths.png`, `combat/conq_ship_vs_sea_monster.png`.
- The towns with their `MON` people, the dungeons (8 levels of 16 x 16), each named by
  its first misty writing (`TLKx` entry 1: "TO YOUR DOOM!!", "FIRES OF HELL!", "TIME
  AWAITS!", "PERINIAN DEPTHS", "MINES OF MORINIA", "DARDIN'S PIT!"; the Time Lord is on
  the Dungeon of Time's level 8). `MAPP`'s first writing, "CLUES TO FOLLOW!", names
  nothing: it is the Dungeon of Snake as the one of the seven left over, a name the
  game's data does not hold.
- **The `CON` combat maps hold tile x 2**, not x 4. `ULT3` `$7E1C` patches the letter
  into `L CON@` (`$7EA2`): C in a dungeon (`$62` = 1, Enter's value at `$58C3`; 2 a
  towne, 3 a castle); the party on a frigate (`$0E` =
  tile 11 x 2): S against a pirate, Q against tiles 11-14 (frigate to man-o-war), R
  against anything else; on land: A against a pirate (it lands as tile 23, a thief), M
  against tiles 11-14; otherwise by the terrain under the party (`$09`, tile x 2, as
  Enter at `$58B0` tests it for dungeon, towne and castle): B brush, F forest, C floor,
  force field or lava, G grass and the rest. What `$0E` and `$4E` (the monster's tile x
  2) hold is inferred from the values they are compared with; the maps fit (CONF
  forest, CONS two decks on water, CONM sea and shore).

## Ultima IV: `u4maps.py [--remastered]`

**From the cart as built**: each disk's block map, each block its zx02 stream or raw, as
the driver reads it -- so the maps are what the game gets, the fixes from Ultima IV
Remastered (by Per Olofsson) included. `--remastered` draws with the Remastered tile set
(`ultima/games/u4/tileset.py`), as the page's G option switches it, into
`build/maps/u4-remastered`.

- Britannia: disk C blocks 1-256, a 16 x 16 block each, row by row; the 32 places from
  game main's `$519A`/`$51BA`, with sextant readings. The Shrine of Spirituality's entry
  repeats Humility's square and is listed without one: it is reached only through
  Minoc's moongate at a double full moon.
- The 16 towns (chunks `$5C-$6B` on disk B, 32 x 32 plus a block of people: 32 tiles, x,
  y) and `$6C`, Castle British's upper floor.
- Each dungeon's levels (chunks `$8C-$93` on disk D, 8 x 8; square kinds: `$F0` wall,
  `$10`/`$20`/`$30` ladders, `$Dn` room n, `$E0` secret door, `$A0-$A3` fields ...) and
  rooms (disk D block = room + 1: 11 x 11 at `+$80`, the start positions per side entered
  at `+$40`..`+$7F`, triggers at `+$00`). A room enterable from a side with no start
  positions there is flagged BAD: on the original disk exactly the four Remastered fixes;
  on the cart none. **Hythloth's level 6 west part leads on only through rooms 7, 8 and
  9**, which is why the original's rooms (7 with no start positions, 9 with none for the
  west and no way out west) left the rest unreachable. **The Abyss reuses its room
  numbers on several levels**, so its rooms are not `$70 + n`; where they are has not
  been looked into.

## Ultima V: `u5maps.py`

From the disks, in the layout Ultima V Remastered (by Drunella) uses in its own map tools:

- Britannia and the Underworld: disks 2A/2B, tracks 20-35 sectors 0-15, a 16 x 16 block
  each (256 x 256).
- Towns: 3A-4B, tracks 32-35, four sectors a town (2 x 2 blocks). **Each map named by
  place and floor** (`towns.txt`) from the game's own data: `main.twn` `$98DA` takes map
  = (entry - 1) & 15 + floor (`$09`, -1 a basement) from a table of the 32 places'
  ground-floor maps at `$81B8` (eight places a disk: towne, dwelling, castle, keep); a
  basement where the ground floor has a ladder down (tile `$C9`; `$C8` up). The names
  are the Enter command's (overlay `E` on 2A), which leaves places 14-18 empty: the two
  castles, named on their own, and three huts (Sutek's, Sin'Vraal's and Grendel's, by
  the one person in each hut's people table, from `ultima/dialogue/u5talk.py`).
- Dungeons: 1B track 35, two sectors a dungeon (8 levels of 8 x 8).
- Graphics: 1A's `S0`-`S3` (8 x 8 characters, four to a tile) and `COLORS` (a byte a
  character).
- **The worlds' places**: the 32 places and 8 dungeons are Enter's coordinate tables
  (`E` `$A80A`/`$A832`, the same in `main.out` `$8947`/`$893D` and 2B's `startup`), each
  on its tile, which also gives its kind (`E` `$A85A`). Ararat is the one place in the
  Underworld; the dungeons sit on the same squares in both worlds (entered from below at
  level 8, `E` `$A7CF`; Doom only from below). Also the shrines (`E` `$ADA8`/`$ADB0`), the
  Codex by its tile, the moongates at the moonstones' squares (`ROSTER` `$1280`/`$1288`),
  Search's reagent spots (`S` `$AB72`), the falls (`main.out` `$9741`) and the
  whirlpool's landing (`$9CBE`).

## Ultima VI: `u6maps.py`, `u6places.py`

The surface overview (2 px a tile), the 64 superchunks at full size, the five dungeon
levels.

- 1A: superchunk (x, y)'s chunk numbers are track y+1 sector x; its bank bits track y+1
  sector 8 bytes 32x.. (chunk n: byte n/8, **bit n & 7, low first**); chunk c's tiles
  track 26 or 30 + c/64, sector (c/4) & 15, offset (c & 3) x 64.
- 1B: level L is track L sectors 0-3 (32 x 32, row by row), its bank bits in **sector 4
  bytes `$00-$7F`** (the chunks join up only with the first half); its chunks on 1B's
  own tracks 26-33.
- Tiles: `TILES`' four 8 x 8 multicolour cells (upper left, upper right, lower left, lower
  right), `COLORS` a tile's screen-RAM byte, colour RAM light grey, `$D021` black --
  measured in VICE by `tools/vice/u6_colours_check.py` (Journey Onward from a fresh cart,
  the view's cells matched against `TILES`). The bank-bit order and the dungeon layout
  were chosen by how many tiles match across chunk borders.
- **Places** (`u6places.py`): 1A's object files are `S<row><column>` (x = third letter x
  128 + byte 1, y = second x 128 + byte 2), six bytes a record (0 type, 3 tile/object, 5
  quality). Shrines are `$FE` records of tile `$DB` whose quality is their conversation
  (T191-T198); dungeons and caves `$FE` records of tile `$6E`/`$69`, named by the quality
  through overlay `$2C`'s list; the Codex, runes and balloon basket by object number; the
  Avatar and Lord British by their actors' start positions. **The towns are inferred**:
  the median of their residents' start positions (the game holds no town coordinates).
  1B's object files are `D<level><quadrant>`.
