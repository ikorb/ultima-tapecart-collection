;;; u6chunk.s -- the objects of the map window, placed in one walk of the pool.
;;;
;;; The window's ring of tile planes (32 x 32 cells: plane 1 the map tile at
;;; $4800, plane 2 an object's tile at $4C00, plane 3 its byte 0 at $5000) is
;;; filled a chunk (8 x 8 cells) at a time.  For every chunk the original
;;; walked the whole object pool ($273E: ~610 nodes, ~40k cycles with
;;; u6walk.s) to find the objects on it:
;;;
;;;   - a step over a chunk line ($262D, $2663: four chunks)     4 walks
;;;   - a window (re)load ($25DB: sixteen)                      16 walks
;;;   - $3FBD, after Get, Drop, Move, Use, Cast, combat (16)    16 walks
;;;
;;; Here a block of chunks is walked once, over the whole box, and each object
;;; in it goes straight into its ring cell.  A cell's outcome depends only on
;;; the nodes that fall on it, in pool order, which one walk keeps: the first
;;; node to find the cell's plane 2 empty sets plane 3 to its byte 0 and plane
;;; 2 to its byte 3 -- except a $FE node with byte 3 $FF while $29 is set,
;;; which puts 0 in plane 3 and leaves the cell open (as $2768-$27AF did).
;;; Where the original went through the buffers $D740/$D780 and then copied,
;;; this writes the planes, so those 128 bytes are no longer written
;;; (their other readers are the view's grid at $D76B, which the view fills
;;; before reading, and Drop's check, before its refresh).
;;;
;;; What the old code left behind is left the same: $33/$34 the last chunk's
;;; corner and $80/$81 = 8 (Look and $39E6 read $80/$81 without setting
;;; them), the row pointers $56/$57, $62-$65 as the last copy left them, the
;;; counters $54/$55, $76/$77, $7A/$7B.  Not $42 (the old walk's temporary)
;;; and not $D740-$D7BF.
;;;
;;; Room: $25FB-$27B0 (the window's fetch loops, the fetch, $273E, and $2752's
;;; walk, which $3399 used and which is replaced here too), $27D1-$27F3 (the
;;; rest of the old $27CE: u6walk.s moves the callers of its two other
;;; entries; $27F4-$27F9 are tables the sprite builder and the fetch read), $33B8-$33F1 ($3399's copy), $3FBD-$4000, and from the init's
;;; spare room $03F1-$03FB and $2082-$2084.  Callers moved: $1197 and $119D
;;; (the two strip entries).  tests/test_u6_chunk.py checks that nothing
;;; else in `game` or an overlay names a byte this rewrites.

U_ROW   = $14b2         ; Y = ring row -> $56/$57, $62/$63, $64/$65
U_HEAD  = $2523         ; $50 = the pool's first node
U_NEXT  = $252b         ; on to the next node (Z set at a link of page 0)
U_FIND  = $27ce         ; the next node in the box $33/$34 $80/$81, C at the end
U_VIEW  = $2242         ; $7A/$7B = the view's first chunk
U_LOAD  = $2809         ; the loader, with the parameter block $0203-$0209
ROWLO   = $020a         ; $00 $20 .. $E0
BITS    = $021d         ; $01 $02 .. $80
TRACKS  = $27f8         ; the chunk tiles' first track, by bank: $1A, $1E

;;; ==================================================================
;;; $25FB: the rest of $25DB, a window's sixteen chunks
;;; ==================================================================
        * = $25fb
k_full: jsr $22e3
        jsr k_grid
        lda $7a                 ; ($54 held the first chunk's x)
        sta $54
        lda #$20                ; the box: all of the ring
        sta $80
        ldx #$01                ; y is the axis that went on
        jsr k_box
        inc $57
        lda #$00
        sta $74
        sta $75
        sta $28
        ldx #$34
        jmp $2c38

;;; the sixteen chunks from ($7A, $7B), ring ($76, $77): four rows of four,
;;; each through k_v (k_fetch, or k_tr for $3FBD); $7A, $76 and $77 as
;;; they were, $7B four on, $54 and $55 0
k_grid: lda #$04
        sta $55
-       ldx #$00                ; a row of four, along x
        jsr k_line
        lda $7a                 ; back to the row's first chunk
        sec
        sbc #$04
        and #$1f
        sta $7a
        inc $7b
        lda $77
        clc
        adc #$08
        and #$18
        sta $77
        dec $55
        bne -
        rts

;;; the two strips: a column of four chunks ($262D) or a row ($2663)
k_col:  jsr U_VIEW
        lda #$08                ; moving right?
        ldx #$00
        beq k_strip
k_row:  jsr U_VIEW
        lda #$02                ; moving down?
        ldx #$01
k_strip:
        bit $46
        beq +
        inc $7a,x               ; then the far side: three chunks on, and
        inc $7a,x               ; the ring slot before the first
        inc $7a,x
        lda $74,x
        sec
        sbc #$08
        and #$18
        !byte $2c
+       lda $74,x
        sta $76,x
        txa
        eor #$01
        tax
        lda $74,x
        sta $76,x
        jsr k_line              ; X: the axis to go along
        lda #$08
        sta $80
        sta $81
        jsr k_box
        inc $57
        rts

;;; four chunks from ($7A, $7B) at ring ($76, $77), going on along axis X
k_line: stx k_ax+1
        lda #$04
        sta $54
-
k_v:    jsr k_fetch
k_ax:   ldx #$00
        lda $76,x
        clc
        adc #$08
        and #$18
        sta $76,x
        inc $7a,x
        dec $54
        bne -
        rts
k_tr:   jmp k_cells2            ; ($3FBD's k_v: in k_fetch's page)

;;; one chunk's tiles into plane 1, planes 2 and 3 of its cells cleared
;;; ($2699 to the read, unchanged but for the offset: (chunk & 3) x 64 by
;;; shifts, not through $27F4's table)
k_fetch:
        lda $7b
        and #$1f
        sta $7b
        lsr
        lsr
        lsr
        ora #$44
        sta $57
        lda $7b
        and #$07
        tay
        lda ROWLO,y
        sta $56
        lda $7a
        and #$1f
        sta $7a
        and #$07
        tay
        lda $7a
        lsr
        lsr
        lsr
        sta $5a
        lda $7b
        asl
        asl
        adc $5a
        tax
        lda $4380,x
        and BITS,y
        beq +
        lda #$01
+       tax
        ldy $7a
        lda ($56),y
        sta $52
        lsr
        lsr
        tay
        lsr
        lsr
        lsr
        lsr
        clc
        adc TRACKS,x
        sta $0204
        tya
        and #$0f
        sta $0205
        lda $52                 ; offset: (chunk & 3) x 64
        ror
        ror
        ror
        and #$c0
        sta $0206
        lda #$40
        sta $0207
        lda #$d7
        sta $0209
        jsr U_LOAD
        ldx #$00
-       txa                     ; the row: ring row + cell / 8
        lsr
        lsr
        lsr
        clc
        adc $77
        tay
        jsr U_ROW
        ldy $76
--      lda $d700,x
        sta ($56),y
        lda #$00
        sta ($62),y
        sta ($64),y
        iny
        inx
        txa
        and #$07
        bne --
        cpx #$40
        bne -
        rts
!if >k_tr != >k_fetch {
        !error "k_tr and k_fetch must share a page (k_v's high byte)"
}

;;; ------------------------------------------------------------------
;;; k_box: the objects of a box of chunks onto planes 2 and 3, whose cells
;;; in the box are clear.  The box: from the chunk ($7A, $7B), less 4 chunks
;;; along axis X (the axis a loop went on along); its size in $80/$81, the
;;; one along X set to 32 here.  The ring: ($76, $77) is the slot of the
;;; chunk ($7A, $7B), which (mod 4 chunks) is what each loop leaves.
;;; ------------------------------------------------------------------
k_box:  lda #$20
        sta $80,x
        ldy #$01
-       lda $007a,y
        asl
        asl
        asl
        sta $0033,y
        dey
        bpl -
        jsr k_cdset             ; (mod 32 the -32 below changes nothing)
        lda $33,x
        sec
        sbc #$20
        sta $33,x
k_walk: jsr U_HEAD
-       jsr U_FIND
        bcs k_done
        tax                     ; byte 0
        ldy #$03
        lda ($50),y
        sta k_b3+1
        dey
        lda ($50),y             ; (C clear from U_FIND)
        adc k_cd+1
        and #$1f
        tay
        jsr U_ROW               ; its row's planes
        ldy #$01
        lda ($50),y
        clc
        adc k_cd
        and #$1f
        tay                     ; Y = the column from here on
        lda ($62),y
        bne k_next              ; taken
        txa
        sta ($64),y             ; plane 3: byte 0
        cmp #$fe                ; (C: a $FE node; $FF ends the walk)
k_b3:   lda #$00                ; (byte 3, stored above)
        bcc k_p2
        cmp #$ff
        bne k_p2
        ldx $29
        beq k_p2                ; $29 clear: plane 2 gets the $FF
        lda #$00
        sta ($64),y             ; plane 3 back to 0, the cell left open
        beq k_next
k_p2:   sta ($62),y
k_next: jsr U_NEXT
        bne -
k_done: jmp k_end
;;; ------------------------------------------------------------------
;;; the rest of $3399 (its copy's room is k_cells): one chunk's objects,
;;; X/Y its corner, $76/$77 its slot -- its cells cleared, the 8 x 8 box
;;; walked, then a $FF in plane 2 turned into 0 with plane 3 0, as $33BB did
;;; ------------------------------------------------------------------
k_one:  stx $33
        sty $34
        lda #$08
        sta $80
        sta $81
        jsr k_cdset
        lda #$ff
        jsr k_cells
        jsr k_walk
        lda #$00
        jmp k_cells

k_box_end:
!if k_box_end > $27b1 {
        !error "u6chunk.s runs into $27B1 by ", k_box_end - $27b1
}

;;; ------------------------------------------------------------------
;;; $27D1-$27F3 (the old walk's room: its entries $27E3 and $27EA have their
;;; callers moved by u6walk.s) and short of $27F4 (00 40 80 C0, which the
;;; sprite builder reads at $093B): what the old per-chunk code leaves --
;;; the box's last chunk for $33/$34, 8 for $80/$81, and the row pointers as
;;; the copy of that chunk left them: its first row's, plane 2's and 3's a
;;; page on (k_full and k_strip then add the $57 that their copy, unlike
;;; $33BB's, advanced)
;;; ------------------------------------------------------------------
        * = $27d1
k_end:  ldx #$01
-       lda $80,x
        sec
        sbc #$08
        clc
        adc $33,x
        sta $33,x
        lda #$08
        sta $80,x
        dex
        bpl -
        lda $34
        clc
        adc k_cd+1
        jmp k_rows
k_end_end:
!if k_end_end > $27ed {
        !error "u6chunk.s runs into $27ED (u6scan.s's s_fire) by ", k_end_end - $27ed
}

;;; and in the init's spare room: A = the ring row (mod 32)
        * = $03f1
k_rows: and #$1f
        tay
        jsr U_ROW
        inc $63
        inc $65
        rts
k_rows_end:
!if k_rows_end > $03fc {
        !error "u6chunk.s runs into the main loop at $03FC by ", k_rows_end - $03fc
}

;;; ------------------------------------------------------------------
;;; $33B8: the rest of $3399, one chunk's objects (X/Y its corner, $76/$77
;;; its slot): clear its cells, walk the 8 x 8 box, then turn a $FF in
;;; plane 2 into 0 with plane 3 0, as its copy $33BB did
;;; ------------------------------------------------------------------
        * = $33b8
k_r2:   jmp k_one
;;; one chunk's cells at ring ($76, $77): A = $FF clears them all, A = 0
;;; only those with $FF in plane 2; the row pointers as $33BB left them
k_cells:
        sta k_m+1
k_cells2:
        ldx #$00
--      txa                     ; the row: ring row + cell / 8
        lsr
        lsr
        lsr
        clc
        adc $77
        tay
        jsr U_ROW
        ldy $76
-       lda ($62),y
k_m:    ora #$00
        cmp #$ff
        bne +
        lda #$00
        sta ($62),y
        sta ($64),y
+       iny
        inx
        txa
        and #$07
        bne -
        cpx #$40
        bne --
        lda $77
        jmp k_rows
k_cells_end:
!if k_cells_end > $33f2 {
        !error "u6chunk.s runs into $33F2 by ", k_cells_end - $33f2
}

;;; ------------------------------------------------------------------
;;; $3FBD: the objects of the whole window again (after an object changed):
;;; the sixteen chunks' cells cleared, one walk, the $FF cells turned to 0
;;; ------------------------------------------------------------------
        * = $3fbd
k_r3:   jsr U_VIEW
        lda $74
        sta $76
        lda $75
        sta $77
        lda #<k_tr
        sta k_v+1
        lda #$ff
        sta k_m+1
        jsr k_grid              ; $7B four on: the box from the view's chunk
                                ; ($7B is left eight on, not as the old
                                ; loop's masked steps left it: only $2242
                                ; writes $7A/$7B, and every reader runs
                                ; after it)
        lda #$20
        sta $80
        ldx #$01
        jsr k_box
        lda #$00
        sta k_m+1
        jsr k_grid
        lda #<k_fetch
        sta k_v+1
        rts

;;; k_cd = the ring slot ($76, $77) less the corner ($33, $34)
k_cdset:
        ldy #$01
-       lda $0076,y
        sec
        sbc $0033,y
        sta k_cd,y
        dey
        bpl -
        rts
k_3fbd_end:
!if k_3fbd_end > $4001 {
        !error "u6chunk.s runs into $4001 by ", k_3fbd_end - $4001
}


;;; ------------------------------------------------------------------
;;; variables, in the init's spare room
;;; ------------------------------------------------------------------
        * = $2082
k_cd:   !byte 0, 0              ; ring - corner, x and y
k_vars_end:
!if k_vars_end > $2084 {
        !error "u6chunk.s's variables run into $2084 (u6scan.s's) by ", k_vars_end - $2084
}

;;; ------------------------------------------------------------------
;;; the step's two calls ($1197 up or down, $119D left or right)
;;; ------------------------------------------------------------------
        * = $1197
k_call1: jsr k_row
k_call1_end:
        * = $119d
k_call2: jsr k_col
k_call2_end:
