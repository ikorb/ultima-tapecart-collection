;;; u6.inc -- what Ultima 6's drivers and build.py agree on.

KEYLEN   = 12                   ; a cart directory key: the name as the game
                                ; sends it, prefix included, zero padded
DATALEN  = 8                    ; address (3), length (2), flags, extra (2)
ENTRYLEN = KEYLEN + DATALEN

F_ZX     = %00000001            ; a zx02 stream
F_LINKS  = %00000010            ; a logged file: its sectors, link bytes
                                ; and all, one per page
M_LOGGED = $ff                  ; block map "length": a raw page the game
                                ; also writes -- look for a logged copy first
M_BAM    = $fe                  ; a BAM: always the original, writes dropped.
                                ; The save's allocator only reads it to pick
                                ; sectors for chunk files, whose position the
                                ; log does not care about; the drive's `!`
                                ; frees a chain first and the cart's does
                                ; not, so a logged BAM would fill up
K_SECTOR = $01                  ; first key byte of a logged sector:
                                ; $01, disk, track, sector (b_logkey: 1)

;;; The access light (the cart's LED may be out of sight): while the cart is busy in play, the frame cell below the cursor
;;; -- row 24, column 23, under the prompt `>` and the cursor at row 23
;;; columns 22/23 -- turns white.  Its colour byte is $89 (only the low
;;; nibble shows there: the frame is "10" pixels, brown, and "11", green
;;; from the colour RAM); row 24 is not among the cells `game` writes in
;;; play (docs/reversing-notes/u6.md), and no file on the six
;;; disks stores into $CFC0-$CFE7 by an absolute address.
LIGHT_CELL = $cc00 + 24 * 40 + 23
LIGHT_ON   = $81
LIGHT_OFF  = $89

;;; `game`'s object-file loader ($2453, $24AD): four loads by name in a row,
;;; one per quadrant of the window, through the command string at OBJ_CMD;
;;; the quadrant's origin is OBJ_QX/OBJ_QY, $00 or $80 each, and the last
;;; of the four is $80/$80 (u6core.s b_name)
OBJ_CMD  = $243b
OBJ_QX   = $2445
OBJ_QY   = $2446

;;; The on-demand part lives in whichever half of the sprite double buffer
;;; is not on screen: $D800-$DBFF (blocks $60-$6F) or $DC00-$DFFF ($70-$7F).
;;; `game` renders objects into the half $27 bit 4 names and shows that one,
;;; so between frames the other is idle -- measured: 521,320 sprite pointer
;;; stores traced over a game start and a save, none into the idle half
;;; during a loader call.
BULK_A   = $d800
BULK_B   = $dc00
BULKMAX  = $0400

;;; ---- the REU (u6reu.s, u6wc.s), 256 KB or more ----------------------
;;; Banks 0-2 from page 0: the read cache, page n of the raw sector block
;;; at n x 256 (RC_PAGES of them, below WC_FREE).  Bank 3 from $0000: the
;;; cache's flag a page; $0300-$03FF: the write cache's counts, one byte a
;;; slot (WC_COUNTS + index: a chunk file's own, from its `!NAME` entry,
;;; or $80 + sector for the save area).  The rest is the write cache's
;;; copies of what this launch last wrote to the log, and the two parts
;;; of the on-demand code that an REU gets instead of the one (u6core.s).
;;; reu_init clears the first WC_CLEAR bytes of bank 3.
REU_STATUS  = $df00
REU_STASH   = $80               ; C64 -> REU, at the next write to $FF00
REU_FETCH   = $81               ; REU -> C64, the same
REU_VERIFY  = $83               ; C64 = REU?  status bit 5 set if not
REU_VFAIL   = %00100000
RC_FLAGBANK = 3
WC_COUNTS   = $0300             ; bank 3
WC_CLEAR    = $0400
WC_BANK     = 2                 ; the pages below are bank 2's (the read
                                ; cache's end there below WC_SAVE: build.py)
WC_SAVE     = $c0               ; the save area's sectors 9-20: $C0 | sector
WC_SCRATCH  = $ef               ; the game's buffer, kept during a flush
WC_PART_A   = $f0               ; part A for $D800, $F4 for $DC00
WC_PART_B   = $f8               ; part B for $D800, $FC for $DC00
                                ; (the chunk files' slots: build.py gives each
                                ; one in its `!NAME` entry, in bank 3 from
                                ; $0400 and in bank 2 below WC_SAVE + 9)
