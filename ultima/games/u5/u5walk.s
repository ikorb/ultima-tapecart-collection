; Ultima V, main.twn $A30F: the town's walkability map, without a call a byte.
;
; Every time a townsperson looks for a way somewhere, $A30F turns the
; town's 32 x 32 map ($4400-$47FF, four 16 x 16 blocks) into a walkability
; map at $BC00 (32 bytes a row): each tile through main.twn's table at
; $9F92 ($00 or $77), the tile the search is after ($A201) as $80 -- 16
; bytes a call of $A35C, each through `JSR $9F85` and an indirect store,
; ~53 cycles a byte, 54k a map, now and then several a turn.  Here the
; sought tile's entry in the table is made $80 for the while (and put back
; after), so a byte is LDA / TAX / LDA / STA: ~22 cycles.  The 16 bytes are
; done by w_seg, in main.subs (resident in town: the room there is the
; view's old lit-square helper $515E, which u5buf.s left without a caller);
; the driver keeps its place and the original's order, and its tail moves
; into $A35C, the old 16-byte routine (called only from here).
;
; The same in every other way: $A1FD/$A1FE cleared (before the build here:
; nothing reads them while it runs), $FC-$FF left as the original left them
; ($FC 0, $FD $48, $FE/$FF $C000), the table as it was.  A, X and Y differ:
; both callers ($A205, then $A345, which loads Y first; $A225, then LDX #$1F
; / LDA) load what they use.

table   = $9F92
sought  = $A201

        * = $A30F                       ; main.twn
w_drv   ldx sought
        lda table,x
        pha
        lda #$80
        sta table,x
        lda #$00
        sta $FE
        sta $FC
        sta $A1FD
        sta $A1FE
        lda #$BC
        sta $FF
        lda #$44
        sta $FD
w_row   jsr w_seg                       ; a row's left half
        inc $FD
        jsr w_seg                       ; and right half
        dec $FD
        lda $FC
        clc
        adc #$10
        sta $FC
        bne w_row
        jmp w_tail
w_drv_end
        !if w_drv_end > $A345 { !error "the walkability driver reaches $A345" }

        * = $A35C                       ; main.twn, the old 16-byte routine
w_tail  inc $FD                         ; the lower two blocks next
        inc $FD
        lda $FD
        cmp #$46
        beq w_row
        pla
        ldx sought
        sta table,x
        rts
w_tail_end
        !if w_tail_end > $A373 { !error "the walkability tail reaches $A373" }

        * = $515E                       ; main.subs, the view's old lit-square helper
w_seg   ldy #$0F
-       lda ($FC),y
        tax
        lda table,x
        sta ($FE),y
        dey
        bpl -
        lda $FE
        clc
        adc #$10
        sta $FE
        bcc +
        inc $FF
+       rts
w_seg_end
        !if w_seg_end > $5184 { !error "the walkability segment reaches $5184" }
