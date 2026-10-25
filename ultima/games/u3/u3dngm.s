;;; u3dngm.s -- Ultima III's peer at a gem in a dungeon (DNGM), in colour.
;;;
;;; The original (disk B's DNGM, $9400, JSR'd by ULT3 after "L DNGM"), as it
;;; was -- the level's 16 x 16 squares as glyphs in cells 4-19 of the view, a
;;; '*' blinking on the party until a key, then the dungeon view redrawn --
;;; but each square's cell gets a colour by what it is.  A hires cell has its
;;; own colours, so that is all it takes.  The screen RAM of those 256 cells is
;;; kept at $9600 (in the overlay window, past this unit) and put back
;;; before the view is redrawn.  Zero page as the original: $02/$03, $79/$7A
;;; (SUBS' glyph position), $7E/$7F.  Built by ultima/games/u3/build.py over DNGM.

clear_view = $46cc              ; SUBS
print_str  = $46c3              ; SUBS: the inline string after the JSR
glyph      = $46d5              ; SUBS: A's glyph at cell ($79, $7A); X not kept
kb_get     = $b80c
kb_flush   = $b80f
redraw     = $1800              ; DDRW: the dungeon view
level      = $23
party_x    = $f7
party_y    = $f8
SCREEN     = $0400
MAP0       = 4
SAVED      = $9600              ; 256 bytes: the cells' screen RAM
ptr        = $7e

        * = $9400

dngm:   jsr clear_view
        ldx #0                  ; the 16 x 16 cells' colours, kept
        jsr dg_cells
        lda #0
        sta $02
        sta $03
dg_sq:  lda $02
        clc
        adc #MAP0
        sta $79
        lda $03
        clc
        adc #MAP0
        sta $7a
        jsr dg_square           ; A = the square
        ldx #dg_kinds - 1
-       cmp dg_val,x
        beq dg_hit
        dex
        bpl -
        cmp #$00
        beq dg_next
        ldx #dg_kinds           ; anything else: '?'
dg_hit: stx dg_x
        lda dg_glyph,x
        jsr glyph
        ldx dg_x
        lda dg_col,x
        jsr dg_colour
dg_next:
        inc $02
        lda $02
        and #$0f
        sta $02
        bne dg_sq
        inc $03
        lda $03
        cmp #$10
        bcc dg_sq

        jsr kb_flush
        clc
        lda party_x
        adc #MAP0
        sta $79
        clc
        lda party_y
        adc #MAP0
        sta $7a
        lda #$10                ; the party: white
        jsr dg_colour
dg_blink:
        lda #$2a                ; '*'
        jsr glyph
        jsr dg_delay
        lda #$20
        jsr glyph
        jsr dg_delay
        jsr kb_get
        cmp #$ff
        beq dg_blink
        jsr kb_flush
        ldx #1                  ; the cells' colours back
        jsr dg_cells
        jsr print_str
        !byte $ff, 0
        jsr redraw
        rts

dg_delay:
        ldx #$00
-       pha
        pla
        dex
        bne -
        rts

;;; the square ($02, $03) of the current level (the original's L94BC)
dg_square:
        clc
        lda $03
        asl
        asl
        asl
        asl
        adc $02
        sta ptr
        clc
        lda #$10
        adc level
        sta ptr+1
        ldy #$00
        lda (ptr),y
        rts

;;; A = the colour byte for the cell ($79, $7A)
dg_colour:
        pha
        ldx $7a
        lda dg_scr_lo,x
        sta ptr
        lda dg_scr_hi,x
        sta ptr+1
        ldy $79
        pla
        sta (ptr),y
        rts

;;; X = 0: the map's cells into SAVED; X = 1: back from it
dg_cells:
        stx dg_x
        ldx #MAP0
dg_c1:  lda dg_scr_lo,x         ; ptr = the row's cell MAP0
        clc
        adc #MAP0
        sta ptr
        lda dg_scr_hi,x
        adc #0
        sta ptr+1
        txa                     ; SAVED + (row - MAP0) * 16
        sec
        sbc #MAP0
        asl
        asl
        asl
        asl
        sta dg_s1+1
        sta dg_s2+1
        ldy #0
dg_c2:  lda dg_x
        bne dg_back
        lda (ptr),y
dg_s1:  sta SAVED,y
        jmp dg_c3
dg_back:
dg_s2:  lda SAVED,y
        sta (ptr),y
dg_c3:  iny
        cpy #16
        bne dg_c2
        inx
        cpx #MAP0 + 16
        bne dg_c1
        rts
!if <SAVED != 0 { !error "SAVED must be page aligned" }

;;; the squares the original tells apart, their glyphs and now colours
;;; (glyph in the cell's colour on black)
dg_val:   !byte $c0, $a0, $80, $30, $20, $10
dg_kinds = * - dg_val
dg_glyph: !byte $5f, $5e, $40, $5b, $5c, $5d, $3f
dg_col:   !byte $80, $40, $c0, $30, $70, $d0, $a0
;;;         $C0    $A0    $80    $30    $20    $10    anything else
;;;         orange purple grey   cyan   yellow lgreen light red
;;; ($80 walls, $C0 doors and $A0 secret doors, $10-$30 the ladders, by
;;; their counts in the level maps -- inferred, not traced in DDRW)
dg_x:     !byte 0
dg_scr_lo:
!for r, 0, 24 { !byte <(SCREEN + r * 40) }
dg_scr_hi:
!for r, 0, 24 { !byte >(SCREEN + r * 40) }
dg_end:
!if dg_end > SAVED { !error "u3dngm.s runs into its buffer" }
