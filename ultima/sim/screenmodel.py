"""The C64 screen editor, as far as the launcher's page uses it, for the
host tests: CHROUT's CR, clear and printable characters, PLOT ($FFF0), the
cursor row and column in $D6/$D3, scrolling.  The page reads $D6 and calls
PLOT, so every harness that runs it traps both (tests/test_page.py,
fakedrive.py)."""


def petscii(b):
    """A screen character as the launcher's lower-case set shows it."""
    return (chr(b + 0x20) if 0x41 <= b <= 0x5A else chr(b - 0x80) if 0xC1 <= b <= 0xDA else
            chr(b) if 0x20 <= b < 0x7F else "?")


class Screen:
    """The screen editor as far as the page uses it: 25 rows of 40, CHROUT's
    CR, clear and printable characters, PLOT, and scrolling.  It keeps the
    cursor row in $D6 (TBLX) and column in $D3 (PNTR) as the KERNAL does.
    `scrolls` counts lines pushed off the top, `wraps` lines printed into
    their 40th column (which the KERNAL links to the next row)."""
    ROWS, COLS = 25, 40

    def __init__(self, mem=None):
        self.mem = mem
        self.clear()
        self.scrolls = self.wraps = 0

    def clear(self):
        self.cells = [[" "] * self.COLS for _ in range(self.ROWS)]
        self.row = self.col = 0

    def _down(self):
        if self.row == self.ROWS - 1:
            self.cells.pop(0)
            self.cells.append([" "] * self.COLS)
            self.scrolls += 1
        else:
            self.row += 1

    def put(self, b):
        if b == 0x93:
            self.clear()
        elif b in (13, 0x8D):
            self.col = 0
            self._down()
        elif 0x20 <= b < 0x80 or 0xA0 <= b:
            self.cells[self.row][self.col] = petscii(b)
            self.col += 1
            if self.col == self.COLS:
                self.wraps += 1
                self.col = 0
                self._down()
        self.sync()

    def plot(self, s):
        if s.mpu.p & 1:
            s.mpu.x, s.mpu.y = self.row, self.col
        else:
            assert s.mpu.x < self.ROWS and s.mpu.y < self.COLS, (s.mpu.x, s.mpu.y)
            self.row, self.col = s.mpu.x, s.mpu.y
            self.sync()

    def sync(self):
        if self.mem is not None:
            self.mem[0xD6], self.mem[0xD3] = self.row, self.col

    def lines(self):
        return ["".join(r).rstrip() for r in self.cells]

    def text(self):
        return "\n".join(self.lines()).rstrip()
