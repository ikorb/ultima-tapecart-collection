;;; u6io_sector.s -- the block map lookup (resident, and the boot driver)

;;; t, s, off, cnt from the command; tc_addr and u6_mlen from the block map
u6_sector:
        jsr u6_cb
        sta u6_t
        jsr u6_cb
        sta u6_s
        jsr u6_cb
        sta u6_off
        jsr u6_cb
        sta u6_cnt
u6_sector_again:
        ;; The block map is a grid of 21 entries per track (the longest
        ;; track), so an entry is (t * 21 + s) * 4 -- a loop, not the 1541's
        ;; zone table.  Tracks 18-35 waste a few entries each.
        ;; (the low byte stays in A; u6_blk is the high byte.  Tracks start
        ;; at 1, so the loop runs at least once.)
        lda #$00
        sta u6_blk
        lda u6_s
        ldx u6_t
-       clc
        adc #21
        bcc +
        inc u6_blk
+       dex
        bne -
u6_lin_done:
        asl                     ; x 4: its map entry
        rol u6_blk
        asl
        rol u6_blk
        ldx u6_disk
        clc
        adc u6_map_lo,x
        sta tc_addr
        lda u6_map_mid,x
        adc u6_blk
        sta tc_addr+1
        lda u6_map_hi,x
        adc #$00
        sta tc_addr+2
        lda #<u6_ment
        ldx #>u6_ment
        ldy #$04
        jsr u6_rdsmall
        ldx #$02                ; (u6_mlen is u6_ment+3)
-       lda u6_ment,x
        sta tc_addr,x
        dex
        bpl -
        rts

