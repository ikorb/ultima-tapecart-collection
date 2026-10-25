;;; u1view.s -- Ultima I's outdoor view drawn only where it changed.
;;;
;;; ST's view renderer ($1C8A, through $166A and every key poll, $1E50) draws
;;; all 19 x 9 tiles into the hidden bitmap and flips it ($1DB2 JSR $1700),
;;; then steps the animation ($1DB5):
;;; 32 bitmap bytes and four colour bytes a tile, ~112k cycles, and a key
;;; poll is one draw.  Here each bitmap keeps a record of the tile drawn in
;;; every cell, in the bitmap's own tail, which the VIC does not show:
;;; $3F40-$3FEA for the one at $2000 ($5C = 0), $5F40-$5FEA for the one at
;;; $4000 ($5C = $60), row r's cells at 19 r on, then a byte that is $80
;;; while the record holds ($3FEB, $5FEB).  A cell whose tile is the one the
;;; record has is not drawn again.  ST $1DB5 animates tiles 0 (water), 4, 6
;;; and 12 by changing their bytes in place, so one of those is recorded as
;;; $FF, which no tile matches, and drawn every time.  Monsters' frames are
;;; tiles of their own.  The rest is ST's code as it was: the rows read from
;;; the map at $6400 (off the map, water), a key read a row ($1ED5), the
;;; party's tile at the centre, the cells right to left, the same zero page
;;; left as ST leaves it but for $5E (the last colour drawn, which every key
;;; read overwrites).
;;;
;;; The record is dropped (its byte shifted right, which never leaves $80
;;; and keeps A, X and Y; none of the routines hooked reads the flags) by
;;; whatever else draws in a bitmap: ST's jump
;;; table entries for the screen's set-up ($163A), the view's clear ($1661),
;;; a flip that is not the renderer's ($1664: what was drawn into the
;;; hidden bitmap is not the record's), points and lines ($168E, $1691,
;;; $1694); text in rows 0-18 (a character, $1A78, from anywhere; a scroll,
;;; $1649; the clearing of a row, $164C/$164F, or of the window, $1652,
;;; when the window's top or the cursor is there); and OU's start ($8C9E),
;;; after any other overlay, which may have drawn without ST.  ST's copy of
;;; one bitmap over the other ($1646 -> $1723, all 32 pages) takes the
;;; record and its byte along with it.  A whole bitmap cleared to zero
;;; clears the byte too.
;;;
;;; The text window's usual scroll is one pass here too (h_scroll, below).
;;;
;;; The animation goes by the clock (anim, below).
;;;
;;; Four sections: the renderer in place of ST's, its helpers after ST's
;;; end ($1F87-$1FFD, which nothing uses; ST's unit is longer by them), the
;;; hooks in the tape buffer and the unused bytes around it ($0334-$03FF)
;;; and the animation in the KERNAL's unused $02A7-$02FF, two boot segments
;;; of their own; and ST $1A78's first bytes, a JMP to its hook.

CACHE   = $3f40                 ; the record of the bitmap at $2000
FLAG    = CACHE + 9 * 19        ; $3FEB
VALID   = $80

rows_lo = $1200                 ; ST: bitmap row n * 8 -> address, low
rows_hi = $12c0                 ; ... high (the bitmap at $2000)
scr_lo  = $1600                 ; ST: screen row -> address, low
scr_hi  = $1619                 ; ... high (the screen at $0400)
t_lo    = $1480                 ; ST: tile -> its 32 bytes at $0C00, low
t_hi    = $14c0                 ; ... high
t_col   = $1500                 ; ST: tile -> its colour
frames  = $b700                 ; a monster's frame bit (OU's world data)
frame_i = $178e                 ; ST: the index into it
party_t = $1639                 ; ST: the party's tile * 2
key_rd  = $1ed5                 ; ST: read the keyboard, N set if a key
key_q   = $1e0d                 ; ST: ... put it in the game's queue

;;; ==================================================================
;;; The animation by the clock, in the KERNAL's unused $02A7-$02FF
;;;
;;; ST steps its animation ($1DB5: the water, the castle's and the town's
;;; flags, tile 12) after every draw, and a monster's frame is picked anew
;;; at every draw ($178E on into $B700).  A draw was six frames; here it is
;;; two to four.  So the step is taken before a draw, and only when six
;;; ticks of CIA 2's timer B have passed since the last (timer A runs out
;;; once a frame on a PAL machine, every 1/50 s on NTSC: init_u1.s), once,
;;; from now on if two or more were missed (the view was away); between
;;; steps the monsters' frames are drawn as at the last, $178E put back.
;;; $1DB5 ends in ST's key read ($1E08) and its RTS.
        * = $02a7

