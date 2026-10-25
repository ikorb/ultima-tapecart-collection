;;; u6wc.s -- the on-demand part's two halves with an REU, and the write cache.
;;;
;;; With an REU (u6reu.s found one) the in-game on-demand code is two
;;; kilobytes, not one, and the second is the room for this: part A is
;;; u6core.s without the writes, part B u6core.s without the loads by name,
;;; plus the code below.  The resident fetches part A from flash as it
;;; fetched u6bulk (reu_init points u6_bulkfl at it); a command for the
;;; other part brings it in over this one by DMA -- part A into the REU first,
;;; part B out of it, or from flash the first time in this half -- and it
;;; runs the command again from its first byte, as after u6pack.
;;;
;;; THE WRITE CACHE.  A save writes about 29 pages, and most are what the
;;; log already has (a probe: 22-27 of them).  Part B keeps a copy in the
;;; REU of the last thing it wrote for every unit the log keys -- a sector
;;; of the save area, a chunk file -- and the count of its pages, and
;;; compares the game's page with it by the REU's own verify, byte by byte:
;;; the same, and nothing goes to the cart.  Never a checksum.  A copy only
;;; stands for the log's newest version once that version's entry is
;;; written; reu_init forgets every copy at each launch (counts 0), so only
;;; what this launch wrote is ever trusted, and nothing but part B writes
;;; the log in the game (u6pack moves entries, their bytes unchanged).
;;;
;;;   a save sector: compared before it is written; the same, no page and
;;;     no entry; else written, its copy kept, its count 1.
;;;   a chunk file: its pages are held back while each is its copy's; at
;;;     the first that is not, the ones held back are written first, from
;;;     the copy (they are the game's bytes), through the game's buffer,
;;;     which waits in the REU meanwhile -- then everything as it comes, a
;;;     copy kept of each page, and the count set when the entry is.  A
;;;     file whose every page was its copy's gets no entry.  So does one the
;;;     game stopped writing short (all its pages so far the copy's): a
;;;     drive leaves the old file there too -- the same sectors, the same
;;;     bytes -- where an entry would cut it short.  (The game writes a
;;;     whole file; a shorter file differs in its last page's link.)
;;;
;;; $01 is $34 here; the REU's registers are reached through rc_dma.

!source "u6reu_syms.inc"        ; generated: rc_dma, rc_c64/ra/ln, wc_*

HALF_N    = (BULK_ORG - BULK_A) >> 10           ; 0 for $D800, 1 for $DC00
PAGE_A    = WC_PART_A + HALF_N * 4
PAGE_B    = WC_PART_B + HALF_N * 4
W_BHELD   = wc_bheld + HALF_N

;;; ---- the DMA ------------------------------------------------------
;;; this half <-> the part at page A of bank WC_BANK; X = the command.
;;; (tc_dest is the command's, but the command is done again after this)
w_part: ldy #<BULK_ORG
        sty tc_dest
        ldy #>BULK_ORG
        sty tc_dest+1
        ldy #>BULKMAX
        sty rc_ln+1
        ldy #WC_BANK
        bne w_any               ; (always)
;;; the page at tc_dest <-> REU page A of bank Y; X = the command
w_page: pha
        lda #$01
        sta rc_ln+1
        pla
w_any:  sta rc_ra+1
        sty rc_ra+2
        lda tc_dest
        sta rc_c64
        lda tc_dest+1
        sta rc_c64+1
        lda #$00
        sta rc_ra
        sta rc_ln
        jmp rc_dma

;;; the part at page A over this one, then the command again from its first
;;; byte: rc_dma returns into u6_bulk, which finds the half kept (b_entry
;;; set u6_keep) and jumps to its start -- not into the bytes overwritten
w_go:   lda #>(u6_bulk-1)       ; (X = the page)
        pha
        lda #<(u6_bulk-1)
        pha
        txa
        ldx #REU_FETCH
        jmp w_part

!ifdef U6_PART_A {
;;; ---- part A: a command for part B ----------------------------------
b_to_b: lda #PAGE_A             ; this one into the REU, for part B's way
        ldx #REU_STASH          ; back
        jsr w_part
        lda W_BHELD
        beq +
        ldx #PAGE_B             ; part B from the REU
        jmp w_go
+       lda #>(u6_bulk-1)       ; or from flash, the first time: tc_read
        pha                     ; returns into u6_bulk as above
        lda #<(u6_bulk-1)
        pha
b_bfl = * + 1                   ; patched by the build: part B's flash
        lda #$ff                ; address for this half
        sta tc_addr
        lda #$ff
        sta tc_addr+1
        lda #$ff
        sta tc_addr+2
        lda #<BULKMAX           ; (tc_dest is this half: w_part set it)
        sta tc_len
        lda #>BULKMAX
        sta tc_len+1
        jmp tc_read
}

!ifdef U6_PART_B {
;;; ---- part B (its way back to part A, and its own copy in the REU, are
;;; in u6core.s's b_entry) ------------------------------------------------
;;; the page at tc_dest against REU page A of bank Y: Z set if every byte
;;; is the same.  Reading the status clears its verify error, and only a
;;; verify sets one: reu_init read it, and every verify is read after.
;;; (rc_status is resident: nothing here may run with the I/O banked in.)
w_same: ldx #REU_VERIFY
        jsr w_page
        jsr rc_status
        and #REU_VFAIL
        rts

;;; the count of slot wc_ix (bank 3, WC_COUNTS + wc_ix) <- A, or (w_count)
;;; <-> wc_old as X says
w_setcount:
        sta wc_old
        ldx #REU_STASH
w_count:
        lda #<wc_old
        sta rc_c64
        lda #>wc_old
        sta rc_c64+1
        lda wc_ix
        sta rc_ra
        lda #>WC_COUNTS
        sta rc_ra+1
        lda #$03                ; (bank 3: rc_set1 sets the bank and one byte)
        jmp rc_set1

;;; room for A pages after the log's data, below its directory?  If not:
;;; compact it now (b_pack: the command again)
b_room: clc
        adc u6_logdata+1
        tax
        lda u6_logdata+2
        adc #$00
        cmp u6_logdir+2
        bcc +
        bne w_pack
        cpx u6_logdir+1
        bcc +
w_pack: jmp b_pack
+       rts

;;; ---- a save sector (1A T6 S9-20: build.py asserts it) ----------------
;;; the page at tc_dest against its copy: Z set if there is one and it is
;;; the same
w_sector:
        lda u6_s
        ora #$80
        sta wc_ix
        ldx #REU_FETCH
        jsr w_count
        lda wc_old
        beq w_sec_new           ; no copy
        jsr w_sslot
        jmp w_same
w_sec_new:
        lda #$01                ; (Z clear)
        rts

;;; its copy's page (written: u6core.s's b_write keeps the copy, then sets
;;; the count once the entry is written)
w_sslot:
        lda u6_s
        ora #WC_SAVE
        ldy #WC_BANK
        rts

;;; ---- a chunk file ----------------------------------------------------
;;; `!NAME` was found: its slot from the entry (address: page, bank;
;;; length: pages, index -- wc_spage.. in that order), its count from the
;;; REU, and the pages compared if it has a copy
w_open: ldx #$03
-       lda tc_addr+1,x
        sta wc_spage,x
        dex
        bpl -
        ldx #REU_FETCH
        jsr w_count
        lda wc_old              ; a copy: 0 (compare from its first page);
        cmp #$01                ; none: $FF (write as it comes)
        lda #$00
        sbc #$00
        sta wc_held
        rts

;;; A = a page's number in the file -> A, Y: its page in the REU
w_cslot:
        clc
        adc wc_spage
        ldy wc_sbank
        rts

;;; one of its pages, at tc_dest
w_chunk:
        lda wc_held
        bmi w_ch_write          ; written as they come
        cmp wc_old
        bcs w_ch_differs        ; longer than its copy
        jsr w_cslot
        jsr w_same
        bne w_ch_differs
        inc wc_held             ; the log's already: held back
        jmp u6_ok
w_ch_differs:
        ;; the pages held back go first.  Room for all of them before any
        ;; (b_append keeps 2 pages clear after each): a compaction among
        ;; them would do the command again with the game's buffer holding
        ;; one of them.
        lda wc_held             ; (the last of them wants wc_held + 1:
        clc                     ; one to spare)
        adc #$02
        jsr b_room
        lda #$00                ; no copy of the file until its entry
        jsr w_setcount          ; (and wc_old, 0, counts the pages below)
        lda #WC_SCRATCH         ; the game's page waits in the REU
        ldy #WC_BANK
        ldx #REU_STASH
        jsr w_page
-       lda wc_old
        cmp wc_held
        bcs +
        jsr w_cslot             ; page i of the copy, which is the game's,
        ldx #REU_FETCH          ; through the buffer
        jsr w_page
        jsr b_append
        inc u6_scount
        inc wc_old
        bne -
+       lda #WC_SCRATCH         ; the game's page back
        ldy #WC_BANK
        ldx #REU_FETCH
        jsr w_page
        lda #$ff                ; from here on as they come (a compaction
        sta wc_held             ; in the append below: the command again,
w_ch_write:                     ; which only writes)
        jsr b_append
        lda u6_scount           ; its copy, if the slot has the room
        cmp wc_cap
        bcs +
        jsr w_cslot
        ldx #REU_STASH
        jsr w_page
+       inc u6_scount
        jmp u6_ok

;;; the session's entry written (u6_scount pages): its count, if they all
;;; had a copy kept
w_close:
        lda u6_scount
        cmp wc_cap
        beq +
        bcc +
        lda #$00                ; more than the slot holds: no copy
+       jmp w_setcount
}   ; !ifdef U6_PART_B
