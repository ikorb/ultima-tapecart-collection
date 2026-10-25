# Player's guide

Ultima I to VI for the Commodore 64 on one 2 MiB tapecart, and Akalabeth, the game
before them. Every game loads from the cart: no disks, no disk swapping, no waiting for a
drive. The games are the originals, with their disk access replaced and a few fixes and
options added. What is different in each game is listed in its own page:
[Akalabeth](changes/u0.md), [Ultima I](changes/u1.md), [II](changes/u2.md),
[III](changes/u3.md), [IV](changes/u4.md), [V](changes/u5.md), [VI](changes/u6.md).

The tapecart is a flash storage device for the C64's tape port (by Ingo Korb, idea by
enthusi). Ultima I-VI are (c) Origin Systems / Lord British. Akalabeth is (c) Richard
Garriott; its C64 conversion is by Andrea Schincaglia, Antonello Molella and David Vigh.

## Building the images

The repository holds no game data: the build reads your own disk images. Put them in
`disks/` (any names; `.d64`, `.g64`, zip archives) and run `make` -- see
[`disks/README.md`](../disks/README.md) for which disks are needed and how played disks
are handled.

| Command | What it makes |
|---|---|
| `make` | `build/ultima-collection.tcrt`, the full image, and `build/ultima-collection-update.bin`, the update image that keeps the saves; and `build/ultima6-ef.crt` (`make ef`) |
| `make cart` | the tapecart's two images alone |
| `make disks` | nothing: it reports what the build found in `disks/` and what is missing |
| `make import [PICK=<image>]` | `build/ultima-collection-imported.tcrt`: the full image with the saved games found on your disks already in it (below) |
| `make editor` | `build/ultima-save-editor.html`, the [save editor](editor.md) |
| `make ef` | `build/ultima6-ef.crt`, [Ultima VI alone on an EasyFlash](easyflash.md) |
| `make play` | starts the cart in VICE (`x64sc`) |
| `make play128` | Ultima V in C128 mode in VICE (`x128`, the C128 launcher on a disk) |
| `make play-ef` | starts the EasyFlash build in VICE |

### Bringing saved games from your disks

`make import` puts the saved games found on your disk images into a full image, using the
same code the launcher runs when you import from a disk on the C64. A disk counts when it
is the game's save disk and nothing on it but the saved game differs from the original.
When a game has saves on more than one image, nothing is imported for that game until you
choose one with `PICK="<the image's file name>"`. `build/ultima-collection.tcrt` stays the
plain image. The imported image is a full image: flashing it replaces every save on the
cart.

## Flashing the cart

Use the tapecart's own flash tool and one of the two images:

| Image | When | Flash it with |
|---|---|---|
| `ultima-collection.tcrt` (or `ultima-collection-imported.tcrt`) | a new cart, or when the cart asks for it (below) | **Write TCRT file to cart** |
| `ultima-collection-update.bin` | updating a cart that already holds the collection | **Advanced options**, **Write data file**, at **offset 0** |

- **Write TCRT erases the whole cart, saved games included.** Use it for a new cart.
- **Write data file at offset 0 keeps your saved games.** The update image covers the
  flash from the start to the end of the game data and stops below the save area, and
  that command erases only the blocks it writes. This is the normal way to update. The
  cart's loader is not touched by it; it always loads the same small first stage, which
  then loads the rest.
- **When a new build lays its saves out differently**, the cart says so at power-on:
  *"The saves on this cart are laid out for another build of the collection."* Nothing
  is started then, so nothing can misread your saves. Either flash the new build's full
  `.tcrt` (your saves are then gone), or first flash the build you had before again,
  **export** your saved games (below), then flash the new `.tcrt` and import them.

## Starting the cart

Power on with the cart in the tape port and load from tape: Shift+RUN/STOP, or type
`LOAD`. The screen goes black, and the game list appears.

## The game list

The list shows the games under the logo and the build's version: **0** Akalabeth, **1-6**
Ultima I-VI. Press a game's number; its page opens.

## A game's page

The page shows the game's name, the saved game if there is one (names, hit points, food
and so on, depending on the game), the game's options, and the commands:

| Key | |
|---|---|
| L | Launch the game. |
| J | Journey onward: straight into the saved game, past the titles and intro. Offered when there is a saved game, for every game but Ultima I (which asks which of its four characters to play). |
| F, P, U, M, A, W, V, S, H, X, G | The game's options, below. Each key turns one on or off, and the cart remembers it. |
| E | Export the saved game (only offered with a saved game). |
| I | Import a saved game. |
| R | Reset the saved game to a new one (asks first; cannot be undone). |
| C | Ultima V only: write the C128 launcher to a disk (see below). |
| T | Ultima VI only: transfer your Avatar from Ultima IV or V (offered while the Avatar is as character creation left it). |
| B | Back to the game list. |
| 0-6 | Open another game's page. |

Questions appear below the commands. A (Y/N) question takes only Y or N (RUN/STOP and
`<-` count as N), so a key that bounces cannot answer it by accident.

### The options

| Key | Option | Games |
|---|---|---|
| F | Food used while walking (off: walking costs no food; camping and monsters that eat food still do) | Akalabeth, I, II, III, IV, V |
| P | Turn passes when idle (off: no turn passes while you think) | I, II, III, IV |
| U | Torches used up when lit (off: igniting one keeps it) | II, III, IV, V |
| M | Magic and items used up (off: spells need no reagents or MP, keys don't break, gems aren't used up) | III, IV, V |
| A | Attacks can't be avoided (off: "AVOID?" is asked when a monster attacks). Akalabeth: Attacks can miss (off: you always hit, and always kill) | Akalabeth, III, IV |
| W | Balloon drifts with wind (off: you steer it) | IV |
| V | Counts wrap past 99/9999 (off: gold, experience and food stop at 9999, attributes, weapons, armour, spells and items at 99, instead of starting again at 0) | II |
| S | NPCs can steal items (off: the bard, the jester and the dungeons' thieves take nothing) | I |
| H | Monsters can hurt you (off: they do no damage) | Akalabeth |
| X | Ultima I: F1 shows the position, F7 teleports (a land and X, Y), B brings a horse, cart, raft, frigate or aircar. Ultima II: F1 shows the position, F7 teleports (X, Y), B brings a horse, frigate or plane. Ultima III: Ultima III Gold's trainer keys (B mounts, F7 teleports, X wins a fight, O AMBROSIA). Ultima IV: T teleports, B brings a transport, X wins a fight. Ultima V: F7 teleports, B brings a horse, carpet, ship or skiff. | I, II, III, IV, V |
| G | Ultima IV: Graphics, original or Remastered (Ultima IV Remastered's tiles and character creation pictures). Akalabeth: Gold spent when buying (off: the shops take no gold) | Akalabeth, IV |

All options are off (the game as it was) on a new cart. Ultima VI has no options. The
details of each option are on the game's own page in `changes/`.

Akalabeth's four are the trainer of the release the cart is built from (Genesis Project's,
"fixed and trained by Wertstahl"), which asks them as the game starts; on the cart they
are options instead, and the game starts without the questions.

Ultima III's trainer keys are Ultima III Gold's, which was cracked, trained and enhanced
by MagerValp (released at BFP 2007, music by Zabutom). Ultima IV's Remastered graphics are
from Ultima IV Remastered by Per Olofsson (MagerValp), its new graphics by Vanja Utne.

### Ultima VI and an REU

With a Commodore REU (or a compatible one) of 256 KB or more, Ultima VI uses it as a cache:
sectors it has read once come from the REU afterwards, and, if the REU's verify command
works, a save writes only what changed. Ultima VI's page says what it found, below the
saved game: `REU: 512 KB, for loads and saves`, `... for loads only` with "its verify
command failed" under it, or `REU: 128 KB, too small to use`. Without an REU there is no
line. Nothing has to be switched on; the game finds the REU by itself.

## Akalabeth

Akalabeth saves nothing: a game lasts until you switch off, as on the disk. Its page has
only its options, L and B. Its instructions (Y at "INSTRUCTIONS (Y/N)") are all there,
without the three pictures the disk shows before them: the cart has no room for them.

## Saving

Each game saves the way it always did: Ultima I and III with Q, Ultima IV and V with
Quit & save, Ultima II and VI as the game saves (Ultima VI also at every map-window edge
and level change). A save takes a second or two.

## After a power cut

**Switching off during a save loses nothing.** Ultima I, III, IV and V write each save
twice, first to a spare place (a journal), then over the old one; Ultima II and VI keep a
log. If the power goes in the middle, you get either the save before or the new one,
whole. When it went while the old save was being overwritten, the cart finishes the job
the next time it is switched on, before anything else starts; the list then appears a
moment later than usual.

The one exception: Ultima V played in C128 mode writes its saves in place, without the
journal. A journal the C64 version left is finished at the next C64 power-on.

Ultima VI's log fills up after about four saves; the cart then tidies it up, at the next
power-on or during a save, behind a progress bar or a spinning cursor. That can take from
about ten seconds to under a minute. Ultima II's log tidies itself up the same way, much
less often; that save takes a few seconds longer.

## Export and import

With **E** and **I** a saved game goes to a real disk and back. E and I first ask:

- **(D)isks**: the game's own disks, as the original game uses them -- copies of your
  original disks (Ultima II's Player disk, Ultima III's Scenario disk, Ultima IV's
  Britannia disk, and so on; the cart asks for each by name and checks the disk's name).
  An exported game plays in the original game too. Ultima VI's export writes the whole
  world, all 84 chunk files, and takes a few minutes to a stock 1541 (about 3 min 35 s,
  disk swaps excluded).
- **(F)ile**: one file on any disk, `ULTIMA I SAVE` ... `ULTIMA VI SAVE`. Small, and only
  this collection reads it (its format: [save-format.md](save-format.md)). Good as a
  backup before a full flash.

Any drive from 8 to 11 works, an SD2IEC or a 1541 Ultimate as well: at the "in drive 8"
prompt **D** steps to the next drive (8, 9, 10, 11, 8), and the cart remembers it.
RUN/STOP cancels. With no drive there, the page says "Drive 8 is not there".

An import reads and checks everything before it changes the cart, so a wrong disk, a bad
file or RUN/STOP leaves your saved game as it was. An export to a file overwrites the file
of that name on the disk; an export to the game's disks overwrites the saved game on them.

Ultima IV saved in a dungeon: the export says that the original game would start that
save on the surface.

## Reset

**R** on a page puts the game's save back to the cart's starting state, as after a fresh
flash: no saved game (Ultima VI: its world as shipped). It asks first, and cannot be
undone, so export first if you want to keep the game. The options and the drive number are
kept.

## Keys and joysticks

The games take the keys they always did, with a few changes:

- **Ultima III and Ultima IV** keep every key typed ahead (the originals kept only the
  last), and take a **joystick in port 2**: it walks, and fire enters, talks or attacks,
  depending on where the party is.
- **Ultima V** moves the party with the joystick, as the original does.
- **Ultima VI** moves and aims with the key block `+ - £` / `@ ↑` / `: ; =` (north-west,
  north, north-east; west, east; south-west, south, south-east), and Return confirms.
  A quick tap of a direction key or of Return counts even when the game is busy, and a
  second tap of the same key is not lost. The text boxes of the opening, the
  introduction and the ending take Space or fire.
- In the launcher, `<-` and RUN/STOP cancel.

## Ultima V on a Commodore 128

On a C128, Ultima V can run in C128 mode, with its music and its faster command overlays.
On Ultima V's page, press **C** and give it a disk: it writes a small program, `ULTIMA V
128`. Then, on the C128 with the cart in the tape port, after a reset, in C128 mode:

    DLOAD"ULTIMA V 128"
    RUN

(add `,U9` and so on for another drive; the page prints the exact line). The disk keeps
working after the cart is updated. The saved game is the same one the C64 plays. In C128
mode saves are written in place (see "After a power cut").

## Ultima V's music on a C64

With an Action Replay cartridge (4.2, 5 or 6) plugged in, Ultima V plays its music on a
C64 too, and loads faster. Start the Action Replay's fastload mode, then load the tapecart
as usual.

The collection's [Ultima VI EasyFlash](easyflash.md) does the same: with it in the
expansion port and the tapecart in the tape port, press **5** on the EasyFlash's page.
It starts the tapecart's Ultima V, with its saved game and the options set on its page
on the tapecart; both carts have to be from the same build.

## Ultima VI: transferring an Avatar

On Ultima VI's page, **T** lists the Avatars of your Ultima IV and Ultima V saves on the
cart. After you pick one and answer Y, Journey onward starts Ultima VI with the converted
strength, dexterity, intelligence, level, health, magic and experience; the name and sex
stay as created. T is offered while Ultima VI's Avatar is as character creation left it.

Ultima V's own "Transfer from Ultima IV" (in its character creation) reads your Ultima IV
save from the cart.

## The access light

The cart's LED lights while data moves and is dark otherwise. In Ultima VI a cell of the
screen frame, below the cursor at the bottom right, turns white whenever the cart is busy.

## Editing a saved game on a PC

The [save editor](editor.md) is one HTML page that runs in a web browser, offline. It
opens the file an export with **E**, **F** writes, the game's own disk with its save, or
the cartridge image an emulator plays, and writes it back in the same format, ready to
import with **I**.
