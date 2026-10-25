"""Exomizer `raw` decrunching, forward, protocol flags 0 (`exomizer raw -d -P0`).

A Python port of dec_ctx_decrunch() and its helpers in exomizer's src/exodec.c
(copyright (c) 2002 - 2005 Magnus Lind, zlib licence: this is an altered,
reduced version -- one protocol, no LOG, no tables dump; see NOTICE.md).
The collection crunches with zx02; this is only for reading Ultima III
Gold's disk, whose data files are crunched this way
(docs/reversing-notes/u3-gold.md), on the host and without the exomizer
binary.
"""


def exo_raw(data):
    """Decrunch one stream.  Raises ValueError when `data` is not one (it
    runs off its end), which is how a file stored raw shows up."""
    pos = 0
    bitbuf = 0

    def byte():
        nonlocal pos
        if pos >= len(data):
            raise ValueError("not an exomizer raw stream: ran off its end")
        c = data[pos]
        pos += 1
        return c

    def bits(n):
        nonlocal bitbuf
        val = 0
        for _ in range(n):
            carry = bitbuf & 1                  # ror: bits come out low first
            bitbuf >>= 1
            if bitbuf == 0:
                bitbuf = byte()
                carry = bitbuf & 1
                bitbuf = (bitbuf >> 1) | 0x80
            val = val << 1 | carry
        return val

    bitbuf = byte()
    # the 52-entry table of bases and bit counts the stream starts with
    lo, bi = [0] * 52, [0] * 52
    a = b = 0
    for i in range(52):
        a = a + (1 << b) if i & 15 else 1
        lo[i] = a
        b = bits(4)
        bi[i] = b
    off, obits = (48, 32, 16), (2, 4, 4)

    def cooked(i):
        return lo[i] + bits(bi[i])

    out = bytearray()
    while True:
        if bits(1):                             # one literal byte
            out.append(byte())
            continue
        g = 0
        while bits(1) == 0:
            g += 1
            if g > 17:
                raise ValueError("not an exomizer raw stream: bad gamma code")
        if g == 16:                             # the end
            return bytes(out)
        if g == 17:                             # a run of literals
            n = bits(16)
            out += bytes(byte() for _ in range(n))
            continue
        length = cooked(g)
        i = min(length, 3) - 1
        offset = cooked(off[i] + bits(obits[i]))
        src = len(out) - offset
        if src < 0:
            raise ValueError("not an exomizer raw stream: offset before the start")
        for _ in range(length):
            out.append(out[src])
            src += 1
