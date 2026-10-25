"""Fixes from Ultima IV Remastered (MagerValp, v2.2.1), applied to the disk
images before the flash is laid out.

The kit is the external/u4remastered submodule (Per Olofsson, Apache 2.0:
NOTICE.md), read-only; what the tapecart build can take from it is in
docs/reversing-notes/u4-remastered.md.  Taken:

- the bug fixes, attacking static NPCs included (u4a0.s);
- the conversation and map data fixes;
- the faster dungeon renderer (chunk $95, the kit's dungeon.s assembled
  with its colour tables on the original's single table at $E1B0);
- mixed-case dialogue (MIXED_CASE): the conversations, the talk code's own
  lines, the shopkeepers and Lord British, in the kit's case.  The game's
  own messages stay as they were;
- the colour peer (chunk $77), "EXIT?" at a town's
  edge, and the keyboard queue fix with the joystick (u4key.s).

And the bugs Sean Gugler's continuation of the kit (2.3.0-2.4.1) found and
fixed, written here as patches of the original (fork_fixes, MAP_FIXES,
HUMILITY, the torch in dungeon()); that repository is not used.

Every patch names its chunk, runtime address, the original bytes and the new
ones, and goes on every disk that carries that chunk: our layout stores each
page once by content, so a patch on one copy only would leave the other
disks' original.  The original bytes are checked everywhere.

Disk numbers are the game's, as in build.py: 1 = A (Program), 2 = C
(Britannia), 3 = B (Towne), 4 = D (Underworld).
"""
import difflib
import json
import os
import re
import subprocess
import zlib
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
from ultima import paths
from ultima.pin import Pin
KIT = os.path.join(paths.EXTERNAL, "u4remastered")

BUILD = paths.BUILD
A, C, B, D = 1, 2, 3, 4

# ---- code fixes: (what, chunk, runtime address, original, new, disks) ----
# From the kit's binpatches and runtime patch list (src/gamemain/
# patchmain.s), each checked against a disassembly of the original
# (docs/reversing-notes/u4-remastered.md).  Helper addresses (fx_*) come from u4fix.s.
def t(s):
    """The game's text: ASCII with bit 7 set."""
    return bytes(ord(c) | 0x80 for c in s)


