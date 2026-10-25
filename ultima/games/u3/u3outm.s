;;; u3outm.s -- Ultima III's peer at a gem on the surface (OUTM), in colour.
;;;
;;; The original (disk B's OUTM, $9400, JSR'd by ULT3 after "L OUTM") draws
;;; the 64 x 64 map as 2 x 2 hires pixels a tile, a dither pattern per
;;; terrain, white on black, and blinks the party until a key.  This one draws
;;; it in multicolour: a tile is one multicolour pixel (2 hires pixels wide)
;;; and two lines -- the same size -- in the tile's colour(s), the map in cells
;;; 4-19 of both rows and columns, the middle of the 22 x 22 view (the original
;;; sat a pixel to the left of that).  Water is the background (blue, $D021);
;;; each cell of 4 x 4 tiles picks up to three colours of its own (screen RAM
;;; high and low nibble, colour RAM), towns, castles, dungeons and the like
;;; first, then the commonest terrain; a colour that did not make it takes a
;;; stand-in (ol_fb), else the cell's first.
;;;
;;; Multicolour is the whole screen's, so everything else is blanked to the
;;; sea's blue meanwhile, the border too: the panels' screen RAM holds only
;;; $E0 (the frame) and $10 (text) outside the view, one bit a cell here and
;;; put back afterwards (a cell holding anything else is left alone); the view
;;; is left $10, as the original leaves it, for the game's redraw.  Colour RAM
;;; is not used in hires bitmap mode, so it needs no restoring.  Zero page:
;;; $02/$03 (SUBS' map read), $7E/$7F and $75-$78, as the original used.
;;; Built by ultima/games/u3/build.py over the OUTM unit (up to 4 blocks: $9400-$97FF
;;; is the overlays' window, which SHP0/2/3/6 fill whole).

get_tile   = $4708              ; SUBS: A = the tile at ($02, $03), X kept
clear_view = $46cc              ; SUBS: the view's bitmap cleared
kb_get     = $b80c              ; the DOS module: a key, or $FF
kb_flush   = $b80f
party_x    = $f7
party_y    = $f8
line_lo    = $4300              ; SUBS: bitmap address of each line
line_hi    = $43c0
SCREEN     = $0400
COLRAM     = $d800
BG         = 6                  ; blue: water, and everything off the map
BLANK      = BG << 4 | BG
MAP0       = 4                  ; the map's first cell, row and column
ptr        = $7e
bp         = $75                ; the cell's bitmap
cp         = $77                ; the cell's screen RAM

        * = $9400

outm:   jsr clear_view
        lda $d016
        sta ol_d016
        lda $d020
        sta ol_d020
        lda $d021
        sta ol_d021
        jsr ol_blank
        lda #BG
        sta $d020
        sta $d021
        lda ol_d016
        ora #$10
        sta $d016               ; multicolour: everything blue until drawn

        lda #0
        sta ol_cy
ol_row: lda #0
        sta ol_cx
ol_col: jsr ol_cell
        inc ol_cx
        lda ol_cx
        cmp #16
        bne ol_col
        inc ol_cy
        lda ol_cy
        cmp #16
        bne ol_row

        ;; the party's tile blinks until a key, as it did
        jsr kb_flush
        lda party_x
        lsr
        lsr
        sta ol_cx
        lda party_y
        lsr
        lsr
        sta ol_cy
        jsr ol_addr
        lda party_y
        and #3
        asl
        sta ol_line
        lda party_x
        and #3
        tax
        lda ol_pair,x
        sta ol_mask
        lda cp+1                ; a third colour to blink with, if the cell
        clc                     ; has none: white
        adc #>(COLRAM - SCREEN)
        sta cp+1
        ldy #0
        lda (cp),y
        and #$0f
        cmp #BG
        bne ol_wait
        lda #C_WHITE
        sta (cp),y
ol_wait:
        lda #16                 ; frames between toggles
        sta ol_frames
ol_frame:
        lda $d012
        cmp #$fa
        bne ol_frame
ol_line2:
        lda $d012
        cmp #$fa
        beq ol_line2
        jsr kb_get
        cmp #$ff
        bne ol_key
        dec ol_frames
        bne ol_frame
        jsr ol_blink
        jmp ol_wait
ol_key: lda ol_on
        beq +
        jsr ol_blink            ; the tile as it was
+       jsr kb_flush

        ;; back to hires, the panels as they were, the view $10
        lda ol_d016
        sta $d016
        lda ol_d020
        sta $d020
        lda ol_d021
        sta $d021
        jmp ol_restore

ol_blink:
        lda ol_on
        eor #1
        sta ol_on
        ldy ol_line
        lda (bp),y
        eor ol_mask
        sta (bp),y
        iny
        lda (bp),y
        eor ol_mask
        sta (bp),y
        rts

;;; ---- one cell: 4 x 4 tiles ---------------------------------------------
ol_cell:
        ldx #15
        lda #0
-       sta ol_hist,x
        dex
        bpl -
        lda ol_cy               ; the tiles, their colours, the counts
        asl
        asl
        sta $03
        ldx #0
ol_ty:  lda ol_cx
        asl
        asl
        sta $02
ol_tx:  jsr get_tile            ; (X kept)
        lsr
        lsr
        tay
        lda ol_top,y
        sta ol_st,x
        jsr ol_count
        lda ol_top,y
        cpy #2                  ; brush: light green over green
        bne +
        lda #C_GREEN
+       sta ol_sb,x
        jsr ol_count
        inx
        inc $02
        txa
        and #3
        bne ol_tx
        inc $03
        cpx #16
        bne ol_ty

        ;; up to three colours, by weight
        ldx #15
        lda #$ff
-       sta ol_code,x
        dex
        bpl -
        lda #0
        sta ol_code+BG
        lda #BG
        sta ol_slot
        sta ol_slot+1
        sta ol_slot+2
        ldy #0
ol_pick:
        lda #0
        sta ol_bv
        ldx #15
ol_pk1: lda ol_hist,x
        cmp ol_bv
        bcc ol_pk2
        beq ol_pk2
        sta ol_bv
        stx ol_bc
ol_pk2: dex
        bpl ol_pk1
        lda ol_bv
        beq ol_picked
        ldx ol_bc
        lda #0
        sta ol_hist,x
        txa
        sta ol_slot,y
        iny
        tya
        sta ol_code,x           ; slot 0 -> %01, 1 -> %10, 2 -> %11
        cpy #3
        bne ol_pick
ol_picked:
        ;; every sample to its 2-bit code
        ldx #15
-       lda ol_st,x
        jsr ol_resolve
        sta ol_st,x
        lda ol_sb,x
        jsr ol_resolve
        sta ol_sb,x
        dex
        bpl -

        jsr ol_addr
        ldy #0
        lda ol_slot
        asl
        asl
        asl
        asl
        ora ol_slot+1
        sta (cp),y
        lda cp+1                ; colour RAM: the same offset from $D800
        pha
        clc
        adc #>(COLRAM - SCREEN)
        sta cp+1
        lda ol_slot+2
        sta (cp),y
        pla
        sta cp+1

        ldx #0                  ; 4 rows of tiles, two lines each
ol_wr:  lda ol_st,x
        asl
        asl
        ora ol_st+1,x
        asl
        asl
        ora ol_st+2,x
        asl
        asl
        ora ol_st+3,x
        sta (bp),y
        iny
        lda ol_sb,x
        asl
        asl
        ora ol_sb+1,x
        asl
        asl
        ora ol_sb+2,x
        asl
        asl
        ora ol_sb+3,x
        sta (bp),y
        iny
        inx
        inx
        inx
        inx
        cpy #8
        bne ol_wr
        rts

;;; A = a colour: its weight onto its count (the background counts nothing)
ol_count:
        cmp #BG
        beq ++
        sty ol_ty0
        tay
        lda ol_prio,y
        clc
        adc ol_hist,y
        bcc +
        lda #$ff
+       sta ol_hist,y
        ldy ol_ty0
++      rts

;;; A = a colour -> its code: its own slot, its stand-in's, else slot 0's
ol_resolve:
        tay
        lda ol_code,y
        bpl +
        lda ol_fb,y
        tay
        lda ol_code,y
        bpl +
        lda #1
+       rts

;;; the cell (ol_cx, ol_cy) of the map: bp its bitmap, cp its screen RAM
ol_addr:
        lda ol_cy
        clc
        adc #MAP0
        tax
        asl
        asl
        asl
        tay
        lda ol_cx
        clc
        adc #MAP0
        sta ol_ty0
        asl
        asl
        asl                     ; column * 8 (the map's columns are < 32)
        clc
        adc line_lo,y
        sta bp
        lda line_hi,y
        adc #0
        sta bp+1
        lda ol_scr_lo,x
        clc
        adc ol_ty0
        sta cp
        lda ol_scr_hi,x
        adc #0
        sta cp+1
        rts

;;; ---- the panels -------------------------------------------------------
;;; Every cell: in the view (rows and columns 1-22) blanked; outside it,
;;; $10 and $E0 blanked with a bit saying which, anything else left.
ol_blank:
        lda #0
        sta ol_r
ol_b1:  jsr ol_rowptr
        ldy #39
ol_b2:  jsr ol_inview
        bcs ol_b5
        lda (ptr),y
        cmp #$10
        beq ol_b3
        cmp #$e0
        bne ol_b6
        jsr ol_bitclr
        jmp ol_b5
ol_b3:  jsr ol_bitset
ol_b5:  lda #BLANK
        sta (ptr),y
ol_b6:  lda ptr+1
        pha
        clc
        adc #>(COLRAM - SCREEN)
        sta ptr+1
        lda #BG
        sta (ptr),y
        pla
        sta ptr+1
        dey
        bpl ol_b2
        inc ol_r
        lda ol_r
        cmp #25
        bne ol_b1
        rts

ol_restore:
        lda #0
        sta ol_r
ol_r1:  jsr ol_rowptr
        ldy #39
ol_r2:  jsr ol_inview
        lda #$10
        bcs ol_r4               ; the view: $10, for the game's redraw
        lda (ptr),y
        cmp #BLANK
        bne ol_r5               ; not ours
        jsr ol_bittest
        lda #$10
        bcs ol_r4
        lda #$e0
ol_r4:  sta (ptr),y
ol_r5:  dey
        bpl ol_r2
        inc ol_r
        lda ol_r
        cmp #25
        bne ol_r1
        jmp clear_view          ; the variables, and the map, out of the view

ol_rowptr:
        ldx ol_r
        lda ol_scr_lo,x
        sta ptr
        lda ol_scr_hi,x
        sta ptr+1
        lda #0                  ; the row's mask bytes: row * 5
        ldx ol_r
        beq +
-       clc
        adc #5
        dex
        bne -
+       sta ol_r5x
        rts

;;; C set: (ol_r, Y) is in the view
ol_inview:
        lda ol_r
        beq +
        cmp #23
        bcs +
        cpy #0
        beq +
        cpy #23
        bcs +
        sec
        rts
+       clc
        rts

;;; the mask bit of (ol_r, Y): X its byte, A its bit
ol_bitpos:
        tya
        lsr
        lsr
        lsr
        clc
        adc ol_r5x
        tax
        tya
        and #7
        sty ol_ty0
        tay
        lda ol_bits,y
        ldy ol_ty0
        rts
ol_bitset:
        jsr ol_bitpos
        ora ol_mbits,x
        sta ol_mbits,x
        rts
ol_bitclr:
        jsr ol_bitpos
        eor #$ff
        and ol_mbits,x
        sta ol_mbits,x
        rts
ol_bittest:                     ; C = the bit
        jsr ol_bitpos
        and ol_mbits,x
        cmp #1
        rts

;;; ---- tables -------------------------------------------------------------
ol_bits: !byte $01, $02, $04, $08, $10, $20, $40, $80
ol_pair: !byte $c0, $30, $0c, $03         ; a tile's pair, by x & 3
ol_scr_lo:
!for r, 0, 24 { !byte <(SCREEN + r * 40) }
ol_scr_hi:
!for r, 0, 24 { !byte >(SCREEN + r * 40) }

;;; a tile's colour (tile / 4), both its lines but brush's lower one (ol_cell) -- the
;;; game's own where they tell things apart (UPDT's table: grass, brush and
;;; forest green, mountains orange, towns and castles white), two greens for
;;; the three kinds of green, and the rest by kind
C_BLACK = 0
C_WHITE = 1
C_RED   = 2
C_CYAN  = 3
C_GREEN = 5
C_YELLOW = 7
C_ORANGE = 8
C_GREY  = 12
C_LGREEN = 13
C_LGREY = 15
ol_top:
        !byte BG, C_LGREEN, C_LGREEN, C_GREEN           ; water grass brush forest
        !byte C_ORANGE, C_BLACK, C_WHITE, C_YELLOW      ; mountains dungeon town castle
        !fill 24, C_LGREY                               ; $20-$7C: floor, objects
        !byte C_LGREY, C_RED, C_CYAN, C_GREY            ; $80 field, $84 lava, $88 gate, $8C wall
        !fill 28, C_LGREY                               ; $90-$FC
;;; a colour's weight in a cell: places before terrain
ol_prio:
        !byte 32, 32, 32, 32, 1, 1, 0, 32               ; black white red cyan ... yellow
        !byte 1, 1, 1, 1, 1, 1, 1, 1
;;; a colour's stand-in when it did not get a slot
ol_fb:  !byte C_GREY, C_LGREY, C_ORANGE, C_WHITE, 0, C_LGREEN, BG, C_WHITE
        !byte C_GREY, C_ORANGE, 0, 0, C_LGREY, C_GREEN, 0, C_WHITE

ol_end:
!if ol_end > $9800 {
        !error "u3outm.s runs past the overlay window at $9800 by ", ol_end - $9800
}

;;; Variables: in the view's bitmap above the map (view rows 1 and 2), which
;;; clear_view has cleared and whose cells are blue in all four colours while
;;; the peer is up -- the overlay window has no room left.  ol_restore's
;;; clear_view at the end wipes them before the view is hires again.
VARS = $2000 + 1 * 320 + 8
ol_d016  = VARS
ol_d020  = VARS + 1
ol_d021  = VARS + 2
ol_cx    = VARS + 3
ol_cy    = VARS + 4
ol_line  = VARS + 5
ol_mask  = VARS + 6
ol_on    = VARS + 7
ol_frames = VARS + 8
ol_bv    = VARS + 9
ol_bc    = VARS + 10
ol_ty0   = VARS + 11
ol_r     = VARS + 12
ol_r5x   = VARS + 13
ol_slot  = VARS + 14            ; 3
ol_hist  = VARS + 17            ; 16
ol_code  = VARS + 33            ; 16
ol_st    = VARS + 49            ; 16
ol_sb    = VARS + 65            ; 16, to VARS + 81
ol_mbits = $2000 + 2 * 320 + 8  ; 125 of view row 2's 176
