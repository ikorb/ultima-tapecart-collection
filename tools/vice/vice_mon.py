#!/usr/bin/env python3
"""Drive VICE through its text remote monitor.

Lets the build actually play the games -- set breakpoints, read memory, type
at the keyboard -- instead of handing a .tcrt to a human and asking what
happened.  Written for the Ultima 3 party-position hunt, where reproducing
the bug needs a character creation session.
"""
import re
import socket
import subprocess
import time


class Vice:
    def __init__(self, tcrt, prg=None, port=6510, extra=None, update_tcrt=False,
                 log=None, emu="x64sc", keybuf="load\n", easyflash=None):
        """easyflash: an EasyFlash .crt in the expansion port instead of the
        tapecart (the U6 side quest, ef/); update_tcrt then writes it back."""
        self.port = port
        self.emu = emu
        self.logfile = open(log, "w") if log else None
        if easyflash:
            cmd = [emu, "-warp", "-cartcrt", easyflash,
                   "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
            if update_tcrt:
                cmd.append("-easyflashcrtwrite")
            update_tcrt, keybuf, log = False, None, None
        else:
            cmd = [emu, "-warp", "-tapeport1device", "6", "-tcrt", tcrt,
                   "-remotemonitor", "-remotemonitoraddress", f"ip4://127.0.0.1:{port}"]
        if emu == "x128":
            # the text monitor's screenshot is canvas 0, the VDC's; the
            # binary monitor can ask for the VIC's (vic_shot)
            cmd += ["-binarymonitor", "-binarymonitoraddress", f"ip4://127.0.0.1:{port + 1}"]
        self.bin = None
        if update_tcrt:
            cmd.append("-tapecartupdatetcrt")
        if extra:
            cmd += extra
        if prg:
            cmd += ["-autostart", prg]
        else:
            # lower case!  VICE maps upper case to Shift+key, which on a C64
            # types graphics characters instead of letters and loads nothing.
            if keybuf:
                cmd += ["-keybuf", keybuf]
        if self.logfile and not easyflash:
            cmd += ["-tapecartloglevel", "2"]
        out = self.logfile or subprocess.DEVNULL
        self.proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT)
        self.sock = None
        for _ in range(100):
            try:
                self.sock = socket.create_connection(("127.0.0.1", port), timeout=2)
                break
            except OSError:
                time.sleep(0.1)
        if not self.sock:
            self.kill()
            raise RuntimeError("could not reach the remote monitor")
        self.sock.settimeout(30)
        self._drain(0.4)

    # -- plumbing --------------------------------------------------------
    def _drain(self, wait=0.2):
        self.sock.settimeout(wait)
        out = b""
        try:
            while True:
                chunk = self.sock.recv(65536)
                if not chunk:
                    break
                out += chunk
        except (socket.timeout, TimeoutError):
            pass
        self.sock.settimeout(30)
        return out.decode("latin1")

    def cmd(self, text, wait=0.3):
        self.sock.sendall((text + "\n").encode("latin1"))
        return self._drain(wait)

    # -- conveniences ----------------------------------------------------
    MEM_CHUNK = 256

    def mem(self, start, end):
        """Read memory as bytes (inclusive range).

        Split into short dumps and check the length of each.  A single `m`
        over several KiB arrives in pieces and the drain can stop early,
        which silently returns a SHORT buffer -- so every byte after the gap
        compares against the wrong offset and a perfectly good transfer looks
        corrupt from some arbitrary point on.  That cost a debugging session.
        """
        out = bytearray()
        addr = start
        while addr <= end:
            last = min(addr + self.MEM_CHUNK - 1, end)
            chunk = self._mem_chunk(addr, last)
            if len(chunk) != last - addr + 1:
                raise RuntimeError(f"monitor returned {len(chunk)} bytes for "
                                   f"${addr:04x}-${last:04x}")
            out += chunk
            addr = last + 1
        return bytes(out)

    def _mem_chunk(self, start, end):
        """One `m` dump, parsed by the address each line carries.

        Take at most 16 byte tokens per line and place them at that line's
        address.  Scanning tokens until the first non-hex one is not enough:
        the monitor prints an ASCII column after the bytes, and when that
        column happens to contain space-separated characters that look like
        hex -- ` ee ` for two 'e's -- they get appended as data and every
        byte after them shifts by one.
        """
        out = self.cmd(f"m {start:04x} {end:04x}", wait=0.4)
        seen = {}
        for line in out.splitlines():
            m = re.match(r"^\s*>\s*(?:C:)?([0-9a-fA-F]{4})\s+(.*)$", line)
            if not m:
                continue
            addr = int(m.group(1), 16)
            for i, tok in enumerate(m.group(2).split()[:16]):
                if len(tok) != 2:
                    break
                try:
                    seen[addr + i] = int(tok, 16)
                except ValueError:
                    break
        return bytes(seen[a] for a in range(start, end + 1) if a in seen) \
            if all(a in seen for a in range(start, end + 1)) else b""

    POKE_CHUNK = 32

    def poke(self, addr, data):
        """Write bytes into memory.

        Split into short commands: VICE's monitor truncates an input line at
        about 256 characters, so a single `>` with 256 bytes on it silently
        writes only the first 85 and drops the rest.  That cost a debugging
        session -- a save looked as though the game had corrupted the buffer
        it was writing, when the test harness had never filled it.
        """
        out = ""
        for i in range(0, len(data), self.POKE_CHUNK):
            chunk = data[i:i + self.POKE_CHUNK]
            out += self.cmd(f"> {addr + i:04x} " + " ".join(f"{b:02x}" for b in chunk))
        return out

    def goto(self, addr, seconds=2.0):
        """Start execution at addr and let it run."""
        import time as _t
        self.sock.sendall(f"g {addr:04x}\n".encode())
        _t.sleep(seconds)
        return self.cmd("r", wait=0.5)

    def run(self, seconds=2.0):
        """Resume, run for a while, then pause again."""
        import time as _t
        self.sock.sendall(b"x\n")
        _t.sleep(seconds)
        return self.cmd("r", wait=0.5)

    def pc(self):
        """Current program counter, from the monitor's register dump."""
        import re as _re
        out = self.cmd("r", wait=0.5)
        m = _re.search(r"^\.;([0-9a-fA-F]{4})", out, _re.M)
        return int(m.group(1), 16) if m else None

    def shot(self, path):
        """Take a real screenshot through VICE itself.

        Much better than reading $2000/$0400 by hand: the emulator renders
        exactly what the VIC produces, so raster splits, sprites and any
        mid-frame register changes are all accounted for.  Format 2 = PNG;
        omitting the format silently writes a BMP.
        """
        import os as _os
        path = _os.path.abspath(path)
        if _os.path.exists(path):
            _os.remove(path)
        self.cmd(f'screenshot "{path}" 2', wait=1.0)
        return path if _os.path.exists(path) else None

    # VICE's own palette for the VIC-II ("pepto-pal"), for vic_shot
    VIC_RGB = [(0, 0, 0), (255, 255, 255), (104, 55, 43), (112, 164, 178), (111, 61, 134),
               (88, 141, 67), (53, 40, 121), (184, 199, 111), (111, 79, 37), (67, 57, 0),
               (154, 103, 89), (68, 68, 68), (108, 108, 108), (154, 210, 132),
               (108, 94, 181), (149, 149, 149)]

    def vic_shot(self, path):
        """A PNG of what the VIC-II shows, through the binary monitor's
        display get -- on x128, where shot() gets the VDC's window."""
        import os as _os
        import struct as _st
        import zlib as _z
        if self.bin is None:
            for _ in range(50):
                try:
                    self.bin = socket.create_connection(("127.0.0.1", self.port + 1), timeout=5)
                    break
                except OSError:
                    time.sleep(0.1)
        body = bytes([1, 0])                        # the VIC-II, 8-bit indexed
        self.bin.sendall(bytes([2, 2]) + _st.pack("<II", len(body), 1) + bytes([0x84]) + body)

        def need(n):
            out = b""
            while len(out) < n:
                chunk = self.bin.recv(n - len(out))
                if not chunk:
                    raise RuntimeError("binary monitor closed")
                out += chunk
            return out
        while True:
            head = need(12)
            length, rtype = _st.unpack("<I", head[2:6])[0], head[6]
            data = need(length)
            if rtype == 0x84:
                break
        _fl, dw, dh, xo, yo, iw, ih, _bp, blen = _st.unpack("<IHHHHHHBI", data[:21])
        buf = data[21:21 + blen]
        raw = b"".join(b"\x00" + bytes(c for i in buf[(yo + y) * dw + xo:(yo + y) * dw + xo + iw]
                                        for c in self.VIC_RGB[i & 15])
                       for y in range(ih))
        chunk = lambda t, d: _st.pack(">I", len(d)) + t + d + _st.pack(">I", _z.crc32(t + d) & 0xFFFFFFFF)
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", _st.pack(">IIBBBBB", iw, ih, 8, 2, 0, 0, 0)) + \
            chunk(b"IDAT", _z.compress(raw)) + chunk(b"IEND", b"")
        path = _os.path.abspath(path)
        with open(path, "wb") as fh:
            fh.write(png)
        return path

    def dump(self, path):
        """Save a machine snapshot (needs a VICE build with tapecart support)."""
        import os as _os
        path = _os.path.abspath(path)
        self.cmd(f'dump "{path}"', wait=2.0)
        return path if _os.path.exists(path) else None

    def undump(self, path):
        import os as _os
        return self.cmd(f'undump "{_os.path.abspath(path)}"', wait=2.0)

    def screen(self):
        d = self.mem(0x0400, 0x0400 + 999)
        rows = []
        for r in range(25):
            rows.append(''.join(
                chr(64 + (c & 0x7f)).lower() if 1 <= (c & 0x7f) <= 26
                else (chr(c & 0x7f) if 32 <= (c & 0x7f) < 63 else ' ')
                for c in d[r*40:(r+1)*40]).rstrip())
        return rows

    def keys(self, text):
        """Type into the keyboard buffer.

        The monitor's keybuf takes its text UNQUOTED -- wrapping it in quotes
        types the quote characters too, which silently breaks every keypress.
        Use "\\n" (two characters) for RETURN, as VICE expects.

        Give letters in LOWER case: VICE maps upper case to Shift+key, which
        types graphics characters on a C64 rather than letters.
        """
        return self.cmd("keybuf " + text.replace("\n", "\\n"))

    # The C64's keyboard matrix as VICE's keymatrix command numbers it: row
    # = the $DC00 bit driven low, column = the $DC01 bit read.
    MATRIX = ["\x14\r\x1d\x88\x85\x86\x87\x11", "3wa4zse\x01", "5rd6cftx", "7yg8bhuv",
              "9ij0mkon", "+pl-.:@,", "\x5c*;\x13\x02=^/", "1_\x042 \x05q\x03"]
    # \x01 left shift, \x02 right shift, \x04 CTRL, \x05 C=, \x03 RUN/STOP,
    # \x5c pound, _ left arrow, ^ up arrow, \x88/\x85/\x86/\x87 F7/F1/F3/F5

    def tap(self, key, frames=4, gap=0.4, shift=False):
        """Press a key in the emulated keyboard matrix (VICE's keymatrix
        command, VICE 3.11 or later), hold it for some frames, release it,
        and let the machine run on for gap seconds (a +count is decimal
        frames, the other numbers hex).  Unlike the KERNAL's
        queue this reaches every keyboard scan, a game's own included."""
        key = key.lower() if isinstance(key, str) and key.isalpha() else key
        for row, keys in enumerate(self.MATRIX):
            if key in keys:
                break
        else:
            raise ValueError(f"no key {key!r} in the matrix")
        if shift:
            self.cmd(f"keymatrix 1 7 +{frames + 2}", wait=0.1)
        self.cmd(f"keymatrix {row:x} {keys.index(key):x} +{frames}", wait=0.1)
        return self.run(gap)

    def type(self, text, frames=4, gap=0.4):
        for ch in text:
            self.tap(ch, frames, gap)

    def joystick(self, port, value, frames=None):
        """Port 1/2; value 1/2/4/8 up/down/left/right, $10 fire."""
        self.cmd(f"joystick {port} {value:x}" + (f" +{frames}" if frames else ""), wait=0.1)

    def go(self, seconds=1.0):
        """Resume and let the machine run for a while."""
        self.sock.sendall(b"x\n")
        time.sleep(seconds)
        # re-enter the monitor so the next command is answered
        self.sock.sendall(b"\n")
        return self._drain(0.4)

    def run_to(self, addr, timeout=60):
        """Continue until the CPU reaches addr.  Returns True if it did.

        Needs a VICE build whose remote monitor reports breakpoint hits.
        """
        import time as _t
        self.cmd(f"break {addr:04x}", wait=0.3)
        self.sock.sendall(b"x\n")
        deadline = _t.time() + timeout
        seen = ""
        while _t.time() < deadline:
            seen += self._drain(0.5)
            if "Stop on" in seen or f"C:{addr:04x}" in seen.lower():
                self.cmd("delete", wait=0.2)
                return True
        self.cmd("", wait=0.2)          # pause
        self.cmd("delete", wait=0.2)
        return False

    def u6_journey_onward(self, timeout=90):
        """Ultima 6 from the cart: stop at the init ($1000) once the boot
        program is in, and patch its cold start to Journey Onward ($C025:
        LDA #$00 / BNE $C036 -> BEQ $C054).  The cart's first stage runs at
        $1000 too; a stop there, before the boot program has arrived, is
        passed over -- poking then was lost under the load, and the game
        played its intro (an intermittent failure of every U6 script)."""
        cold = bytes([0xA9, 0x00, 0xD0, 0x0F])
        for _ in range(6):
            if not self.run_to(0x1000, timeout):
                break
            self.cmd("bank ram", wait=0.2)
            if self.mem(0xC023, 0xC026) == cold:
                self.poke(0xC025, bytes([0xF0, (0xC054 - 0xC027) & 0xFF]))
                return True
        raise RuntimeError("U6's boot program never appeared at $C023")

    def u6_save_keys(self, entry, prompt=0x3E6C, tries=4):
        """Ultima 6's save: Shift-S, and Y only once the "SAVE Game ?"
        prompt is waiting for it (a breakpoint on its key loop `prompt`,
        $3E6C).  Typed blind, a Y could come too early or be left in the key
        queue -- the next prompt then took it during the Shift-S, and the save
        ran before its breakpoint was set (seen with the REU, whose read
        cache brings the prompt up at once).  And a Shift-S is not always
        taken as one (the save command wants the modifier state $48 = 1 when
        the key is read; with the party taking turns, the keys go to a
        member): no prompt, so Shift-S again, up to `tries` times.
        Returns False with Y pressed, the machine paused and a breakpoint
        armed on `entry` for the caller to resume to (the save has not begun
        -- the callers' at_start); True if it began without the Y (a queued
        key), stopped at `entry`."""
        self.keys_stop = None                   # a stop that was not the prompt's (a watch)
        for _ in range(tries):
            made = self.cmd(f"break {prompt:04x}", wait=0.2)
            n = re.search(r"BREAK:\s*(\d+)", made)
            out = self.tap("s", frames=10, gap=2.0, shift=True)
            m = re.search(r"^\.;([0-9a-fA-F]{4})", out, re.M)
            # only this breakpoint: a caller's watchpoints stay
            self.cmd(f"delete {n.group(1)}" if n else "delete", wait=0.2)
            if m and int(m.group(1), 16) == prompt:
                # Shift is still held for a few frames: a Y now is Shift-Y,
                # which the prompt does not take.  Let the keys go first --
                # with the save's breakpoint armed, in case a queued key
                # answers meanwhile.
                self.cmd(f"break {entry:04x}", wait=0.1)
                out = self.run(1.0)
                m = re.search(r"^\.;([0-9a-fA-F]{4})", out, re.M)
                if m and int(m.group(1), 16) == entry:
                    return True
                self.cmd("keymatrix 3 1 +4", wait=0.1)                # Y
                return False
            if "Stop on" in out:
                self.keys_stop = out
                return False
            self.run(2.0)
        raise RuntimeError(f"no save prompt after {tries} Shift-S")

    def ef_launch(self, key="j", timeout=30):
        """The EasyFlash build (ef/): at its launcher press J (Journey
        onward, the default) or L (the title), and stop at U6's cold start
        $C00C.  With J the launcher's pokes must be in place there.  The
        launcher offers J only with a saved game; on a world never saved
        (a fresh image: the benches) J falls back to L and the same poke at
        $C00C, which plays the build's own party."""
        self.run(3.0)

        def press(k):
            row = next(r for r, keys in enumerate(self.MATRIX) if k in keys)
            self.cmd(f"keymatrix {row:x} {self.MATRIX[row].index(k):x} +6", wait=0.1)
        press(key)
        if not self.run_to(0xC00C, 5 if key == "j" else timeout):   # (a tap would run past it)
            if key != "j":
                raise RuntimeError("the EF launcher never reached U6's cold start $C00C")
            press("l")
            if not self.run_to(0xC00C, timeout):
                raise RuntimeError("the EF launcher never reached U6's cold start $C00C")
            self.cmd("bank ram", wait=0.2)
            self.poke(0xC025, bytes([0xF0, (0xC054 - 0xC027) & 0xFF]))
        self.cmd("bank ram", wait=0.2)
        if key == "j" and self.mem(0xC025, 0xC025)[0] != 0xF0:
            raise RuntimeError("the EF launcher's Journey onward poke is not at $C025")
        return True

    def ef_launch_u5(self, timeout=30):
        """The EasyFlash build with the tapecart plugged in too: at its
        launcher press 5 (ef/efu5.s) and stop at Ultima V's init stub,
        $0200, the segments read from the tapecart and patched."""
        import time as _t
        self.run(3.0)
        # the breakpoint first: the launch can be past $0200 before a
        # run_to after the key would have set it
        self.cmd("break 0200", wait=0.3)
        row = next(r for r, keys in enumerate(self.MATRIX) if "5" in keys)
        self.cmd(f"keymatrix {row:x} {self.MATRIX[row].index('5'):x} +6", wait=0.1)
        self.sock.sendall(b"x\n")
        seen, deadline = "", _t.time() + timeout
        hit = "(Stop on  exec 0200)"         # (the break command's own reply
        while _t.time() < deadline and hit not in seen:   # says "Stop on" too)
            seen += self._drain(0.5)
        self.cmd("delete", wait=0.2)
        if hit not in seen or self.pc() != 0x0200:
            raise RuntimeError("the EF launcher's 5 never reached Ultima V's init stub $0200")
        return True

    def send_key_at(self, addr, key, timeout=60):
        """Deliver a keypress exactly when the game polls for one.

        The game flushes the keyboard queue all over its attract loop, so a
        key stuffed at a random moment is usually gone before the poll reads
        it.  Breaking at the poll and filling the queue there is reliable.
        $B952 reads $0276,x with x = $C6, so one key means $C6=1, $0277=key.
        """
        if not self.run_to(addr, timeout):
            return False
        self.poke(0x0277, bytes([ord(key) if isinstance(key, str) else key]))
        self.poke(0x00c6, b"\x01")
        return True

    # Ultima 3's key poll: SUBS $4E9C blocks in a loop whose "is a key there?"
    # test is the jsr $B80C at $4EB4.  Breaking there and filling the queue is
    # the only reliable way to deliver input -- the game flushes the keyboard
    # all over its attract and menu loops, so a key stuffed at an arbitrary
    # moment is usually gone before the poll reads it.
    U3_POLL = 0x4EB4

    def press(self, key, timeout=30, settle=2.0):
        """Deliver one keypress to Ultima 3 and let the game react.

        Breaking at the poll and stuffing the queue is not enough on its own:
        resuming with a plain "continue" is racy.  Read the poll's return
        address off the stack first, then run to it -- that proves the caller
        actually consumed our key before we let the game run on.
        """
        import re as _re
        if not self.run_to(self.U3_POLL, timeout):
            return False
        out = self.cmd("r", wait=0.5)
        m = _re.search(r"^\.;([0-9a-f]{4})\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)",
                       out, _re.M)
        if not m:
            return False
        sp = int(m.group(5), 16)
        st = self.mem(0x0100 + sp + 1, 0x0100 + sp + 2)
        ret = ((st[0] | st[1] << 8) + 1) & 0xFFFF
        self.poke(0x0277, bytes([ord(key) if isinstance(key, str) else key]))
        self.poke(0x00c6, b"\x01")
        if not self.run_to(ret, timeout=15):
            return False
        self.run(settle)
        return True

    def brk(self, addr):
        return self.cmd(f"break {addr:04x}")

    def delbreaks(self):
        return self.cmd("delete")

    def quit(self):
        try:
            self.cmd("quit", wait=0.3)
        except Exception:
            pass
        self.kill()

    def kill(self):
        try:
            if self.logfile:
                self.logfile.flush()
                self.logfile.close()
        except Exception:
            pass
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