def code_fixes(fx, kb, a0, ff, pw):
    w = lambda a: bytes([a & 0xFF, a >> 8])
    return [
        # the kit's T and B (u4pw.s), always hooked -- the launcher's option
        # is a flag they test (pw_on), since the options byte is full
        ("T: teleport, or Talk", 0x5B, 0x59CE, bytes.fromhex("20 21 08"),
         bytes([0x20]) + w(pw["pw_teleport"]), [A]),
        ("B on nothing: a transport, or WHAT?", 0x5B, 0x47AC, w(0x4112), w(pw["pw_board"]), [A]),
        # the title's J with no saved game: "NO ACTIVE GAME!", then the title
        # again rather than a hang (u4ff.s ff_nogame)
        ("J without a saved game: back to the title", 0x5B, 0x404D, bytes.fromhex("4c 4d 40"),
         bytes([0x4C]) + w(ff["ff_nogame"]), [A]),
        # the active character in combat (u4a0.s, at $A006): combat's start,
        # each round's first player, each player's turn, a digit command
        ("active character: combat starts", 0x5B, 0x7097, w(0xA112), w(a0["ac_start"]), [A]),
        ("active character: the round's first", 0x5B, 0x709D, bytes.fromhex("a9 01 85 54"),
         bytes([0x20]) + w(a0["ac_turn"]) + b"\xEA", [A]),
        ("active character: a turn", 0x5B, 0x70C2, bytes.fromhex("20 4b 08"),
         bytes([0x20]) + w(a0["ac_check"]), [A]),
        ("active character: 0-8", 0x5B, 0x7131, w(0x4112), w(a0["ac_key"]), [A]),
        # X in combat (u4a0.s pw_win): its letter-table entry, "WHAT?" before
        ("X in combat: VICTORY!, or WHAT?", 0x5B, 0x77C8, w(0x4112), w(a0["pw_win"]), [A]),
        # attacking a static NPC (u4a0.s): the foe's tile, the "can't" check,
        # combat's animation (SUBS)
        ("attack: the foe's tile", 0x5B, 0x4733, bytes.fromhex("bd 60 ac"),
         bytes([0x20]) + w(a0["fx_attack"]), [A]),
        ("attack: a chest cannot be", 0x5B, 0x46E1, bytes.fromhex("bd 60 ac"),
         bytes([0x20]) + w(a0["fx_attackable"]), [A]),
        ("attack: the ankh and a camp fire keep still", 0x4F, 0x0B6D, bytes.fromhex("bd 70 ad"),
         bytes([0x20]) + w(a0["fx_animate"]), [A]),
        # "EXIT?" at a town's edge (u4fix.s): the four steps in town mode
        ("EXIT?: north", 0x5B, 0x42E1, bytes.fromhex("c6 11 a5 11"),
         bytes([0x20]) + w(fx["fx_exit_n"]) + b"\xEA", [A]),
        ("EXIT?: south", 0x5B, 0x43EF, bytes.fromhex("e6 11 a5 11"),
         bytes([0x20]) + w(fx["fx_exit_s"]) + b"\xEA", [A]),
        ("EXIT?: west", 0x5B, 0x44B9, bytes.fromhex("c6 10 a5 10"),
         bytes([0x20]) + w(fx["fx_exit_w"]) + b"\xEA", [A]),
        ("EXIT?: east", 0x5B, 0x4591, bytes.fromhex("e6 10 a5 10"),
         bytes([0x20]) + w(fx["fx_exit_e"]) + b"\xEA", [A]),
        # the key read (u4key.s): PHP / LDA $0277 / ORA #$80 / PLP becomes
        # JSR kb_get / ORA #$80 / CMP #$80 -- the BEQ after it still means
        # "no key" -- and the queue is no longer emptied after it
        ("keyboard: one key off the queue, or the joystick", 0x4F, 0x1580,
         bytes.fromhex("08 ad 77 02 09 80 28"),
         bytes([0x20]) + w(kb["kb_get"]) + bytes.fromhex("09 80 c9 80"), [A]),
        ("keyboard: the queue is not emptied", 0x4F, 0x159D, b"\x20", b"\x2C", [A]),
        # the music plays on through a load (u4drv.s u4_irq): the six
        # LDA #$00 / JSR $AF20 that stop it before one -- Descend, Klimb,
        # Mix, Quit & save, Search, Use -- become BIT (the kit's patch_music);
        # the LDA #$01 / JSR $AF20 after each then finds it playing and does
        # nothing, where it restarted the song from the start
        *[(f"music: not stopped for a load ({what})", 0x5B, at, bytes.fromhex("a9 00 20 20 af"),
           bytes.fromhex("a9 00 2c 20 af"), [A])
          for what, at in (("Descend", 0x4F94), ("Klimb", 0x55FC), ("Mix", 0x56B5),
                           ("Quit & save", 0x5831), ("Search", 0x59B7), ("Use", 0x5AFF))],
        # stack leaks (patchmain.s patch_stack): the JMP that leaves a
        # return address behind goes through a PLA / PLA first
        ("stack: attacked by a monster", 0x5B, 0x670D, w(0x4731), w(fx["fx_attacked"]), [A]),
        ("stack: bridge trolls", 0x5B, 0x62E8, w(0x6EA3), w(fx["fx_trolls"]), [A]),
        # the party dead: from one to four calls deep (a sinking ship), so
        # the command level's stack is set rather than one address dropped
        ("stack: the party dead", 0x5B, 0x83E1, w(0x621E), w(fx["fx_top"]), [A]),
        # after death, Lord British's castle gets its own music ('C', $59)
        # instead of the previous area's
        ("resurrection music", 0x5B, 0x83DC, b"\x01", b"\xC3", [A]),
        # B on a dungeon ladder (tiles $10-$13 are ships in Britannia)
        ("board: no frigate off a ladder", 0x5B, 0x47B1, w(0x480B), w(fx["fx_board"]), [A]),
        # Enter while flying the balloon
        ("enter: not while flying", 0x5B, 0x4FDA, bytes.fromhex("a5 1a f0 03 4c 12 41"),
         bytes([0x4C]) + w(fx["fx_enter"]) + bytes.fromhex("ea ea ea ea"), [A]),
        # a saved game loaded while flying comes back flying: LDA #0 / STA
        # $1D / STA $74 kept neither; now $74 = the saved $1D, A = 0 as before
        # -- and one saved in a dungeon goes on there (u4ff.s dg_load, the
        # kit's load_dungeon; its surface branch is what was in place here)
        ("load: keep the balloon flying, or the dungeon", 0x5B, 0x405C,
         bytes.fromhex("a9 00 85 1d 85 74"),
         bytes([0x20]) + w(ff["dg_load"]) + bytes.fromhex("ea ea ea"), [A]),
        # Quit & save in a dungeon too ($582A LDA $1A / BEQ / JMP $4178 "NOT
        # HERE!" outside Britannia: u4ff.s dg_save; towns still say it)
        ("quit & save: in a dungeon", 0x5B, 0x582F, w(0x4178), w(ff["dg_save"]), [A]),
        # DEL arrives as $94 on a C64; $88 is the Apple II's backspace
        ("number entry: DEL (giving gold)", 0x4F, 0x12F4, b"\x88", b"\x94", [A]),
        ("number entry: DEL", 0x4F, 0x130B, b"\x88", b"\x94", [A]),
        ("Use in dungeons: DEL (stones)", 0x7A, 0x8B09, b"\x88", b"\x94", [D]),
        # the ending, thrown out after a wrong answer: both return addresses
        # (the Use command's, the overlay's) dropped before the main loop
        ("ending: 'R' $9A by JMP", 0x7A, 0x8A52, b"\x20", b"\x4C", [D]),
        ("ending: thrown out, stack", 0x9A, 0x90D8, bytes.fromhex("4c 09 40"),
         bytes.fromhex("4c 7f 98"), [D]),
        ("ending: thrown out, PLA / PLA", 0x9A, 0x987F, bytes.fromhex("41 45 31 30 0d"),
         bytes.fromhex("68 68 4c 09 40"), [D]),
        # main menu and character creation: 'R' by JSR where JMP was meant
        ("menu: Journey Onward by JMP", 0x50, 0x6966, b"\x20", b"\x4C", [A]),
        ("menu: Initiate by JMP", 0x50, 0x6A27, b"\x20", b"\x4C", [A]),
        ("creation: game main by JMP", 0x51, 0x640B, b"\x20", b"\x4C", [A]),
        # character creation's random hangs: both IRQ restores did CLI before
        # the raster IRQ was off and acknowledged; the CLI goes after (151
        # binpatch, one byte out and one in each, nothing else moves)
        ("creation: CLI after the raster IRQ is off (1)", 0x51, 0x67F5,
         bytes.fromhex("58 ad 1a d0 29 fe 8d 1a d0 a9 01 8d 19 d0"),
         bytes.fromhex("ad 1a d0 29 fe 8d 1a d0 a9 01 8d 19 d0 58"), [A]),
        ("creation: CLI after the raster IRQ is off (2)", 0x51, 0x681E,
         Pin("#17:604b108cd0e1fa4e"),           # CLI, then 16 bytes: the CLI moves last
         lambda o: o[1:] + o[:1], [A]),
        # shrine: 0 cycles tested Z of CMP #$04 (STA sets none), so it meant
        # 256; now Z of get_number's own result (shrine.s)
        # JSR get_number / CMP #$04 / BCS / STA / STA / BNE +3 / JMP: the
        # BNE and JMP move up behind the JSR, the BCS 5 bytes further back
        ("shrine: 0 cycles", 0x82, 0x8907,
         Pin("#18:badc361720976283"),
         lambda o: o[:3] + o[13:18] + o[3:6] + bytes([(o[6] - 5) & 0xFF]) + o[7:13], [C]),
        # shrine: 1, 2 and 3 cycles give the first, second and third hint
        # (shrine_msg_per_cycle at $8BFE: $18, 0, 0, 0 ... -> $18, 0, 1, 2)
        ("shrine: a hint per cycle", 0x82, 0x8C00, b"\x00\x00", b"\x01\x02", [C]),
        # typos, in the original's upper case (15b.binpatch, use_underworld.s)
        ("text: WH0- (a zero)", 0x5B, 0x49DA, t("WH0-"), t("WHO-"), [A]),
        ("text: the chest's -GOLD!", 0x5B, 0x5498, t("-GOLD!"), t(" GOLD!"), [A]),
        ("text: THE ALTER ROOM", 0x5B, 0x6DCA, t("THE ALTER ROOM"), t("THE ALTAR ROOM"), [A]),
        ("text: THE ALTER (the Abyss)", 0x7A, 0x8A29, t("ALTER"), t("ALTAR"), [D]),
        ("text: THYNE EYES", 0x7A, 0x8A3E, t("THYNE"), t("THINE"), [D]),
    ]


