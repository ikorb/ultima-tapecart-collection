;;; c128fast.s -- the C128 build's reads into bank 1, in common RAM.
;;;
;;; The C128 build of the driver has 26 bytes free in bank 0; its 2-bit read
;;; (TC_GUARD's, sub128.s b1_pick / b1_get) needs ~150, so it is in bank 1,
;;; and tclib reaches it through these: C_PICK is its TC_PICK routine
;;; (tc_host_pick), C_GET its fetch (TC_FETCH), both into bank 1 with the I/O
;;; in, and C_BACK the way back to bank 0 with all RAM, where every transfer
;;; runs (u5drv.s u5_enter).  A is the result both ways; X is clobbered, as
;;; tclib's own receive clobbers it; Y is kept.
;;;
;;; Two pieces, in the two gaps of common RAM left: C_PICK/C_GET after C_B0
;;; ($0113-$0122, under the music's code at $0123) and C_BACK after C_CFG
;;; ($0297-$029C).  acme emits one blob from $0113; build.py slices it.
;;; Defined by build.py: B1_PICK, B1_GET (sub128.s's b1_pick, b1_get).

!source "c128.inc"

        * = C_PICK
        lda #MMU_B1IO
        sta $ff00
        jmp B1_PICK
!if * != C_GET {
        !error "C_GET moved: ", *
}
        lda #MMU_B1IO
        sta $ff00
        jmp B1_GET
c_fast_end:
!if c_fast_end > C_FAST_END {
        !error "C_PICK/C_GET run into the music's code at $0123"
}

        * = C_BACK
        ldx #MMU_B0
        stx $ff00
        rts
c_back_end:
!if c_back_end > C_BACK_END {
        !error "C_BACK runs past the BASIC input buffer"
}
