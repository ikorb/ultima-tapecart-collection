; Ultima V, main.subs $5A90: the text window's scroll, unrolled.
;
; The text window is columns 24-39 of character rows 12-24 (the row tables'
; rows 11-23: startup and qs fill $1400/$14C0 with bitmap line n at $2000 +
; 320 * (n / 8 + 1) + n % 8, and $03D0/$03E8 with screen row k at $0400 +
; 40 * (k + 1); build.py checks both files).  The original moved table rows
; 12-23 up a row, 128 bitmap bytes and 16 screen bytes each, through
; self-modified operands set from the tables, with a CPY #$10 on every byte
; to know when to do the screen byte too (~20 cycles a byte, 33.7k a scroll,
; twice a step), then cleared row 23's bitmap.  Its first row, $72, is
; always $58 (its only stores, startup $8A45 and qs $8071, are LDA #$58).
;
; Here the bitmap is one loop over the 128 columns with the twelve row
; copies spelt out (fixed addresses, ~9 cycles a byte) and row 23 cleared in
; the same pass; rows go upwards within a column, as they must.  The screen
; bytes: rows 11-16 and 17-22 each as one Y span over 240 bytes (row k + 1
; at 40 bytes past row k), 16 columns a row.  Registers are dead after it:
; its caller $5A86 falls into $5A89, which reloads X, Y and A.

        * = $5A90

line    = $2000 + $C0           ; the window's first bitmap byte, table row -1
scr     = $0400 + $18           ; ... and screen byte

!macro pair .r {
        lda line + 320 * (.r + 2),x
        sta line + 320 * (.r + 1),x
}

!macro span .first {            ; screen rows .first .. .first + 5 <- the rows under them
        ldy #0
-       ldx #16
--      lda scr + 40 * (.first + 2),y
        sta scr + 40 * (.first + 1),y
        iny
        dex
        bne --
        tya                     ; C is clear here: set before, or by the CPY below
        adc #24
        tay
        cpy #240
        bcc -
}

scroll  dec $CA
        ldx #$7F
-       +pair 11
        +pair 12
        +pair 13
        +pair 14
        +pair 15
        +pair 16
        +pair 17
        +pair 18
        +pair 19
        +pair 20
        +pair 21
        +pair 22
        lda #0
        sta line + 320 * 24,x   ; row 23 cleared
        dex
        bpl -
        clc
        +span 11
        clc
        +span 17
        rts
scroll_end
        !if scroll_end > $5B14 { !error "the scroll reaches $5B14" }