# ---- from Sean Gugler's continuation of the kit (2.3.0-2.4.1) -------------
# github.com/sean-gugler/u4remastered, Apache 2.0 as the kit: its changelog,
# binpatches, patchmain.s and reassembled overlays, each found here in the
# original and checked against its disassembly.  Same format as code_fixes.
REAGENT_SEARCH = bytes.fromhex("a5 22 05 23 f0 03 4c 0a 88 a5 2f 29 f0 c5 2a d0 03 4c 0a 88 20 41 88")


def fork_fixes(fx, ff):
    w = lambda a: bytes([a & 0xFF, a >> 8])
    return [
        # stack leaks: a moongate is JMPed to from a step's subroutine
        # ($448D and its siblings, JSRed by the direction commands, twice at
        # a gallop) and leaves by JMP -- to cmd_done, or into a shrine
        ("stack: a moongate jump", 0x5B, 0x86CB, w(0x621E), w(fx["fx_top"]), [A]),
        ("stack: a moongate into a shrine", 0x5B, 0x8699, w(0x5183), w(fx["fx_gate_shrine"]), [A]),
        # combat's Ztats JSRs the Ztats command, which ends in JMP $621E
        ("stack: Ztats in combat", 0x5B, 0x7CEA, bytes.fromhex("20 c8 5c"),
         bytes.fromhex("4c c8 5c"), [A]),
        # Z-down on the lowest level: JSR to the spell's "failed", a JMP end
        ("stack: Z-down on the lowest level", 0x5B, 0x4DFC, bytes.fromhex("20 b9 4e"),
         bytes.fromhex("4c b9 4e"), [A]),
        # "ALL MUST USE THE SAME EXIT!": combat's move is entered by JMP, so
        # its PLA / PLA took what the main loop never pushed
        ("stack: all must use the same exit", 0x5B, 0x7918, b"\x68\x68", b"\xEA\xEA", [A]),
        # a non-monster foe's strength: (tile & $1F) + $24 skipped the halving
        # for its two animation frames (past the table's end from a shepherd
        # on).  AND #$1E / LSR halves and leaves C clear for the ADC.
        ("combat: a non-monster's strength", 0x5B, 0x7DA9, bytes.fromhex("29 1f 18 69 24"),
         bytes.fromhex("29 1e 4a 69 24"), [A]),
        # Ztats with the bell or book but no candle: the branch past "CANDL"
        # went to the middle of the key's letters
        ("Ztats: the 3-part key after BELL/BOOK", 0x5B, 0x60AF, bytes.fromhex("f0 2c"),
         bytes.fromhex("f0 09"), [A]),
        # the inn: a sleeper ('S') woke with status 'A', which no code knows
        # -- not alive, not dead -- until Lord British; now 'G'
        ("inn: a sleeper wakes Good", 0x73, 0x8A72, bytes.fromhex("a9 c1"),
         bytes.fromhex("a9 c7"), [B]),
        # talking: the last gold piece given was Honor's (5), the shrine of
        # Sacrifice's first hint asks it for Sacrifice (4)
        ("talk: the last gold given is Sacrifice", 0x78, 0x8CD2, bytes.fromhex("a9 03 a0 05"),
         bytes.fromhex("a9 03 a0 04"), [B]),
        # the healer's spell: the flash took the bitmap line's address low
        # byte twice ($4048-$59F7 inverted, the view not) and one column too
        # many; now $E0C8 for the high byte and the view's $B0 bytes
        ("healer: the spell's flash, high byte", 0x72, 0x8E7D, bytes.fromhex("ad 08 e0"),
         bytes.fromhex("ad c8 e0"), [B]),
        ("healer: the spell's flash, width", 0x72, 0x8E8D, bytes.fromhex("c0 b8"),
         bytes.fromhex("c0 b0"), [B]),
        # the seer's virtue reward: on the shrine's counter byte ($2E), as
        # last_meditated ($29) is the shrine's
        ("seer: Hawkwind's cooldown", 0x76, 0x8A02, bytes.fromhex("a5 2f c5 29"),
         bytes.fromhex("a5 2e c5 29"), [B]),
        # Search: "YOU FIND..." ($8841) set the reagent cooldown ($2A) for
        # every find; now only mandrake and nightshade set it: their
        # BNE +3 / JMP "nothing" becomes BEQ to the moon check's own JMP
        # "nothing", STA $2A, NOP
        ("search: no cooldown from \"YOU FIND...\"", 0x79, 0x8851,
         bytes.fromhex("a5 2f 29 f0 85 2a"), bytes.fromhex("a5 2f 29 f0 ea ea"), [C]),
        *[(f"search: the {what}'s cooldown", 0x79, at, REAGENT_SEARCH,
           REAGENT_SEARCH[:15] + bytes.fromhex("f0 f5 85 2a ea") + REAGENT_SEARCH[20:], [C])
          for what, at in (("mandrake", 0x8869), ("nightshade", 0x88AB))],
        # the shrine after meditating: BIT $C010 (the Apple II's keyboard
        # strobe) is the kernel's clear-keyboard
        ("shrine: keys typed while meditating dropped", 0x82, 0x895A, bytes.fromhex("2c 10 c0"),
         bytes.fromhex("20 12 a1"), [C]),
        # the skull's shake in Britannia: BIT where the sound's JSR was meant.
        # The page is also on B, a stale copy past the end of the towns' Use
        # (whose own shake JSRs): patched there too, it stays one page.
        *[(f"skull: the shake's sound ({n})", 0x7A, at, bytes.fromhex("2c 09 a1"),
           bytes.fromhex("20 09 a1"), [C, B]) for n, at in ((1, 0x8BCC), (2, 0x8BFB))],
        # the skull destroyed at the Abyss: +10 for each virtue, LDY #$6A
        # (a constant) where LDY $6A (the loop's virtue) was meant
        ("skull: destroyed, every virtue gains", 0x7A, 0x8ADA, bytes.fromhex("a0 6a a9 10"),
         bytes.fromhex("a4 6a a9 10"), [C]),
        # helpers: u4fix.s (fx_) in $5B's tail, u4ff.s (ff) at $FF00
        # bridge trolls not while flying over the bridge (u4fix.s fx_bridge)
        ("trolls: not while flying", 0x5B, 0x62B6, bytes.fromhex("a5 48 c9 17"),
         b"\x20" + w(fx["fx_bridge"]) + b"\xEA", [A]),
        # the last of the three virtues lost for attacking a townsperson
        ("attack: the ankh drawn after the virtues lost", 0x5B, 0x472E, bytes.fromhex("20 72 84"),
         b"\x20" + w(ff["fx_ankh"]), [A]),
        # a townsperson's chest has no conversation
        ("combat: a dropped chest says nothing", 0x5B, 0x767B, bytes.fromhex("4c d6 76"),
         b"\x4C" + w(ff["fx_loot"]), [A]),
        # X-it: the transport's object slot down to 0 in a town (the rest of
        # the old search, to $5C49, is left behind the JMP)
        ("X-it: no one vanishes in a town", 0x5B, 0x5C36, bytes.fromhex("a2 1f bd 60 ac f0"),
         b"\x20" + w(ff["fx_free_slot"]) + bytes.fromhex("4c 4a 5c"), [A]),
        # Board: the transport is looked for in every slot, as X-it may now
        # have put it below 8 -- DEX / CPX #$08 / BCS / BCC becomes BPL / BMI
        ("board: the transport in any slot", 0x5B, 0x4827, bytes.fromhex("e0 08 b0 e4 90 08"),
         bytes.fromhex("10 e6 30 0a 90 08"), [A]),
        # Katrina: "HUMBLE" then RTS (u4ff.s fx_humble), not on into "EXPERIENCED"
        ("talk: the humility reason ends", 0x78, 0x8D62, bytes.fromhex("20 21 08 c8"),
         b"\x20" + w(ff["fx_humble"]) + b"\x60", [B]),
    ]


