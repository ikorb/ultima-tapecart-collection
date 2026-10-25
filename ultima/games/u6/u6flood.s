;;; u6flood.s -- `game`'s line-of-sight flood, $17A3-$189E (252 bytes in the
;;; original), rewritten to be faster with the same result.
;;;
;;; $178C works out what of the 11 x 11 window (cell = 11 x row + column,
;;; the party's at 60) the party can see: a flood from the party's cell
;;; through the cells that do not block ($18C7), one cell at a time off a
;;; stack, each looking at its eight neighbours in the order $18AF gives
;;; (X = 7 down to 0) and marking the unseen ones in $D600 (the tile).  The
;;; first visit decides how a cell is marked, and $18C7 looks at the cell
;;; the neighbour is seen *from*, so the order of the visits is kept as it
;;; was.  Then a pass over all the cells: unseen ones go dark, and a seen
;;; blocking one ($A200 bit 2) gets the edge variant of its tile ($90 + a
;;; shape) from which of its four neighbours were seen.
;;;
;;; The original asked of every neighbour "is it in the grid, and in the row
;;; it should be?" (an add, a compare, a table read, a subtract and a
;;; compare: 60 cycles, 690 times a step).  Now each cell's directions that
;;; stay in the grid are one byte (f_valid: the row's edges and the column's
;;; edges ANDed, bit n for the direction of X = n), and a neighbour is a bit
;;; shifted out.  The 22 bytes of tables are the end of this block.

        * = $17a3
dirs    = $18af                 ; neighbour offsets: -11 -12 +1 +12 +11 +10 -1 -10
dwt     = $18b7                 ; the weights the edge variants add up
opaque  = $18c7                 ; X = A; carry set if the tile blocks the view
times11 = $0212                 ; 0, 11, 22 ... 110
bitsets = $021d                 ; 1, 2, 4 ... $80

f_exp:  ldy $2b                 ; the cell being looked from
        jsr f_valid             ; $2C: the directions that stay in the grid
        ldx #$07
f_dir:  asl $2c
        bcc f_nx
        lda $2b
        clc
        adc dirs,x
        tay                     ; the neighbour
        lda $d600,y
        bne f_nx                ; seen already
        lda $d6f2,y
        sta $d600,y             ; seen now, as its tile
        stx $2d
        jsr opaque
        ldx $2d
        bcs f_nx                ; if it blocks, not looked from
        tya
        pha
        inc $2a
f_nx:   dex
        bpl f_dir
        lda $2a
        beq f_all
        pla
        sta $2b
        dec $2a
        jmp f_exp

f_all:  ldx #$78
f_cell: lda $589e
        beq f_seen
        lda $d679,x
        bne f_seen
        lda #$04
        sta $d679,x
        lda #$40
        sta $d76b,x
f_seen: lda $d600,x
        bne f_edge
        sta $d679,x
        beq f_step
f_edge: tay
        lda $a200,y
        and #$04
        beq f_step
        stx $2b
        txa
        tay
        jsr f_valid
        lda #$00
        sta $2e
        tax
f_four: lda bitsets,x
        and $2c
        beq f_no
        lda $2b
        clc
        adc dirs,x
        tay
        lda $d600,y
        beq f_no
        lda dwt,x
        ora $2e
        sta $2e
f_no:   inx
        inx
        cpx #$08
        bcc f_four
        ldx $2b
        lda $2e
        cmp #$0f
        beq f_step
        ldy $d6f2,x
        lda $a200,y
        lsr
        lsr
        lsr
        lsr
        cmp #$07
        beq f_var
        cmp #$0b
        beq f_var
        cmp #$0d
        bcs f_var
        cmp $2e
        bne f_step
f_var:  and $2e
        tay
        lda $189f,y
        clc
        adc #$90
        sta $d6f2,x
f_step: dex
        bmi f_out
        jmp f_cell
f_out:  rts

;;; Y = a cell; $2C and A = the directions (bit n = X of n above) that stay in
;;; the grid.  Clobbers X.
f_valid:
        ldx $5f37,y             ; its row
        lda f_rows,x
        sta $2c
        tya
        sec
        sbc times11,x
        tax                     ; its column
        lda f_cols,x
        and $2c
        sta $2c
        rts
f_rows: !byte $7c, $ff, $ff, $ff, $ff, $ff, $ff, $ff, $ff, $ff, $c7
f_cols: !byte $9d, $ff, $ff, $ff, $ff, $ff, $ff, $ff, $ff, $ff, $73
f_end:
!if f_end > $189f {
        !error "u6flood.s runs past $189E by ", f_end - $189f
}
