;;; u4los.s -- the town view's line of sight, faster.  SUBS' $0D65-$0E6B,
;;; after the buffer at $AE80 has its creatures: $AE00 gets the tiles the
;;; party can see and $7E (blank) elsewhere.  Two passes over the 11 x 11
;;; cells (index 11 * y + x, the party at 60 = (5, 5)):
;;;  1. a cell is seen if walking from it toward the party -- both
;;;     coordinates a step nearer 5, until one is there -- reaches 60 before
;;;     an opaque tile ($06, $08, $49, $7E, $7F);
;;;  2. a cell not seen is seen if walking the other way -- along the longer
;;;     distance only, both when equal -- does.
;;; The original walked every cell on its own, 408 steps of 76 cycles for
;;; pass 1 (31k a step in a town).  A cell's walk from its next cell on is
;;; that cell's own, so here pass 1 goes through the cells nearest the party
;;; first (rows 5, 4, 6, 3, 7 ... and in each row columns the same way, so
;;; the next cell is always done): a cell is seen if its next cell is 60, or
;;; is not opaque and was seen -- seen is "$AE00 is not $7E", true of every
;;; cell not opaque.  One look a cell.  Pass 2 is the original's walk, for
;;; the few cells pass 1 left blank, with the seen cells skipped first and
;;; the opaque test shared.  Same bytes as the original ($0D65-$0E6B, 263);
;;; $70 and $71 end as they did, $40/$41/$44/$45 are scratch as before.

        * = $0d65
        lda #0
        sta $45                 ; pass 1: the row (in the order below)
nrow:   ldx $45
        lda ord,x
        sta $41                 ; y
        lda #0
        sta $44                 ; the column
ncell:  ldx $44
        lda ord,x
        sta $40                 ; x
        ldy $41
        clc
        adc row,y
        sta $70                 ; the cell, 11 * y + x
        ldx $40
        clc
        adc $0f57,x             ; a step toward 5 in x
        clc
        adc $0f62,y             ; and in y (11 times)
        cmp #$3c
        beq seen
        tax                     ; the next cell
        lda $ae80,x
        jsr opq
        beq blank
        lda $ae00,x             ; was it seen?
        cmp #$7e
        beq blank
seen:   ldx $70
        lda $ae80,x
        !byte $2c               ; (BIT: skips the LDA #$7E)
blank:  lda #$7e
        ldx $70
        sta $ae00,x
        inc $44
        lda $44
        cmp #11
        bne ncell
        inc $45
        lda $45
        cmp #11
        bne nrow
        jmp pass2

ord:    !byte 5, 4, 6, 3, 7, 2, 8, 1, 9, 0, 10
row:    !byte 0, 11, 22, 33, 44, 55, 66, 77, 88, 99, 110

opq:    cmp #$06                ; Z set if the tile is opaque
        beq +
        cmp #$08
        beq +
        cmp #$49
        beq +
        cmp #$7e
        beq +
        cmp #$7f
+       rts

pass2:  lda #$78
        sta $70
        lda #$0a
        sta $44
        sta $45
p2:     ldx $70
        lda $ae00,x
        cmp #$7e
        bne p2next              ; seen already
        lda $44
        sta $40
        lda $45
        sta $41
        stx $71
walk:   ldx $40
        ldy $41
        lda $0f6d,x             ; the distances from 5
        cmp $0f6d,y
        beq both
        bcc ystep
        lda $71                 ; x is farther: a step in x
        clc
        adc $0f57,x
        jsr $0f78
        jmp test
ystep:  lda $71
        clc
        adc $0f62,y
        jsr $0f84
        jmp test
both:   lda $71
        clc
        adc $0f57,x
        clc
        adc $0f62,y
        jsr $0f78
        jsr $0f84
test:   cmp #$3c
        beq see
        sta $71
        tax
        lda $ae80,x
        jsr opq
        bne walk
        beq p2next
see:    ldx $70
        lda $ae80,x
        sta $ae00,x
p2next: dec $70
        dec $44
        bpl p2
        lda #$0a
        sta $44
        dec $45
        bmi +
        jmp p2
+       jmp $0e6c
pend:
