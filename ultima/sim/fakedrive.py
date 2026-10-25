#!/usr/bin/env python3
"""A 1541 behind the KERNAL's I/O calls, for the page's export and import on
the host (tests/test_xfer.py).

Traps SETLFS, SETNAM, OPEN, CLOSE, CHKIN, CHKOUT, CLRCHN, CHRIN, CHROUT and
READST on a sim6502.Sim, and answers them from a .d64 image in memory the
way CBM DOS does for what the page uses: the command channel (15) with its
error messages, "U1"/"U2" block read and write and "B-P" on a "#" buffer
channel, "S0:" scratch, and PRG and SEQ files opened by name with ",P,R" /
",P,W" / ",S,R" / ",S,W" (reading one as the other type: 64, FILE TYPE
MISMATCH).
CHROUT with no output channel is the screen, collected in `screen`.

Files are written the way DOS writes them: a free sector from the BAM for
each block, the chain linked, a directory entry in the first free slot.  It
is not a DOS: no directory growth, one drive, one disk at a time
(swap() puts another in).
"""
from ultima.disks.d64 import D64, SECTORS_PER_TRACK
from ultima.sim.screenmodel import Screen

SETLFS, SETNAM, OPEN, CLOSE = 0xFFBA, 0xFFBD, 0xFFC0, 0xFFC3
CHKIN, CHKOUT, CLRCHN, CHRIN, CHROUT, READST = 0xFFC6, 0xFFC9, 0xFFCC, 0xFFCF, 0xFFD2, 0xFFB7


