# Ultima VI on EasyFlash

A side build: Ultima VI alone on a 1 MiB EasyFlash cartridge. It is not a replacement for
the tapecart collection, which holds all the games and is the main build; the EasyFlash
build carries the same Ultima VI -- every fix and speed change of the collection's
Ultima VI ([changes/u6.md](changes/u6.md)) -- with different storage and drivers.

## What it is

- **The game from the cartridge's ROM**: no disks, no disk swaps. The cartridge is
  memory-mapped, so reads are plain memory copies, much faster than the tapecart's
  serial reads: a conversation starts in well under a second, and a step on the map
  at a chunk boundary is quicker.
- **Saves in the cartridge's flash**, in a write log like the collection's: a power cut
  during a save leaves the save before or the new one. Pages a save would write
  unchanged are compared with what is there and skipped, so a save at a map-window edge
  is short (about 2.6 s for the whole window shift in VICE, where the tapecart takes about
  8.5 s).
- **The log is tidied up inside the game**, when a save finds it full: the spinner turns
  in the cursor's cell after the prompt `>`, for a few seconds (on an EasyFlash 3 about
  3 s of spinner).
- **The access light**: as on the tapecart, a cell of the screen frame below the cursor
  turns white while the cartridge is busy.
- **No REU use**: the collection's REU cache is not in this build; it does not need it.

## Building and flashing

    make ef

builds `build/ultima6-ef.crt` from your disk images (see the [player's guide](guide.md),
"Building the images"). `make play-ef` starts it in VICE (`x64sc -cartcrt ...
-easyflashcrtwrite`); VICE writes the flash back into the `.crt` only on a clean exit.

Flash the `.crt` with **EasyProg**. EasyProg also puts the cart's own flash driver (EAPI)
into it; the build relies only on EAPI's documented interface, so a cart with another
EAPI works the same.

**The saves survive a new build.** The write log lives in banks 48-63, which the `.crt`
does not contain, so flashing a new build with EasyProg leaves the saved game in place.
Export the game first anyway (below) if it matters to you.

**A cart that runs `.crt` files straight from its card** (no EasyProg) keeps the log in
the `.crt` file it writes back. A new build's file has no log, so carry the old one over
before using it:

    python3 -m ultima.ef.efcrt keep-log OLD.crt build/ultima6-ef.crt NEW.crt

where `OLD.crt` is the file the cart wrote back, and `NEW.crt` the one to put on the card.

## The launcher

Power on: a page in Ultima VI's own text-box font, "Ultima VI on EasyFlash", the saved
game (the party with hit points) or "No saved game", and:

| Key | |
|---|---|
| L | Launch the game: its title and menu. |
| J | Journey onward: straight into the saved game. Only with a saved game. |
| E | Export the saved game (only with one): to the game's own disks, a file, or the tapecart. |
| I | Import a saved game: from the game's own disks, a file, or the tapecart. |
| R | Reset the world: the saved game is erased, and the world is the game's own again (asks first). |
| 5 | Ultima V from the tapecart, with its music (below). Only in a build made with Ultima V's disks. |

Below the commands, an `EAPI:` line names the cart's EAPI by its version string, which is worth noting in
any report about a cart. "(not this flash)" after it, or "This cartridge's flash is not
one its EAPI knows: nothing can be saved", means the EAPI does not fit the cart's flash
chips.

On a cart that never held this game, the first launch is black for a second or two while
the log is made (two 64 KiB sector erases).

### Export and import

E and I are the tapecart launcher's own code, so everything in the guide's "Export and
import" holds: **(D)isks** -- copies of Ultima VI's Surface and Dungeon disks, in the
original game's format; **(F)ile** -- `ULTIMA VI SAVE` on any disk, the format in
[save-format.md](save-format.md); drives 8-11, D at the drive prompt for the next one;
RUN/STOP cancels; an import checks everything before it changes the cart. The drive
number is not kept across power-ons (keeping it would cost a 64 KiB erase).

**(T)apecart**: with both cartridges plugged in -- the EasyFlash in the expansion port, the
tapecart with the collection in the tape port -- **E T** copies this cart's world into the
collection's Ultima VI save, and **I T** copies the collection's back. Only what differs
from the original disks is copied, so it takes seconds rather than minutes (6-10 s in VICE
for a small world). Before anything is written, the launcher checks that a tapecart
answers ("The tapecart: none answers" otherwise), that it holds the collection with the
save layout this build knows, and, for an import, that it holds a saved game of Ultima VI.
A copy cut short leaves the receiving cart's world as it was.

### Ultima V from the tapecart (5)

With both cartridges plugged in, **5** starts the tapecart's Ultima V with its music and
faster loads, the music player and all fifteen songs coming from this cartridge -- what
an Action Replay gives Ultima V otherwise ([changes/u5.md](changes/u5.md)). The game, its
saved game and its options are the tapecart's: the cheats set on Ultima V's page there
apply, and the line "Cheats:" shows which while the game starts. The 5 is on the page
only when Ultima V's disks were there when this cartridge was built.

It starts nothing, and says why, when:

- no tapecart answers, or it holds a collection with another save layout;
- the tapecart's Ultima V is from another build than this cartridge ("Flash both carts
  from the same build");
- a save on the tapecart was cut short by a power cut: start the tapecart on its own once,
  and it finishes that save.

## Limits

- **Ultima VI only** on the cartridge itself; the whole collection does not fit 1 MiB.
  (Ultima V's 5 plays the tapecart's game.)
- **No Avatar transfer** from Ultima IV or V (the collection's page has it: those games'
  saves are not on this cart). Ultima VI has no options to set.
- **The screen may flicker while the flash is written** (window-edge saves, the log being
  tidied up): short dashes or lines across the screen, depending on the cart. This is
  cosmetic. The likely cause (inferred, not verified) is EAPI writing each byte in the
  cartridge's Ultimax mode, during which the video chip briefly sees cartridge ROM in
  place of part of the screen's bitmap; reads do not do this.
- **A write the flash refuses for good** (a worn or protected sector) makes the game retry
  forever, with the LED on and no message. In the launcher a failed write stops all further
  writing and says "A write to the cartridge failed: the saved game may be the old one".
- The music holds silent for a moment at the end of character creation, while the world
  reset erases the log (interrupts are off during the erases).

## Credits

EasyFlash and its flash drivers (EAPI) are by Thomas 'skoe' Giesel
(https://skoe.de/easyflash/); the build includes EAPI for the AM29F040 from
`external/eapi`, under its own license. Ultima VI is (c) Origin Systems / Lord British.
