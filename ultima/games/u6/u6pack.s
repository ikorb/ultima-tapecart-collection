;;; u6pack.s -- Ultima 6's in-game log compaction.
;;;
;;; The boot compacts the write log when it is getting full (asm/init_u6.s),
;;; but a session can still fill it: a save is 33 pages and the game saves
;;; as often as the player likes.  Dropping writes then would lose the save
;;; without a word, so instead the on-demand part (u6bulk.s), finding no
;;; room for a page, fetches this over itself -- into the same idle sprite
;;; half, through the resident's own fetch -- and this compacts the log
;;; into the other half exactly as the boot does, then calls the resident
;;; fetch again: the on-demand part comes back and restarts the command
;;; from its first byte, now with room.  Restarting is safe because the one
;;; thing a command can have done before its first append is close the
;;; write session, and closing a closed session does nothing.
;;;
;;; No live table here, there is no room for one: an entry is live if the
;;; cart's DIR_LOOKUP of its key, in the old directory, answers with its
;;; own address -- the lookup meets the newest version of a key first.
;;; The open write session (a chunk file being saved: pages, no entry yet)
;;; moves along, after everything else, so the file's later pages follow.
;;;
;;; Order, as at boot: the other half erased, the live units copied, the
;;; header (generation + 1) written last, the old half erased.  A power cut
;;; leaves the old half, the log as it was before this save.
;;;
;;; A spinner turns in one character cell of the game screen meanwhile (the
;;; cell is put back afterwards): it takes 15 to 50 seconds.  The bitmap and
;;; its colours are RAM ($E000, $CC00), so no I/O is needed -- which matters,
;;; because this runs under it.
;;;
;;; LOG_LO, LOG_HI and BULK_ORG come from build.py.

TC_NO_CMDMODE  = 1
TC_NO_FAST     = 1
TC_EXTRAS_ONLY = 1
TC_NO_STREAM   = 1

!source "u6.inc"
!source "u6res_syms.inc"        ; generated: the resident's labels

HALF     = (LOG_HI - LOG_LO) / 2
MID      = LOG_LO + HALF
K_HEADER = $fe
CHUNK    = 64                   ; bytes per copy: the buffer
SPIN_ROW = 23                   ; the cursor's cell, after the prompt `>`
SPIN_COL = 23                   ; (row 23: col 22 is the `>`)
SPIN_BM  = $e000 + SPIN_ROW * 320 + SPIN_COL * 8
SPIN_SC  = $cc00 + SPIN_ROW * 40 + SPIN_COL

        * = BULK_ORG
p_start:
        ldx #$07                ; the spinner's cell, kept
-       lda SPIN_BM,x
        sta p_save,x
        dex
        bpl -
        lda SPIN_SC
        sta p_save+8
        lda #$10                ; white on black, in either bitmap mode
        sta SPIN_SC

        ;; ---- which half is active: where the data grows ---------------
        ldx #$00
        lda u6_logdata+1
        cmp #<(MID >> 8)
        lda u6_logdata+2
        sbc #<(MID >> 16)
        bcc +
        ldx #$03
+       stx act
        txa
        eor #$03
        sta tgt

        ;; ---- its generation: a header's, or 0 (every variable here starts
        ;; at the image's zero: this is fetched afresh each time)
        jsr topslot             ; tc_addr <- half X's top slot
        jsr rdent
        lda ent
        cmp #K_HEADER
        bne +
        lda ent+KEYLEN
        sta gen
        lda ent+KEYLEN+1
        sta gen+1
+
        ;; ---- the other half, erased (which sets ndata to its base); its
        ;; entries go below its top slot, which the header gets last
        ldx tgt
        jsr erase_half
        ldx tgt
        jsr topslot             ; (ndir too)

        ;; ---- the cart looks keys up in the old directory ---------------
        jsr tc_enter
        lda #CMD_DIR_SETPARAMS
        jsr tc_sendbyte
        ldy #$00
-       lda u6_logdir,y         ; address (3), count (2)
        jsr tc_sendbyte
        iny
        cpy #$05
        bne -
        lda #KEYLEN
        jsr tc_sendbyte
        lda #DATALEN
        jsr tc_sendbyte
        jsr tc_leave

        ;; ---- every entry, newest first: copy it if it is live -----------
        ldx #$04
