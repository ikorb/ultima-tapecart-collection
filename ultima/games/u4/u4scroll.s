;;; u4scroll.s -- the text window's scroll, faster.  SUBS' scroll ($160E, from
;;; the newline at $1041; a step in a town scrolls twice) moves rows 13-23 of
;;; the text window (columns 24-39) up a row: 128 bitmap bytes and 16 screen
;;; RAM bytes a row, patched for each row, ~15 cycles a byte; then it cleared
;;; row 23 by printing 16 spaces through the character routine.  Here:
;;;  * the bitmap rows are copied with all eleven row copies unrolled in one
;;;    loop over the 128 columns (absolute,X, no patching: ~9.5 cycles a
;;;    byte); the rows are the game's own ($2000 + 320 * row + 24 * 8 --
;;;    its tables at $E000/$E0C0 -- remastered.py checks the table is the one
;;;    this was written for), and row 23's bitmap is zeroed in the same loop,
;;;    which is what a space is;
;;;  * the screen RAM rows are still patched, from the game's table
;;;    ($E180/$E198), with the source row 40 bytes on from the destination;
;;;    X counts $F5..$FF so the loop needs no compare (the table operands are
;;;    $E18C-$F5 and $E1A4-$F5);
;;;  * row 23's colour ($10, the space's, entry $20 of the table at $E2B0) is
;;;    written by ts_colour (u4scrollc.s), in SUBS' dead swap prompt after
;;;    u4key.s, where this jumps and it returns.
;;; Same bytes as the original, from $160E to $1686 (121, one NOP spare);
;;; what it leaves in $3D/$3E and $7C/$7D (the character routine's scratch,
;;; the inline-string printer's pointer) it no longer does.

TS_BITMAP = $2000 + 24 * 8              ; the window's first byte in row 0

        * = $160e
        ldx #$7f
-
        !for r, 12, 22 {
            lda TS_BITMAP + 320 * (r + 1),x
            sta TS_BITMAP + 320 * r,x
        }
        lda #$00
        sta TS_BITMAP + 320 * 23,x
        dex
        bpl -

        ldx #$f5                        ; rows 12-22 are X + 23
ts_row: lda $e18c - $f5,x               ; the row's screen RAM address
        sta ts_dst + 1
        clc
        adc #40                         ; the next row's
        sta ts_src + 1
        lda $e1a4 - $f5,x
        sta ts_dst + 2
        adc #0
        sta ts_src + 2
        ldy #$18
ts_src: lda $ffff,y
ts_dst: sta $ffff,y
        iny
        cpy #$28
        bne ts_src
        inx
        bne ts_row
        jmp $19a3                       ; ts_colour, and its RTS
        nop
