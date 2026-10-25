;;; journal.s -- a save slot written so that a power cut cannot lose it.
;;;
;;; Writing a slot in place erases it first: a power cut before the new save
;;; is complete leaves neither.  So a driver writes the slot twice, first
;;; into its game's journal (regions.journal), then into the slot itself:
;;;
;;;         (tc_addr = the slot: page aligned, the start of its erase block)
;;;         jsr jr_begin    ; tc_addr <- the journal's second page
;;;         <write the slot exactly as before, relative to tc_addr>
;;;         jsr jr_commit   ; the journal's header, last; tc_addr <- the slot
;;;         <write the slot again>
;;;         jsr jr_end      ; the journal erased
;;;
;;; "Exactly as before" includes the erase: tclib's tc_erase_block erases the
;;; block holding tc_addr, which is the journal's first; a slot of two blocks
;;; (U3's) erases the next one too.  The header -- "JN" and bits 8-23 of the
;;; slot's address, regions.JOURNAL_MAGIC -- is written last, so a journal
;;; without one is an unfinished copy and the slot still holds the old save.
;;; With one, the first stage (asm/boot.s) copies the journal into the slot
;;; at the next power-on and erases it: a cut while the slot itself was
;;; written loses nothing either.  And a cut after both, before jr_end, makes
;;; the first stage copy the same save again.
;;;
;;; The driver defines JOURNAL, the journal's flash address; tclib first.
;;; Short of room in one place, it includes this twice, with JR_PART (!set)
;;; 1, then 2: jr_begin and jr_set, then the rest.

!ifndef JR_PART {
!set JR_1 = 1
!set JR_2 = 1
} else {
!set JR_1 = JR_PART = 1
!set JR_2 = JR_PART = 2
}

!if JR_1 {
jr_begin:
        lda tc_addr+1
        sta jr_hdr+2
        lda tc_addr+2
        sta jr_hdr+3
        lda #>(JOURNAL + $100)
        ldx #^(JOURNAL + $100)
jr_set: sta tc_addr+1
        stx tc_addr+2
        lda #$00
        sta tc_addr
        rts
}

!if JR_2 {
jr_commit:
        lda #>JOURNAL
        ldx #^JOURNAL
        jsr jr_set
        lda #<jr_hdr
        sta tc_dest
        lda #>jr_hdr
        sta tc_dest+1
        lda #4
        sta tc_len
        lda #$00
        sta tc_len+1
        jsr tc_write
        lda jr_hdr+2
        ldx jr_hdr+3
        jmp jr_set

jr_end:
        lda #>JOURNAL
        ldx #^JOURNAL
        jsr jr_set
        jmp tc_erase_block

jr_hdr: !text "JN"
        !byte 0, 0
}

!if (JOURNAL & $fff) != 0 {
        !error "JOURNAL is not an erase block's start: ", JOURNAL
}