anim:   lda a_last
        sec
        sbc $dd06               ; ticks since the last step (B counts down)
        cmp #6
        bcc a_hold
        cmp #12
        bcs +                   ; two or more missed: the step from now
        lda #6
+       eor #$ff
        sec
        adc a_last
        sta a_last
        lda frame_i
        sta a_frame
        jmp $1db5
a_hold: lda a_frame
        sta frame_i
        rts
a_last: !byte 0
a_frame:
        !byte 0
anim_end:

;;; ==================================================================
;;; The hooks, in the tape buffer and the KERNAL's spare bytes around it
        * = $0334

;;; the record of both bitmaps dropped; A, X and Y kept
drop:   lsr FLAG
        lsr FLAG + $2000
        rts

;;; ST's jump table entries that draw in a bitmap
h_setup:
        jsr drop
        jmp $178f
h_clear:
        jsr drop
        jmp $16ad
h_flip: jsr drop
        jmp $1700
h_point:
        jsr drop
        jmp $17ed
h_line: jsr drop
        jmp $1866
h_line2:
        jsr drop
        jmp $186a

;;; text: only in rows 0-18 (the window's top $30, the cursor's row $33)
text:   pha
        lda $30
        cmp #19
        bcc +
        lda $33
        cmp #19
        bcs ++
+       jsr drop
++      pla
        rts

;;; ST $1649, the scroll.  The usual window -- columns 0-29 of rows 20-23
;;; ($2E-$31 = 0, 30, 20, 24) with both bitmaps in use ($5D = $60) -- in one
;;; pass over its 240 columns of bytes: rows 21-23 up a row in both bitmaps,
;;; read from the one at $2000 as ST does, and row 23 filled with $1F; then
;;; what ST's leaves: the colour bytes it sets, the cursor at row 23 column
;;; 0, its counters ($43 = 0, $5F = $FF), X = 23 * 8, Y = $EF, and a key
;;; read ($1E08), as it ends.  ST's own ($1910) for any other window.
W_ROW   = $2000 + 20 * 320      ; $3900: row 20, column 0
h_scroll:
        ldx #3
-       lda $2e,x
        cmp window,x
        bne scroll
        dex
        bpl -
        lda $5d
        cmp #$60
        bne scroll
        lda #$60
        sta $0720
        sta $0748
        sta $0770
        sta $6320
        sta $6348
        sta $6370
        ldy #240
-       lda W_ROW + 320 - 1,y
        sta W_ROW - 1,y
        sta W_ROW + $2000 - 1,y
        lda W_ROW + 640 - 1,y
        sta W_ROW + 320 - 1,y
        sta W_ROW + $2000 + 320 - 1,y
        lda W_ROW + 960 - 1,y
        sta W_ROW + 640 - 1,y
        sta W_ROW + $2000 + 640 - 1,y
        lda $1f
        sta W_ROW + 960 - 1,y
        sta W_ROW + $2000 + 960 - 1,y
        dey
        bne -
        sty $32
        sty $43
        dey
        sty $5f
        lda #23
        sta $33
        ldx #23 * 8
        ldy #$ef
        jmp $1e08
scroll: jsr text
        jmp $1910
window: !byte 0, 30, 20, 24
h_row:  jsr text
        jmp $199e
h_eol:  jsr text
        jmp $19a6
h_win:  jsr text
        jmp $1a48
h_char: pha                     ; ST $1A78's first two instructions
        stx $1b05
        jsr text
        jmp $1a7c

;;; OU $8C9E's first two instructions, after the record is dropped
h_ou:   jsr drop
        lda #$30
        sta $01
        rts

hooks_end:

;;; ==================================================================
;;; ST $1C8A: the view
        * = $1c8a

view:   jsr setup
row:    jsr key_rd
        bpl +
        jsr key_q
+       lda $47
        cmp #$40
        bcs off_map
        lsr
        sta $4d
        lda #$00
        ror
        lsr $4d
        ror
        sta $4c
        lda $4d
        adc #$64
        sta $4d                 ; $6400 + 64 y
        ldx #$00
        ldy $46
