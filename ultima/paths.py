"""Where things are: the repository's directories, and the disks the build
reads -- stand-ins the scanner assembled from your own images
(`make disks`), never the images themselves."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.environ.get("ULTIMA_BUILD") or os.path.join(ROOT, "build")
ASM = os.path.join(ROOT, "asm")
EXTERNAL = os.path.join(ROOT, "external")
USER_DISKS = os.path.join(ROOT, "disks")
# the stand-ins: one <key>.d64 per disk (ultima/disks/keys.py), written by
# `make disks`; ULTIMA_DISKS points elsewhere (the tests, a maintainer's
# reference set)
STAND_INS = os.environ.get("ULTIMA_DISKS") or os.path.join(BUILD, "disks")


def disk(key):
    """The stand-in for one of the games' disks, by its key (it need not
    exist yet: require_disks() says what is missing)."""
    from ultima.disks.keys import DISKS
    if key not in DISKS:
        raise KeyError(f"no disk {key!r}")
    return os.path.join(STAND_INS, key + ".d64")


def require_disks(keys=None):
    """Stop, saying what to do, if a stand-in the build needs is missing."""
    from ultima.disks.keys import DISKS
    missing = [k for k in (keys or DISKS) if not os.path.exists(disk(k))]
    if missing:
        raise SystemExit("missing: " + ", ".join(DISKS[k] for k in missing) +
                         f"\nput your disk images in {USER_DISKS} and run `make disks`")


def build(*parts):
    os.makedirs(BUILD, exist_ok=True)
    return os.path.join(BUILD, *parts)
