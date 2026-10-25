"""Ultima VI's places on the surface, from the C64 disks.

    places() -> [(key, x, y, name, kind)]   x, y: surface tiles, 0-1023

What holds them:
- The surface's objects: 1A's 64 files S<y><x> -- the second letter is the
  superchunk's row, the third its column (A-H), so x = column x 128 + byte
  1 and y = row x 128 + byte 2 -- six bytes a record, $FF ends the list:
  byte 0 the record type ($FE a map feature, 0/1 objects), byte 3 the tile
  or object number, byte 5 its "quality" (game $329B).  (The U6 notes call
  the files "Sxy"; read that way the caves land in water.)
- Shrines: $FE records of tile $DB whose quality is the shrine's
  conversation, T191 (Honesty) ... T198 (Humility).  Two more shrine tiles
  have no conversation; Spirituality's shrine is on dungeon level 1.
- Dungeons and caves: $FE records of tile $6E ("dungeon") or $69 ("hole");
  the quality names them through the list in overlay $2C (1A T21 S16, read
  from game $11CF).  Each one's step down lands on a level-1 ladder up.
- Objects by number (1A T35's names): the Codex ($91), the runes ($88-$8F,
  in virtue order), the balloon basket ($68).
- People: the actors' start positions in the state (1A T6 S9-20, x
  $5B25/$5BE9, y $5CAD/$5D71, level $5E35): the Avatar (1), Lord British (5).
- Towns: the game holds no town coordinates and no sign names a town, so a
  town is placed at the median of its residents' start positions -- the
  residents grouped by the PC version's actor numbering, each group backed
  by something on the C64 (a rune, a sign, a scroll, a conversation that
  names the town).  Inferred, and labelled so.
"""
import statistics

from ultima.disks.d64 import D64
from ultima import paths

SURFACE = paths.disk("u6-1a")
LETTERS = "ABCDEFGH"
VIRTUES = ["Honesty", "Compassion", "Valor", "Justice", "Sacrifice", "Honor", "Spirituality", "Humility"]
FEATURE, SHRINE, DUNGEON, HOLE, LADDER = 0xFE, 0xDB, 0x6E, 0x69, 0x67
CODEX, RUNE, BALLOON = 0x91, 0x88, 0x68
FIRST_SHRINE_TALK = 191
STATE = 0x5400                                  # 1A T6 S9-20 in RAM
ACTOR_X, ACTOR_XH, ACTOR_Y, ACTOR_YH, ACTOR_Z = 0x5B25, 0x5BE9, 0x5CAD, 0x5D71, 0x5E35
AVATAR, LORD_BRITISH = 1, 5
NAMES_AT = 0xC8E5                               # overlay $2C (1A T21 S16 at $C800)
# (town, its residents' actor numbers -- the conversation file Tnnn is actor nnn)
TOWNS = [
    ("Britain", list(range(8, 32)) + [133, 134, 135, 137, 163]),
    ("the Lycaeum", range(33, 38)),
    ("Moonglow", range(38, 43)),
    ("Jhelom", range(43, 54)),
    ("Yew", list(range(54, 63)) + [136, 181]),
    ("Minoc", range(63, 75)),
    ("Trinsic", range(75, 82)),
    ("Skara Brae", [82, 83, 84, 85, 86, 87, 88, 89, 91]),
    ("New Magincia", range(92, 99)),
    ("Paws", list(range(99, 111)) + [180]),
    ("Buccaneer's Den", range(111, 122)),
    ("Cove", range(122, 129)),
    ("Empath Abbey", [146, 147, 148, 149, 150, 151, 178, 179]),
    ("Serpent's Hold", list(range(152, 163)) + [186]),
    ("Sutek's castle", [129]),
    ("Sin'Vraal's hut", [141]),
    ("Iolo's hut", [132]),
    ("the gypsies' caravan", [138, 139, 140]),
]


def records(d, name):
    data = d.file(name)[0]
    out = []
    for i in range(0, len(data) - 5, 6):
        if data[i] == 0xFF:
            break
        out.append(data[i:i + 6])
    return out


def surface_objects(d):
    """[(record, x, y)] of every object on the surface."""
    out = []
    for name, *_ in d.directory():
        if len(name) == 3 and name[0] == "S" and name[1] in LETTERS and name[2] in LETTERS:
            for r in records(d, name):
                out.append((r, LETTERS.index(name[2]) * 128 + r[1], LETTERS.index(name[1]) * 128 + r[2]))
    return out


def dungeon_names(d):
    ov = b"".join(d.sector(21, 16 + i) for i in range(2))
    names = []
    for w in ov[NAMES_AT - 0xC800:].split(b"\x00")[:20]:
        names.append("".join(chr(c + 0x60) if 1 <= c <= 26 else chr(c) for c in w))
    assert names[0] == "Deceit" and names[19] == "Buccaneer's Cave", names
    return names


def actors(d):
    st = b"".join(d.sector(6, s) for s in range(9, 21))
    m = lambda a: st[a - STATE]
    return lambda n: (m(ACTOR_X + n) | m(ACTOR_XH + n) << 8, m(ACTOR_Y + n) | m(ACTOR_YH + n) << 8, m(ACTOR_Z + n))


def places():
    d = D64(SURFACE)
    objs = surface_objects(d)
    names = dungeon_names(d)
    actor = actors(d)
    out = []
    for r, x, y in objs:
        if r[0] == FEATURE and r[3] == SHRINE:
            v = r[5] - FIRST_SHRINE_TALK
            if 0 <= v < 8:
                out.append((f"S{v + 1}", x, y, f"shrine of {VIRTUES[v]}", "shrine"))
            else:
                out.append(("S", x, y, "shrine (no conversation)", "shrine"))
    for r, x, y in objs:
        if r[0] == FEATURE and r[3] in (DUNGEON, HOLE):
            out.append((f"D{r[5]}", x, y, names[r[5] - 1], "dungeon" if r[3] == DUNGEON else "hole"))
        elif r[0] == FEATURE and r[3] == LADDER:
            out.append(("L", x, y, "ladder down (no name)", "ladder"))
    for r, x, y in objs:
        if r[0] in (0, 1) and r[3] == CODEX:
            out.append(("CX", x, y, "the Codex", "codex"))
        elif r[0] == 0 and RUNE <= r[3] < RUNE + 8:
            out.append((f"R{r[3] - RUNE + 1}", x, y, f"rune of {VIRTUES[r[3] - RUNE]}", "rune"))
        elif r[0] in (0, 1) and r[3] == BALLOON:
            out.append(("B", x, y, "balloon basket", "balloon"))
    ax, ay, _ = actor(AVATAR)
    lx, ly, _ = actor(LORD_BRITISH)
    out.append(("A", ax, ay, "the Avatar's start", "start"))
    out.append(("LB", lx, ly, "Lord British (his castle)", "castle"))
    for i, (name, ids) in enumerate(TOWNS):
        pts = [(x, y) for x, y, z in map(actor, ids) if z == 0]
        out.append((f"T{i + 1}", int(statistics.median(p[0] for p in pts)),
                    int(statistics.median(p[1] for p in pts)), f"{name} (inferred, by its people)",
                    "town" if len(pts) > 3 else "home"))
    return out


if __name__ == "__main__":
    for p in places():
        print(p)
