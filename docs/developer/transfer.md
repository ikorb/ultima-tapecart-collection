# How the drivers read the cart

What every driver shares when it reads flash: the 1-bit and 2-bit reads, `TC_GUARD` (the
2-bit read with the screen on), `TC_NMI_HOLD`, and compression. The four `$00`/`$01`
rules and tclib's design are in the [overview](README.md).

## The two reads

tclib (`asm/tclib.s`) has two ways to receive a byte from the cart:

- **1 bit per handshake** (`tc_getbyte`): the C64 pulls the write line low, the cart puts
  a bit on sense, the C64 reads it. The protocol is clocked by the C64, so interrupts,
  badlines and sprites only stretch it. tclib reads the bit 8 cycles after the falling
  edge (low phase 5 cycles, high 19; 24 cycles a bit). The loop is rolled; A and X are
  clobbered, Y is kept. Both kinds of cart (an ARM Cortex-M0 at 48 MHz and the AVR at
  8 MHz) handle receives read down to 6 cycles after the edge without error, so the
  C64's loop is the limit, not the cart. `tc_sendbyte` is rolled too, at about 25
  cycles a bit; faster would need unrolling, about 70 bytes the drivers do not have.
- **2 bits per handshake** (the cart's `READ_FLASH_FAST`): a cycle-exact read of two bit
  pairs per byte. The timed body is `asm/tcfast.s`, shared by `tc_getbyte_fast` and
  `tc_getbyte_guard`. Every access to `$00`/`$01` there has to stay on the same cycle
  relative to the `STX $01` that raises the write line, as the tapecart's reference
  `getbyte_fast` has them; do not "optimise" it. The four port values in it are
  placeholders that `tc_init` patches (or, for code nothing patches, fixed by
  `TC_F_START`, `TC_F_DFAST`, `TC_F_DFEND`, `TC_F_END`). Its lookup table must stay on
  one page; the code pads in front of it when needed.

Measured on hardware: the 2-bit read about 8.5 KB/s. The 1-bit read measured about
2.8 KB/s with a receive of ~35 cycles a bit; the 24-cycle receive tclib has is faster,
but has not been timed on hardware.

Without the guard, the 2-bit read needs a quiet display: `tc_blank`/`tc_unblank` clear
DEN and wait a whole frame (the VIC samples DEN on raster line `$30`), keyed on raster
line `$F8`, and handle sprites. `TC_NO_FAST` leaves that path out.

## `TC_GUARD`: 2 bits with the screen on

The C64 starts every byte, and the cart's firmware waits for that start without a
timeout. So only 53 cycles per byte are timed -- from the start signal to the last port
write -- and the gaps between bytes may be anything, a decruncher's work included.

`tc_getbyte_guard` (`asm/tcguard.s`) reads `$D012` and `$D011` before each byte and waits
while this raster line or the next is a badline (`(raster - YSCROLL) & 7` is 0 or 7). The
timed part then ends at most 9 cycles into the line after next, before any badline's halt
at cycle 12. `$D011` is read every time, so a raster split that changes YSCROLL is
followed. Lines outside `$30-$F7` are treated alike: two in eight wait, about 25 cycles a
byte on average.

Sprite DMA it does not dodge: `tc_read` and `tc_stream_open` pick the 1-bit read whenever
`$D015` is non-zero (`tc_pick`).

Requirements:

- `tc_init` must have run.
- Interrupts off -- or, with `TC_IRQ_ON` (U4, for its music), each byte's check and
  timed part sit between a `PHP`/`SEI` and a `PLP` (`TC_F_PLP`, then only with
  `TC_NO_FAST`), so an interrupt waits a line at most. Every IRQ handler then has to keep
  `$01`'s bits 3-5.
- The code that runs with I/O banked in must not live under I/O. U4's tclib is in the RAM
  under I/O, so U4 sets `TC_GUARD_ELSEWHERE` and includes `tcguard.s` in its resident
  part. U3's `tcguard.s` is in its decoder segment (`$C6D9`), the driver's `$BC00-$BFFF`
  being full.

Who uses it:

- **U1, U2, U3**: their `U?_FAST` switch is 0, so every bulk load, raw or crunched, is one
  `tc_read` or stream, 2-bit unless a sprite is on, with no blanking (`TC_NO_FAST`).
- **U4**: everything, with `TC_IRQ_ON`.
- **U5**: only with an Action Replay (the receive lives in the AR's RAM; the C64 build
  has 64 bytes free in all) and in C128 mode (from bank 1). See [u5.md](u5.md).
- **U6**: not in play (interrupts are on during its loads, and sprites are on in the game
  view); its boot's compaction uses it.
- **The first stage** (`asm/boot.s`) loads the launcher with it.

U5's own fastloader (`u5siz.o` `$7892`) makes the same check against `$2F + YSCROLL`, and
turns sprites off for the load instead.

How it is checked:

- `tests/test_tc_guard.py` runs the routine in py65 against a model VIC that halts the CPU
  on badlines, starting from every cycle of the lines around the display's start and end
  and the raster's wrap, for PAL, NTSC and old NTSC and three YSCROLL values. The port
  accesses land on the reference routine's cycles, at least 2 cycles clear of any halt
  (3-4 on NTSC). With the check disabled, 119 of 2520 PAL bytes are hit; checking only
  the line before a badline fails too.
- In VICE, whose tapecart puts each bit pair on the line at fixed cycles (so a stalled
  read gets wrong bits): `tools/vice/u4_check.py --sweep` reads every chunk and record of
  every U4 disk byte-exact with the display on, and with `--noguard` (the check turned off
  in RAM) the first block is wrong from its second byte.
- `tools/vice/unit_check.py u1|u2|u3` sends every read-only unit of the game's own table
  through that driver's routine, with YSCROLL stepping through all eight values and
  sprites on for every fifth unit (see [emulation.md](emulation.md)).

What it buys, in VICE cycles, all read-only units with sprites off, against raw loads at
2 bits behind `tc_blank` and crunched ones at 1 bit: U1 27.3M -> 16.6M (1.64x), U2 37.2M
-> 26.7M (1.40x), U3 32.2M -> 21.3M (1.51x). The big code units gain about 1.6x (U2's
`ULTIMA` 4.54M -> 2.81M, U3's `ULT3` 5.43M -> 3.31M); U2's raw map pages 1.33x, since each
paid a frame of blanking.

## `TC_NMI_HOLD`

With `TC_NMI_HOLD` (which goes with `TC_GUARD`), `tc_enter` holds the NMI line the way
U4's own `u4_in` does (see [u4.md](u4.md)): through the RAM's vector at `$FFFA` -- the ROMs
are out -- which it puts back right after the one NMI is taken, before anything is loaded
(a load may land there). `tc_leave` switches the NMI off and acknowledges it. A RESTORE
pressed during a transfer is then lost instead of jumping through whatever that RAM holds.

- **U2 and U3 have it.** Neither touches CIA 2's timers or interrupt mask: a scan of their
  disks for absolute `$DD04-$DD0F` operands finds none.
- **U4** has its own hold.
- **U1 does not**: the ~70 bytes are not free before its entry table (5 are). A RESTORE
  during a U1 load does what it does in the original. (U1's disk has one `STA`/`LDA
  $DD0D`: its boot's `LDA #$7F`, which masks every CIA interrupt.)
- **U5 and U6** do not.

`tests/test_tc_guard.py` checks the sequence in py65: the vector put back at least 8
cycles after the timer starts, X, Y and the carry kept, and the NMI off and acknowledged
on leaving. `tools/vice/u4_nmi_check.py [--nohold]` checks U4's hold in VICE.

## Compression

**zx02 everywhere, per unit, stored raw where it would not shrink.** zx02 (`external/zx02`: Daniel
Serpell's (DMSC) MIT-licensed zx02, based on Einar Saukas's ZX0) matches exomizer's
ratio on this data and decodes about 1.6 times faster, with a table-free decoder of 117-144 bytes. The cruncher is
compiled from the submodule into `build/tools/zx02`; `ultima/flash/zx.py` drives it, and
`zx.decode` is a Python mirror of the 6502 decoder, which is how the host tests decode
flash.

A unit is stored raw when zx02 does not make it smaller (`zx.smaller`), and when it is
under 16 bytes, which the `zx02` tool cannot take (it crashes on one byte).

### The two decoders

One format (plain `zx02`, no `-b`/`-1`/`-e`/`-s`), two decoders, both pulling their input
from the cart through `tc_stream_byte`, so a unit decodes straight out of flash with no
staging buffer:

| Decoder | Size | Used by | Zero page |
|---|---|---|---|
| `asm/zx02s.s` | 117 bytes | U4, U5 | saves and restores four bytes: only with interrupts off |
| `asm/zx02a.s` | 144 bytes | U6; U1-U3 and the menu through `asm/zxdecr.s` | none: self-modified operands |

`zx02s.s` is a streaming variant of zx02's `6502/zx02-optim.asm`: its three input reads
become `jsr zx_getbyte`. `zx02a.s` is the same decoder with the two `(zp),y` pointers
replaced by self-modified absolute operands (`zx_put`, the one store; `zx_get`, the match
read).

`asm/zxdecr.s` gives `zx02a.s` the two entries the games' tables need:

- `zxd_unpack`: `tc_addr` = the stream, `tc_len` = its length, `tc_dest` = the
  destination (U1's and U2's tables have a length field);
- `zxd_unpack_sized`: the same, but the blob starts with its own 16-bit length
  (`zx.sized()`), since U3's catalog entry has a block *count*, and the menu's boot
  segments are shared with it.

Where the decoders sit: U1 `$C600-$C6EC` (the original fastloader's buffer), U3
`$C500-$C5EC`, U2 inside its driver.

### The cost

Compressed units stream at whatever rate the read gives, and decoding takes time of its
own: with a 1-bit stream, a crunched unit takes longer than the same unit raw at 2 bits
(U1's `TC`, 7.5 KiB, the biggest single overlay: 926k cycles raw, 1223k crunched). U2, U3
and U4 load at stock KERNAL speed in the original (~400 B/s), so crunched they are still
far faster; U1, U5 and U6 ship 2-bit fastloaders of their own, so for them compression
trades throughput for flash, while the seek, spin-up and disk-swap savings remain.
Hence the per-unit choice.

### The menu decodes too

`asm/menu.s` and the two standalone launchers (`asm/boot_u1.s`, `asm/boot_u3.s`) decode
segments: bit 0 of a descriptor segment's flags byte says the segment is crunched and
sized. U3's `EXOD` is 22 KiB of intro and a third of that game; without this it would have
to be stored raw, or twice.

### Where "crunched" is marked is per-game work

Getting it wrong is silent.

- U1's table has a dedicated flags byte.
- U2 uses bit 6 of its disk byte.
- U3 has **no** free bit in its length byte: `EXOD` is 87 blocks, and 87 already has
  bit 6 set. "Crunched" lives in bit 15 of the start-page field, which is spare because
  2 MiB is only 8192 pages. A flag in the length byte would truncate `EXOD` to 23 blocks.

The host tests decode every U1-U3 unit and segment in flash and compare them with the
disks; in VICE, `make run-menu` launches every game, `make run-u1test` (a 7.5 KiB crunched
load and the save round trips) and `make run-u3test` pass.