# ---- data fixes: (what, disk, block, offset, original, new) -------------
# Dungeon rooms: disk D block = room page index + 1 (dng_2c etc.).  Maps:
# chunk data offsets (binpatch offset - 2).
ROOMS = {  # the kit's dng_*.binpatch
    0x2C: [(0x50, "08 08 08 09 09 09 0a 0a"), (0x58, "05 06 04 05 06 04 06 04"),
           (0x70, "02 02 02 01 01 01 00 00"), (0x78, "05 06 04 05 06 04 06 04")],
    0x2E: [(0x50, "08 08 08 09 09 09 0a 0a"), (0x58, "05 06 04 05 06 04 06 04"),
           (0x70, "02 02 02 01 01 01 00 00"), (0x78, "05 06 04 05 06 04 06 04")],
    0x67: [(0x50, "08 08 08 09 09 09 0a 0a"), (0x58, "02 03 01 02 03 01 03 01"),
           (0x60, "02 01 03 02 01 03 01 03"), (0x68, "08 08 08 09 09 09 0a 0a")],
    0x69: [(0x00, "16 98 05 04"),       # a trigger: (9,8) opens the west wall
           (0x70, "01 01 02 03 03 03 04 01"), (0x78, "05 04 05 05 04 06 05 03")],
}
MAP_FIXES = [  # (what, disk, chunk -- or None: a block --, offset in it, original, new)
    ("Serpent's Hold: the gate guards' own conversation", B, 0x5F, 0x4FC, b"\x01\x01", b"\x02\x02"),
    ("Britain: Thevel's own conversation", B, 0x61, 0x4ED, b"\x07", b"\x06"),
    # from Sean Gugler's continuation (fork_fixes): the shopkeepers' rows
    # (record $19: block 352, 128 bytes to $8800), Serpent's Hold's healer
    # at row $12, written $0C
    ("Serpent's Hold: the healer's row", B, None, 352 * 256 + 0x1D, b"\x0C", b"\x12"),
    # dungeon Wrong (chunk $8F, $E800: eight levels of 8 x 8): a ladder
    # down on level 3 at (7, 4) met a chest on level 4, whose ladder up was
    # a row higher; level 8's ladder up at (4, 3) had no ladder down above
    ("Wrong: level 4's ladder up under level 3's down", D, 0x8F, 0xD8,
     bytes.fromhex("f0 00 00 00 00 00 f0 10 f0 00 f0 d2 f0 00 f0 40"),
     bytes.fromhex("f0 00 00 00 00 00 f0 40 f0 00 f0 d2 f0 00 f0 10")),
    ("Wrong: level 7's ladder down over level 8's up", D, 0x8F, 0x198,
     bytes.fromhex("f0 00 00 f0 00 00 f0 40"), bytes.fromhex("f0 00 00 f0 20 00 f0 40")),
    # the cart's own, found by the same check: Covetous (chunk $90) level 6
    # has a ladder up and down at (3, 3), the foot of a stack from level 4,
    # over level 7's corridor; there, a ladder up only
    ("Covetous: level 6's ladder down over level 7's floor", D, 0x90, 0x158,
     bytes.fromhex("f0 00 00 30 00 00 00 80"), bytes.fromhex("f0 00 00 10 00 00 00 80")),
]
# Conversations whose question is a humility test ("Hast thou never
# lied?"; yes is the boast) and whose page lacked the flag ($FE): Sean
# Gugler's continuation.  (page, name)
HUMILITY = [(0x48, "BROWNING"), (0x95, "ARISTOTLE"), (0xA2, "SANTAYANA"), (0xD4, "SLYSAM")]

# ---- conversations: disk B blocks 1-256 ---------------------------------
TALK_DISK, TALK_FIRST = B, 1
KEYS = ["name", "pronoun", "description", "job", "health", "keyword_response_1",
        "keyword_response_2", "question", "question_yes_answer", "question_no_answer"]
TRIG_NUM = {None: 0, "job": 3, "health": 4, "keyword 1": 5, "keyword 2": 6}


def alnum(s):
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def talk_decode(p):
    """The original page: $00, ten NUL-terminated strings in $01-$EF
    (7-bit, $8D a line break), keyword 1 at $F0 and 2 at $F6 (six
    characters), $FC the question's trigger."""
    assert p[0] == 0
    text = lambda bs: "".join("\n" if b & 0x7F == 0x0D else chr(b & 0x7F) for b in bs)
    strings = bytes(p[1:0xF0]).split(b"\0")
    conv = {k: text(strings[i]) for i, k in enumerate(KEYS)}
    conv["keyword_1"] = text(p[0xF0:0xF6]).rstrip()
    conv["keyword_2"] = text(p[0xF6:0xFC]).rstrip()
    conv["trigger"] = p[0xFC]
    return conv


