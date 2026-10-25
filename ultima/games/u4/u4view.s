;;; u4view.s -- the town view's buffer, built faster.  SUBS' $0C0B (a town
;;; or castle, game mode 2) fills the 11 x 11 buffer at $AE80 with the map
;;; tiles around the party -- the map is 32 x 32 at $E800, a cell outside it
;;; is tile $04 -- and then goes on at $0CD0 to put the creatures on it and
;;; draw it.  The original worked a row pointer out afresh for every cell
;;; (~98 cycles a cell, 12k a step); here it is worked out once a row, a cell
;;; is the column in Y against $20, and a row outside the map is filled
;;; whole.  Columns and rows wrap as 8-bit numbers as they did ($FB + 5 is
;;; column 0).  Same bytes as the original ($0C0B-$0C71, 103), the same
;;; buffer, X = 121, Y = 0, and $42/$43 as the loops leave them; $44/$45
;;; (the last cell's coordinates) and $7C/$7D (its pointer) are scratch that
;;; the code after $0CD0 sets before it reads.

        * = $0c0b
        jsr $0f90               ; the creatures' animation frames
        sec
        lda $10
        sbc #5
        sta $40                 ; the view's first column
        sec
        lda $11
        sbc #5
        sta $41                 ; and row
        ldx #0                  ; the buffer's index
        stx $43                 ; the row
row:    lda $41
        clc
        adc $43
        sta $45                 ; the map row
        cmp #$20
        bcs rowout
        lsr
        lsr
        lsr
        clc
        adc #$e8
        sta $7d                 ; the row's address: $E800 + row * 32
        lda $45
        asl
        asl
        asl
        asl
        asl
        sta $7c
        ldy $40                 ; the first column
        lda #11
        sta $42                 ; cells to go
cell:   cpy #$20
        bcs out
        lda ($7c),y
        bcc put                 ; (carry is clear: Y < $20)
out:    lda #$04
put:    sta $ae80,x
        inx
        iny
        dec $42
        bne cell
next:   inc $43
        lda $43
        cmp #11
        bne row
        ldy #0                  ; (as the original left it)
        jmp $0cd0
rowout: lda #$04
        ldy #11
-       sta $ae80,x
        inx
        dey
        bne -
        sty $42                 ; (as the cell loop leaves it)
        beq next                ; (Y = 0)
