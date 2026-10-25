#!/usr/bin/env python3
"""Drive Ultima 5 from the cartridge: main menu, then character creation.

Why this is not just "stuff a key and run":

* The attract sequence polls GETIN to see whether it should stop, so a key
  written at the $F142 break ends it -- but only at a poll; between scenes
  there can be many seconds of warp with no poll at all.  Loop on it.
* The main menu polls through $9153 -> $9176 -> "JSR $4C4E" at $9190, and
  $9176 counts down $9152 and, at zero, drops the return addresses and jumps
  back to the attract loop.  That is the ~1 second timeout.  NOP the count.
* The read itself is replaced with "LDA #$00 / NOP", a poll that always says
  "no key"; a key is then delivered by writing its code into $9191.  The BMI
  at $9193 is the "a key came back" test, so codes must carry bit 7 -- the
  menu accepts several synonyms for each direction and only some of them do:
  $BB = next entry, $C0 = previous, $A0 = select.  ($C1-$CF are *digits*,
  routed to "number of drives" at $85A2, not to the cursor handlers.)
* All of that has to happen *after* the menu is on screen: every attract
  cycle reloads `startup` and wipes any earlier patch.  Once an entry is
  picked the read goes back to the JSR: character creation's prompts poll
  through the same routine.

Run it as `python -m tools.vice.u5_drive` for the character-creation walkthrough.
"""
import os
import re
import sys
import time
from pathlib import Path

from tools.vice import menu_check                                   # noqa: E402
from tools.vice.vice_mon import Vice                           # noqa: E402

MENU_POLL = 0x854d      # startup's menu poll, once per time the menu appears
MENU_READ = 0x9190      # "JSR $4C4E" -- the key read
MENU_TMO = 0x917b       # "DEC $9152" -- the watchdog countdown
SEL_H = 0x85d9          # the menu's select handler
NEXT_H = 0x85c1         # ... and its "move down" handler
GETIN = 0xf142
K_NEXT, K_SELECT = 0xbb, 0xa0


def symbols(path="build/u5drv.sym"):
    return {m.group(1): int(m.group(2), 16)
            for m in re.finditer(r"(\w+)\s*=\s*\$([0-9a-fA-F]+)", Path(path).read_text())}


# an Action Replay 6 ROM image (yours; not in the repository)
AR_ROM = os.path.abspath(os.environ.get("AR_ROM", "ar-60pal.bin"))
AR_ARGS = ["-cartar5", AR_ROM, "-jamaction", "2"]


def ar_boot(v, tries=40):
    """With an Action Replay 6 (VICE started with AR_ARGS and no keybuf): its
    start menu, F7 (install fastload) once it is up, BASIC's READY. with
    the fastload banner, then LOAD from the tapecart.  True once Ultima V
    has found the AR ($C8 bit 6 set, $0314 moved); now and then VICE's AR
    goes to its freezer menu instead, so the caller should retry."""
    def has(text):
        return any(text in r for r in v.screen())
    for _ in range(tries):
        v.go(0.5)
        if has("install fastload"):
            break
    else:
        print("  ar_boot: no start menu"); return False
    v.cmd("keybuf \\x88", 0.3)
    for _ in range(tries):
        v.go(0.5)
        if has("backup"):
            print("  ar_boot: the freezer menu"); return False
        if has("fastload v6.0") and has("ready."):
            break
    else:
        print("  ar_boot: no READY."); return False
    v.cmd("keybuf load\\x0d", 0.3)
    for _ in range(90):
        v.go(1)
        if v.mem(0xc8, 0xc8)[0] & 0x40 and v.mem(0x0314, 0x0315) != b"\x31\xea":
            return True
    print("  ar_boot: U5 did not find the AR"); return False


