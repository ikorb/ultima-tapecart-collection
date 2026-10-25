;;; tcguard.s -- TC_GUARD's receive and the one read of the VIC tc_pick
;;; needs: the code that runs with I/O banked in.  tclib.s includes it where
;;; it stands; a host whose tclib is in the RAM under I/O (Ultima 4) defines
;;; TC_GUARD_ELSEWHERE and includes this file itself, somewhere else -- the
;;; instructions here are fetched while $D000-$DFFF shows the chips.  The
;;; timed part (tcfast.s) comes with it, since it has to follow the check's
;;; start signal directly.

;;; ==================================================================
;;; tc_getbyte_guard -- the same receive, screen on, sprites off.
;;;
;;; The timed part runs from the start signal (the STX $01 at tc_v_fstart,
;;; 19 cycles after the $D012 read below) to the final STX $01, 53 cycles
;;; later: 72 cycles after the read at most, so it ends at most 9 cycles
;;; into the line after next.  A badline halts the CPU from its cycle 12 to
;;; 54, so the byte may start unless this line or the next is a badline --
;;; the one where (raster - YSCROLL) & 7 is 0, or 7 for the line before.
;;; $D011 is read each time, so a split that changes YSCROLL is followed.
;;; The low three bits of raster - $D011 - 1 are those of raster - YSCROLL
;;; - 1 whatever $D011's other bits, and 6 or 7 there is 7 or 0.  Lines
;;; outside $30-$F7, which never have badlines, are treated alike: two in
;;; eight wait, about 25 cycles a byte on average.  tests/test_tc_guard.py
;;; runs this from every cycle of the lines where the display starts and
;;; ends, PAL and NTSC, three YSCROLL values, against a model of the halt.
;;; Clobbers A, X.  Preserves Y.
;;; ==================================================================
!ifdef TC_GUARD_ELSEWHERE {       ; assembled before tclib.s, which would set
!ifdef TC_IRQ_ON {              ; it too late for this copy (Ultima IV's)
!ifndef TC_F_PLP { TC_F_PLP = 1 }
}
}
!ifndef TC_GIO { TC_GIO = $25 }  ; (tc_init patches it; see tcfast.s's TC_F_*)
tc_getbyte_guard:
        lda #BIT_SENSE
tc_gg_rdy:
        bit $01
        beq tc_gg_rdy
!ifdef TC_F_PLP {
        php                     ; no interrupt from the check to the end of
        sei                     ; the timed part (tcfast.s's PLP)
}
tc_v_gio:
        ldx #TC_GIO             ; patched: I/O in, write low
        stx $01
tc_gg_wait:
        lda $d012               ; 4 - the raster, read on its last cycle
        clc                     ; 2
        sbc $d011               ; 4
        and #$07                ; 2
        cmp #$06                ; 2
        bcs tc_gg_wait          ; 2 - this line or the next is a badline

!source "tcfast.s"

;;; (TC_GUARD_BARE: the receive alone, for a host that picks for itself.)
!ifndef TC_GUARD_BARE {
;;; A = $D015 (and Z from it), with I/O banked in for the read and out
;;; again before the RTS fetches from wherever the caller is.  tc_v_base is
;;; read first: in U4 it is under the I/O.  Keeps Y.
tc_sprites:
        lda tc_v_base
        sta tc_sp_out+1
        lda tc_v_gio+1          ; I/O in for a moment
        sta $01
        ldx $d015
tc_sp_out:
        lda #$00                ; the all-RAM value
        sta $01
        txa
        rts
}
