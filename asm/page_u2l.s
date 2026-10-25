;;; page_u2l.s -- Ultima II's write log, for the launcher's page (included by
;;; page.s): where a unit's newest version is, for the info line and the
;;; export, and an import written as a fresh half.  The layout is the
;;; driver's (ultima/games/u2/u2log.s; u2log.py on the host): two halves of
;;; LG_PAGES pages at U2_LOG, the directory the last page of each, its bytes
;;; $FE/$FF the half's generation and complement.

LG_PAGES = 64
LG_DATA  = LG_PAGES - 1
LGBUF    = $0400                ; a directory ($0500 U6's BAM, $0600 a sector, $0700 the settings)

;;; tc_addr = unit A's seed on entry; its newest version in the log on exit
lg_find:
        sta lg_unit
        lda tc_addr+1           ; (seeds are whole pages)
        sta lg_seed
        lda tc_addr+2
        sta lg_seed+1
        jsr lg_active
        bcs lf_seed             ; an empty log
        jsr lg_dir
        lda #>LGBUF
        ldx #$01
        jsr fread_to
        ldy #$00
        ldx #$ff                ; the last page holding it
-       lda LGBUF,y
        cmp #$ff
        beq +
        cmp lg_unit
        bne ++
        sty lg_last
        ldx #$00
++      iny
        cpy #LG_DATA
        bne -
+       txa
        bne lf_seed
        lda #$00
        sta tc_addr
        lda lg_last
        clc
        adc lg_hp
        sta tc_addr+1
        lda lg_hp+1
        adc #$00
        sta tc_addr+2
        rts
lf_seed:
        lda #$00
        sta tc_addr
        lda lg_seed
        sta tc_addr+1
        lda lg_seed+1
        sta tc_addr+2
        rts

;;; the active half: C clear, lg_ha = which, lg_hp its first page, lg_hg its
;;; generation; C set if neither is valid
lg_active:
        lda #<(U2_LOG + LG_DATA * 256 + $fe)
        sta tc_addr
        lda #>(U2_LOG + LG_DATA * 256 + $fe)
        sta tc_addr+1
        lda #^(U2_LOG + LG_DATA * 256 + $fe)
        sta tc_addr+2
        lda #<lg_h
        jsr lg_hread
        lda #>(U2_LOG + LG_PAGES * 256 + LG_DATA * 256 + $fe)
        sta tc_addr+1
        lda #^(U2_LOG + LG_PAGES * 256 + LG_DATA * 256 + $fe)
        sta tc_addr+2
        lda #<(lg_h + 2)
        jsr lg_hread
        ldx #$00
        lda lg_h+2
        eor #$ff
        cmp lg_h+3
        bne la_h0
        inx
        lda lg_h
        eor #$ff
        cmp lg_h+1
        bne la_pick
        lda lg_h                ; both: half 1 if its generation is 0's + 1
        clc
        adc #$01
        cmp lg_h+2
        beq la_pick
        dex
        beq la_pick
la_h0:  lda lg_h
        eor #$ff
        cmp lg_h+1
        beq la_pick
        sec                     ; neither
        rts
la_pick:
        stx lg_ha
        txa
        asl
        tay
        lda lg_h,y
        sta lg_hg
        jsr lg_half
        clc
        rts

;;; two header bytes from tc_addr to A (low byte; lg_h is in one page)
lg_hread:
        sta tc_dest
        lda #>lg_h
        sta tc_dest+1
        lda #$02
        sta tc_len
        lda #$00
        sta tc_len+1
        lda tc_addr+1           ; tc_read keeps tc_addr
        pha
        lda tc_addr+2
        pha
        jsr tc_read
        pla
        sta tc_addr+2
        pla
        sta tc_addr+1
        rts

;;; X = half -> lg_hp, its first page
lg_half:
        lda #>U2_LOG
        ldy #^U2_LOG
        cpx #$00
        beq +
        clc
        adc #LG_PAGES
        bcc +
        iny
+       sta lg_hp
        sty lg_hp+1
        rts

;;; tc_addr = the directory page of half lg_hp
lg_dir: lda #$00
        sta tc_addr
        lda lg_hp
        clc
        adc #LG_DATA
        sta tc_addr+1
        lda lg_hp+1
        adc #$00
        sta tc_addr+2
        rts

;;; ---- import ---------------------------------------------------------
;;; The staged units go into the half that is not active (half 0 if none
;;; is), after erasing it; lg_done writes its header, generation one more,
;;; then erases the old half's directory.  Until the header, the old half
;;; is the valid one, so a cut changes nothing.

;;; first unit of an import: the new half, erased
lg_start:
        lda #$00
        sta lg_j
        sta lg_had
        sta lg_ng
        jsr lg_active
        ldx #$00                ; none: half 0, generation 0
        bcs +
        inc lg_had
        lda lg_hp
        sta lg_op
        lda lg_hp+1
        sta lg_op+1
        ldx lg_hg
        inx
        stx lg_ng
        lda lg_ha
        eor #$01
        tax
+       jsr lg_half
        lda #$00
        sta tc_addr
        ldy #$00
-       sty count
        tya
        clc
        adc lg_hp
        sta tc_addr+1
        lda lg_hp+1
        adc #$00
        sta tc_addr+2
        jsr tc_erase_block
        lda count
        clc
        adc #$10
        tay
        cpy #LG_PAGES
        bne -
        rts

;;; one staged unit (A = the unit, a page at xs_stage) into the next page
lg_put: sta lg_unit
        lda #$00
        sta tc_addr
        sta tc_dest
        lda lg_j
        clc
        adc lg_hp
        sta tc_addr+1
        lda lg_hp+1
        adc #$00
        sta tc_addr+2
        lda xs_stage
        sta tc_dest+1
        lda #$00
        sta tc_len
        lda #$01
        sta tc_len+1
        jsr tc_write
        jsr lg_dir
        lda lg_j
        sta tc_addr
        lda #<lg_unit
        ldx #$01
        jsr lg_wr
        inc lg_j
        rts

;;; the end of an import: the header, then the old half's directory erased
lg_done:
        lda lg_j
        bmi ld_out              ; no unit of the log in this import
        lda lg_ng
        sta lg_h
        eor #$ff
        sta lg_h+1
        jsr lg_dir
        lda #$fe
        sta tc_addr
        lda #<lg_h
        ldx #$02
        jsr lg_wr
        lda lg_had
        beq ld_out
        lda lg_op
        sta lg_hp
        lda lg_op+1
        sta lg_hp+1
        jsr lg_dir
        jsr tc_erase_block
ld_out: rts

;;; write X bytes from A (low byte, in lg_h's page) to tc_addr
lg_wr:  sta tc_dest
        lda #>lg_h
        sta tc_dest+1
        stx tc_len
        lda #$00
        sta tc_len+1
        jmp tc_write

lg_h:    !fill 4, 0
lg_unit: !byte 0                ; (lg_wr and lg_hread: in lg_h's page)
!if >lg_h != >lg_unit {
        !error "lg_h and lg_unit straddle a page"
}
lg_last: !byte 0
lg_ha:   !byte 0
lg_hg:   !byte 0
lg_hp:   !word 0
lg_j:    !byte $ff              ; the import's next page; $FF: not started
lg_had:  !byte 0
lg_ng:   !byte 0
lg_op:   !word 0
lg_seed: !word 0
