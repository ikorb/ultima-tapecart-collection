;;; efstart.s -- bank 0's ROML at $8000: the launcher (efpage.s) from its
;;; image, $8100 on into ROMH, to LAUNCH_ORG in RAM, and into it.  Nothing
;;; of the game is in memory yet, so zero page is free for the copy.

        * = $8000
        sei
        lda #<LAUNCH_IMG
        sta $fb
        lda #>LAUNCH_IMG
        sta $fc
        lda #<LAUNCH_ORG
        sta $fd
        lda #>LAUNCH_ORG
        sta $fe
        ldx #LAUNCH_PAGES
        ldy #$00
-       lda ($fb),y
        sta ($fd),y
        iny
        bne -
        inc $fc
        inc $fe
        dex
        bne -
        jmp LAUNCH_ORG
start_end:
!if start_end > LAUNCH_IMG {
        !error "the start code runs into the launcher's image"
}
