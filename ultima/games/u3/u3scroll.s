;;; u3scroll.s -- the message window scrolled a row at a time, in place of SUBS $4770.
;;;
;;; The window is the bitmap's text rows 17-23, columns 24-39 (SUBS' line
;;; tables $4300/$43C0: the bitmap at $2000, screen RAM at $0400).  A newline
;;; ($FF in a string, $475B) calls $4770, which copied rows 18-23 up a row
;;; one bitmap line at a time through ($7C),Y / ($7E),Y, eight bytes apart,
;;; and their screen RAM (the colours) every eighth line; then printed 16
;;; spaces at (24, 23) through $473B, each a blank glyph ($48C5) and the
;;; DOS module's colour for it ($B81E -> $B895: $B851 + $10, the high
;;; nibble).  31k cycles.  But a text row of the window is 128 bytes in a
;;; row (16 cells of 8), so here each column of the six is copied in one
;;; loop, and the last row cleared in it: 9k.
;;;
;;; What the original leaves behind is left the same: the screen, $33/$34
;;; (the DOS module's pointer at row 23's screen RAM), $70 (the last
;;; glyph's offset, 0), $79/$7A (the cursor past the spaces), $7C/$7D (the
;;; last source line's pointer), $7E/$7F kept, A = $7F, X = $FF, Y = 0.
;;; Not the flags, nor the scratch the glyph printer and $B895 write
;;; before they read it ($4912-$4916, $B891-$B893).  build.py assembles
;;; this at $4770 and checks it fits the original's $4770-$47FB.

        * = $4770

W17 = $2000 + 17 * 320 + 24 * 8         ; the window's row 17 in the bitmap
S17 = $0400 + 17 * 40 + 24              ; ... and in screen RAM
ROW = 320
SROW = 40

        ldx #127
-       lda W17 + 1 * ROW,x
        sta W17 + 0 * ROW,x
        lda W17 + 2 * ROW,x
        sta W17 + 1 * ROW,x
        lda W17 + 3 * ROW,x
        sta W17 + 2 * ROW,x
        lda W17 + 4 * ROW,x
        sta W17 + 3 * ROW,x
        lda W17 + 5 * ROW,x
        sta W17 + 4 * ROW,x
        lda W17 + 6 * ROW,x
        sta W17 + 5 * ROW,x
        lda #0                          ; a space's glyph is blank
        sta W17 + 6 * ROW,x
        dex
        bpl -
        ldx #15
-       lda S17 + 1 * SROW,x
        sta S17 + 0 * SROW,x
        lda S17 + 2 * SROW,x
        sta S17 + 1 * SROW,x
        lda S17 + 3 * SROW,x
        sta S17 + 2 * SROW,x
        lda S17 + 4 * SROW,x
        sta S17 + 3 * SROW,x
        lda S17 + 5 * SROW,x
        sta S17 + 4 * SROW,x
        lda S17 + 6 * SROW,x
        sta S17 + 5 * SROW,x
        lda $b851 + $10                 ; a space's colour, as $B895 finds it
        and #$f0
        sta S17 + 6 * SROW,x
        dex
        bpl -
        lda #<(S17 + 6 * SROW - 24)     ; $B895's pointer: row 23
        sta $33
        lda #>(S17 + 6 * SROW - 24)
        sta $34
        lda #0
        sta $70
        tay
        lda #$28
        sta $79
        lda #$17
        sta $7a
        lda #$c7                        ; line $BF, +$100: the last source
        sta $7c
        lda #$3d
        sta $7d
        lda $7f
        rts                             ; X = $FF from the loop
