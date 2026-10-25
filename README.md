# Ultima Tapecart Collection

This is a patch kit for the C64 versions of Ultima I-VI (and Akalabeth) that
bundles all of them on a single [tapecart](https://github.com/ikorb/tapecart),
applying additional performance improvements, bug fixes and cheat options on top.
It also builds an EasyFlash cartridge version of Ultima VI and includes a save
game editor and tools to generate maps and dump dialogue for the games.

This repository does not include code or data from the original game disks
except for very small snippets to validate patch locations and file names
from the original disks.

## AI Disclosure

This README is the only human-written file in the repositor. Everything
else has been AI-generated using Claude Opus 5.0/5.5.

Originally I planned to use Claude Opus only to reverse-engineer the games
and adapt them myself, but on a lark I asked Claude to do it just to see how
far it would get. It soon became my test project to see how far I could take
an AI assistant without writing a line of code myself, but occasionally helping
things along with hints and insights. The result is this repository - I did
not write a single line of code.

## Compatibility Warning

As far as I am aware, the Ultima64 and C64U boards at the time of release
do not have a fully C64-compatible tape port, so a tapecart will not work
on these clones. I have only tested this with a real C64 and C128 and only
on PAL machines.

## Features

The tapecart versions of the games have a number of bug fixes, enhancements
and performance improvements compared to the original. Some of them are
original to this project, others are ~~blatantly stolen~~ adopted from
other fan patches. All of them are of course updated to use the tapecart
for loading and saving, which tends to be quite a bit faster than the original
disk versions. The games generally save in a way that avoids corruption if
the save is interrupted mid-way.

The LED of the tapecart and/or EasyFlash cartridge is used as an access indicator,
so if a game seems to be unresponsive for a moment you can tell that it is
currently loading/saving data.

### Launcher

The individual game pages have a few features that are common to all games,
but as usual there is an exception to every rule and so there is always at least
one game where one of these points is missing.

- **Save game info:** If there is a saved game on the tapecart, the game's
    page in the launcher shows you information about the party or "No saved game"
    if there is none.
- **Cheats:** Depending on the game, various cheat options are available.
    Their current setting is stored on the tapecart, so you only need to set
    your preferred options once.
- **Journey Onward**: If there is a saved game, you can select to immediately
    launch into that saved game with this option, skipping parts or all of
    the intro sequence of the game.
- **Import/Export:** You can import and export the save of each game from/to
    original disks or a single per-game file. The single-file format is specific
    to this project, but the save game editor supports it. For the disk option,
    only the original disks can be used, Ultima III/IV Gold and Ultima IV
    Reloaded store their saved games in an incompatible format.
- **Reset save**: Wipes the saved game from the cartridge, including any world
    changes where applicable.

When the launcher prompts you to insert a disk, you can use the **D** key to
change the drive number, cycling from 8 to 11.

### Akalabeth

Unfortunately the crack intro and the three images in the instructions had to be
left out because there was not enough space left.

Akalabeth does not offer a way to save the game, so it has no options to
import/export/reset the save or journey directly.

#### Cheats

The trainer options of GP's release are integrated as options on the launcher page:

- **F**: Turn food consumption on/off
- **G**: Turn gold consumption when buying on/off
- **A**: When off, the player has perfect aim and will never miss.
- **H**: When off, monster attacks deal no damage.

### Ultima I

Ultima I does not have a direct "Journey Onward" option since you need to choose
which of the four character slots you want to use in the game.

#### Improvements

Surface traversal speed has been improved slightly by optimizing the drawing
routines. Originally the tile animation and idle passing (when enabled) were
done by counting the number of redraws, but have been modified to use real time
instead because the new drawing code only draws changed tiles. Using real time
avoids variable animation speed and erratic idle passes depending on the amount of
water on screen. The cursor animation is still linked to the render time, so you
can see how fast the game actually runs. Movement from key repeats is capped
at 5/second, but you can move faster by tapping a direction.

#### Cheats

There are four cheat options:

- **F**: Choose if you want to consume food while travelling through the world.
    Certain enemies can still take your food even if this is off.
- **P**: Choose if you want the game to automatically issue Pass commands when
    you are not inputting any action yourself for some time. Unlike the later Ultima
    games, Ultima I does not show "Pass" when this happens and it is only triggered
    after approximately 15 seconds without input, so it is a bit subtle.
- **S**: Choose if NPCs are allowed to steal items from the player. This applies
    to thieves in dungeons as well as Bards and Jesters in towns/castles.
- **X**: Movement-related cheats, inspired by Ultima III Gold's changes:
    - The **F1** key on the surface shows the current coordinates.
    - **F7** asks for coordinates and teleports the player there.
      The *land* part is *0* for the Lands of Lord British, *1* for the Feudal Lords,
      *2* for the Dark Unknown and *3* for Danger and Despair; the *X* and *Y*
      coordinates can be any value between 00 and 63.
    - Using the **B**oard command while standing on a tile without a vehicle
      offers you a choice of *(H)orse,(C)art,(R)aft,(F)rigate,(A)ircar*. Choosing
      one of them spawns a vehicle of that type where you stand and puts the player
      into it. You should make sure that you are on or adjacent to a tile that
      is valid for that type of transport unless you want to be stuck.

### Ultima II

There are two releases of Ultima II for the C64, the original Sierra one and the
later Origin version. The exact differences have not been investigated, but they
are significant enough that the tapecart collection can only be built from the
Origin version.

#### Save Game Notes

Ultima II does not change its world data in an irreversible way, but touches
many small files during gameplay. To support this without reserving a lot of
unused flash memory for the save area of the game, the AI decided to implement
an append-only system with two reserved blocks. For you as a player this means
that approximately every twenty saves or town exits the process will take a
few seconds longer than usual. During this time the game copies the latest
versions of the saved files from the current block to the other one and switches
over to it. If anything interrupts this process, e.g. a power failure, the
game will read from the old block the next time it starts and your save should
still be intact.

#### Bug Fixes

The game has received one permanent and one optional bug fix. The permanent
one is locking the CBM+Shift key combination which would temporarily garble
the screen in the original. The optional fix is the V cheat documented below.

#### Improvements

Improving the performance of Ultima II was very simple: The original version needs
about 220ms per step, 128ms of which are just a busy loop for the click sound.
It has been moved into an interrupt instead and walking through the world of the
game now feels really snappy.

#### Cheats

There are five cheat options available for Ultima II:

- **F**: Choose if you want to consume food while travelling through the world.
- **P**: Choose if you want the game to automatically issue Pass commands when
    you are not inputting any action yourself for some time.
- **U**: Infinite torches, as long as you have at least one by not consuming
    them when igniting one.
- **V**: In the original version, increasing a value like a character attribute,
    an item count or gold would wrap it around to 0. Some people see this as an
    intentional feature to stop the player from being too greedy, others consider
    it a bug. If you are in the second group, you can use this cheat option to
    make values stop at their maximum instead of wrapping around.
- **X**: Movement-related cheats, inspired by Ultima III Gold's changes:
    - The **F1** key on the surface shows the current coordinates.
    - **F7** asks for coordinates and teleports the player there. It can only
      teleport you within the current map, not between maps. The *X* and *Y*
      coordinates can be any value between 00 and 63.
    - Using the **B**oard command while standing on a tile without a vehicle
      offers you a choice of *(H)orse, (F)rigate, (P)lane*. Choosing one of them
      spawns a vehicle of that type where you stand and puts the player
      into it. You should make sure that you are on or adjacent to a tile that
      is valid for that type of transport unless you want to be stuck.
      This bypasses the usual requirements for boarding, you may not be able to
      re-board the vehicle after exiting it.

### Ultima III

Ultima III is one of the two problematic games that update the world on their
disks during play, which is why the original manual pointed the player to the
integrated disk copier so they still had the original state available on the
original disks. In the tapecart version, you can just use the Reset option in
the launcher to restore the world to a pristine state if you want to start over
completely.

#### Bug Fixes and Improvements

The tapecart version adopts a number of fixes and improvements from Ultima III Gold:

- Tile plotting speed is improved
- Redundant map saves are removed
- The map is cached in RAM when entering towns
- No automatic save when the party dies
- Buy more than one dagger at a time
- Select a default character for actions by pressing **1**-**4** or **0** to revert
    to the default "ask every time" behaviour
- Ask before exiting back to the main map
- Delete key works when entering the player name
- The map when peering into a gem is now in color (inspired by Ultima IV Remastered)
- Typeahead keys are buffered instead of discarded (inspired by Ultima IV Remastered)
- Joystick support (Port 2) for movement, the fire button is context dependent
    and works as **E**nter on the surface, **T**ransact in towns and **A**ttack
    in combat (inspired by Ultima IV Remastered)

In addition to that, the tapecart version also optimizes the step sounds similar
to Ultima II and removes a redundant party panel redraw, increasing the
responsiveness of the game even further.

The launcher option to directly Journey Onward is probably least effective in
Ultima III, the game still shows its title sequence and main menu. They are
aborted immediately with no user interaction though, so it's still more convenient
than going through the regular launch by hand.

#### Cheats

- **F**: Choose if you want to consume food while travelling through the world.
- **P**: Choose if you want the game to automatically issue Pass commands when
    you are not inputting any action yourself for some time.
- **U**: Infinite torches, as long as you have at least one by not consuming
    them when igniting one.
- **M**: Ultima III Gold's "unlimited magic/keys/gems" trainers: Everyone can
    cast all kinds of magic and don't need MP for it, doors can be unlocked
    without a key, peering works without gems and negating time doesn't require
    powder.
- **A**: Make combat optional by asking "AVOID?" when attacked, inspired by
    Ultima IV Remastered's cheat.
- **X**: Ultima III Gold's in-game trainer keys:
    - **F7** asks for X/Y coordinates and teleports the player there. It works
      on the surface only and the coordinates must be between 0 and 63.
    - Using the **B**oard command while standing on a tile without a vehicle
      asks "Board-" and accepts either **S** for a ship or **H** for a horse.
      It then spawns the chosen type and puts the party in it. You should make
      sure that you are on or adjacent to a tile that is valid for that type of
      transport unless you want to be stuck.
    - **X** in combat immediately ends it with a party victory and a loot chest.
    - The **O**ther key with the "AMBROSIA" command moves the party between
      Sosaria and Ambrosia. Unlike Ultima III Gold, this will not litter your
      map with unwanted water tiles.

### Ultima IV

MagerValp's [Ultima IV Remastered](https://github.com/MagerValp/u4remastered)
is already an extremely impressive project and Sean Gugler's
[fork](https://github.com/sean-gugler/u4remastered) improves upon it even further,
so there was no way I could leave their changes out.

#### Bug Fixes and Improvements

Many fixes and improvements were taken from Ultima IV Remastered:

- Improved graphics:
    - New graphics by Vanja 'Mermaid' Utne for the character creation intro
    - More colorful tiles
    - Maps from peering or a spell are in color
    - Items and monsters are drawn in color
- Faster dungeon renderer
- Text improvements:
    - Mixed case dialogue and game text
    - Many dialogue bugs have been fixed
- New Game Features:
    - Select an active character in combat with **1**-**8** or use **0** to return
      to party mode
    - Quit and Save in dungeons
    - Confirmation question before leaving a settlement back to Britannia
    - Joystick control (port 2)
    - typeahead for more than just one key
    - Dungeons get darker when a torch is close to burning out
- Bug fixes:
    - Different hints at shrines for 1/2/3 meditation cycles
    - Hythloth dungeon rooms on level 6 are now accessible
    - No more random hangs in character creation
    - Balloon flying state restored when loading
    - Delete key works for more input prompts
    - Can't enter a location from a flying balloon
    - various stack fixes that avoid crashes in long play sessions or specific situations
    - multiple fixes in rooms of Destard and Hythloth
    - castle music plays after Lord British resurrects the party
    - no more boarding a frigate with B while on a dungeon ladder
    - forbid entering a town while floating in a balloon (but do allow it when landed)
    - show the proper foe when attacking a non-monster
    - some typo fixes
- Music is not interrupted during loads
- Some cheats are adapted from IV Remastered, see the section below

The tapecart collection allows you to choose between original and remastered
graphics using the **G** key in the launcher. Like cheats, your choice is
saved to flash and it's no problem if you resume a save that was made while
the opposite option was active.

If you have saved within a dungeon, the tapecart's export option will warn
you that the original game does not support this. If you load it there, the
party will appear on the surface at the wrong coordinates.

Additional fixes and improvements were taken from Sean Gugler's fork of
Ultima IV Remastered:

- more stack fixes that avoid crashes in long play sessions
- incorrect state when staying at an inn with an asleep character
- healer in Serpent's Hold can now talk
- completing the skull quest increases the virtues instead of random bytes in memory
- last piece of gold raises sacrifice, as per the shrine's advice
- getting healed as a shop uses the spellcasting visual effect
- reagent cooldown timer should not reset when finding non-reagent items
- ladders in the dungeon Wrong are now symmetric between levels
- dialogue fix for Katrina
- four dialogues flagged as humility tests
- cooldown timer for Hawkwind's reward matches shrine cooldown timer
- non-monster combat strength fixed
- bridge trolls cannot attack a balloon
- attacking townsfolk immediately updates the Ankh
- chests from defeated townsfolk cannot be talked to
- east-facing horses do not flicker in combat
- teleport only wipes monsters from map, preserving chests and transports
- a wall is removed from room 11 in dungeon Covetous (discovered independently
  because one of my original disks had that fix already baked in)
- dismounting a horse in some towns could cause a random NPC to vanish
- Ztats display of key is fixed if the player doesn't have the candle
- dungeons are drawn in full white while the torch is fresh enough

Some additional changes by Sean could unfortunately not be applied to the
tapecart version (e.g. the "talk to chest dropped by townspeople" fix) due
to lack of free memory.

And on top of that, the tapecart collection has a few additional fixes and improvements:

- ladders between levels 6/7 of the dungeon Covetous are now symmetrical (inspired
    by Sean's Ultima IV Remastered fork)
- Journey Onward at the title screen with no saved game just returns to the title
    after showing the "No active game" message instead of softlocking
- Further optimizations to scrolling, drawing and line-of-sight calculation that
    speed up surface/settlement steps by about 20%

#### Cheats

- **F**: Choose if you want to consume food while travelling through the world.
    Certain enemies can still take your food even if this is off.
- **P**: Choose if you want the game to automatically issue Pass commands when
    you are not inputting any action yourself for some time.
- **U**: Infinite torches, as long as you have at least one by not consuming
    them when igniting one.
- **M**: Ultima IV Remastered's "unlimited magic/keys/gems" trainers: Magic without
    mixtures or MP, doors can be unlocked without a key, peering works without gems.
- **A**: Ultima IV Remastered's "avoid combat" trainer: Make combat optional by
    asking "AVOID?" when attacked.
- **W**: Ultima IV Remastered's "control balloon" trainer: The balloon can be
    controlled with the direction keys instead of floating based on wind direction.
- **X**: Ultima IV Remastered's in-game trainer keys:
    - **T** in Britannia can teleport you to a **T**own, **D**ungeon, **S**hrine,
      special **L**ocation or **C**oordinates. For the first four options, you
      choose your destinations with **1**-**8** and for the coordinate option,
      you enter them as four letters **A**-**P** just like the sextant shows them.
    - Using the **B**oard command while standing on a tile without a vehicle
      asks "Board WHAT?" and accepts **S** for a ship, **H** for a horse or
      **B** for a balloon. Unlike other variants of this cheat, the game will
      refuse to spawn a ship unless you are adjacent to a seawater tile.
    - **X** in combat immediately ends it with a party victory and a loot chest.

There is also a cheat key available from the original game: **Shift+Home**
prints the current standing for all eight virtues in hexadecimal.

### Ultima V

Although there is already an [Ultima V Remastered](https://github.com/Drunella/u5remastered)
out there by Drunella, no fixes or enhancements from it were adapted into
the tapecart collection. The repository did however provide some valuable
information that was used for the save game editor and map renderer.

#### Variants

The original version of Ultima V can run on the C128 in its native mode by
booting from the first disk and uses the extra memory to play music in-game
as well as for caching data to reduce load times. This variant of the game
can also be played from the tapecart, but unfortunately a tapecart cannot
boot directly on a C128. You need to load the collection from the tapecart
in C64 mode, use the **C** option on the game's page to write a small C128-mode
launcher to disk and then load that in C128 mode with `RUN"ULTIMA V 128"`.
Like the original game, this launcher supports direct journeying by holding
down the **J** key. If cheats are enabled in the C64 launcher, they will be
active in the C128 game launched this way too. The C128 version is still the
fastest because it still utilizes the machine's extra RAM as cache and the
tapecart transfers are about 25-35% faster than the C64 baseline according to
AI measurements.

On a regular C64 with just the tapecart, no music is available and due to
limited available RAM, the game loads slightly slower. There are two ways
around this:

1. Use an Action Replay 4.2/5/6. These cartridges contain 8KB of extra RAM that
    the tapecart version of Ultima V can utilize for the music player and faster
    transfer routines, speeding up loads by about 20% (the decruncher limits
    the possible speed gains).
2. Use the EasyFlash version of Ultima VI and use the **5** key to launch the
    tapecart version of Ultima V from it. The music player and faster transfer
    routines are read from spare space of the EasyFlash cartridge, everything
    else is loaded from the tapecart. Like the C128 launcher, your selection
    of active cheats carries over and you can hold the **J** key to directly
    journey into the main game.

(Protip: Don't build four variants of one game, it really blows up the testing matrix)

#### Bug Fixes and Improvements

The original version of Ultima V could in very rare cases misdetect a C64 as
C128 and crash. This is fixed in the tapecart version.

The renderer and NPC path finding have been optimized to improve world traversal
speed by about 30% (based on AI measurements).

#### Cheats

- **F**: Choose if you want to consume food while travelling through the world.
    Certain enemies can still take your food even if this is off.
- **U**: Infinite torches, as long as you have at least one by not consuming
    them when igniting one.
- **M**: Cast spells without mixing them or consuming MP, although the level
    check is still active; locks can be jimmied without ever breaking a key, but
    you still need to have at least one; viewing does not use up gems, but you
    still need to have at least one. (inspired by Ultima IV Remastered's trainers)
- **X**: In-game movement cheat keys, inspired by Ultima IV Remastered:
    - **F7** teleports the party in either Britannia or the underworld. It asks
      for the X and Y coordinates, which have a range from 0 to 255 in this game.
    - Using the **B**oard command while standing on a tile with no transport asks
      *H)orse C)arpet S)hip sK)iff?* and spawns the chosen type with your party in
      it at your current location. You should make sure that you are next to a
      suitable tile for your chosen type of transport, otherwise your vehicle will
      be stuck.

There is also a cheat key already available in the original game: **CBM+1**
prints a hex string that shows your current karma, location and something else
I don't remember.

#### Known Bugs and Limitations

Unlike all the other games, the C128 save code is not fully crash-proof. If
a save is interrupted mid-way, it may result in a blanked or corrupted save
on the tapecart.

Rarely after launching into the actual game, the top line is partially shifted
and has incorrect colors. Restarting the game should fix it. If you can find a
reliable way to reproduce it, that would be very helpful in finding a permanent fix.

### Ultima VI

Ultima VI is the black sheep among the C64 versions of the series. On the one
hand it's the only 8-bit port the game has ever received, on the other hand
it is feature-reduced compared to the PC version, requires constant disk swapping,
plays very slowly due to constant disk access and has some easily noticeable bugs.
This collection does not address the feature reductions, but playability is
significantly improved, especially in the EasyFlash version - but you may still
prefer to play the PC version instead.

#### Save Game Notes

Since Ultima VI rewrites its world during gameplay, it needs to save a lot more
often and with finer granularity than the other Ultima titles on the C64.
The tapecart version therefore uses a log-structured, two-block save system
with "merely" 256 KBytes of tapecart memory dedicated to Ultima VI saves to
handle this. The downside is that occasionally one of the two save blocks is
full and needs to be garbage collected. If it is close to the limit, the launcher
will do this before starting the game while showing "Tidying the world of Ultima VI".
If it happens within the game, you will see a spinner in the text area - the
process can take up to 50 seconds in the worst case. Unfortunately this can happen
even while just walking across the world because the game loads new map data
whenever the player crosses a 128-tile boundary and needs to save changes to
the previous area.

Unlike the original game, the tapecart version fully resets the world when
you create a new character or if you use the **R**eset option in the launcher.

#### Bug Fixes and Improvements

Ultima VI has a few quirks or bugs in the original version that have been fixed
in the tapecart collection:

- The text boxes in the intro and ending do not flicker on PAL machines anymore.
- The (undocumented) **Shift+L** load command now accepts Y for yes and N for no,
    in the original game they were swapped.
- The level check of the shrines was using an incomplete method to compare
    values, so levelling up there came too late or too early. The shrines now
    check the same values and the boundaries for gaining a level match the PC
    version.
- *R*esting now allows you to select the last character in the party as a guard.
- *R*esting with a guard did not actually wake up the characters when the guard
    detected anything nearby, instead you were in control of the camp fire until
    the planned resting time was over. The tapecart version now wakes up everyone
    and puts you back into control of the main character.

There are also additional improvements:

- The three characters with copy protection questions now accept almost any
    non-empty answer.
- The input code has been improved in multiple ways:
  - Short taps of a direction key, return or the joystick are buffered instead of lost
  - The over-eager key debounce of the original was softened, reducing lost keys
    further.
  - Space advances the text boxes in the introduction (the one selectable in the
    main menu, not the one before it)
- (deserves a repeated mention here) Journey Onward in the launcher skips the
    entire before-menu intro and the menu itself, so resuming the game is a lot
    less tedious.
- One of the cells in the bottom row of the frame below the text area serves
    as a "drive access light" so you can better tell that the game is busy.
- Various code optimizations improve traversal speed, especially the every-eighth-step
    pause when the game reads new map data as well as the pause after action
    commands.
- A 256 KByte REU (e.g. Commodore 1764) or larger can be used to improve the game's
    speed further. It will be used to cache the various overlays of the game
    and to reduce the amount of data the game needs to save by holding a copy
    of the current state, which not only reduces the time needed to save but
    also makes the garbage collection process occur less frequently. The first
    time something is saved after launching the game still writes out everything
    though, so the effect will accumulate over a longer game session.
- Creating a new character from the game's menu resets the world to its original
    state.

#### EasyFlash Version

Mostly out of curiosity I also had the AI build an EasyFlash version of Ultima
VI with the same features and enhancements of the tapecart one, except for REU
support. This improves the perceived performance of the game even further and
cuts down on the save garbage collection time to about three seconds on an
EasyFlash 3. Unfortunately saving to the cartridge requires enabling its ROM in
a way that influences what data the video chip can see, so you may see
a bit of garbage on screen whenever the game needs to save something - the exact
effect depends on the cartridge, for example with a 1541UltimateII+ there are
horizontal stripes flickering across the screen.

The EasyFlash version can export and import its save not just to original disks
and a single file but also to Ultima VI on an attached tapecart. It will check
that the tapecart contains a compatible version of the Ultima Collection to
avoid clobbering data from unrelated software.

#### Cheats

No cheats have been added to the game, but it already comes with some in the
original version:

**Run/Stop + F7** asks for coordinates and teleports the player there. The
map coordinates appear to be compatible with the ones from the PC version,
but they need to be entered as hexadecimal numbers. [This](https://zelphuria.com/u6map)
seems to be a very nice online map viewer for the PC version, but it only
shows the coordinates in decimal.

Talking to yourself and saying "I", "Want", "Cheat" opens the built-in cheat
menu. From there you can get arbitrary items ([list](https://www.wiki.ultimacodex.com/wiki/Ultima_VI_Get_Items_list#The_C64_Version_Ultima_VI_Get_Items_List)),
set flags, edit the party and player and modify the known spells.

#### Gameplay Notes

If you get a "Not possible" message when using the Orb of the Moons, the object
pool is full and the game is unable to spawn a moon gate. The easiest workaround
is to save and reload the game. This might indicate a leak in the original game,
but has not been investigated yet.

### Save Game Editor

The save game editor is a self-contained HTML page that you can open in your
browser to edit the saves from all six included Ultima games. You first need
to open or drop a file containing a save - this can be a .tcrt image, an
image of a game disk or an exported single-file save from the tapecart collection.
Changes are kept in memory until you use the "Download" button to download the
modified file in the same format you previously opened. Each change is reported
in the "Changes" tab and can be reverted individually there. For advanced users
there is also a tab with the data in hex form with the option to edit it.

### Map Generators

A set of scripts can generate graphical maps for all six Ultima games.
Hopefully self-explanatory. The generated maps in `build/maps` show the world
in the state presented by the cartridge versions, so the dungeon fixes
in Ultima IV are included.

### Dialogue Extractors

A set of scripts can extract the dialogue from all six Ultima games to
text files in `build/dialogue`. Hopefully self-explanatory, added because
it was useful for me during testing.

## Building

To build the cartridge images and extras, you will need a suitable build
environment as well as a total of 25 disk images for the games.

### Build Environment

The project can be built on a reasonably up-to-date Linux or macOS system.
Besides the usual host C development tools you will need:
- [acme](https://sourceforge.net/projects/acme-crossass/)
- [cc65](https://github.com/cc65/cc65)
- [py65](https://github.com/mnaberez/py65), which as a python module can just be
    installed locally:

    python3 -m venv .venv
    source .venv/bin/activate
    pip install py65

For the save editor, you will also need:
- [node](https://nodejs.org/) 22.18+
- the [TypeScript](https://www.typescriptlang.org/) compiler `tsc`
- [bun](https://bun.com/)

Running the unit tests additionally requires the [VICE](https://vice-emu.sourceforge.io/)
emulator version 3.11 or a nightly build of r46292 or later.

### Required Disk Images

Building the cartridge images requires quite a large number of disk images.
It is preferable if they are pristine, but the patch kit tries to undo changes
made by playing the game where possible and can sometimes accept alternate
versions. For Ultima III and VI however the games rewrite their world files
during gameplay. The build process tries to revert this and checks if the
result is identical to a pristine world. This is highly likely to succeed for
Ultima III, but for Ultima VI only the character generation can be reverted - as
soon as you loot something in Lord British's castle or open the door at the
drawbridge, the world is permanently modified and the disk will be rejected.

The images go into the `disks` subdirectory, in either D64 or G64 format,
optionally zipped. Names do not matter, the required data is located using
content hashes. Cracked version of Ultima I-VI may or may not work.
If you put multiple variants of the same disk in the directory,
the script will check all of them and pick up the pieces it needs.

| Game | Disk count | Notes |
|---|---|---|
| Akalabeth | 1 | A single disk containing Genesis Project's release of the port by Andrea Schincaglia, Antonello Molella and David Vigh |
| Ultima I | 1 | The original disk has a copy protection on track 6, but a plain D64 is sufficient. |
| Ultima II | 2 | Must be the later Origin release, not the original Sierra version. My originals were labeled "Program + Galactic" and "Player Master". |
| Ultima III | 2 | "Program" and "Player Master" - the latter must contain a pristine world file. |
| Ultima III Gold | 1 | MagerValp's improved version fits on one disk, some of his improvements are incorporated in the tapecart version. |
| Ultima IV | 4 | "Program", "Towne", "Britannia" and "Underworld" |
| Ultima V | 8 | "Program", "Dungeon", "Britannia", "Underworld", "Towne", "Dwelling", "Castle", "Keep" |
| Ultima VI | 6 | "Surface", "Dungeon", "Populace A/B/C", "Game" - the Surface and Dungeon disks must have unmodified world files |

You can check if your current set of disk images is sufficient for building
the cartridge by running `make disks` in the root directory of the repository.

If your disk images contain saved games, you can optionally build a special
cartridge image with them imported already with `make import`.
For Ultima VI this may require both an image with a saved game as well as a pristine one.

If you want to read the AI version of this section instead which may include
additional details, see [disks/README.md](disks/README.md).

### Building

When `make disks` reports that all games are complete ("7 of 7 games complete"),
you can build both the tapecart and EasyFlash cartridge images by running
`make`. You can optionally build the save editor with `make editor`,
maps with `make maps` and dialogue dumps with `make dialogue`. Or just build
everything in one go with `make all`. The files are built in the `build` subdirectory,
specifically:

| File | Description |
|---|---|
| `ultima-collection.tcrt` | the full tapecart image with all games |
| `ultima-collection-update.bin` | a data-only file for updating, see below |
| `ultima6-ef.crt` | an EasyFlash version of Ultima VI only, with a bit of Ultima V companion features |
| `ultima-save-editor.html` | the save game editor as a single HTML file |
| `maps` | multiple subdirectories with maps for all games |
| `dialogue` | multiple subdirectories with dialogue dumps for all games |

### Updating

If there are future releases of this project, we'll try to do it in a way that
allows you to keep your saved games on your cartridge, but you will need to
be a bit careful when updating a tapecart with the flashtool. You have two options:

1. Export all saves to original disks or files, flash `ultima-collection.tcrt`, import them again
2. Use the advanced options in the tapecart flashtool to write `ultima-collection-update.bin` as a data file at address $000000.

If you just flash the new `ultima-collection.tcrt` file,
it will wipe your saved games because the flashtool always erases the entire
memory on the tapecart.

For the EasyFlash version you can just write the `ultima6-ef.crt` file with EasyProg,
it will preserve your saved game. If you use a device that loads the `ultima6-ef.crt`
file directly from a memory device (e.g. 1541Ultimate), you will need to use
the export/import route to move your saved game to the new `ultima6-ef.crt` file.

## More Documentation

The AI has written a lot of notes in the usual distinct Claudish style which
includes more details than this file. Some of it may even be true.
If you want to read it, [README.ai.md](README.ai.md) is a good starting point.

## Credits

This project builds on the shoulders of giants, specifically and in no
particular order:

- Akalabeth is copyrighted by Richard Garriott
    - The C64 conversion is by Andrea Schincaglia, Antonello Molella and David Vigh.
    - The included version of it is the compiled and trained release by Genesis Project.
- Ultima I-VI are copyrighted by Origin Systems
- Ultima III Gold is a fan-made improved version by MagerValp, this project
    incorporates some of its changes and was inspired by it to add vehicle,
    teleport and torch consumption cheats to most of the games.
- [Ultima IV Remastered](https://github.com/MagerValp/u4remastered)
    is © 2006-2015 Per Olofsson, the new graphics are © 2015 Vanja Utne;
    this project incorporates some of its changes and the new graphics.
- Sean Gugler's Ultima IV Remastered [fork](https://github.com/sean-gugler/u4remastered)
    was a valuable source for additional bug fixes for Ultima IV.
- [Ultima V Remastered](https://github.com/Drunella/u5remastered) is © 2025 Drunella.
    While no code or data were incorporated from it into this collection, the
    save editor and map renderer are based on information from it.
- zx02 by Daniel Serpell is used for compressing data on the cartridge
- C64UltimaEditor by Christopher J Mallery served as a valuable source for details
    of the save format and unit test data for the save editor

## License

Since this patch kit is basically 100% AI-generated, it is released into the
public domain under [CC0 1.0](LICENSE). Some parts were derived from other
projects under different licenses though:

- The tapecart transfer code is derived from the original reference loader,
    licensed under [BSD 2-clause](LICENSES/BSD-2-Clause-tapecart.txt).
- The modified zx02 decompressor is under the [MIT license](LICENSES/MIT-zx02.txt),
    original version Copyright (c) 2020 Daniel Serpell
- The EasyFlash build includes a version of Thomas 'skoe' Giesel's EAPI for the
    AM29F040 licensed under the [zlib license](external/eapi/LICENSE.md).
- This repository contains a Python port of the Exomizer decruncher, the original
    code is by Magnus Lind under the [zlib license](LICENSES/Zlib-exomizer.txt).
- Some of the Ultima IV changes are derived from Ultima IV Remastered and use the
    [Apache 2.0](LICENSES/Apache-2.0.txt) license.
- Drunella's Ultima V Remastered is available under the
  [Apache 2.0](LICENSES/Apache-2.0.txt) license, this project has used some
  information from it for the save editor and map renderer, but no code or data
  are incorporated here.
