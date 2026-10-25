"""Disk images as the scanner reads them: .d64 (35 or 40 tracks, with or
without an error map), .g64 (GCR, decoded here), and zip archives holding
either (one level of nesting).

read(path) -> [(label, data, errmap)]: data is 683 sectors, 174848 bytes;
errmap is 683 codes as a .d64's would be (1 = read fine), or b"" when the
image says nothing about errors.  A .g64's map is made while decoding:
a sector whose header is not found is 2 (DOS error 20), one whose data
block is not found 4 (22), one whose data checksum is wrong 5 (23) --
which is how a copy protection's unreadable track shows up in a .g64.
"""
import io
import os
import re
import zipfile

from ultima.disks.d64 import SECTORS_PER_TRACK, TOTAL_SECTORS, DATA_LENGTH

D64_SIZES = {DATA_LENGTH: (DATA_LENGTH, False),
             DATA_LENGTH + TOTAL_SECTORS: (DATA_LENGTH, True),
             196608: (DATA_LENGTH, False),            # 40 tracks
             196608 + 768: (DATA_LENGTH, True)}       # 40 tracks, error map
EXTENSIONS = (".d64", ".g64", ".zip")

# GCR: the 5-bit code of each nybble, and back
GCR = [0x0A, 0x0B, 0x12, 0x13, 0x0E, 0x0F, 0x16, 0x17,
       0x09, 0x19, 0x1A, 0x1B, 0x0D, 0x1D, 0x1E, 0x15]
UNGCR = {code: n for n, code in enumerate(GCR)}
SYNC = re.compile(r"1{10,}")


def _from_d64(blob):
    length, has_map = D64_SIZES[len(blob)]
    data = blob[:length]
    errmap = blob[len(blob) - (768 if len(blob) > 197000 else TOTAL_SECTORS):][:TOTAL_SECTORS] if has_map else b""
    return data, errmap


def _ungcr(bits, start, nbytes):
    """nbytes bytes from the GCR bit string at bit `start`, or None where a
    5-bit group is not a GCR code."""
    out = bytearray()
    p = start
    for _ in range(nbytes):
        hi = UNGCR.get(int(bits[p:p + 5], 2)) if len(bits) >= p + 5 else None
        lo = UNGCR.get(int(bits[p + 5:p + 10], 2)) if len(bits) >= p + 10 else None
        if hi is None or lo is None:
            return None
        out.append(hi << 4 | lo)
        p += 10
    return bytes(out)


def _track(raw, track):
    """{sector: (status, 256 bytes)} from one track's GCR bytes."""
    bits = "".join(f"{b:08b}" for b in raw)
    bits += bits[:8 * 400]                      # the track is a circle
    found = {}
    pending = None                              # the last header's sector
    for m in SYNC.finditer(bits):
        p = m.end()
        if p >= len(bits) - 80:
            break
        head = _ungcr(bits, p, 1)
        if head == b"\x08":
            h = _ungcr(bits, p, 8)
            pending = None
            if h and h[3] == track and h[1] == h[2] ^ h[3] ^ h[4] ^ h[5] and h[2] < SECTORS_PER_TRACK[track]:
                pending = h[2]
                found.setdefault(pending, (4, bytes(256)))      # header, no data yet
        elif head == b"\x07" and pending is not None:
            d = _ungcr(bits, p, 258)
            if d is not None:
                body, cks = d[1:257], d[257]
                x = 0
                for b in body:
                    x ^= b
                status = 1 if x == cks else 5
                if found[pending][0] != 1:
                    found[pending] = (status, body)
            pending = None
    return found


def _from_g64(blob):
    if blob[:8] != b"GCR-1541":
        raise ValueError("not a G64")
    halftracks = blob[9]
    data = bytearray(DATA_LENGTH)
    errmap = bytearray([1] * TOTAL_SECTORS)
    o = 0
    for track in range(1, 36):
        i = (track - 1) * 2
        n = SECTORS_PER_TRACK[track]
        sectors = {}
        if i < halftracks:
            at = int.from_bytes(blob[0x0C + 4 * i:0x10 + 4 * i], "little")
            if at:
                size = int.from_bytes(blob[at:at + 2], "little")
                sectors = _track(blob[at + 2:at + 2 + size], track)
        for s in range(n):
            status, body = sectors.get(s, (2, bytes(256)))
            data[(o + s) * 256:(o + s + 1) * 256] = body
            errmap[o + s] = status
        o += n
    return bytes(data), bytes(errmap)


def _one(name, blob):
    low = name.lower()
    if low.endswith(".g64") or blob[:8] == b"GCR-1541":
        return [(name, *_from_g64(blob))]
    if len(blob) in D64_SIZES:
        return [(name, *_from_d64(blob))]
    return []


def read(path):
    """Every disk image in `path` (a .d64, a .g64, or a zip of them)."""
    with open(path, "rb") as fh:
        blob = fh.read()
    if zipfile.is_zipfile(io.BytesIO(blob)):
        return _from_zip(os.path.basename(path), blob, nested=True)
    return _one(os.path.basename(path), blob)


def _from_zip(label, blob, nested):
    out = []
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            member = z.read(info)
            name = f"{label}:{info.filename}"
            if nested and zipfile.is_zipfile(io.BytesIO(member)):
                out += _from_zip(name, member, nested=False)
            elif info.filename.lower().endswith((".d64", ".g64")) or len(member) in D64_SIZES:
                out += _one(name, member)
    return out
