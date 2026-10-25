; Ultima V, main.subs $4D06: the view's buffers, a row at a time.
;
; For each of the 11 x 11 squares around the party (x = $62 + column, y =
; $63 + row, $62/$63 the party's place in the 32 x 32 window less 5) the
; original called $51AF for the tile ($4880: the window $4400-$47FF, laid
; out as four 16 x 16 blocks, or $47FF for a square outside it) and $515E
; for whether the square is lit ($4980: bit x & 7 of byte 4y + x / 8 of the
; bitmap at $7E80, 0 or 1), working both out again from x and y each time:
; ~170 cycles a square, 21k a turn.  Here a row's pointers are worked out
; once (here) and the squares of the row are done by u5bufcells (in
; update.himem, after the draw: there is no room here).  A row outside the
; window is done by the same loop, started at x = $20, which is outside all
; through.
;
; The same results and the same values left in $60 (0), $61 (11), $62,
; $63, $66 (121) and A (11).  Left differently: $FC/$FD and $BE, which
; $51AF and $515E set as a side effect and nothing reads before writing:
; the whole view update writes $FC/$FD again, and every read of $BE in the
; game's files follows a write to it in the same routine (ENTER.PLAY
; $82BF/$82FB, MAIN.SUBS $6265, $62BA, $6A70, MAIN.OUT $97BD, $9897,
; MAIN.TWN $9884, S $B6A5 -- a scan of all 236 files on the eight disks).

        * = $4D06

cells   = u5bufcells            ; update.himem: -Du5bufcells=...
ptrl    = u5buf_l               ; its self-modified operands
ptrr    = u5buf_r

buf     sec
        lda $02
        sbc #$05
        sta $62
        sec
        lda $03
        sbc #$05
        sta $63
        ldy #$00
        sty $61
row     ldx #$20                ; a row outside the window: every square out
        lda $63
        clc
        adc $61
        cmp #$20
        bcs +
        tax                     ; the row's place in the window's four blocks
        lda $51F2,x             ; (C is clear)
        sta ptrl + 1
        adc #$F0                ; the right-hand blocks: $F0 on, so that + x
        sta ptrr + 1            ; for x >= 16 lands 256 on
        lda $51D2,x
        sta ptrl + 2
        adc #$00
        sta ptrr + 2
        txa                     ; A: the row's first byte of the lit bitmap
        asl
        asl
        ora #$80
        ldx $62
+       jsr cells
        inc $61
        lda $61
        cmp #$0B                ; (A = 11 at the end, as the original left it)
        bcc row
        sty $66
        rts

buf_end
        !if buf_end > $4D51 { !error "the buffers reach $4D51" }
