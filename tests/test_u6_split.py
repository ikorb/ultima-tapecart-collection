"""Ultima VI's text-box raster split in the opening, the intro and the ending
(ultima/games/u6/build.py steady_split), as the cart stores them: the switch
routine run in py65 against a raster that follows the cycle count -- 63
cycles a line for PAL, 65 for NTSC -- entered at every delay from the
interrupt's line onward.  The three stores ($D011, $D018, $DD00) must all
fall between the last visible column of the line before the box's first
character row and cycle 12 of that row, where the VIC takes the bus.

Skipped without py65 (the repository's .venv has it)."""
import unittest

try:
    from py65.devices.mpu6502 import MPU
    from py65.memory import ObservableMemory
except ImportError:
    MPU = None

from tests import test_u6_compendium as tc
from ultima import paths

u6 = tc.u6
FIRST, LAST = 57, 12        # the first store after this cycle; the last before the row's 12th


def switch_routine(data, name):
    """(address, bytes) of the stored switch routine, and its table."""
    var, table = u6.SPLIT_FILES[name]
    for y in u6.SPLIT_Y:
        i = data.find(y + bytes([0xAE, var & 0xFF, var >> 8]))
        if i >= 0:
            return 0x0200 + i - 2, var, table
    raise AssertionError(f"{name}: no steady switch routine")


class TestU6Split(unittest.TestCase):
    setUpClass = classmethod(tc.TestCompendium.setUpClass.__func__)
    stored = tc.TestCompendium.stored

    def overlay(self, name):
        return bytes(self.stored(name))

    def test_the_tables_are_a_line_earlier(self):
        d = tc.D64(paths.disk("u6-3b"))
        orig = {n: d.file(n)[0] for n in u6.SPLIT_FILES}
        for name, (var, table) in u6.SPLIT_FILES.items():
            with self.subTest(name=name):
                got = self.overlay(name)
                o = table - 0x0200 + 2
                self.assertEqual(bytes(got[o:o + 8]), bytes(b - 1 for b in orig[name][o:o + 8]))

    def run_switch(self, data, name, entry_delay, line_cycles, flags=0):
        """Enter the routine `entry_delay` cycles after the start of the IRQ's
        line; return [(line offset, cycle in line) of each store]."""
        addr, var, table = switch_routine(data, name)
        irq_line = 0xD0                                 # any of the table's lines
        mem = ObservableMemory()
        for i, b in enumerate(data[2:]):
            mem[0x0200 + i] = b
        mem[var] = irq_line
        mem[0x10] = flags
        mpu = MPU(memory=mem)
        now = [0]
        mem.subscribe_to_read([0xD012], lambda a: (irq_line + (now[0] + 3) // line_cycles) & 0xFF)
        mem.subscribe_to_read([0xDD00], lambda a: 0x97)
        stores = []
        for reg in (0xD011, 0xD018, 0xDD00):
            mem.subscribe_to_write([reg], lambda a, v, reg=reg: stores.append((reg, now[0] + 3)))
        mpu.sp = 0xFD
        mem[0x1FF], mem[0x1FE] = 0xFF, 0xEF             # return to $FFF0
        mpu.pc = addr
        cycles = entry_delay
        while mpu.pc != 0xFFF0:
            now[0] = cycles
            before = mpu.processorCycles
            mpu.step()
            cycles += mpu.processorCycles - before
        self.assertEqual([r for r, _c in stores], [0xD011, 0xD018, 0xDD00])
        return [divmod(c, line_cycles) for _r, c in stores]

    @unittest.skipIf(MPU is None, "py65 is not installed (use the repository's .venv)")
    def test_the_stores_land_in_the_border(self):
        """Entered anywhere from the IRQ's line to 20 cycles into the line
        after it (the handlers reach the routine 40-70 cycles in), on PAL and
        NTSC: every store between cycle FIRST of the line before the row
        (the IRQ's line + 2) and cycle LAST of the row (+3)."""
        for name in u6.SPLIT_FILES:
            data = self.overlay(name)
            for line_cycles in (63, 65):
                for delay in range(0, line_cycles + 20):
                    with self.subTest(name=name, line=line_cycles, delay=delay):
                        stores = self.run_switch(data, name, delay, line_cycles)
                        at = [l * line_cycles + c for l, c in stores]
                        self.assertGreaterEqual(at[0], 2 * line_cycles + FIRST, stores)
                        self.assertLessEqual(at[-1], 3 * line_cycles + LAST - 2, stores)


if __name__ == "__main__":
    unittest.main()