class U5:
    def __init__(self, tcrt=None, extra=None, log=None, ar=False):
        """ar: with an Action Replay; boot with ar_boot() before anything."""
        self.sym = symbols()
        self.v = Vice(tcrt or menu_check.with_autokey(5), update_tcrt=True,
                      extra=(extra or []) + (AR_ARGS if ar else []), log=log,
                      keybuf=None if ar else "load\n")

    def arm(self, *addrs):
        for a in addrs:
            self.v.cmd(f"break {a:04x}", wait=0.15)

    def stop(self, timeout=40):
        """Resume until any breakpoint hits; return the PC, or None."""
        self.v.sock.sendall(b"x\n")
        deadline = time.time() + timeout
        seen = ""
        while time.time() < deadline:
            seen += self.v._drain(0.5)
            if "Stop on" in seen:
                return self.v.pc()
        self.v.cmd("", wait=0.2)
        return None

    def flags(self):
        """The status register, as the monitor prints it (NV-BDIZC)."""
        out = self.v.cmd("r", wait=0.4)
        m = re.search(r"^\.;[0-9a-fA-F]{4}(?:\s+[0-9a-fA-F]{2}){6}\s+([01]{8})",
                      out, re.M)
        return m.group(1) if m else "?"

    def irq_enabled(self):
        f = self.flags()
        return None if f == "?" else f[5] == "0"     # NV-BDIZC

    def key(self, code):
        self.v.poke(0x0277, bytes([code]))
        self.v.poke(0x00c6, b"\x01")

    # -- the joystick ------------------------------------------------------
    #
    # In the game proper the party is moved with the *joystick*: `$4CAE` is
    # zero, so `$5BDF` reads port A at `$DC00` and never looks at the keyboard
    # queue.  (Commands are read from the queue elsewhere, which is why a
    # cursor code stuffed there comes back as "What?".)  Nothing in the
    # monitor can press an emulated joystick, so repoint the read at a byte
    # we can write -- `$0334`, in the free block above the KERNAL's vectors.
    JOY_READ = 0x5be4           # "LDA $DC00" inside the key/joystick reader
    JOY_BYTE = 0x0334
    JOY = {"up": 0xfe, "down": 0xfd, "left": 0xfb, "right": 0xf7,
           "fire": 0xef, "idle": 0xff}

    def joystick_patch(self):
        self.v.poke(self.JOY_BYTE, b"\xff")
        self.v.poke(self.JOY_READ,
                    bytes([0xad, self.JOY_BYTE & 0xff, self.JOY_BYTE >> 8]))
        return self.v.mem(self.JOY_READ, self.JOY_READ + 2) == \
            bytes([0xad, self.JOY_BYTE & 0xff, self.JOY_BYTE >> 8])

    def push(self, direction, hold=0.6, rest=0.4):
        self.v.poke(self.JOY_BYTE, bytes([self.JOY[direction]]))
        self.v.run(hold)
        self.v.poke(self.JOY_BYTE, b"\xff")
        self.v.run(rest)

    def loaded_name(self):
        pat = self.sym["u5_pat"] + 1
        ptr = int.from_bytes(self.v.mem(pat, pat + 1), "little")
        raw = self.v.mem(ptr, ptr + 15)
        return (self.v.mem(self.sym["u5_disk"], self.sym["u5_disk"])[0],
                raw.split(b"\x00")[0].decode("latin1", "replace"),
                self.v.mem(self.sym["u5_ok"], self.sym["u5_ok"])[0])

    # -- getting somewhere ------------------------------------------------
    def boot_to_menu(self, tries=25):
        self.v.run_to(0x8000, timeout=60)
        self.v.delbreaks()
        self.v.run(10.0)
        self.arm(GETIN, MENU_POLL)
        for _ in range(tries):
            pc = self.stop(40)
            if pc is None:
                break
            if pc == MENU_POLL:
                self.v.delbreaks()
                self.v.poke(MENU_TMO, b"\xea\xea\xea")      # no watchdog
                self.v.poke(MENU_READ, b"\xa9\x00\xea")     # poll says "no key"
                return True
            self.key(0x20)
        self.v.delbreaks()
        return False

    def menu_pick(self, index):
        """Move to entry `index` and select it.  The menu must be up."""
        for _ in range(index):
            self.arm(NEXT_H)
            self.v.poke(MENU_READ + 1, bytes([K_NEXT]))
            pc = self.stop(40)
            self.v.delbreaks()
            self.v.poke(MENU_READ + 1, b"\x00")
            if pc != NEXT_H:
                return False
            self.v.run(0.5)
        self.arm(SEL_H)
        self.v.poke(MENU_READ + 1, bytes([K_SELECT]))
        pc = self.stop(40)
        self.v.delbreaks()
        # the read again: creation's prompts poll through it too ($915D
        # sets its operand), and with "no key" there they never get one
        self.v.poke(MENU_READ, b"\x20\x4e\x4c")
        return pc == SEL_H


def main():
    """Create a character: pick the menu entry, then answer every prompt.

    The lore screens need no keypress -- they are timed, which is why they
    froze solid when a cart load left interrupts disabled.
    """
    # UPPER case: the KERNAL queue holds PETSCII, where $41-$5A are the
    # unshifted letters -- lower case ($61+) is shift+letter and is not what
    # a player types.
    keys = list(b"AVATAR\r") + list(b"M") + list(b"A" * 20)
    u = U5()
    try:
        if not u.boot_to_menu():
            print("never reached the menu"); return 1
        print("main menu, interrupts enabled:", u.irq_enabled(), flush=True)
        if not u.menu_pick(1):
            print("could not pick Create New Character"); return 1
        print("picked Create New Character", flush=True)
        # Wait for the lore to play out -- it is timed, not keyed -- then type.
        # Breaking at the KERNAL's GETIN is no use here: U5 runs at $01 = $00
        # with its own copy of the KERNAL in RAM, so $FFE4 never reaches
        # $F142.  The keyboard queue is still the queue, though: fill it and
        # let the game's poll pick it up.
        u.v.run(8.0)
        print("after the lore, interrupts enabled:", u.irq_enabled(), flush=True)
        u.v.shot("build/u5cr_lore.png")
        for i, k in enumerate(keys):
            u.key(k)
            u.v.run(1.2)
            if i % 3 == 0:
                u.v.shot(f"build/u5cr_{i:02d}.png")
        u.v.shot("build/u5cr_end.png")
        print("ended at", hex(u.v.pc() or 0), flush=True)
        u.v.quit()
        return 0
    except Exception as e:
        print("ERR", repr(e)); return 1
    finally:
        try: u.v.kill()
        except Exception: pass


if __name__ == "__main__":
    sys.exit(main())