-       lda u6_logdir,x         ; walk (3), left (2): as logdir, dircount
        sta walk,x
        dex
        bpl -
p_walk: lda left
        ora left+1
        bne +
        jmp p_session
+
        jsr spin
        ldx #$02
-       lda walk,x
        sta tc_addr,x
        dex
        bpl -
        jsr rdent
        lda ent
        cmp #K_HEADER
        beq p_next
        jsr tc_enter            ; live?
        lda #CMD_DIR_LOOKUP
        jsr tc_sendbyte
        ldy #$00
-       lda ent,y
        jsr tc_sendbyte
        iny
        cpy #KEYLEN
        bne -
        jsr tc_getbyte          ; found (it is: this very entry at worst)
        ldy #$00
        sty diff
-       jsr tc_getbyte          ; the address the newest version has
        cmp ent+KEYLEN,y
        beq +
        inc diff
+       iny
        cpy #$03
        bne -
-       jsr tc_getbyte          ; the rest of the reply
        iny
        cpy #DATALEN
        bne -
        jsr tc_leave
        lda diff
        bne p_next              ; an older version: dead
        ldx #$01                ; its pages: a file its count, a sector one
        ldy #$00
        lda ent+KEYLEN+5
        and #F_LINKS
        beq +
        ldx ent+KEYLEN+3
        ldy ent+KEYLEN+4
+       stx npages
        sty npages+1
        ldx #$02                ; from where they are to ndata, which is
-       lda ent+KEYLEN,x        ; the entry's new address
        sta src,x
        lda ndata,x
        sta ent+KEYLEN,x
        dex
        bpl -
        jsr copy
        jsr ndir_down           ; the entry, below the one before
        jsr wrent
        inc nlive
p_next: clc
        lda walk
        adc #ENTRYLEN
        sta walk
        bcc +
        inc walk+1
        bne +
        inc walk+2
+       lda left
        bne +
        dec left+1
+       dec left
        jmp p_walk

        ;; ---- the open write session's pages follow ---------------------
p_session:
        lda u6_open
        beq p_header
        ldx #$02
-       lda u6_sstart,x
        sta src,x
        lda ndata,x
        sta u6_sstart,x
        dex
        bpl -
        lda u6_scount
        sta npages
        lda #$00
        sta npages+1
        jsr copy

        ;; ---- the header, last: the new half is valid from here on --------
p_header:
        ldx #ENTRYLEN-1
        lda #$00
-       sta ent,x
        dex
        bpl -
        ldx #$03
-       lda p_key,x
        sta ent,x
        dex
        bpl -
        clc
        lda gen
        adc #$01
        sta ent+KEYLEN
        eor #$ff
        sta ent+KEYLEN+2
        lda gen+1
        adc #$00
        sta ent+KEYLEN+1
        eor #$ff
        sta ent+KEYLEN+3
        ldx #$02                ; (ndir is the directory's start: keep it)
-       lda ndir,x
        sta walk,x
        dex
        bpl -
        ldx tgt
        jsr topslot             ; (ndir too)
        jsr wrent

        ;; ---- the log goes on in the new half ----------------------------
        ldx #$02
-       lda walk,x
        sta u6_logdir,x
        lda ndata,x
        sta u6_logdata,x
        dex
        bpl -
        ldx nlive               ; its entries: the live ones, the header
        inx
        stx u6_dircount
        lda #$00
        sta u6_dircount+1
        ldx act                 ; and only now the old half goes
        jsr erase_half
        ldx #$07                ; the cell back as it was
-       lda p_save,x
        sta SPIN_BM,x
        dex
        bpl -
        stx u6_keep             ; (X = $FF) this half holds u6pack now
        lda p_save+8
        sta SPIN_SC
        jmp u6_bulk             ; the on-demand part, back: the command again

;;; ==================================================================
;;; helpers
;;; ==================================================================

;;; tc_addr and ndir <- half X's top slot (X = 0 or 3)
topslot:
        ldy #$00
-       lda tslot,x
        sta tc_addr,y
        sta ndir,y
        inx
        iny
        cpy #$03
        bne -
        rts

rdent:  lda #<ent               ; ENTRYLEN bytes from tc_addr
        ldx #>ent
        ldy #ENTRYLEN
        jmp u6_rdsmall

;;; npages pages from src to ndata, both moving on -- through a CHUNK-byte
;;; buffer, all there is room for (a page program need not fill the page)
copy:   asl npages              ; in chunks
        rol npages+1
        asl npages
        rol npages+1
