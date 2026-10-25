"""Write an EasyFlash .crt (CRT format: a 64-byte header, then a CHIP packet
per 8 KiB that holds anything: ROML at $8000, ROMH at $A000).

    python -m ultima.ef.efcrt keep-log OLD.crt NEW.crt OUT.crt

OUT is NEW with OLD's write log (banks 48-63): for a cart that runs .crt files
straight from its card and writes the flash back into them, where a new build
would otherwise start without the saves.  OLD must be a .crt the cart has
written back (one with the log in it).
"""
import struct
import sys

TYPE_EASYFLASH = 32


def write(path, flash, name, skip_banks=(), keep_empty=False):
    """flash: 1 MiB in lhlh order (efregions.py).  Banks in skip_banks are
    left out, and so is any chip that is all $FF unless keep_empty."""
    assert len(flash) == 1 << 20
    out = bytearray(b"C64 CARTRIDGE   ")
    out += struct.pack(">IHH", 0x40, 0x0100, TYPE_EASYFLASH)
    out += bytes([1, 0])                    # EXROM inactive, GAME active: Ultimax at reset
    out += bytes(6)
    out += name.encode("ascii")[:32].ljust(32, b"\x00")
    assert len(out) == 0x40
    chips = 0
    for bank in range(64):
        if bank in skip_banks:
            continue
        for chip, load in ((0, 0x8000), (1, 0xA000)):
            off = bank * 0x4000 + chip * 0x2000
            data = flash[off:off + 0x2000]
            if not keep_empty and data == b"\xff" * 0x2000:
                continue
            out += b"CHIP" + struct.pack(">IHHHH", 0x10 + 0x2000, 2, bank, load, 0x2000) + data
            chips += 1
    with open(path, "wb") as fh:
        fh.write(out)
    return chips


def read(path):
    """The flash image a .crt describes (absent chips $FF), and its name."""
    with open(path, "rb") as fh:
        data = fh.read()
    assert data[:16] == b"C64 CARTRIDGE   "
    hlen = struct.unpack(">I", data[16:20])[0]
    assert struct.unpack(">H", data[22:24])[0] == TYPE_EASYFLASH
    name = data[32:64].rstrip(b"\x00").decode("ascii")
    flash = bytearray(b"\xff" * (1 << 20))
    p = hlen
    while p < len(data):
        assert data[p:p + 4] == b"CHIP"
        plen, _ty, bank, load, size = struct.unpack(">IHHHH", data[p + 4:p + 16])
        chip = 0 if load == 0x8000 else 1
        off = bank * 0x4000 + chip * 0x2000
        flash[off:off + size] = data[p + 16:p + 16 + size]
        p += plen
    return flash, name


def keep_log(old, new, out):
    from ultima.ef import efregions as R
    o, _n = read(old)
    f, name = read(new)
    if o[R.LOG_LO:R.LOG_HI] == b"\xff" * (R.LOG_HI - R.LOG_LO):
        raise SystemExit(f"{old} holds no log: nothing to keep")
    f[R.LOG_LO:R.LOG_HI] = o[R.LOG_LO:R.LOG_HI]
    chips = write(out, f, name)
    print(f"{out}: {new} with the log of {old} ({chips} chips)")


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "keep-log":
        keep_log(*sys.argv[2:])
    else:
        raise SystemExit(__doc__)
