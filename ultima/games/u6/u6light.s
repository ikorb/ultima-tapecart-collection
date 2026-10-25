;;; u6light.s -- `game`'s light map, $18E8-$198D (the routine, 102 bytes, and
;;; its distance table, 64 bytes in the original), rewritten to be faster.
;;;
;;; $18E8 gives each of the 11 x 11 window's cells a light level, 0-4
;;; ($D679,x): the party's light ($26: the ambient light, $1A3E, plus a
;;; light for each member who holds one, $3F04) plus the cell's own ($A600
;;; bit 0-1 of its tile, or 0 with $589E set) less the distance to the
;;; party's cell, which is the table below at 8 x |rows| + |columns|, clamped
;;; to 0-4.  It also clears the grid at $D600.  The original worked the two
;;; distances out for every cell with a call each ($30A9: an absolute value);
;;; they are two table reads now.  The loop is otherwise the original's,
;;; down to the carries, which the clamp depends on.
;;;
;;; The table is only ever read at 8 x 5 + 5 = 45 and below, so its 46 bytes
;;; are all that is kept, with the 11 of |column - 5|, at the end of the
;;; original's room; what is left over in between is free (build.py puts
;;; the lit cell's copy loop there, see u6view.s).

        * = $18e8
l_start:
        lda $26
        bmi l_n
        jsr $3f04
        adc $26
        sta $26
l_n:    lda #$0a
        sta $54                 ; the cell's column, 10 down to 0
        sta $55                 ; and its row
        ldx #$78
l_cell: lda #$00
        ldy $589e
        bne l_f
        ldy $d6f2,x
        lda $a600,y
        and #$03
l_f:    sta $2e
        ldy $55
        lda l_ac,y
        asl
        asl
        asl                     ; 8 x |row - 5|  (carry clear: at most 40)
        ldy $54
        clc
        adc l_ac,y              ; + |column - 5|
        tay
        lda #$05
        adc $26
        adc $2e
        sbc l_t,y
        bmi l_z
        cmp #$04
        bcc l_s
        lda #$04
        !byte $2c
l_z:    lda #$00
l_s:    sta $d679,x
        dec $54
        bpl l_c
        lda #$0a
        sta $54
        dec $55
l_c:    lda #$00
        sta $d600,x
        dex
        bpl l_cell
        rts
l_code_end:

l_ac    = $1955                 ; |n - 5|, n = 0 to 10
l_t     = $1960                 ; the distances: 8 rows of 8, the first 46 bytes
        * = l_ac
        !byte 5, 4, 3, 2, 1, 0, 1, 2, 3, 4, 5
        * = l_t
        !byte 0, 1, 2, 3, 4, 5, 6, 7
        !byte 1, 1, 2, 3, 4, 5, 6, 7
        !byte 2, 2, 3, 4, 5, 6, 6, 7
        !byte 3, 3, 4, 4, 5, 6, 7, 8
        !byte 4, 4, 5, 5, 6, 7, 7, 8
        !byte 5, 5, 6, 6, 7, 7
l_end:
!if l_code_end > l_ac {
        !error "u6light.s: the code runs into its tables by ", l_code_end - l_ac
}
!if l_end != $198e {
        !error "u6light.s must end at $198D"
}
