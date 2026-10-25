;;; u6io_small.s -- command reader and small helpers (resident, and the boot driver)

;;; read Y bytes from tc_addr into A/X (lo/hi)
u6_rdsmall:
        sta tc_dest
        stx tc_dest+1
        sty tc_len
        lda #$00
        sta tc_len+1
        jmp tc_read

;;; tc_dest <- the next two command bytes (the destination, or a source)
u6_dest:
        jsr u6_cb
        sta tc_dest
        jsr u6_cb
        sta tc_dest+1
        rts

;;; A <- the next byte of the command.  Placed last but one, so a host can
;;; pin where its RTS falls (U6_CB_RTS_AT): in `game`, $02AE is a jump-table
;;; entry to $29B6, which was a lone RTS, and this one serves it.
!ifdef U6_CB_RTS_AT {
!if * > U6_CB_RTS_AT - 11 {
        !error "u6_cb cannot end at U6_CB_RTS_AT: the helpers reach ", *
}
        !fill U6_CB_RTS_AT - 11 - *, $ea
}
u6_cb:
u6_c:   lda $ffff
        inc u6_c+1
        bne +
        inc u6_c+2
+       rts
!ifdef U6_CB_RTS_AT {
!if * != U6_CB_RTS_AT + 1 {
        !error "u6_cb's RTS is not at U6_CB_RTS_AT"
}
}

;;; how the original left $01 ($34 in the game, $35 at boot), and C clear
u6_ok:  lda #U6_EXIT01
        sta $01
        clc
        rts
