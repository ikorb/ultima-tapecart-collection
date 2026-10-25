; Ultima V, update.himem $1DE4: the view's draw, with absolute operands.
;
; The 11 x 11 view, every cell every turn: the cell's tile ($4800, or for 0
; the object layer $4900: $F8 is tile 4, $FF tile 0, anything else an
; object, drawn from the object bank) as 32 bitmap bytes from the tile set
; ($C000 + 32t, objects $E000 + 32t: 16 bytes for the upper two characters,
; 16 for the lower, 320 further on) and four screen bytes ($0800 + 4t,
; objects $0C00 + 4t: 2 above, 2 below).  The original worked out the
; addresses with shifts through zero page and copied through (zp),Y -- 13
; cycles a byte, 633 a cell, 77k a turn.  Here the bitmap source and the
; destinations are the operands of a 16-pass loop (lda abs,X / sta abs,X,
; ~11.5 cycles a byte); the screen bytes still go through ($50),Y and
; ($52),Y, as the original's did.
;
; The same in every other way: $50-$5C are saved to $7F00-$7F0C first and
; put back last (so what is left in them in between does not matter --
; $52/$53 and $5B/$5C are still used as the original used them), $0A35 =
; $90, $6C06 first, $01 = $26 (the original's $06 with the motor bit, which
; build.py MOTOR puts into update.himem) and $FF00 = $0E last, and on a C128
; ($C8 bit 7) the calls through $1D89 where the original made them, with
; interrupts let in between rows.  The original's helper at $1F62 (called
; only from here) is gone.

        * = $1DE4

zsave   = $7F00
cell    = $5B                   ; the original's: this cell, and the row's end
rowend  = $5C
scr     = $52                   ; the cell's screen bytes
col     = $50                   ; its screen bytes' source
t       = $54                   ; scratch from here on
gbank   = $55
cbank   = $56

draw    ldx #$0C
-       lda $50,x
        sta zsave,x
        dex
        bpl -
        lda #$51
        sta scr
        lda #$04
        sta scr + 1
        lda #$88                ; the first cell's bitmap: $2288, $2288 + 320 + 16
        sta top + 1
        lda #$22
        sta top + 2
        lda #$C8
        sta bot + 1
        lda #$23
        sta bot + 2
        lda #$00
        sta cell
        lda #$0B
        sta rowend
        lda $C8
        bpl +
        sei
        jsr $1D89
+       jsr $6C06
        lda #$90
        sta $0A35

row     ldy cell
next    ldx #$08                ; the tile set and its colours
        lda #$C0
        sta gbank
        lda $4800,y
        bne go
        lda $4900,y             ; nothing there: the object layer
        cmp #$F8
        bne +
        lda #$04
        bne go
+       cmp #$FF
        bne obj
        lda #$00
        beq go
obj     ldx #$E0                ; an object
        stx gbank
        ldx #$0C
go      stx cbank
        sta t
        lsr                     ; bitmap: bank + 32t
        lsr
        lsr
        ora gbank
        sta src1 + 2
        sta src2 + 2
        lda t
        asl
        asl
        sta col                 ; colours: bank + 4t
        asl
        asl
        asl
        sta src1 + 1
        ora #$10
        sta src2 + 1
        lda t
        rol
        rol
        rol
        and #$03
        ora cbank
        sta col + 1
        ldy #$00                ; the four screen bytes
        lda (col),y
        sta (scr),y
        iny
        lda (col),y
        sta (scr),y
        iny
        lda (col),y
        ldy #$28
        sta (scr),y
        ldy #$03
        lda (col),y
        ldy #$29
        sta (scr),y
        ldx #$0F                ; the 32 bitmap bytes
src1    lda $C000,x
top     sta $2288,x
src2    lda $C010,x
bot     sta $23C8,x
        dex
        bpl src1
        clc                     ; on to the next cell: 16 bitmap bytes, 2 screen bytes
        lda top + 1
        adc #$10
        sta top + 1
        bcc +
        inc top + 2
        clc
+       lda bot + 1
        adc #$10
        sta bot + 1
        bcc +
        inc bot + 2
        clc
+       lda scr
        adc #$02
        sta scr
        bcc +
        inc scr + 1
+       inc cell
        ldy cell
        cpy rowend
        bcs +
        jmp next

+       lda $C8                 ; the row's end
        bpl +
        jsr $1D89
        cli
        sei
        jsr $1D89
+       clc                     ; down two character rows, back 11 cells
        lda top + 1
        adc #$D0
        sta top + 1
        lda top + 2
        adc #$01
        sta top + 2
        clc
        lda bot + 1
        adc #$D0
        sta bot + 1
        lda bot + 2
        adc #$01
        sta bot + 2
        clc
        lda scr
        adc #$3A
        sta scr
        bcc +
        inc scr + 1
+       lda rowend
        clc
        adc #$0B
        sta rowend
        cmp #$7D
        bcs +
        jmp row

+       lda #$26
        sta $01
        lda #$0E
        sta $FF00
        lda $C8
        bpl +
        jsr $1D89
+       cli
        ldx #$0C
-       lda zsave,x
        sta $50,x
        dex
        bpl -
        rts

; ---------------------------------------------------------------------------
; The squares of one row of the view's buffers, for main.subs $4D06
; (u5buf.s: its header says what and why here).  In: X = the first square's
; x (from $20 on, all out of the window), Y = its cell, A = the row's first
; byte of the lit bitmap ($80 + 4y), the row's block operands set.  Out: Y
; on 11, $60 = 0.

u5bufcells
        sta u5buf_base + 1
        lda #$0B
        sta $60
-       cpx #$20
        bcs out
        cpx #$10
        bcs +
u5buf_l lda $4400,x             ; the left-hand blocks
        bcc ++
+
u5buf_r lda $4400,x             ; the right-hand blocks
++      sta $4880,y
        txa
        pha
        and #$07
        tax
        lda $6A9C,x
        sta bitm + 1
        pla
        tax
        lsr
        lsr
        lsr
u5buf_base
        ora #$80                ; the row's first bitmap byte, $7E80 + 4y
        sta litb + 1
litb    lda $7E80
bitm    and #$00
        beq lit
        lda #$01
lit     sta $4980,y
        iny
        inx
        dec $60
        bne -
        rts
out     lda $47FF               ; outside the window
        sta $4880,y
        lda #$00
        beq lit

draw_end
        !if draw_end > $1F8B { !error "the draw reaches $1F8B" }
