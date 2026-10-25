;;; efend.s -- the ending overlay's loader on EasyFlash.
;;;
;;; The ending's code overlay (1A/1B T23 S16-18 at $C800) loads `end` with a
;;; loader of its own at $C8C2, since `end` fills $0200-$7599 -- `game` and
;;; its driver included (ultima/games/u6/u6end.s says more).  This goes in its
;;; place, same address, same contract: X/Y -> a descriptor chain ("%NAME",
;;; $00 = another follows / $80+ = the last, then the destination), C clear
;;; when done and $01 = $34 on return.  It is called twice:
;;;
;;;   $C86F  %THEME2 -> $9000
;;;   $C879  %ICHARS -> $8000, %END -> $0200
;;;
;;; Those three names are all it ever loads, so their places in flash are
;;; built in (E_FILES, from ultima/ef/build.py) and it needs no directory and no
;;; driver: a copy with the cart in 16K mode, interrupts off throughout --
;;; `end` lands on page 3, the KERNAL's IRQ vector, as it goes, and the music
;;; can wait the third of a second.  Everything here lives in $C8C2-$CAFF.

!source "efvars.inc"

        * = $c8c2
e_load: stx e_rd+1
        sty e_rd+2
        php
        sei
        lda #$37
        sta $01
        lda #EF_16K
        sta EF_CTRL_REG

e_next: jsr e_byte              ; the name, "%" and all, zero padded
        ldy #$00
-       cmp #$00
        beq +
        cmp #$80
        bcs +
        sta e_key,y
        iny
        jsr e_byte
        jmp -
+       sta e_term
        lda #$00
-       cpy #KEYLEN
        beq +
        sta e_key,y
        iny
        bne -
+       jsr e_byte              ; the destination
        sta e_dst+1
        jsr e_byte
        sta e_dst+2

        lda #$00                ; which of the three?
        sta e_ix
e_find: ldx e_ix
        ldy #$00
-       lda e_files,x
        cmp e_key,y
        bne e_miss
        inx
        iny
        cpy #KEYLEN
        bne -
        ldy #$00                ; found: address (3), length (2)
-       lda e_files,x
        sta e_a,y
        inx
        iny
        cpy #$05
        bne -
        jsr e_copy
        lda e_term
        bne e_done              ; $80+: that was the last
        jmp e_next
e_miss: lda e_ix                ; the next name
        clc
        adc #E_STRIDE
        sta e_ix
        cmp #3 * E_STRIDE
        bcc e_find
        lda #EF_OFF             ; not one of them: the caller retries -- a
        sta EF_CTRL_REG         ; hang, visibly
        lda #$34
        sta $01
        plp
        sec
        rts
e_done: lda #EF_OFF
        sta EF_CTRL_REG
        lda #$34
        sta $01
        plp
        clc
        rts

e_byte:
e_rd:   lda $ffff
        inc e_rd+1
        bne +
        inc e_rd+2
+       rts

;;; e_l bytes from the linear address e_a to e_dst, a byte at a time with
;;; the bank switched as the source crosses into the next
e_copy: lda e_a+2
        sta e_bank
        lda e_a+1
        asl
        rol e_bank
        asl
        rol e_bank
        lda e_bank
        sta EF_BANK_REG
        lda e_a
        sta e_src+1
        lda e_a+1
        and #$3f
        ora #$80
        sta e_src+2
ec_loop:
        lda e_l
        ora e_l+1
        beq ec_out
e_src:  lda $ffff
e_dst:  sta $ffff
        inc e_dst+1
        bne +
        inc e_dst+2
+       inc e_src+1
        bne +
        inc e_src+2
        lda e_src+2
        cmp #$c0
        bne +
        lda #$80
        sta e_src+2
        inc e_bank
        lda e_bank
        sta EF_BANK_REG
+       lda e_l
        bne +
        dec e_l+1
+       dec e_l
        jmp ec_loop
ec_out: rts

e_term: !byte 0
e_bank: !byte 0
e_a:    !fill 3, 0
e_l:    !word 0
e_key:  !fill KEYLEN, 0
e_ix:   !byte 0
;;; three entries: key (12, zero padded), address (3), length (2)
E_STRIDE = KEYLEN + 5
e_files:
        !fill 3 * E_STRIDE, $ff ; filled in by ultima/ef/build.py

e_end:
!if e_end > $cb00 {
        !error "efend runs past the overlay's three sectors by ", e_end - $cb00
}