fetch:  cpy #$40
        bcc +
        lda #$00                ; off the map: water
        beq ++
+       lda ($4c),y
        and #$7e
        cmp #$20
        bcc ++
        cmp #$59
        bcs ++
        stx $48                 ; a monster: one of its two frames
        sta $49
        inc frame_i
        ldx frame_i
        lda frames,x
        and #$02
        adc $49
        ldx $48
++      lsr
        sta $66,x
        inx
        iny
        cpx #19
        bcc fetch
        bcs fetched
off_map:
        ldx #18
        lda #$00
-       sta $66,x
        dex
        bpl -
fetched:
        lda $47
        inc $47
        cmp $21
        bne +
        lda party_t             ; the party's row: its tile in the middle
        lsr
        sta $6f
+       ldx $45
        lda rows_lo,x
        clc
        adc #$28                ; column 37, the rightmost cell's left half
        sta $60
        lda rows_hi,x
        adc #$01
        eor $5c
        sta $61
        lda $60
        adc #$40                ; the char row under it
        sta $62
        lda $61
        adc #$01
        sta $63
        lda $45
        lsr
        lsr
        lsr
        tay
        lda scr_lo,y
        sta $64
        lda scr_hi,y
        ldx $5c
        beq +
        clc
        adc #$5c
+       sta $65
        ldx #18
cell:   ldy $66,x
        tya
rd:     cmp CACHE,x
        beq skip
        jsr mark
wr:     sta CACHE,x
        lda t_col,y
        sta $5e
        lda t_lo,y
        sta src + 1
        clc
        adc #$10
        sta src2 + 1
        lda t_hi,y
        sta src + 2
        adc #$00
        sta src2 + 2
        ldy #$0f
src:    lda $0c00,y
        sta ($60),y
src2:   lda $0c10,y
        sta ($62),y
        dey
        bpl src
        txa
        asl
        tay
        iny
        lda $5e
        sta ($64),y
        iny
        sta ($64),y
        tya
        clc
        adc #$28
        tay
        lda $5e
        sta ($64),y
        dey
        sta ($64),y
skip:   lda $60
        sec
        sbc #$10
        sta $60
        lda $61
        sbc #$00
        sta $61
        lda $62
        sec
        sbc #$10
        sta $62
        lda $63
        sbc #$00
        sta $63
        dex
        bpl cell
        jsr next_row
        bcs +
        jmp row
+
view_flip:
        jsr $1700               ; the flip
        jmp $1e08               ; a key read and RTS, as ST's ends (its
view_end:                       ; animation at $1DB5 is anim's, below)

;;; ==================================================================
;;; After ST's end: the renderer's helpers
        * = $1f87

;;; the renderer's start: the animation by the clock; the record of the
;;; bitmap it draws in ($5C), and if it does not hold, $FF in every cell;
;;; then ST's own start
setup:  jsr anim
        lda #>CACHE
        eor $5c
        sta rd + 2
        sta wr + 2
        sta fl + 2
        sta fl2 + 2
        sta fill + 2
        lda #<CACHE
        sta rd + 1
        sta wr + 1
fl:     lda FLAG
        cmp #VALID
        beq +
        lda #$ff                ; no tile is $FF: every cell drawn
        ldy #9 * 19
fill:   sta CACHE - 1,y
        dey
        bne fill
        lda #VALID
fl2:    sta FLAG
+
        lda #$08                ; bitmap row 1 (* 8): the view's top
        sta $45
        sec
        lda $20
        sbc #$09
        sta $46                 ; the leftmost column's x
        sec
        lda $21
        sbc #$04
        sta $47                 ; the top row's y
        rts

;;; a row done: the next row's record, and C set after the last
next_row:
        lda rd + 1
        clc
        adc #19
        sta rd + 1
        sta wr + 1
        lda $45
        clc
        adc #$10
        sta $45
        cmp #$98
        rts
;;; A cell to draw, Y its tile: A the tile to record, $FF for one ST animates
mark:   tya
        beq +
        cmp #4
        beq +
        cmp #6
        beq +
        cmp #12
        bne ++
+       lda #$ff
++      rts
tail_end:

;;; ==================================================================
;;; ST $1A78, a character: through the hook
        * = $1a78
        jmp h_char
char_end:
