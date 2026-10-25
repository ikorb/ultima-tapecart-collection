;;; tcfast.s -- the timed part of the 2-bit receive, shared by tclib's
;;; tc_getbyte_fast and tcguard.s's tc_getbyte_guard (both come in here with
;;; the cart ready).  CYCLE EXACT: every access to $00/$01 has to stay on
;;; the same cycle relative to the STX $01 that raises the write line, as
;;; ProgRef's getbyte_fast has them.  Clobbers A, X.  Preserves Y.
;;;
;;; The four port values are placeholders tc_init patches -- or, for code
;;; nothing patches (Ultima 5's copy in the Action Replay's RAM), fixed by
;;; TC_F_START / TC_F_DFAST / TC_F_DFEND / TC_F_END.  The byte is put
;;; together from two reads of $01 per bit pair, and bits 1 and 2 of the
;;; second read land in each nibble: 0 in all-RAM banking, as tclib runs,
;;; but code that must run with LORAM and HIRAM set -- from ROML -- sees
;;; them, a constant TC_F_XOR in both nibbles, which the table then takes
;;; out again (EOR instead of ORA: same length, same cycles).
!ifndef TC_F_START { TC_F_START = $38 }
!ifndef TC_F_DFAST { TC_F_DFAST = $27 }
!ifndef TC_F_DFEND { TC_F_DFEND = $2f }
!ifndef TC_F_END   { TC_F_END   = $30 }

tc_v_fstart:
        ldx #TC_F_START         ; patched: write high + sense high, start signal
tc_d_fast:
        lda #TC_F_DFAST         ; patched: switch write to input
        stx $01
        sta $00                 ; 3
        nop                     ; 2

        lda $01                 ; 3 - bits 5+4
        and #$18                ; 2
        lsr                     ; 2
        lsr                     ; 2
        eor $01                 ; 3 - bits 7+6
        lsr                     ; 2
        and #$0f                ; 2
        tax                     ; 2

        lda $01                 ; 3 - bits 1+0
        and #$18                ; 2
        lsr                     ; 2
        lsr                     ; 2
        eor $01                 ; 3 - bits 3+2
        lsr                     ; 2
        and #$0f                ; 2
!ifdef TC_F_XOR {
        eor tc_nibbletab,x      ; 4 - the high nibble, and the low one's flip
} else {
        ora tc_nibbletab,x      ; 4
}

tc_d_fend:
        ldx #TC_F_DFEND         ; 2 - patched: write back to output
        stx $00                 ; 3
tc_v_fend:
        ldx #TC_F_END           ; patched: write low
        stx $01
!ifdef TC_F_PLP {
        plp                     ; tcguard.s's PHP / SEI: interrupts as they were
}
        rts

!ifdef TC_GUARD {               ; the table must not cross a page (the ORA's
!if (* & $ff) > $f0 {           ; timing): pad to the next one when it would --
        !fill $100 - (* & $ff), $00     ; it follows the RTS, so this is not run
}
}
tc_nibbletab:
!ifdef TC_F_XOR {
!for n, 0, 15 {
        !byte ((n XOR TC_F_XOR) << 4) | TC_F_XOR
}
} else {
        !byte $00,$10,$20,$30,$40,$50,$60,$70
        !byte $80,$90,$a0,$b0,$c0,$d0,$e0,$f0
}
!ifdef TC_GUARD {
!if >tc_nibbletab != >(tc_nibbletab + 15) {
!error "tc_nibbletab crosses a page: the ORA would take a cycle more"
}
}