def talk_encode(page, conv):
    """`page` with conv's strings, keywords and trigger; None if the strings
    do not fit $01-$EF."""
    enc = lambda s: bytes(0x8D if c == "\n" else ord(c) & 0x7F for c in s)
    body = b"\0" + b"".join(enc(conv[k]) + b"\0" for k in KEYS)
    if len(body) > 0xF0:
        return None
    out = bytearray(page)
    out[:0xF0] = body.ljust(0xF0, b"\0")
    out[0xF0:0xF6] = (conv["keyword_1"] + " " * 6)[:6].encode()
    out[0xF6:0xFC] = (conv["keyword_2"] + " " * 6)[:6].encode()
    out[0xFC] = conv["trigger"]
    return bytes(out)


def talk_fixes(images):
    """The kit's conversation content fixes (src/talk/talk.json), in the
    original page format and upper case, as the analysis's
    talk_content_port.py: a text field whose letters or digits differ is
    the kit's; a keyword whose first four letters differ is the kit's; the
    question trigger is the kit's.  Fields that differ only in case or
    punctuation stay.  A page that no longer fits stays as it was (the
    analysis found two, both cosmetic: Zorin's and Dupre's).
    Returns {page: (new page, [what changed])} and the pages left out."""
    talk = json.loads(Path(os.path.join(KIT, "src", "talk", "talk.json")).read_text())
    assert len(talk) == 256
    out, skipped = {}, []
    for i, kit in enumerate(talk):
        blk = TALK_FIRST + i
        raw = bytes(images[TALK_DISK][blk * 256:(blk + 1) * 256])
        o = talk_decode(raw)
        conv, notes = dict(o), []
        for k in KEYS:
            if alnum(o[k]) != alnum(kit[k]):
                conv[k] = kit[k].upper()
                notes.append(k)
        for k in ("keyword_1", "keyword_2"):
            if (o[k] + "    ")[:4].upper() != (kit[k] + "    ")[:4].upper():
                conv[k] = kit[k].upper()
                notes.append(k)
        t = TRIG_NUM[kit["question_trigger"]]
        if t != o["trigger"]:
            conv["trigger"] = t
            notes.append("trigger")
        if not notes:
            continue
        page = talk_encode(raw, conv)
        if page is None:
            skipped.append(i)
            continue
        assert talk_decode(page) == {**conv}, i
        out[i] = (page, notes)
    return out, skipped


# ---- the dungeon view: chunk $95, $8C00-$9BFF, disk D -------------------
def dungeon():
    """The kit's dungeon.s assembled as it is, but with its three extra
    colour tables (which live in the Remastered loader's RAM, our tclib) on
    the original's one at $E1B0: the analysis's dungeon_alone.s.  Items and
    monsters then take the original tile colours; the speed-up, the torch
    dimming and the new scaling are unchanged."""
    work = os.path.join(BUILD, "u4dng")
    os.makedirs(work, exist_ok=True)
    src = Path(os.path.join(KIT, "src", "patchedgame", "dungeon.s")).read_text()
    new, n = re.subn(r"^(tilecolors[123]\s*=\s*)\$[0-9a-f]+", r"\1$e1b0", src, flags=re.M)
    assert n == 3, f"dungeon.s: {n} colour tables, expected 3"
    # the torch's colour by light left ($21 / 8, at most $64 / 8): white
    # from 32 on, as the original's view always was, then the kit's greys
    # (Sean Gugler's continuation)
    old_light = "light_color:\n" + "\t.byte $b0, $c0, $f0, $f0\n" + "\t.byte $f0, $f0, $f0, $f0\n" * 3
    new_light = "light_color:\n" + "\t.byte $b0, $c0, $f0, $f0\n" + "\t.byte $10, $10, $10, $10\n" * 3
    assert new.count(old_light) == 1, "dungeon.s: the light table is not the kit's"
    new = new.replace(old_light, new_light)
    s = os.path.join(work, "dungeon.s")
    Path(s).write_text(new)
    inc = os.path.join(KIT, "src", "include")
    for name, path in (("dungeon.o", s), ("loadaddr.o", os.path.join(KIT, "src", "loadaddr.s"))):
        subprocess.run(["ca65", "-t", "c64", "-I", inc, "-o", os.path.join(work, name), path],
                       check=True)
    prg = os.path.join(work, "dungeon.prg")
    subprocess.run(["ld65", "-C", os.path.join(KIT, "src", "patchedgame", "dungeon.cfg"),
                    "-o", prg, os.path.join(work, "dungeon.o"), os.path.join(work, "loadaddr.o")],
                   check=True)
    data = Path(prg).read_bytes()
    assert data[:2] == b"\x00\x8c", data[:2].hex()
    return data[2:]


# ---- mixed-case dialogue --------------------------------------------------
MIXED_CASE = True
LETTER = re.compile(rb"[\xc1-\xda\xe1-\xfa]")
RUN = re.compile(rb"[\x8d\xa0-\xbf\xc1-\xda\xe1-\xfa]{3,}")


def fold(bs):
    """Game text with every letter upper case."""
    return bytes(b & 0xDF if 0xE1 <= b <= 0xFA else b for b in bs)


def case_strings(orig, kit):
    """orig with the case of the kit's text: every all-capitals run of text
    in orig (bit 7 set, NUL-terminated or not) that the kit has too, the
    letters the same, takes the kit's case -- same bytes, same length.
    Runs the kit reworded stay as they were.  Returns (bytes, taken, left)."""
    kit_runs = {}
    for m in RUN.finditer(kit):
        r = m.group()
        if len(LETTER.findall(r)) >= 2:
            kit_runs.setdefault(fold(r), []).append(r)
    out, taken, left = bytearray(orig), 0, 0
    for m in RUN.finditer(orig):
        r = m.group()
        if len(LETTER.findall(r)) < 2 or r != fold(r):
            continue
        cands = set(kit_runs.get(r, []))
        if len(cands) != 1:
            # none, or the kit spells it two ways (a keyword table in
            # capitals, the same word printed mixed): leave it
            left += 1
            continue
        best = cands.pop()
        out[m.start():m.end()] = best
        taken += best != r
    return bytes(out), taken, left


