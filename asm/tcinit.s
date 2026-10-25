;;; tcinit.s -- tclib's tc_init: derive the port and DDR values from the
;;; caller's $00/$01.  tclib.s includes it; a driver short of room defines
;;; TC_INIT_ELSEWHERE and its init stub, which runs once, includes it
;;; instead, against the driver's symbols (build.py writes them out: the
;;; tc_v_*/tc_d_* operands, BIT_*, TC_KEEP_01, TC_IO_01, TC_FAST2, TC_GUARD).
;;; Call once, early.  Clobbers A.
tc_init:
        ;; Base port value: all-RAM banking, motor off, sense low, write low.
        ;; Bits 6/7 of $01 are unconnected on a C64 but preserved anyway.
        lda $01
        and #TC_KEEP_01
        ora #BIT_MOTOR
        sta tc_v_base
        sta tc_v_s0+1           ; sense low, write low
        sta tc_v_w0+1           ; write low
        ora #BIT_SENSE
        sta tc_v_s1+1           ; sense high, write low
        lda tc_v_base
        ora #BIT_WRITE
        sta tc_v_w1+1           ; write high
!ifdef TC_FAST2 {
        lda tc_v_base
        ora #BIT_SENSE|BIT_WRITE
        sta tc_v_fstart+1       ; fast-read start signal (stock loader's $38)
        lda tc_v_base
        ora #BIT_SENSE
        sta tc_v_fend+1         ; fast-read final value (stock loader's $30)
}
!ifdef TC_GUARD {
        lda tc_v_base
        ora #TC_IO_01
        sta tc_v_gio+1          ; I/O in, write low: to read the VIC
}

        ;; DDR: motor + write outputs, sense input
        lda $00
        ora #BIT_MOTOR|BIT_WRITE
        and #%11101111        ; clear BIT_SENSE
        sta tc_d_norm+1
        sta tc_d_norm2+1
!ifdef TC_FAST2 {
        sta tc_d_fend+1
}
        ora #BIT_SENSE
        sta tc_d_sout+1         ; sense as output, for byte transmit
!ifdef TC_FAST2 {
        lda tc_d_norm+1
        and #%11110111        ; clear BIT_WRITE
        sta tc_d_fast+1         ; write as input too, for the fast read
}
        rts

