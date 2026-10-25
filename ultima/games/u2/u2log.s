;;; u2log.s -- Ultima 2's saves as a write log (included by u2drv.s).
;;;
;;; The game writes 256-byte units: the player record (raw T35/S16) at every
;;; save, and a map's MOB and MON files each time the party leaves it on
;;; Earth.  Each used to own a 4 KiB erase block, 26 of them for 6.5 KiB.
;;; Now they go to a log of two halves of LG_PAGES pages (16 KiB each):
;;;
;;;   pages 0 .. LG_DATA-1   a unit's version each, appended in order
;;;   page  LG_DATA          the directory: byte k = the unit in page k
;;;                          ($FF free, $FE dead), bytes $FE/$FF the header:
;;;                          the half's generation and its complement
;;;
;;; Unit 0 is the record, unit n the n-th entry of u2_table (n = index + 1);
;;; a unit the log does not hold is its seed, the original file in the game
;;; data, where the table points to begin with.  The active half is the
;;; valid one (header and complement agree), and of two, the one whose
;;; generation is the other's plus one.  lg_init walks its directory and
;;; points each unit's entry (u2_recpage for the record) at its newest page.
;;;
;;; A write goes to the next free page, then its directory byte.  A full
;;; half is compacted first: the other half erased, each unit's newest page
;;; copied over with its directory byte, the header written last, then the
;;; old half's directory block erased.  A power cut at any point leaves one
;;; valid half with every unit's last complete version: a page written but
;;; not yet recorded is found at boot and marked dead.  (A byte whose
;;; programming is cut could read as another unit's number; that is the one
;;; case not covered, as in U6's log.)
;;;
;;; WHERE THIS LIVES.  All of it, and the page it copies through (LG_BUF),
;;; is in the RAM under I/O at $D000, a segment of its own: the game only
;;; ever sets $01 = $36, so nothing of it reaches that RAM, and nothing it
;;; loads goes there (INTRO, the highest, ends at $CFFD).  The driver's
;;; lg_run banks it in ($01 = $34, interrupts already off) around a call;
;;; tclib keeps whatever $01 it is called with.  The launcher's page reads
;;; and imports this same layout (page_u2l.s); u2log.py is the host model.

LG_PAGES = 64
LG_DATA  = LG_PAGES - 1
LG_BUF   = $df00

;;; ==================================================================
;;; lg_init -- find the active half and point every unit at its newest page
;;; ==================================================================
lg_init:
        ldx #$01                ; both headers -> lg_h (half 0), lg_h+2 (half 1)
-       stx lg_k
        jsr lg_page
        lda #$fe
        ldy #LG_DATA
        jsr lg_at
        lda lg_k
        asl
        adc #<lg_h
        sta tc_dest
        lda #>lg_h
        adc #$00
        sta tc_dest+1
        lda #$02
        jsr lg_len1
        jsr tc_read
        ldx lg_k
        dex
        bpl -

        lda #$00
        sta lg_ok
        sta lg_next
        tax                     ; X = the half; 0 unless half 1 wins
        lda lg_h+2
        eor #$ff
        cmp lg_h+3
        bne li_h0               ; half 1 invalid
        inc lg_ok
        inx
        lda lg_h
        eor #$ff
        cmp lg_h+1
        bne li_pick             ; half 0 invalid: half 1
        lda lg_h                ; both valid: 1 if its generation is 0's + 1
        clc
        adc #$01
        cmp lg_h+2
        beq li_pick
        dex
        beq li_pick
li_h0:  lda lg_h
        eor #$ff
        cmp lg_h+1
        bne li_pick             ; neither: half 0, its header still to write
        inc lg_ok
li_pick:
        stx lg_act
        txa
        asl
        tay
        lda lg_h,y
        sta lg_gen
        jsr lg_page
        lda lg_ok
        beq li_done

        lda #$00                ; the directory, in page order
        ldy #LG_DATA
        jsr lg_at
        lda #LG_DATA
        jsr lg_len1
        jsr tc_stream_open
li_scan:
        jsr tc_stream_byte
        cmp #$ff
        beq li_end
        cmp #$fe
        beq +
        ldy lg_next
        jsr lg_set
+       inc lg_next
        lda lg_next
        cmp #LG_DATA
        bne li_scan
li_end: jsr tc_stream_close

li_torn:                        ; the next page must be erased; if a cut
        lda lg_next             ; left it written, it is dead
        cmp #LG_DATA
        bcs li_done
        tay
        lda #$00
        jsr lg_at
        jsr lg_len256
        jsr tc_stream_open
        lda #$ff
        sta lg_k
-       jsr tc_stream_byte
        and lg_k
        sta lg_k
        lda tc_len
        ora tc_len+1
        bne -
        jsr tc_stream_close
        lda lg_k
        cmp #$ff
        beq li_done
        lda #$fe
        jsr lg_dirbyte
        inc lg_next
        jmp li_torn
li_done:
        rts

;;; ==================================================================
;;; lg_append -- A = unit, tc_dest/tc_len = its data (a page at most)
;;; ==================================================================
lg_append:
        sta lg_u
        lda tc_dest
        sta lg_src
        lda tc_dest+1
        sta lg_src+1
        lda tc_len+1            ; never more than the unit's page
        beq +
        lda #$00
        sta tc_len
        lda #$01
+       sta lg_len+1
        lda tc_len
        sta lg_len

        lda lg_ok               ; a half with no header yet: start it
        bne +
        sta lg_gen
        sta lg_next
        jsr lg_erase
        jsr lg_header
        inc lg_ok
+       lda lg_next
        cmp #LG_DATA
        bcc +
        jsr lg_compact
+       lda #$00                ; the data ...
        ldy lg_next
        jsr lg_at
        lda lg_src
        sta tc_dest
        lda lg_src+1
        sta tc_dest+1
        lda lg_len
        sta tc_len
        lda lg_len+1
        sta tc_len+1
        jsr tc_write
        lda lg_u                ; ... then its directory byte
        jsr lg_dirbyte
        lda lg_u
        ldy lg_next
        jsr lg_set
        inc lg_next
        rts

;;; ==================================================================
;;; lg_compact -- every unit's newest page into the other half
;;; ==================================================================
lg_compact:
        lda lg_p
        sta lg_old
        lda lg_p+1
        sta lg_old+1
        lda lg_act
        eor #$01
        sta lg_act
        tax
        jsr lg_page
        jsr lg_erase
        lda #$00
        sta lg_next
        sta lg_k
lc_unit:
        lda lg_k
        cmp lg_u                ; about to be written anyway
        beq lc_skip
        jsr lg_pageof
        bcs lc_skip
        lda lg_pp               ; in the old half's data pages?
        sec
        sbc lg_old
        tay
        lda lg_pp+1
        sbc lg_old+1
        bne lc_skip
        cpy #LG_DATA
        bcs lc_skip
        lda #$00                ; old page -> LG_BUF -> the next new page
        sta tc_addr
        lda lg_pp
        sta tc_addr+1
        lda lg_pp+1
        sta tc_addr+2
        jsr lg_buf256
        jsr tc_read
        lda #$00
        ldy lg_next
        jsr lg_at
        jsr lg_buf256
        jsr tc_write
        lda lg_k
        jsr lg_dirbyte
        lda lg_k
        ldy lg_next
        jsr lg_set
        inc lg_next
lc_skip:
        inc lg_k
        lda u2_count
        cmp lg_k
        bcs lc_unit             ; units 0 .. u2_count
        inc lg_gen              ; the header, last
        jsr lg_header
        lda #$00                ; the old half's directory: now invalid
        sta tc_addr
        lda lg_old
        clc
        adc #LG_DATA
        sta tc_addr+1
        lda lg_old+1
        adc #$00
        sta tc_addr+2
        jmp tc_erase_block

;;; ==================================================================
;;; helpers
;;; ==================================================================

;;; X = half -> lg_p, its first flash page
lg_page:
        lda lg_base
        ldy lg_base+1
        cpx #$00
        beq +
        clc
        adc #LG_PAGES
        bcc +
        iny
+       sta lg_p
        sty lg_p+1
        rts

;;; tc_addr = byte A of the active half's page Y
lg_at:  sta tc_addr
        tya
        clc
        adc lg_p
        sta tc_addr+1
        lda lg_p+1
        adc #$00
        sta tc_addr+2
        rts

;;; tc_len = A (< 256)
lg_len1:
        sta tc_len
        lda #$00
        sta tc_len+1
        rts

;;; tc_dest = LG_BUF, tc_len = a page
lg_buf256:
        lda #<LG_BUF
        sta tc_dest
        lda #>LG_BUF
        sta tc_dest+1
lg_len256:
        lda #$00
        sta tc_len
        lda #$01
        sta tc_len+1
        rts

;;; the active half's four erase blocks
lg_erase:
        ldy #$00
-       sty lg_j
        lda #$00
        jsr lg_at
        jsr tc_erase_block
        lda lg_j
        clc
        adc #$10
        tay
        cpy #LG_PAGES
        bne -
        rts

;;; the active half's header: lg_gen and its complement
lg_header:
        lda lg_gen
        sta lg_hb
        eor #$ff
        sta lg_hb+1
        lda #$fe
        ldy #LG_DATA
        jsr lg_at
        lda #<lg_hb
        sta tc_dest
        lda #>lg_hb
        sta tc_dest+1
        lda #$02
        jsr lg_len1
        jmp tc_write

;;; directory byte lg_next of the active half = A
lg_dirbyte:
        sta lg_hb
        lda lg_next
        ldy #LG_DATA
        jsr lg_at
        lda #<lg_hb
        sta tc_dest
        lda #>lg_hb
        sta tc_dest+1
        lda #$01
        jsr lg_len1
        jmp tc_write

;;; unit A now lives in the active half's page Y
lg_set: pha
        tya
        clc
        adc lg_p
        sta lg_pp
        lda lg_p+1
        adc #$00
        sta lg_pp+1
        pla
        cmp #$00
        bne +
        lda lg_pp
        sta u2_recpage
        lda lg_pp+1
        sta u2_recpage+1
        rts
+       jsr lg_entry
        bcs +
        ldy #$08
        lda lg_pp
        jsr u2_put
        iny
        lda lg_pp+1
        jsr u2_put
+       rts

;;; unit A's page -> lg_pp; C set if it is not a unit (nothing to copy)
lg_pageof:
        cmp #$00
        bne +
        lda u2_recpage
        sta lg_pp
        lda u2_recpage+1
        sta lg_pp+1
        clc
        rts
+       jsr lg_entry
        bcs +
        ldy #$08
        jsr u2_ent
        sta lg_pp
        iny
        jsr u2_ent
        sta lg_pp+1
        clc
+       rts

;;; the table entry of unit A (1 .. u2_count) -> u2_e and u2_w; C set if
;;; there is none or it is not writable -- a stray byte never repoints a
;;; read-only file
lg_entry:
        cmp u2_count
        beq +
        bcs le_no
+       tax
        lda #<u2_table
        sta u2_e+1
        lda #>u2_table
        sta u2_e+2
-       dex
        beq +
        lda u2_e+1
        clc
        adc #U2_ENTRY
        sta u2_e+1
        bcc -
        inc u2_e+2
        bne -
+       lda u2_e+1
        sta u2_w+1
        lda u2_e+2
        sta u2_w+2
        ldy #$0c
        jsr u2_ent
        and #F_WRITE
        beq le_no
        clc
        rts
le_no:  sec
        rts

u2_put:
u2_w:   sta $ffff,y
        rts

lg_base: !word $ffff            ; build.py: the flash page of half 0
lg_h:    !fill 4, 0             ; the headers read at boot
lg_hb:   !byte 0, 0             ; a header or a directory byte to write
lg_act:  !byte 0                ; the active half
lg_p:    !word 0                ; ... its first flash page
lg_old:  !word 0                ; the half a compaction leaves
lg_pp:   !word 0
lg_ok:   !byte 0                ; the active half has its header
lg_gen:  !byte 0
lg_next: !byte 0                ; its next free page
lg_u:    !byte 0                ; the unit being written
lg_src:  !word 0
lg_len:  !word 0
lg_k:    !byte 0
lg_j:    !byte 0
lg_end:
!if lg_end > LG_BUF {
        !error "the log's code runs into its buffer at ", LG_BUF
}
