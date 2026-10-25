;;; u6io_read.s -- the sector read, `^` (resident, and the boot driver).
;;; Entered with the command reader at the command's first byte; anything
;;; that is not a plain read goes to U6_OTHER (the on-demand part in the
;;; game, the boot driver's own dispatcher at boot).

        jsr u6_cb
        cmp #$5e
        bne U6_OTHER            ; anything but a read
        jsr u6_sector
        lda u6_mlen
        cmp #M_LOGGED
        beq U6_OTHER            ; a sector the game writes: newest copy
u6_rd_tail:                     ; (u6bulk continues here for those)
        jsr u6_dest
        lda u6_off              ; raw pages are page aligned (build.py
        sta tc_addr             ; asserts it), so the offset is the low byte
        lda u6_cnt
        sta tc_len
        lda #$00
        sta tc_len+1
        lda u6_cnt
        bne +
        inc tc_len+1            ; 0 = the whole sector
+       jsr tc_read
        jmp u6_ok

