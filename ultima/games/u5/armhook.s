;;; armhook.s -- xyzzy's C64 path looks for an Action Replay (armusic.s).
;;;
;;; At $2090, the drive prompt's tail, which the collection jumps over
;;; ($208D, build.py XYZZY_PATCHES): $01 is $26 here (I/O in, LORAM clear,
;;; so the AR's RAM cannot appear over anything), the driver is up, and the
;;; game has loaded nothing above $4000 yet.  $DE00 is written, never read.
;;;
;;; With the AR's RAM switched on, its last page answers at $DF00-$DFFF --
;;; and, with LORAM set too, at $9F00-$9FFF through ROML: the same RAM.  So a
;;; byte stored at $DFFF must read back at $9FFF, for two values in turn.
;;; RAM at $DF00 alone is not enough: an EasyFlash has 256 bytes of its own
;;; there, whatever its mode, and its $9FFF is the C64's RAM (or its ROM),
;;; which keeps one value through both stores.  Open I/O2 holds nothing.
;;; $01 goes back to $26 either way; an interrupt in between finds the
;;; KERNAL in, as before.
;;;
;;; If there is one, the stage image comes in from the cart to $4000 and sets
;;; everything up (arinit); if not, nothing else happens and the game runs
;;; as it always did.

        * = $2090
        lda #AR_ON
        sta $de00
        inc $01                 ; $27: LORAM as well, ROML in
        ldx #$a5
-       stx $dfff               ; through I/O2 ...
        cpx $9fff               ; ... and back through ROML
        bne no
        txa
        eor #$ff
        tax
        bpl -                   ; ($A5, then $5A, then done)
        dec $01
        lda #AR_OFF
        sta $de00
        ldx #6                  ; tc_addr (3), tc_len (2), tc_dest (2)
-       lda stage,x
        sta tc_addr,x
        dex
        bpl -
        jsr tc_read
        jsr STAGE
        jmp $20d5
no:     dec $01
        jmp $20d5
stage:  !byte <STAGE_FLASH, >STAGE_FLASH, ^STAGE_FLASH
        !word STAGE_LEN, STAGE
!if * > $20d5 {
        !error "the hook runs into $20D5 by ", * - $20d5
}