# Strings the kit reworded or moved, in the original's words: their case by
# hand, the same letters and length ($0D a line break).  "SPECIAL!" (a
# trigger no page uses) and the talk code's keyword table (typed input
# arrives in capitals) stay as they are.
MANUAL_CASE = {
    0x78: [("ON GUARD! FOOL!", "On guard! Fool!"),
           (" SAYS:", " says:"),
           ("GIVE OF THY\rPURSE TO THOSE\rWHO BEG AND THY\rDEED SHALL NOT\rBE FORGOTTEN!",
            "Give of thy\rpurse to those\rwho beg and thy\rdeed shall not\rbe forgotten!"),
           ("THIRD, LIGHT THE\rCANDLE OF LOVE\rAT THE ENTRANCE\rTO THE GREAT\rSTYGIAN ABYSS!",
            "Third, light the\rcandle of love\rat the entrance\rto the Great\rStygian Abyss!"),
           ("VICTORIES SCORED\rOVER EVIL\rCREATURES HELP\rTO BUILD A\rVALOROUS SOUL!",
            "Victories scored\rover evil\rcreatures help\rto build a\rvalorous soul!")],
    0x87: [("THOU SEE THE\rKING WITH THE\rROYAL SCEPTRE.", "Thou see the\rking with the\rroyal sceptre."),
           ("THOU SHALT\rLIVE AGAIN!", "Thou shalt\rlive again!")],
    # the resurrection (chunk $89, $8800): Lord British's words, which the kit
    # left in capitals (it has no unit for $89); the narration around them
    # ("ALL IS DARK...", "YOU HEAR:") is a game message and stays
    0x89: [("LORD BRITISH\rSAYS: I HAVE\rPULLED THY\rSPIRIT AND SOME\rPOSSESSIONS FROM\r"
            "THE VOID. BE\rMORE CAREFUL IN\rTHE FUTURE!",
            "Lord British\rsays: I have\rpulled thy\rspirit and some\rpossessions from\r"
            "the void. Be\rmore careful in\rthe future!")],
}


def manual_case(data, chunk):
    out = bytearray(data)
    for old, new in MANUAL_CASE.get(chunk, []):
        a, b = t(old), t(new)                   # (t: "\r" is $8D, a line break)
        assert fold(b) == a and len(a) == len(b), old
        assert bytes(out).count(a) == 1, (hex(chunk), old)
        i = bytes(out).find(a)
        out[i:i + len(b)] = b
    return bytes(out)


def kit_overlay(source, cfg, include_root=False):
    """One of the kit's units, assembled as its Makefile does."""
    work = os.path.join(BUILD, "u4kit")
    os.makedirs(work, exist_ok=True)
    name = os.path.splitext(os.path.basename(source))[0]
    inc = ["-I", os.path.join(KIT, "src", "include"), "-I", KIT]
    obj, lao = os.path.join(work, name + ".o"), os.path.join(work, "loadaddr.o")
    subprocess.run(["ca65", "-t", "c64", *inc, "-o", obj, os.path.join(KIT, source)], check=True)
    subprocess.run(["ca65", "-t", "c64", "-o", lao, os.path.join(KIT, "src", "loadaddr.s")],
                   check=True)
    prg = os.path.join(work, name + ".prg")
    subprocess.run(["ld65", "-C", os.path.join(KIT, cfg), "-o", prg, obj, lao], check=True)
    return Path(prg).read_bytes()[2:]


def binpatch_case(data, path):
    """The kit's binpatch file, whose every replace() is the same text in
    another case (the shops): applied to a chunk's bytes (a binpatch offset
    counts the load address, so -2).  Anything else in the file is an
    error: this takes case, nothing more."""
    def args(text):
        vals, inq, qs, hv = [], False, "", None
        for ch in text:
            if ch == '"':
                if inq:
                    vals.extend(ord(x) | 0x80 for x in qs)
                qs, inq = "", not inq
            elif inq:
                qs += ch
            elif ch == " ":
                if hv is not None:
                    vals.append(hv)
                    hv = None
            elif ch in "0123456789abcdefABCDEF":
                hv = int(ch, 16) if hv is None else hv * 16 + int(ch, 16)
        if hv is not None:
            vals.append(hv)
        return bytes(vals)
    out, off, want, n = bytearray(data), 0, None, 0
    for line in Path(path).read_text().splitlines():
        line = re.sub(r"\s*#.*$", "", line).strip()
        for cmd, a in re.findall(r"\b(\w+)\(([^)]*)\)", line):
            if cmd == "offset":
                off = int(a, 16) - 2
            elif cmd == "match":
                want = args(a)
                assert bytes(out[off:off + len(want)]) == want, (path, hex(off))
            elif cmd == "replace":
                new = args(a)
                assert len(new) == len(want) and fold(new) == fold(want), (path, hex(off))
                out[off:off + len(new)] = new
                n += 1
            else:
                raise ValueError(f"{path}: {cmd}() is not a case change")
    return bytes(out), n


def casemap_text(orig, kit):
    """orig's characters in kit's case where the letters line up
    (difflib on the upper-case forms); the rest lower case, but capitals
    at the start and after . ! ?"""
    sm = difflib.SequenceMatcher(None, orig.upper(), kit.upper(), autojunk=False)
    kmap = {}
    for a, b, n in sm.get_matching_blocks():
        for j in range(n):
            kmap[a + j] = kit[b + j]
    out, cap = [], True
    for i, c in enumerate(orig):
        k = kmap.get(i)
        out.append(k if k is not None and k.upper() == c.upper() else (c.upper() if cap else c.lower()))
        if c in ".!?":
            cap = True
        elif c.isalpha():
            cap = False
    return "".join(out)


def talk_mixed(images, upper):
    """Every conversation in the kit's own text and case, in the original
    page format: the upper-case content fixes' keywords and triggers
    (`upper`, from talk_fixes), the kit's strings -- a name keeps the full
    stop the original had, since the original talk code prints none after
    it.  A page too long for $01-$EF falls back field by field to the
    original's words in the kit's case, first where the kit only added
    punctuation, then everywhere.  Returns {page: (bytes, fallback)}."""
    talk = json.loads(Path(os.path.join(KIT, "src", "talk", "talk.json")).read_text())
    out = {}
    for i, kit in enumerate(talk):
        blk = TALK_FIRST + i
        raw = bytes(images[TALK_DISK][blk * 256:(blk + 1) * 256])
        o = talk_decode(raw)
        base = talk_decode(upper[i][0]) if i in upper else o
        conv = dict(base)
        for k in KEYS:
            conv[k] = kit[k]
        if o["name"].endswith(".") and not conv["name"].endswith("."):
            conv["name"] += "."
        page, fallback = talk_encode(raw, conv), 0
        if page is None:
            # the fields where the kit's letters are the original's
            for k in sorted(KEYS, key=lambda k: len(o[k]) - len(conv[k])):
                if alnum(o[k]) == alnum(kit[k]):
                    conv[k] = casemap_text(o[k], kit[k])
                    fallback += 1
                    page = talk_encode(raw, conv)
                    if page is not None:
                        break
        if page is None:
            for k in KEYS:
                conv[k] = casemap_text(base[k], kit[k])
            fallback = 99
            page = talk_encode(raw, conv)
        assert page is not None, i
        out[i] = (page, fallback)
    return out


