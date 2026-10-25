"""The games' disks the build needs, by key: what the manifest, the scanner
and the game builds call them.  The stand-in for each is build/disks/<key>.d64.

The labels name the disks as the Ultima Trilogy releases do (the reference
the manifest was made from); other editions' disks are found by content.
Akalabeth's is Genesis Project's release of the C64 conversion."""

DISKS = {
    "u0": "Akalabeth (Genesis Project's release, \"accept no limits\")",
    "u1": "Ultima I",
    "u2a": "Ultima II, side A (program and galactic)",
    "u2b": "Ultima II, side B (player master)",
    "u3a": "Ultima III, side A (program)",
    "u3b": "Ultima III, side B (player master)",
    "u3gold": "Ultima III Gold",
    "u4a": "Ultima IV, disk A (program)",
    "u4b": "Ultima IV, disk B (towne)",
    "u4c": "Ultima IV, disk C (Britannia)",
    "u4d": "Ultima IV, disk D (underworld)",
    "u5-1a": "Ultima V, 1A (program)",
    "u5-1b": "Ultima V, 1B (dungeon)",
    "u5-2a": "Ultima V, 2A (Britannia)",
    "u5-2b": "Ultima V, 2B (underworld)",
    "u5-3a": "Ultima V, 3A (towne)",
    "u5-3b": "Ultima V, 3B (dwelling)",
    "u5-4a": "Ultima V, 4A (castle)",
    "u5-4b": "Ultima V, 4B (keep)",
    "u6-1a": "Ultima VI, 1A (surface)",
    "u6-1b": "Ultima VI, 1B (dungeon)",
    "u6-2a": "Ultima VI, 2A (populace A)",
    "u6-2b": "Ultima VI, 2B (populace B)",
    "u6-3a": "Ultima VI, 3A (populace C)",
    "u6-3b": "Ultima VI, 3B (game)",
}
GAMES = {"0": "Akalabeth", "1": "Ultima I", "2": "Ultima II", "3": "Ultima III", "4": "Ultima IV", "5": "Ultima V", "6": "Ultima VI"}


def game_of(key):
    return key[1]