cp_loop:
        lda npages
        ora npages+1
        beq cp_out
        jsr spin
        ldx #$02
-       lda src,x
        sta tc_addr,x
        dex
        bpl -
        jsr buflen
        jsr tc_read
        ldx #$02
-       lda ndata,x
        sta tc_addr,x
        dex
        bpl -
        jsr buflen
        jsr tc_write
        ldx #src - ndata        ; src += CHUNK, then ndata += CHUNK
        jsr step
        ldx #$00
        jsr step
        lda npages
        bne +
        dec npages+1
+       dec npages
        jmp cp_loop
cp_out: rts

;;; ndata+X (3 bytes) += CHUNK
step:   clc
        lda ndata,x
        adc #CHUNK
        sta ndata,x
        bcc +
        inc ndata+1,x
        bne +
        inc ndata+2,x
+       rts

buflen: lda #<p_buf
        sta tc_dest
        lda #>p_buf
        sta tc_dest+1
        lda #CHUNK
        sta tc_len
        lda #$00
        sta tc_len+1
        rts

;;; ndir -= ENTRYLEN
ndir_down:
        sec
        lda ndir
        sbc #ENTRYLEN
        sta ndir
        lda ndir+1
        sbc #$00
        sta ndir+1
        lda ndir+2
        sbc #$00
        sta ndir+2
        rts

;;; ent to ndir
wrent:  ldx #$02
-       lda ndir,x
        sta tc_addr,x
        dex
        bpl -
        lda #<ent
        sta tc_dest
        lda #>ent
        sta tc_dest+1
        lda #ENTRYLEN
        sta tc_len
        lda #$00
        sta tc_len+1
        jmp tc_write

;;; erase half X (0 or 3), spinning; ndata <- its base
erase_half:
        ldy #$00
-       lda hbase,x
        sta tc_addr,y
        sta ndata,y
        inx
        iny
        cpy #$03
        bne -
        lda #<(HALF / $1000)
        sta blocks
-       jsr spin
        jsr tc_erase_block
        clc
        lda tc_addr+1
        adc #$10
        sta tc_addr+1
        bcc +
        inc tc_addr+2
+       dec blocks
        bne -
        rts

;;; the spinner's next frame
spin:   inc frame
        lda frame
        and #$03
        asl
        asl
        asl
        tax
        ldy #$00
-       lda p_frames,x
        sta SPIN_BM,y
        inx
        iny
        cpy #$08
        bne -
        rts

TCLIB_ORG = *
!source "tclib.s"               ; erase and write only

;;; ---- constants -------------------------------------------------------
hbase:  !24 LOG_LO, MID         ; half 0's base, then half 1's
tslot:  !24 MID - ENTRYLEN, LOG_HI - ENTRYLEN   ; and their top slots
p_key:  !byte K_HEADER, $4c, $4f, $47       ; "LOG"
p_frames:                       ; a bar turning, in %01 pixel pairs
        !byte $14, $14, $14, $14, $14, $14, $14, $14        ; |
        !byte $01, $01, $04, $04, $10, $10, $40, $40        ; /
        !byte $00, $00, $00, $55, $55, $00, $00, $00        ; -
        !byte $40, $40, $10, $10, $04, $04, $01, $01        ; \

;;; ---- scratch -----------------------------------------------------------
act:    !byte 0
tgt:    !byte 0
gen:    !word 0
nlive:  !byte 0
diff:   !byte 0
blocks: !byte 0
frame:  !byte 0
npages: !word 0
walk:   !fill 3, 0              ; walk (3) and left (2): adjacent, as
left:   !word 0                 ; u6_logdir and u6_dircount
ndata:  !fill 3, 0
src:    !fill 3, 0              ; (after ndata: step indexes both)
ndir:   !fill 3, 0
p_save: !fill 9, 0              ; the spinner's cell: 8 bitmap bytes, 1 colour
ent:    !fill ENTRYLEN, 0
p_buf = *                       ; CHUNK bytes, not part of the image

p_end = p_buf + CHUNK
!if p_end - BULK_ORG > BULKMAX {
        !error "u6pack is ", p_end - BULK_ORG - BULKMAX, " bytes over its kilobyte"
}
!if HALF & $fff { !error "the log's halves must be whole erase blocks" }