def apply_mixed_case(images, chunk_entry, upper, applied):
    pages = talk_mixed(images, upper)
    for i, (page, fb) in sorted(pages.items()):
        o = (TALK_FIRST + i) * 256
        images[TALK_DISK][o:o + 256] = page
    applied.append(("mixed case: 256 conversations, %d with the original words somewhere"
                    % sum(1 for _p, fb in pages.values() if fb), TALK_DISK, TALK_FIRST * 256))
    for chunk, disk, source, cfg in (
            (0x78, B, "src/talk/talk.s", "src/talk/talk.cfg"),
            (0x87, C, "src/patchedgame/lord_british_talk.s", "src/patchedgame/overlay8800.cfg"),
            (0x88, C, "src/patchedgame/lord_british_help.s", "src/patchedgame/overlay8800.cfg")):
        start, count, dest = chunk_entry(chunk)
        o = start * 256
        orig = bytes(images[disk][o:o + count * 256])
        new, taken, left = case_strings(orig, kit_overlay(source, cfg))
        new = manual_case(new, chunk)
        assert fold(new) == fold(orig) and len(new) == len(orig)
        images[disk][o:o + len(new)] = new
        applied.append((f"mixed case: chunk ${chunk:02X}, {taken} strings ({left} reworded, left)",
                        disk, o))
    for chunk, disk in ((0x89, C),):           # ours alone (MANUAL_CASE)
        start, count, dest = chunk_entry(chunk)
        o = start * 256
        orig = bytes(images[disk][o:o + count * 256])
        new = manual_case(orig, chunk)
        assert fold(new) == fold(orig) and len(new) == len(orig)
        images[disk][o:o + len(new)] = new
        applied.append((f"mixed case: chunk ${chunk:02X}, Lord British's words", disk, o))
    for chunk in range(0x6D, 0x77):             # the shops
        start, count, dest = chunk_entry(chunk)
        o = start * 256
        new, n = binpatch_case(bytes(images[B][o:o + count * 256]),
                               os.path.join(KIT, "patches", f"3{chunk:02x}.binpatch"))
        images[B][o:o + len(new)] = new
        applied.append((f"mixed case: shop ${chunk:02X}, {n} strings", B, o))
    return pages


