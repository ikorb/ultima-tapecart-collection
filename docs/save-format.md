# The launcher's save files

What the launcher page writes when a saved game is exported with **E**, **F**, and reads
back with **I**, **F** (see the [player's guide](guide.md)). The code is
`asm/page_file.s`; the host tests are `tests/test_file_xfer.py`. The format is the
collection's own: no other program on the C64 reads it. The [save editor](editor.md)
reads and writes it.

## The file

Each game has one sequential (SEQ) file, on any disk in drive 8-11. An export scratches
the old file of that name first.

| Game | File name |
|---|---|
| Ultima I | `ULTIMA I SAVE` |
| Ultima II | `ULTIMA II SAVE` |
| Ultima III | `ULTIMA III SAVE` |
| Ultima IV | `ULTIMA IV SAVE` |
| Ultima V | `ULTIMA V SAVE` |
| Ultima VI | `ULTIMA VI SAVE` |

Every 16-bit value in the file is low byte first.

```
header   "UCSV"      4 bytes, ASCII
         game        1 byte: the game's number, 1-6
         version     1 byte: 1
body     Ultima I-V: slots (below); Ultima VI: records (below)
check    s1, s2      2 bytes (below)
```

Nothing may follow the check bytes. An import refuses the file if any of these is wrong:

- the magic, the game or the version;
- the slot count, a slot's flag, or a length that does not fit its slot;
- the check bytes;
- the file is cut short, or has anything after the check bytes.

The page's messages for these are "That is not a saved game file.", "That file is another
game's.", "That file is from another version." and "The file is damaged."

The cart is changed only after the whole file has been read and checked (Ultima VI: its
records go into the unused half of the write log as they are read, and that half becomes
the active one only after the check, so a bad file leaves the log in use as it was).

### Check bytes

Both sums cover every byte from the `U` of `UCSV` up to the last byte of the body, each
kept mod 256:

```
s1 = s2 = 0
for each byte b:  s1 = (s1 + b) & 255;  s2 = (s2 + s1) & 255
```

The two check bytes themselves are not summed.

## Ultima I-V: slots

```
count                1 byte: the number of slots in the game's table
then per slot, in the table's order:
  flag               1 byte: 1 = data follows, 0 = the slot is empty
  length             2 bytes (0 for an empty slot)
  data               length bytes
```

An empty slot is `0, 0, 0`. It occurs when the cart's slot has never been written, for
example an Ultima I character that was never made. An import leaves that slot erased on
the cart.

A slot is one of the places where the original game keeps its saved game on its own
disks. The data is what the export to the game's disks would write there, and nothing
more. There are two kinds:

- **Sectors**: one or more whole 256-byte disk sectors, in the order listed below. The
  length is always the number of sectors x 256. Byte 0 of the data is byte 0 of the first
  sector; these sectors are read and written by track and sector, so they carry no link
  bytes of their own.
- **A file**: the contents of a program (PRG) file on the original disk, **without its
  two-byte load address**. That address is fixed for each slot and listed below. The file
  on disk is the load address, then the data.

### The slots, per game

**Ultima I**: the Ultima I disk, five files.

| # | Slot | Load address | Length |
|---|---|---|---|
| 1 | file `RO` | `$B000` | 64 |
| 2-5 | files `P0`, `P1`, `P2`, `P3` | `$81E2` | 458 each, or empty |

**Ultima II**: the Player disk, eleven files and one sector.

| # | Slot | Load address | Length |
|---|---|---|---|
| 1-5 | files `MOB 00`, `MOB 10`, `MOB 20`, `MOB 30`, `MOB 40` | `$3000` | 256 |
| 6-11 | files `MON 00`, `MON 03`, `MON 10`, `MON 20`, `MON 30`, `MON 40` | `$8F00` | 256 |
| 12 | the player record, track 35 sector 16 | -- | 256 |

On the cart these are units in Ultima II's save log. The file holds each unit's newest
version, or the original for a unit never written.

**Ultima III**: the Scenario disk, five sector runs. These are units of the game's own
catalog, not CBM files.

| # | Unit | Sectors | Length |
|---|---|---|---|
| 1 | SOSA | track 15, sectors 2-17 | 4096 |
| 2 | SOSM | track 15, sector 18 | 256 |
| 3 | ROST | track 16, sectors 12-16 | 1280 |
| 4 | PLRS | track 16, sector 17 | 256 |
| 5 | PRTY | track 16, sector 18 | 256 |

**Ultima IV**: the Britannia disk, five sectors: track 13 sectors 19 and 20, then track 14
sectors 0, 1 and 2 (the game's blocks 271-275), 256 bytes each.

**Ultima V**: six files, on two disks.

| # | Disk | File | Load address | Length |
|---|---|---|---|---|
| 1 | Britannia (2A) | `ROSTER` | `$1000` | 1024-1025 |
| 2 | Britannia (2A) | `PRTY.DATA` | `$BC00` | 48 |
| 3 | Britannia (2A) | `LIST` | `$4A00` | 512 |
| 4 | Britannia (2A) | `SLIST` | `$4A00` | 512 |
| 5 | Britannia (2A) | `TLIST` | `$4A00` | 256-512 |
| 6 | Underworld (2B) | `TLIST` | `$4A00` | 256-512 |

The two `TLIST` files are different files, one on each disk.

## Ultima VI: records

Ultima VI's saved game is the whole world: 84 chunk files and the save area. The cart
carries the original disks and keeps every change in a write log. The file holds only
what the log has. Anything not in the file is as on the original disks, and an import puts
the whole world back to that before adding the file's records.

```
1  name n pages      a chunk file: its 3-letter name (PETSCII, as in the directory),
                     n (1-20), then n x 256 bytes
2  sector data       a save-area sector: its number s (9-20), then 256 bytes
0                    the end
```

- **Chunk files** are `SAA`-`SHH` on Surface (1A) and `DAA`-`DED` on Dungeon (1B: five
  levels, A-E, of four quadrants, A-D). The names do not overlap, so the name says which
  disk a file belongs to.
  - The n pages are the file's disk sectors in chain order, as the game wrote them. Bytes
    0-1 of each page are the CBM chain link: the next track and sector, or in the last
    page 0 and the index of the last byte used. So the file's contents are bytes 2-255 of
    each page, and of the last page only up to that index.
  - The link values point where the game put the file on its own disk. The export to the
    game's disks ignores them: it writes each file through a fresh chain and a BAM of its
    own.
- **A save-area sector `s`** is Surface (1A) track 6, sector `s`, all 256 bytes. A file
  need not hold all of them: a sector the game has not rewritten is as on the original
  disk.
- **Order:** the export writes 1A's chunk files in directory order, then 1B's, then the
  sectors from 9 up. The import does not depend on the order. A chunk file name that is not
  one of the game's, an n of 0 or over 20, or a sector outside 9-20 makes the file damaged.

## Sizes

For a typical save: Ultima I 6 blocks, II 13, III 25, IV 6, V 13. Ultima VI depends on how
much of the world the game has rewritten: about 13 blocks (3105 bytes) for a save that
holds only the party, about 61 blocks after a longer session.
