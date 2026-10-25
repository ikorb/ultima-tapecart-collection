;;; efhook.s -- xyzzy's C64 path with the Ultima VI EasyFlash cart: the
;;; music's stage from the cart (armusic.s EF_MUSIC).
;;;
;;; ultima/ef/efu5.s puts this over the Action Replay's hook (armhook.s) in
;;; the xyzzy it read from the tapecart, so it runs where that one does: at
;;; $2090, the drive prompt's tail, which the collection jumps over ($208D),
;;; with $01 = $26, the driver up and nothing of the game's above $4000 yet.
;;; There is no looking: the launcher only starts Ultima V this way with
;;; the EasyFlash in.  The music's bank is selected, the cart mapped in 16K
;;; mode just long enough to copy the stage from it to $4000, and arinit
;;; does the rest, as the AR's hook has it do.
;;;
;;; Defined by build.py: BANK, STAGE_ROM (where the stage is in the bank, as
;;; the CPU sees it), STAGE_PAGES, STAGE.

EF_BANK_REG = $de00
EF_CTRL_REG = $de02
EF_16K      = $07
EF_OFF      = $04

        * = $2090
        php
        sei
        lda #$27                ; LORAM and HIRAM: ROML and ROMH; motor off
        sta $01                 ; (every write of the cart's registers is at
        lda #BANK               ; $01 = $27, as the glue's)
        sta EF_BANK_REG
        lda #EF_16K
        sta EF_CTRL_REG
        ldx #STAGE_PAGES
        ldy #$00
from:   lda STAGE_ROM,y
to:     sta STAGE,y
        iny
        bne from
        inc from + 2
        inc to + 2
        dex
        bne from
        lda #EF_OFF
        sta EF_CTRL_REG
        lda #$26
        sta $01
        plp
        jsr STAGE
        jmp $20d5
!if * > $20d5 {
        !error "the hook runs into $20D5 by ", * - $20d5
}
