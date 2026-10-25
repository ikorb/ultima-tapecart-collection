;;; u6clear.s -- the line-of-sight flood, skipped when nothing in the window
;;; can block it.
;;;
;;; The flood ($178C, u6flood.s) walks the 11 x 11 window from the party's
;;; cell, marking each cell it sees in $D600 with its tile; it is stopped
;;; only by a tile whose flags ($A600 & $0C) say it blocks or is a window
;;; or door.  When no tile of the window does -- open country: grass, water,
;;; sand -- it reaches every cell and its whole result is "$D600 = the tiles,
;;; the party's cell $3C" (the original marks the party's own cell with $3C,
;;; not its tile, and so does this).  The order of the visits then decides
;;; nothing.  So: look at the 121 tiles (~20 cycles each, and a blocked
;;; window stops at its first blocker), and if all are clear copy them and go
;;; on to the pass over the cells (f_all), ~27k cycles a step saved; else
;;; the flood, as before.  A tile 0 (never marked: $D600 = 0 means unseen)
;;; also takes the flood.
;;;
;;; The hook is the prologue's `STA $D63C` at $17A0 (A = $3C).  The code is in
;;; the room the one-time init leaves (build.py relocate_init).

        * = $17a0
c_jump: jmp c_pre
c_jump_end:

c_pre   = $1302
        * = c_pre
        ldx #$78
c_scan: ldy $d6f2,x
        beq c_slow              ; tile 0
        lda $a600,y
        and #$0c
        bne c_slow              ; it blocks, or is a window or a door
        dex
        bpl c_scan
        ldx #$78
c_copy: lda $d6f2,x             ; every cell seen, marked with its tile
        sta $d600,x
        dex
        bpl c_copy
        lda #$3c
        sta $d63c               ; but the party's own cell with $3C
        jmp f_all
c_slow: lda #$3c
        sta $d63c
        jmp f_exp
c_end:
