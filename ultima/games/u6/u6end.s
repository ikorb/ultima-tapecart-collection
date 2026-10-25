;;; u6end.s -- the ending overlay's loader, replaced.
;;;
;;; The ending is started by a code overlay (disk 1A/1B, track 23 sectors
;;; 16-18, loaded to $C800 by `game`'s overlay table at $2C80).  It cannot use
;;; `game`'s loader: `end` fills $0200-$7599, `game` included, so the overlay
;;; carries a loader of its own at $C8C2 -- serial code for the drive, which
;;; is not there, so on the cart the ending hung.  It is called twice, with
;;; X/Y pointing at the overlay's own descriptor chains (same format as the
;;; resident loader's: "%NAME", $00 = another follows / $FF = last, dest):
;;;
;;;   $C86F  %THEME2 -> $9000               then JSR $9000 (the music)
;;;   $C879  %ICHARS -> $8000, %END -> $0200  then JMP $0200
;;;
;;; This goes in its place, at the same address and with the same contract
;;; (C clear when done, $01 = $34 on return), and asks the cart: every name
;;; is an entry in the static directory, found with DIR_LOOKUP as the boot
;;; driver does.  Where that directory is, it copies from `game`'s resident
;;; on the first call -- the second call's END load overwrites the resident.
;;; The Game-disk files are stored raw, so a load is one READ_FLASH.
;;;
;;; The overlay's IRQ (music, at $C88A) stays on during the loads, as on the
;;; original; build.py patches its `LDA #$35 / STA $01` like the others.
;;; Everything here lives in $C8C2-$CAFF, which no load touches.
;;;
;;; G_SDIR (the resident's u6_sdir) comes from build.py.

TC_NO_CMDMODE = 1
TC_NO_FAST    = 1
TC_NO_STREAM  = 1
TC_NO_ERASE   = 1
TC_NO_WRITE   = 1
TC_IRQ_ON     = 1
TC_NO_C0      = 1
TC_STATIC_01  = $35
TC_STATIC_00  = $2f

!source "u6.inc"

        * = $c8c2
e_load: stx e_rd+1
        sty e_rd+2
        lda #$35
        sta $01
        lda e_have              ; the static directory's address and count,
        bne e_next              ; once, while `game` is still there
        ldx #$04
-       lda G_SDIR,x
        sta e_dir,x
        dex
        bpl -
        inc e_have

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
        sta tc_dest
        jsr e_byte
        sta tc_dest+1

        jsr tc_enter            ; where is it?
        lda #CMD_DIR_SETPARAMS
        jsr tc_sendbyte
        ldy #$00
-       lda e_dir,y
        jsr tc_sendbyte
        iny
        cpy #$05
        bne -
        lda #KEYLEN
        jsr tc_sendbyte
        lda #DATALEN
        jsr tc_sendbyte
        lda #CMD_DIR_LOOKUP
        jsr tc_sendbyte
        ldy #$00
-       lda e_key,y
        jsr tc_sendbyte
        iny
        cpy #KEYLEN
        bne -
        jsr tc_getbyte
        bne e_miss
        ldy #$00                ; address (3) and length (2): tc_addr and
-       jsr tc_getbyte          ; tc_len, contiguous in tclib
        sta tc_addr,y
        iny
        cpy #$05
        bne -
-       jsr tc_getbyte          ; flags and extra: raw files, nothing to do
        iny
        cpy #DATALEN
        bne -
        jsr tc_leave
        jsr tc_read
        lda e_term
        bmi +
        jmp e_next              ; $00: another name follows
+       clc
        !byte $24               ; BIT zp: skip the SEC
e_miss: sec                     ; (the caller retries: a hang, visibly)
        php
        jsr tc_leave
        lda #$34                ; as the original loader left it
        sta $01
        plp
        rts

e_byte:
e_rd:   lda $ffff               ; patched: the descriptor chain
        inc e_rd+1
        bne +
        inc e_rd+2
+       rts

TCLIB_ORG = *
!source "tclib.s"

e_have: !byte 0
e_term: !byte 0
e_dir:  !fill 5, 0
e_key:  !fill KEYLEN, 0

e_end:
!if e_end > $cb00 {
        !error "u6end runs past the overlay's three sectors by ", e_end - $cb00
}