class Disk:
    """A .d64 in memory: sectors, the BAM, the directory."""

    def __init__(self, data):
        self.data = bytearray(data)

    def sector(self, t, s):
        o = D64.offset(t, s)
        return self.data[o:o + 256]

    def put(self, t, s, blk):
        o = D64.offset(t, s)
        self.data[o:o + 256] = blk

    def free(self, t, s, flag):
        bam = self.sector(18, 0)
        e = 4 * t
        byte, bit = 1 + s // 8, 1 << (s % 8)
        was = bool(bam[e + byte] & bit)
        if flag and not was:
            bam[e + byte] |= bit
            bam[e] += 1
        elif not flag and was:
            bam[e + byte] &= ~bit
            bam[e] -= 1
        self.put(18, 0, bam)

    def is_free(self, t, s):
        return bool(self.sector(18, 0)[4 * t + 1 + s // 8] & (1 << (s % 8)))

    def alloc(self):
        for t in list(range(17, 0, -1)) + list(range(19, 36)):
            for s in range(SECTORS_PER_TRACK[t]):
                if self.is_free(t, s):
                    self.free(t, s, False)
                    return t, s
        raise IOError("72,DISK FULL")

    def entries(self):
        t, s = 18, 1
        while t:
            blk = self.sector(t, s)
            for i in range(8):
                yield (t, s, i * 32, blk[i * 32:(i + 1) * 32])
            t, s = blk[0], blk[1]

    def find(self, name):
        for t, s, o, e in self.entries():
            if e[2] & 0x07 and bytes(e[5:21]).rstrip(b"\xa0") == name:
                return t, s, o, e
        return None

    def read_file(self, name):
        hit = self.find(name)
        if hit is None:
            return None
        e = hit[3]
        t, s, out = e[3], e[4], bytearray()
        while t:
            blk = self.sector(t, s)
            out += blk[2:] if blk[0] else blk[2:blk[1] + 1]
            t, s = blk[0], blk[1]
        return bytes(out)

    def scratch(self, name):
        hit = self.find(name)
        if hit is None:
            return 0
        dt, ds, o, e = hit
        t, s = e[3], e[4]
        while t:
            blk = self.sector(t, s)
            self.free(t, s, True)
            t, s = blk[0], blk[1]
        d = self.sector(dt, ds)
        d[o + 2] = 0
        self.put(dt, ds, d)
        return 1

    def file_type(self, name):
        hit = self.find(name)
        return hit[3][2] & 0x07 if hit else None

    def write_file(self, name, data, ftype=0x82):
        chunks = [data[i:i + 254] for i in range(0, len(data), 254)] or [b""]
        secs = [self.alloc() for _ in chunks]
        for i, (t, s) in enumerate(secs):
            if i + 1 < len(secs):
                link = bytes(secs[i + 1])
            else:
                link = bytes([0, len(chunks[i]) + 1])
            self.put(t, s, (link + chunks[i]).ljust(256, b"\x00"))
        for dt, ds, o, e in self.entries():
            if not e[2] & 0x07:
                d = self.sector(dt, ds)
                ent = bytes([ftype]) + bytes(secs[0]) + name.ljust(16, b"\xa0") + bytes(9) + \
                    bytes([len(secs) & 0xFF, len(secs) >> 8])
                d[o + 2:o + 32] = ent
                self.put(dt, ds, d)
                return
        raise IOError("72,DISK FULL")


class FakeDrive:
    def __init__(self, sim, disk=None, device=8):
        self.sim, self.device = sim, device
        self.disk = Disk(disk) if disk is not None else None
        self.files = {}                     # lfn -> channel dict
        self.lfs = (0, 0, 0)
        self.name = b""
        self.inp = self.out = None
        self.st = 0
        self.status = "73,CBM DOS V2.6 1541,00,00"
        self.screen = bytearray()
        self.scr = Screen(sim.mem)
        sim.traps[0xFFF0] = self.scr.plot
        self.log = []
        for addr, fn in ((SETLFS, self.setlfs), (SETNAM, self.setnam), (OPEN, self.open),
                         (CLOSE, self.close), (CHKIN, self.chkin), (CHKOUT, self.chkout),
                         (CLRCHN, self.clrchn), (CHRIN, self.chrin), (CHROUT, self.chrout),
                         (READST, self.readst)):
            sim.traps[addr] = fn

    def swap(self, disk):
        """Another disk in the drive -- which must have no channel open: a
        real drive with one open may keep the old disk's BAM."""
        if self.files:
            raise AssertionError(f"disk swapped with channels open: {sorted(self.files)}")
        self.disk = Disk(disk) if disk is not None else None

    # -- the KERNAL calls --------------------------------------------------
    def setlfs(self, s):
        self.lfs = (s.mpu.a, s.mpu.x, s.mpu.y)

    def setnam(self, s):
        a = s.mpu.x | s.mpu.y << 8
        self.name = bytes(s.mem[a:a + s.mpu.a])

    def carry(self, set_):
        self.sim.mpu.p = (self.sim.mpu.p & ~1) | (1 if set_ else 0)

    def open(self, s):
        lfn, dev, sa = self.lfs
        if lfn in self.files:               # the KERNAL: FILE OPEN, nothing done
            s.mpu.a = 2
            self.carry(True)
            return
        if dev != self.device or self.disk is None:
            self.st = 0x80
            self.carry(False)               # serial OPEN: the error shows in ST
            self.files[lfn] = dict(sa=sa, kind="none", absent=True)
            return
        ch = dict(sa=sa, kind="none", buf=bytearray(256), pos=0)
        if sa == 15:
            ch["kind"] = "cmd"
            ch["cmd"] = bytearray()
            if self.name:
                self.command(self.name)
        elif self.name == b"#":
            ch["kind"] = "buf"
            self.status = "00, OK,00,00"
        else:
            name, *opts = self.name.split(b",")
            mode = opts[1] if len(opts) > 1 else b"R"
            ftype = {b"S": 1, b"P": 2}.get(opts[0] if opts else b"P", 2)
            if mode == b"W":
                if self.disk.find(name) is not None:
                    self.status = "63,FILE EXISTS,00,00"
                else:
                    ch.update(kind="write", name=name, data=bytearray(), ftype=0x80 | ftype)
                    self.status = "00, OK,00,00"
            else:
                data = self.disk.read_file(name)
                if data is None:
                    self.status = "62,FILE NOT FOUND,00,00"
                    ch["kind"] = "none"
                elif opts and self.disk.file_type(name) != ftype:
                    self.status = "64,FILE TYPE MISMATCH,00,00"
                    ch["kind"] = "none"
                else:
                    ch.update(kind="read", data=bytearray(data), pos=0)
                    self.status = "00, OK,00,00"
        self.files[lfn] = ch
        self.log.append(("open", lfn, sa, self.name))
        self.carry(False)

    def close(self, s):
        ch = self.files.pop(s.mpu.a, None)
        if ch and ch["kind"] == "write":
            try:
                self.disk.write_file(ch["name"], bytes(ch["data"]), ch["ftype"])
                self.status = "00, OK,00,00"
            except IOError as e:
                self.status = str(e) + ",00,00"
            self.log.append(("save", ch["name"], len(ch["data"])))
        self.carry(False)

    # With no device the KERNAL's CHKIN/CHKOUT fail: TALK/LISTEN leave ST
    # $80, they return carry set with A = 5 (DEVICE NOT PRESENT), and the
    # input/output stays what it was -- the keyboard and the screen, where
    # CHROUT then prints (on hardware, the page's "i0" came out that way).
    def absent(self, lfn):
        ch = self.files.get(lfn)
        return self.disk is None or (ch is not None and ch.get("absent"))

    def chkin(self, s):
        if self.absent(s.mpu.x):
            self.st = 0x80
            s.mpu.a = 5
            self.carry(True)
            return
        self.inp = self.files.get(s.mpu.x)
        self.st = 0
        self.carry(False)

    def chkout(self, s):
        if self.absent(s.mpu.x):
            self.st = 0x80
            s.mpu.a = 5
            self.carry(True)
            return
        self.out = self.files.get(s.mpu.x)
        self.st = 0
        self.carry(False)

    def clrchn(self, s):
        if self.out and self.out["kind"] == "cmd" and self.out["cmd"]:
            self.command(bytes(self.out["cmd"]))
            self.out["cmd"] = bytearray()
        self.inp = self.out = None

    def chrin(self, s):
        ch = self.inp
        a = 13
        if ch is None:
            # the keyboard: the screen editor would wait for a line
            raise AssertionError("CHRIN with no input channel: the page waits for a line typed")
        if self.disk is None:
            self.st = 0x80 | 0x02
        elif ch["sa"] == 15:
            msg = self.status.encode() + b"\r"
            p = ch.setdefault("spos", 0)
            a = msg[p]
            ch["spos"] = p + 1
            if a == 13:
                ch["spos"] = 0
                self.status = "00, OK,00,00"
                self.st = 0x40
        elif ch["kind"] == "buf":
            a = ch["buf"][ch["pos"]]
            ch["pos"] = (ch["pos"] + 1) & 0xFF
        elif ch["kind"] == "read":
            d = ch["data"]
            if ch["pos"] < len(d):
                a = d[ch["pos"]]
                ch["pos"] += 1
                self.st = 0x40 if ch["pos"] == len(d) else 0
            else:
                self.st = 0x42
        s.mpu.a = a
        self.carry(False)

    def chrout(self, s):
        ch = self.out
        a = s.mpu.a
        if ch is None:
            self.screen.append(a)
            self.scr.put(a)
        elif ch["kind"] == "cmd":
            ch["cmd"].append(a)
        elif ch["kind"] == "buf":
            ch["buf"][ch["pos"]] = a
            ch["pos"] = (ch["pos"] + 1) & 0xFF
        elif ch["kind"] == "write":
            ch["data"].append(a)
        self.carry(False)

    def readst(self, s):
        s.mpu.a = self.st
        s.mpu.p = (s.mpu.p & ~0x82) | (0x80 if self.st & 0x80 else 0) | (0 if self.st else 0x02)

    # -- DOS commands --------------------------------------------------------
    def buffer(self):
        return next((c for c in self.files.values() if c["kind"] == "buf"), None)

    def command(self, cmd):
        cmd = cmd.rstrip(b"\r")
        self.log.append(("cmd", cmd))
        try:
            if cmd[:2] in (b"U1", b"U2"):
                _ch, _dr, t, sec = (int(x) for x in cmd[3:].split())
                if not 1 <= t <= 35 or not 0 <= sec < SECTORS_PER_TRACK[t]:
                    self.status = f"66,ILLEGAL TRACK OR SECTOR,{t:02},{sec:02}"
                    return
                buf = self.buffer()
                if cmd[:2] == b"U1":
                    buf["buf"][:] = self.disk.sector(t, sec)
                    buf["pos"] = 0
                else:
                    self.disk.put(t, sec, bytes(buf["buf"]))
                self.status = "00, OK,00,00"
            elif cmd.startswith(b"B-P"):
                _ch, pos = (int(x) for x in cmd[4:].split())
                self.buffer()["pos"] = pos
                self.status = "00, OK,00,00"
            elif cmd in (b"I0", b"I"):
                # as a 1541: not with a buffer channel taken
                self.status = ("70,NO CHANNEL,00,00" if self.buffer() else "00, OK,00,00")
            elif cmd.startswith(b"S0:") or cmd.startswith(b"S:"):
                n = self.disk.scratch(cmd.split(b":", 1)[1])
                self.status = f"01, FILES SCRATCHED,{n:02},00"
            else:
                self.status = "31,SYNTAX ERROR,00,00"
        except IOError as e:
            self.status = str(e) + ",00,00"
