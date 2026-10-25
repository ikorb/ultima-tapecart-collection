"""ROM images from a VICE installation, for the simulators: never in the
repository.  Looked for in $VICE_ROMS/<machine>, next to the emulator on
$PATH (<prefix>/share/vice/<machine>), then in the usual install places."""
import os
import shutil

PLACES = ["/usr/share/vice", "/usr/local/share/vice", "/opt/homebrew/share/vice",
          "/usr/lib/vice", "/usr/local/lib/vice"]


def find(machine, name, emulator):
    """machine: "C64" or "C128"; name: e.g. "kernal-901227-03.bin";
    emulator: "x64sc" or "x128".  The path, or None."""
    dirs = []
    if os.environ.get("VICE_ROMS"):
        dirs.append(os.path.join(os.environ["VICE_ROMS"], machine))
    exe = shutil.which(emulator)
    if exe:
        prefix = os.path.dirname(os.path.dirname(os.path.realpath(exe)))
        dirs.append(os.path.join(prefix, "share", "vice", machine))
    dirs += [os.path.join(p, machine) for p in PLACES]
    for d in dirs:
        path = os.path.join(d, name)
        if os.path.exists(path):
            return path
    return None
