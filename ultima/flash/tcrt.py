#!/usr/bin/env python3
"""TCRT v1 container reader/writer.

Format per the tapecart project's doc/TCRT Format.md.  Offsets are fixed:

      0  16b  signature "tapecartImage\\r\\n\\x1a"
     16   u16 version (1)
     18   u16 data address   \\
     20   u16 data length     | fastload-mode LOADINFO
     22   u16 call address    |
     24  16b  file name      /
     40   u8  misc flags     bit0 = custom loader present, bit1 = data block offset ok
     41 171b  initial loader (zero-filled when bit0 is clear)
    212   u32 flash content length
    216    n  flash content

Note the LOADINFO data address and length are 16-bit: whatever the initial
loader fastloads must live in the first 64 KiB of flash and be < 64 KiB long.
"""
import struct

SIGNATURE = b"tapecartImage\r\n\x1a"
VERSION = 1
HEADER_LEN = 216
LOADER_LEN = 171
FILENAME_LEN = 16
FLASH_SIZE = 2 * 1024 * 1024

FLAG_CUSTOM_LOADER = 0x01
FLAG_DATA_OFFSET = 0x02


class TCRT:
    def __init__(self, data_address=0, data_length=0, call_address=0,
                 filename="", flags=0, loader=None, flash=b""):
        self.data_address = data_address
        self.data_length = data_length
        self.call_address = call_address
        self.filename = filename
        self.flags = flags
        self.loader = loader or b"\x00" * LOADER_LEN
        self.flash = flash

    # -- validation ------------------------------------------------------

    def check(self):
        """Raise ValueError if this image would be rejected by the flash tool."""
        if len(self.loader) != LOADER_LEN:
            raise ValueError(f"loader is {len(self.loader)} bytes, must be {LOADER_LEN}")
        if len(self.flash) > FLASH_SIZE:
            raise ValueError(f"flash content {len(self.flash)} exceeds {FLASH_SIZE}")
        if len(self.filename.encode("latin1")) > FILENAME_LEN:
            raise ValueError(f"file name {self.filename!r} longer than {FILENAME_LEN}")
        for name, value in (("data_address", self.data_address),
                            ("data_length", self.data_length),
                            ("call_address", self.call_address)):
            if not 0 <= value <= 0xFFFF:
                raise ValueError(f"{name} {value:#x} does not fit in 16 bits")
        if self.flags & FLAG_CUSTOM_LOADER and self.flags & FLAG_DATA_OFFSET:
            raise ValueError("a custom loader may not also claim data block offset support")
        if not self.flags & FLAG_CUSTOM_LOADER and self.loader != b"\x00" * LOADER_LEN:
            raise ValueError("loader bytes must be zero when the custom-loader flag is clear")
        end = self.data_address + self.data_length
        if end > len(self.flash):
            raise ValueError(
                f"fastload block {self.data_address:#x}+{self.data_length} "
                f"runs past the {len(self.flash)}-byte flash content")

    # -- serialisation ---------------------------------------------------

    def pack(self, trim=True):
        self.check()
        flash = self.flash
        if trim:
            flash = flash.rstrip(b"\xff")
        name = self.filename.encode("latin1").ljust(FILENAME_LEN, b"\x00")
        header = (SIGNATURE
                  + struct.pack("<HHHH", VERSION, self.data_address,
                                self.data_length, self.call_address)
                  + name
                  + bytes([self.flags])
                  + self.loader
                  + struct.pack("<I", len(flash)))
        assert len(header) == HEADER_LEN, len(header)
        return header + flash

    def write(self, path, trim=True):
        with open(path, "wb") as fh:
            fh.write(self.pack(trim))

    @classmethod
    def parse(cls, blob):
        if blob[:16] != SIGNATURE:
            raise ValueError("not a TCRT image (bad signature)")
        version, data_address, data_length, call_address = struct.unpack_from("<HHHH", blob, 16)
        if version != VERSION:
            raise ValueError(f"TCRT version {version}, expected {VERSION}")
        name = blob[24:24 + FILENAME_LEN].split(b"\x00")[0].decode("latin1")
        flags = blob[40]
        loader = blob[41:41 + LOADER_LEN]
        (flash_len,) = struct.unpack_from("<I", blob, 212)
        flash = blob[HEADER_LEN:HEADER_LEN + flash_len]
        if len(flash) != flash_len:
            raise ValueError(f"truncated: header claims {flash_len} flash bytes, "
                             f"file holds {len(flash)}")
        if not flags & FLAG_CUSTOM_LOADER:
            loader = b"\x00" * LOADER_LEN
        return cls(data_address, data_length, call_address, name, flags, loader, flash)

    @classmethod
    def read(cls, path):
        with open(path, "rb") as fh:
            return cls.parse(fh.read())

    def __eq__(self, other):
        if not isinstance(other, TCRT):
            return NotImplemented
        return (self.data_address == other.data_address
                and self.data_length == other.data_length
                and self.call_address == other.call_address
                and self.filename == other.filename
                and self.flags == other.flags
                and self.loader == other.loader
                and self.flash.rstrip(b"\xff") == other.flash.rstrip(b"\xff"))

    def __repr__(self):
        return (f"TCRT(name={self.filename!r}, data={self.data_address:#06x}"
                f"+{self.data_length}, call={self.call_address:#06x}, "
                f"flags={self.flags:#04x}, flash={len(self.flash)})")
