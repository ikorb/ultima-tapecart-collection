;;; u6view.s -- `game`'s view draw loop, $1697-$178B (245 bytes in the
;;; original), rewritten to be faster with the same effect.
;;;
;;; The loop draws the 9 x 9 cells of the view, each a tile or an object:
;;; its colours into the colour matrix ($CC00..) and colour RAM, then its
;;; 32 bytes of graphics into the bitmap, ANDed with the mask for the
;;; cell's light level ($D679,x: 0-4; the masks are 16 bytes at $93B0 +
;;; 16 x (5 - level), in the TILES file).  The AND is the only reason for
;;; the original's loop (41 cycles a byte pair, 81 cells a step: a fifth
;;; of a step):
;;;   level 4 (lit)   mask $FF all through: a plain copy, 27 cycles
;;;   level 0 (dark)  mask $00 all through: a fill, 17
;;;   levels 1-3      the original loop
;;; build.py asserts that the mask table is as that needs.  Everything else
;;; the original did is kept, including which cells are not drawn at all
;;; (a large overlay in use, $FD, and a tile of $40 or more).
;;;
;;; The two short loops live in the spare room of the other two patches: the
;;; flood's tail (v_dark) and the light map's middle (v_lit); build.py gives
;;; their addresses (-Dv_dark, -Dv_lit) and where the room ends.
;;;
;;; The entry $1697 is also called from $25ED (a full redraw after a window
;;; load); $1777 had no other caller, so it is part of the loop now.

        * = $1697
v_start:
        lda #$09
        sta $7c                 ; cells left in the row
        lda #$0c
        sta $42                 ; the first cell: grid row 1, column 1
        lda #$00
        sta $7d                 ; rows done
v_row:  asl
        tax
        lda $1e5e,x
        sta $58                 ; colour matrix, this row
        lda $1e70,x
        sta $59
        lda $1e3a,x
        sta $52                 ; bitmap, the cell's upper half
        lda $1e4c,x
        sta $53
v_cell: lda #$0f
        sta $2e                 ; colour RAM: $0F, 0 for the objects from $9E
        ldy $42
        ldx $d76b,y             ; the object here, if any
        beq v_tile
        ldy $a100,x
        cpx #$9e
        bcc v_obj
        lda #$00
        sta $2e
        tya
        ora #$10
        tay
v_obj:  lda #$80
        bne v_src
v_tile: ldx $d6f2,y             ; else the tile
        ldy $a000,x
        lda #$60
v_src:  sta $5b                 ; its graphics: page $60 + tile / 8 (objects
        txa                     ; $80), 32 bytes at 32 x (tile mod 8)
        lsr
        lsr
        lsr
        ora $5b
        sta $5b
        sta $5d
        txa
        asl
        asl
        asl
        asl
        asl                     ; 32 x (tile mod 8)
        sta $5a
        ora #$10
        sta $5c                 ; ($5C) is the second 16 bytes of the 32
        tya                     ; the colour matrix gets Y's colour, four
        jsr v_four              ; characters of it,
        inc $01
        lda $2e
        jsr v_four              ; and colour RAM the other value
        dec $01
        lda $52
        clc
        adc #$40
        sta $54
        lda $53
        adc #$01
        sta $55
        ldx $42
        ldy $d679,x             ; the light level
        bne v_lvl
        jmp v_dark              ; dark: zeros, in the flood's spare room
v_lvl:  lda $fd
        beq v_draw
        lda $5b
        cmp #$68
        bcc v_draw
        cmp #$80
        bcc v_next              ; (with an overlay up, a tile from $40 is left)
v_draw: cpy #$04
        bne v_mask
        jmp v_lit               ; lit: a plain copy, in the light map's spare room
v_mask: ldx $9410,y             ; the others: ANDed with the level's mask
        ldy #$0f
v_and:  lda $93bf,x
        and ($5a),y
        sta ($52),y
        lda $93bf,x
        and ($5c),y
        sta ($54),y
        dex
        dey
        bpl v_and
v_next: clc
        lda $52
        adc #$10
        sta $52
        bcc +
        inc $53
+       inc $58
        inc $58
        bne +
        inc $59
+       inc $42
        dec $7c
        beq v_rowend
        jmp v_cell
v_rowend:
        lda #$09
        sta $7c
        inc $42
        inc $42
        inc $7d
        lda $7d
        cmp #$09
        bcs v_done
        jmp v_row
v_done: rts

;;; A at the four characters of the cell in the matrix at ($58) (and the
;;; page toggled between the matrix and colour RAM, as the original's $1777)
v_four: ldy #$01
        sta ($58),y
        dey
        sta ($58),y
        ldy #$29
        sta ($58),y
        dey
        sta ($58),y
        lda $59
        eor #$14
        sta $59
        rts
v_end:
!if v_end > $178c {
        !error "u6view.s runs past $178B by ", v_end - $178c
}

;;; The lit cell's copy, in the room u6light.s leaves from its code's end
;;; ($1945) to its tables ($1955): 16 bytes, exactly.
* = v_dark
        tya                     ; (Y = 0: dark)
        ldy #$0f
-       sta ($52),y
        sta ($54),y
        dey
        bpl -
        jmp v_next
v_dark_end:
!if v_dark_end > v_dark_limit {
        !error "u6view.s: the dark loop runs past its room by ", v_dark_end - v_dark_limit
}

;;; The lit cell's copy, in the room u6light.s leaves between its code and its
;;; tables: 16 bytes, exactly.
        * = v_lit
        ldy #$0f
-       lda ($5a),y
        sta ($52),y
        lda ($5c),y
        sta ($54),y
        dey
        bpl -
        jmp v_next
v_lit_end:
!if v_lit_end > v_lit_limit {
        !error "u6view.s: the lit loop is ", v_lit_end - v_lit, " bytes, the room ", v_lit_limit - v_lit
}
