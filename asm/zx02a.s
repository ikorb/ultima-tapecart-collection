;;; zx02a.s -- zx02 streaming decoder with NO zero page.
;;;
;;; The same decoder as zx02s.s (plain `zx02` format, input pulled through
;;; zx_getbyte), but the two (zp),y pointers are replaced by self-modified
;;; absolute operands, the way tclib's transfer loops are.  For hosts that
;;; decode with interrupts ENABLED (Ultima 6, whose music plays from the IRQ
;;; during loads): zx02s.s saves and restores four zero-page bytes, which is
;;; only safe while no interrupt handler can look at them.
;;;
;;;   zx_put   -- the one store, `sta $ffff` with the output pointer as its
;;;               operand; both copy loops call it
;;;   zx_get   -- the match read, `lda $ffff,y` with Y = the output pointer's
;;;               low byte, exactly what `lda (pntr),y` computed
;;;
;;; Contract: set the destination with `lda #lo / sta zx_put+1 / lda #hi /
;;; sta zx_put+2` (or zx_setdst), open the stream, jsr zx_unpack, close it.
;;; zx_getbyte must preserve X, Y and the carry (tc_stream_byte does).

zx_unpack:
        lda #$80
        sta zx_bitr
        lda #$ff                ; last offset = 1
        sta zx_get+1
        ldy #$00
        sty zx_offhi
        ldx #$00

zx_literal:
        inx
        jsr zx_elias
-       jsr zx_getbyte
        jsr zx_put
        dex
        bne -
        asl zx_bitr
        bcs zx_newoff

        inx
        jsr zx_elias
zx_copy:
        lda zx_put+2
        sbc zx_offhi            ; C=0 from zx_elias
        sta zx_get+2
-       ldy zx_put+1
        jsr zx_get
        jsr zx_put_inc          ; store, and carry the match page along
        dex
        bne -
        asl zx_bitr
        bcc zx_literal

zx_newoff:
        inx
        jsr zx_elias
        beq zx_done             ; the end marker
        dex
        txa
        lsr
        sta zx_offhi
        jsr zx_getbyte          ; carry from the lsr survives the call
        ror
        eor #$ff
        sta zx_get+1
        ldx #$01
        jsr zx_skip1
        inx
        bcc zx_copy

zx_elias_get:
        asl zx_bitr
        rol
        tax
zx_elias:
        asl zx_bitr
        bne zx_skip1
        jsr zx_getbyte          ; carry (the bit shifted out) survives
        rol
        sta zx_bitr
zx_skip1:
        txa
        bcs zx_elias_get
zx_done:
        rts

zx_get: lda $ffff,y
        rts

;;; store A at the output pointer and advance it; the match copy also
;;; advances its source page when the output page does
zx_put_inc:
        jsr zx_put
        bne +
        inc zx_get+2
+       rts

zx_put: sta $ffff
        inc zx_put+1
        bne +
        inc zx_put+2
        lda #$00                ; Z clear on the common path below, set here
+       rts

zx_bitr:  !byte 0
zx_offhi: !byte 0
