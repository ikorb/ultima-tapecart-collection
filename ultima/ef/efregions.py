"""The EasyFlash cart's flash map: one place, pinned by tests/test_ef.py.

Linear addresses are 24 bits in EAPI's "lhlh" order (efvars.inc): bank n's
ROML is n * $4000, its ROMH n * $4000 + $2000, so a linear address shows at
$8000 | (addr & $3FFF) in bank addr >> 14 with the cart in 16K mode.

  bank 0     the start code at $8000, the launcher (efpage.s) from $8100 into
             ROMH; EAPI at ROMH $1800 (00:1:1800, where EasyProg puts the right
             one for the cart), the cart's name at $1B00, the Ultimax reset
             stub and the vectors in $1B18-$1FFF
  bank 1     the in-game driver (ROML) and the static directory (ROMH)
  bank 2     the boot driver (ROML) and the static directory again (ROMH)
  banks 3-   the game's data, up to the log
  48-63      THE WRITE LOG: two halves of 128 KiB, each one ROML and one
             ROMH 64 KiB sector (banks 48-55, 56-63).  Not in the CRT, so a
             new build flashed over an old one keeps the saves; the boot
             tells a half that holds something else by its top slot.

A save moved is a save lost: LOG_LO/LOG_MID/LOG_HI never move.
"""
FLASH_SIZE = 1 << 20
BANK = 0x4000
CHIP = 0x2000


def lin(bank, chip=0, off=0):
    return bank * BANK + chip * CHIP + off


def bank_of(addr):
    return addr >> 14


def cpu_of(addr):
    """Where a linear address shows with the cart in 16K mode."""
    return 0x8000 | (addr & 0x3FFF)


START_BANK = 0
GAME_DRV_BANK = 1
BOOT_DRV_BANK = 2
EAPI_LIN = lin(0, 1, 0x1800)
EAPI_SIZE = 0x300
NAME_LIN = lin(0, 1, 0x1B00)
STUB_LIN = lin(0, 1, 0x1B18)
STUB_CPU = 0xFB18                   # the same bytes in Ultimax mode
LAUNCH_LIN = lin(0, 0, 0x0100)      # the launcher's image, after the start code:
LAUNCH_MAX = EAPI_LIN - LAUNCH_LIN  # ROML and ROMH, $8100-$B7FF (efstart.s)
SDIR_CPU = 0xA000                   # in each driver bank's ROMH
SDIR_MAX = CHIP

DATA_LO = lin(3)
LOG_LO = lin(48)
LOG_MID = lin(56)
LOG_HI = lin(64)
LOG_BANKS = range(48, 64)

# EAPI's slot, by context: three pages of RAM it may borrow while a write
# runs, and the flash it is put back from afterwards (see efres.s, efboot.s)
GAME_SLOT = 0x6200                  # TILES' tiles 16-39
BOOT_SLOT = 0x5800                  # CREATE, untouched in creation's memmap
