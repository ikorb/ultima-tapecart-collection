;;; efstub.s -- the Ultimax reset stub, in bank 0's ROMH at 00:1:1B18 (the
;;; cart starts in Ultimax mode, so this is $FB18 and the vectors at $FFFA
;;; are ours).  ProgRef's start-up, as EasySDK's banking-test does it: the
;;; stack page, a stub there that turns 16K mode on, lets Run/Stop, C= or Q
;;; held at power-on kill the cart (into BASIC), initialises the machine as
;;; the KERNAL's reset would, and goes on to the start code in bank 0's
;;; ROML at $8000.

!source "efvars.inc"

        * = $fb18
cold:   sei
        ldx #$ff
        txs
        cld
        lda #$08                ; the VIC on (RAM refresh)
        sta $d016
-       sta $0100,x             ; RAM written once before it is trusted
        dex
        bne -
        ldx #su_end - su_code - 1
-       lda su_code,x
        sta $0100,x
        dex
        bpl -
        jmp $0100

su_code:
!pseudopc $0100 {
        lda #EF_16K_LED
        sta EF_CTRL_REG
        lda #$7f                ; row 7: Run/Stop, Q, C=
        sta $dc00
        ldx #$ff
        stx $dc02
        inx
        stx $dc03
        lda $dc01
        stx $dc02
        stx $dc00
        and #$e0
        cmp #$e0
        bne kill
        ldx #$00
        stx $d016
        jsr $ff84               ; IOINIT
        jsr $ff87               ; RAMTAS
        jsr $ff8a               ; RESTOR
        jsr $ff81               ; CINT
        jmp $8000
kill:   lda #EF_OFF
        sta EF_CTRL_REG
        jmp ($fffc)
}
su_end:

nmi:    rti
        !fill $fffa - *, $ff
        !word nmi, cold, nmi