# ---- applying -----------------------------------------------------------
def helpers(name="u4fix"):
    """ultima/games/u4/<name>.s, assembled: its bytes and symbols."""
    out, sym = os.path.join(BUILD, name + ".bin"), os.path.join(BUILD, name + ".sym")
    subprocess.run(["acme", "-f", "plain", "-o", out, "-l", sym,
                    os.path.join(HERE, name + ".s")], check=True)
    syms = {m.group(1): int(m.group(2), 16) for m in
            re.finditer(r"^\s*(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path(sym).read_text(), re.M)}
    return Path(out).read_bytes(), syms


FX_ORG, FX_END = 0x86EF, 0x8800     # $5B's residue, to the end of its block 72
KB_ORG = 0x192A                     # SUBS' dead swap prompt, after its pattern (u4key.s)
# the colour peer (chunk $77, $9000): the kit's units, as they are
PEER = [("src/patchedgame/peer_surface.s", [B, C]), ("src/patchedgame/peer_underworld.s", [D])]


def apply(images, chunk_entry, patch):
    """Patch `images` (disk -> bytearray) in place.  chunk_entry(index) ->
    (first block, count, destination); patch(image, offset, want, new, what)
    is build.py's.  Returns [(what, disk, offset)] of every patch applied."""
    applied = []

    def at(chunk, addr):
        start, count, dest = chunk_entry(chunk)
        assert dest <= addr < dest + count * 256, (hex(chunk), hex(addr))
        return (start + (addr - dest) // 256) * 256 + ((addr - dest) & 0xFF)

    # the helpers into $5B's tail -- which only $44 and $51 load over, and
    # both reload $5B before going on (the analysis; checked here against
    # the chunk table, so a table that changes stops the build)
    code, fx = helpers()
    start, count, dest = chunk_entry(0x5B)
    over = [c for c in range(0x40, 0xA0) if c != 0x5B and
            chunk_entry(c)[2] < FX_ORG + len(code) and
            chunk_entry(c)[2] + chunk_entry(c)[1] * 256 > FX_ORG]
    assert over == [0x44, 0x51], [hex(c) for c in over]
    # The whole residue goes, as the kit truncates $5B there: the helpers,
    # then zeros.  (A stale copy of live code would also hold the launcher's
    # option signatures at their page offsets, which patches.check refuses.)
    o = at(0x5B, FX_ORG)
    end = at(0x5B, FX_END)
    tail = bytes(images[A][o:end])
    stale = at(0x5B, 0x61EF)        # residue: $86EF-$87EE is $61EF-$62EE again
    assert tail[:0x100] == bytes(images[A][stale:stale + 0x100]), "$5B's tail is not the residue it was"
    patch(images[A], o, tail, code.ljust(len(tail), b"\0"), "Remastered fixes: $5B's tail")
    applied.append(("helpers at $%04X, %d bytes; the rest of the tail cleared" % (FX_ORG, len(code)), A, o))

    # the keyboard fix into SUBS' dead swap prompt: $1914 must be build.py's
    # JMP u4_setdisk, and $192A-$19B6 the prompt's own code as it was
    kb_code, kb = helpers("u4key")
    o = at(0x4F, KB_ORG)
    assert images[A][at(0x4F, 0x1914)] == 0x4C, "SUBS' swap prompt is not dead"
    patch(images[A], o, bytes(images[A][o:o + len(kb_code)]), kb_code,
          "Remastered: the keyboard fix in SUBS' dead swap prompt")
    applied.append(("keyboard fix at $%04X, %d bytes" % (KB_ORG, len(kb_code)), A, o))

    # the text window's scroll (u4scroll.s): $160E-$1686 rewritten, its end
    # (the colour of the last row) in the dead prompt after u4key.s.  The
    # scroll's bitmap and screen rows are the game's own, which it hardcodes:
    # the tables they come from must be what it was written for.
    sc_code, _ = helpers("u4scroll")
    sc_col, _ = helpers("u4scrollc")
    o = at(0x4F, 0x160E)
    old = bytes(images[A][o:o + 121])
    assert len(sc_code) == 121 and zlib.crc32(old) == 2692443322, "SUBS' text scroll is not the original"
    assert old[:3] == bytes.fromhex("a2 60 bd") and old[-2:] == b"\xff\x60"
    assert KB_ORG + len(kb_code) == 0x19A3, "u4key.s moved: the scroll's colour routine is at $19A3"
    holder = [c for c in range(0x40, 0xA0) if chunk_entry(c)[2] <= 0xE000 < chunk_entry(c)[2] + chunk_entry(c)[1] * 256]
    assert len(holder) == 1, [hex(c) for c in holder]
    t0 = at(holder[0], 0xE000)
    lines = bytes(images[A][t0:t0 + 0x180])                 # bitmap line n: $E000+n, $E0C0+n
    rows = bytes(images[A][t0 + 0x180:t0 + 0x1B0])          # screen row n: $E180+n, $E198+n
    for n in range(192):
        assert lines[n] | lines[0xC0 + n] << 8 == 0x2000 + 320 * (n // 8) + n % 8, n
    for n in range(24):
        assert rows[n] | rows[0x18 + n] << 8 == 0x0400 + 40 * n, n
    patch(images[A], o, old, sc_code, "Remastered: the text window's scroll")
    applied.append(("text scroll: unrolled bitmap copy", A, o))
    o = at(0x4F, 0x19A3)
    patch(images[A], o, bytes(images[A][o:o + len(sc_col)]), sc_col,
          "Remastered: the scroll's colour routine in SUBS' dead swap prompt")
    applied.append(("text scroll: last row's colour at $19A3, %d bytes" % len(sc_col), A, o))

    # the town view's buffer (u4view.s): $0C0B-$0C71, a row pointer a row, not a cell
    vw_code, _ = helpers("u4view")
    o = at(0x4F, 0x0C0B)
    old = bytes(images[A][o:o + 103])
    assert zlib.crc32(old) == 2490067711 and old[:3] == bytes.fromhex("20 90 0f") \
        and old[-3:] == bytes.fromhex("4c d0 0c"), "SUBS' town view is not the original"
    assert len(vw_code) <= 103
    patch(images[A], o, old, vw_code.ljust(103, b"\xea"), "Remastered: the town view's buffer")
    applied.append(("town view buffer: a row pointer a row, %d bytes" % len(vw_code), A, o))

    # the town view's line of sight (u4los.s): $0D65-$0E6B, one look a cell
    los_code, _ = helpers("u4los")
    o = at(0x4F, 0x0D65)
    old = bytes(images[A][o:o + 263])
    assert zlib.crc32(old) == 3349480674 and old[:3] == bytes.fromhex("a2 78 a9") \
        and old[-3:] == bytes.fromhex("4c e6 0d"), "SUBS' line of sight is not the original"
    assert len(los_code) <= 263
    patch(images[A], o, old, los_code.ljust(263, b"\xea"), "Remastered: the town view's line of sight")
    applied.append(("town view line of sight: one look a cell, %d bytes" % len(los_code), A, o))

    a0_code, a0 = helpers("u4a0")
    ff_code, ff = helpers("u4ff")
    pw_code, pw = helpers("u4pw")
    for what, chunk, addr, want, new, disks in code_fixes(fx, kb, a0, ff, pw) + fork_fixes(fx, ff):
        for disk in disks:
            o = at(chunk, addr)
            patch(images[disk], o, want, new, f"Remastered: {what}")
            applied.append((what, disk, o))

    for room, edits in ROOMS.items():
        blk = room + 1
        for off, new in edits:
            new = bytes.fromhex(new)
            o = blk * 256 + off
            patch(images[D], o, bytes(len(new)), new, f"Remastered: dungeon room ${room:02x}")
            applied.append((f"dungeon room ${room:02X} +${off:02X}", D, o))
    for what, disk, chunk, off, want, new in MAP_FIXES:
        o = off if chunk is None else chunk_entry(chunk)[0] * 256 + off
        patch(images[disk], o, want, new, f"Remastered: {what}")
        applied.append((what, disk, o))

    pages, skipped = talk_fixes(images)
    for i, (page, notes) in sorted(pages.items()):
        applied.append((f"conversation ${i:02X}: " + ", ".join(notes), TALK_DISK,
                        (TALK_FIRST + i) * 256))
    if MIXED_CASE:
        apply_mixed_case(images, chunk_entry, pages, applied)
    else:
        for i, (page, notes) in sorted(pages.items()):
            o = (TALK_FIRST + i) * 256
            images[TALK_DISK][o:o + 256] = page
    for i, name in HUMILITY:
        o = (TALK_FIRST + i) * 256
        assert alnum(talk_decode(bytes(images[TALK_DISK][o:o + 256]))["name"]) == name, (hex(i), name)
        patch(images[TALK_DISK], o + 0xFE, b"\0", b"\1", f"humility question: {name}")
        applied.append((f"conversation ${i:02X}: a humility question", TALK_DISK, o + 0xFE))

    # the colour peer: multicolour, water blue, grass green on the surface;
    # the Underworld's dungeon features coloured.  B's and C's copies are
    # one and the same.
    start, count, dest = chunk_entry(0x77)
    assert (dest, count) == (0x9000, 5), (hex(dest), count)
    o = start * 256
    assert images[B][o:o + count * 256] == images[C][o:o + count * 256]
    for source, disks in PEER:
        code = kit_overlay(source, "src/patchedgame/peer.cfg")
        assert len(code) <= count * 256
        for disk in disks:
            images[disk][o:o + len(code)] = code
            applied.append((f"colour peer: {os.path.basename(source)}, {len(code)} bytes", disk, o))

    dng = dungeon()
    start, count, dest = chunk_entry(0x95)
    assert (dest, count) == (0x8C00, 16), (hex(dest), count)
    assert len(dng) <= count * 256
    o = start * 256
    images[D][o:o + len(dng)] = dng
    applied.append(("dungeon view: the kit's renderer, %d bytes" % len(dng), D, o))
    return applied, skipped
