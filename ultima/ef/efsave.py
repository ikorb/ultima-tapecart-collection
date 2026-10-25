"""Ultima VI's launcher save file (docs/save-format.md, "UCSV", game 6) to and
from the EasyFlash cart's write log, on the host: what the EF launcher's
import and export will do on the C64, for tests and benchmarks.

    efsave.import_file(flash, data)     the world in the file, as log half 0
"""


from ultima.ef import efregions as R               # noqa: E402
from ultima.launcher import u6log                        # noqa: E402


def records(data):
    """[(kind, name or sector, payload)] from a UCSV file, checked."""
    assert data[:4] == b"UCSV" and data[4] == 6 and data[5] == 1, "not an Ultima VI save file"
    s1 = s2 = 0
    for b in data[:-2]:
        s1 = (s1 + b) & 255
        s2 = (s2 + s1) & 255
    assert bytes([s1, s2]) == data[-2:], "check bytes"
    p, out = 6, []
    while True:
        kind = data[p]
        p += 1
        if kind == 0:
            break
        if kind == 1:
            name, n = data[p:p + 3], data[p + 3]
            assert 1 <= n <= 20
            out.append((1, name, data[p + 4:p + 4 + 256 * n]))
            p += 4 + 256 * n
        elif kind == 2:
            out.append((2, data[p], data[p + 1:p + 257]))
            p += 257
        else:
            raise ValueError(f"record kind {kind}")
    assert p == len(data) - 2
    return out


def import_file(flash, data):
    """Erase the log, then write the file's world into half 0, under a header
    of generation 1, as the game's
    driver would have: each chunk file one entry of its pages, links and all
    (F_LINKS), each save-area sector one entry."""
    flash[R.LOG_LO:R.LOG_HI] = b"\xff" * (R.LOG_HI - R.LOG_LO)
    log = u6log.Log(flash, R.LOG_LO, R.LOG_MID)
    log.header(1)                   # (efinit.s: only a header makes a half valid)
    for kind, what, payload in records(data):
        if kind == 1:
            pages = [payload[i:i + 256] for i in range(0, len(payload), 256)]
            log.append(b"/" + what, pages, True)
        else:
            log.append(bytes([1, 0, 6, what]), [payload], False)
    return log
