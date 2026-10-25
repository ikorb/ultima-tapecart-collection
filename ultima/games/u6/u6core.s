;;; u6core.s -- Ultima 6's rarer commands: named loads, `!`, `&`, and reads
;;; of the sectors the game writes (U6 notes 5b).  Assembled into the
;;; on-demand part (u6bulk.s) and into the boot driver (u6boot.s); the write
;;; sessions for chunk files -- `!` and the chunk `&` -- only exist in the
;;; game, so they are behind U6_SESSIONS.
;;;
;;; Needs the u6io_*.s helpers and tclib (core, stream, write) around it.
;;;
;;; With an REU (u6reu.s) the in-game part is two kilobytes, not one: part A
;;; (U6_PART_A) is this without the writes, part B (U6_PART_B) this without
;;; the loads by name plus u6wc.s, the REU's copies of what was written.
;;; Either one is in the idle half and each takes the other's commands by
;;; bringing it in over itself (u6wc.s); the commands' meaning is the same.

b_entry:
!ifdef U6_SESSIONS {
!ifndef U6_PART_A {
        tsx                     ; for b_pack: the stack as the call found it
        stx b_sp
}
        lda #>BULK_ORG          ; the resident need not fetch this again for
        sta u6_keep             ; the next command (b_name says otherwise)
}
!ifdef U6_PART_B {
        lda W_BHELD             ; the first time in this half (from flash):
        bne +                   ; into the REU, for part A to fetch from
        lda #PAGE_B             ; there -- nothing in it changed yet that a
        ldx #REU_STASH          ; later call does not set before its use
        jsr w_part
        inc W_BHELD
+       jsr u6_cb
        cmp #$26
        beq b_write
        cmp #$5e                ; a read: part A's (which leaves the session
        beq b_ba                ; open, as here)
        pha
        jsr b_close             ; anything but a chunk write ends a session
        pla
        cmp #$21
        beq +
b_ba:   ldx #PAGE_A             ; and a load by name is part A's
        jmp w_go
+       jmp b_find
} else {
        jsr u6_cb
        cmp #$5e
        beq b_read
!ifdef U6_PART_A {
        cmp #$26                ; a write, `!`, or a write session open:
        beq b_ab                ; part B's
        cmp #$21
        beq b_ab
        ldx u6_open
        beq b_name
b_ab:   jmp b_to_b
} else {
        cmp #$26
        beq b_write
!ifdef U6_SESSIONS {
        pha
        jsr b_close             ; anything but a chunk write ends a session
        pla
        cmp #$21
        bne b_name
        jmp b_find
}
}
}

!ifndef U6_PART_B {

;;; ---- a load by name, or a chain of them --------------------------
b_name:
        jsr b_key               ; the name into b_keybuf; A = terminator
        sta b_term
!ifdef U6_SESSIONS {
        ;; A load by name comes at any time, between frames drawn into this
        ;; half, so the resident must fetch it again next time -- except
        ;; within the four object-file loads of `game`'s $2453 (its command
        ;; string is OBJ_CMD), which follow each other with no frame drawn;
        ;; the last of the four is the quadrant $80/$80
        lda u6_cmd0
        cmp #<OBJ_CMD
        bne +
        lda OBJ_QX
        and OBJ_QY
        bpl ++
+       sty u6_keep             ; (Y = KEYLEN: no half)
++
}
        jsr u6_dest
        jsr b_lookup
        bcs b_fail
!ifdef U6_SESSIONS {
        lda b_flags             ; a logged chunk file: only ever in the game
        and #F_LINKS
        beq +
        jsr b_unlink
        beq ++                  ; (it returns with Z set)
+
}
        jsr b_fetch
++      lda b_term
        bne b_done              ; $80+: that was the last
        jsr u6_cb               ; another entry follows
        jmp b_name
b_done: jmp u6_ok
}   ; !ifndef U6_PART_B
b_fail: jsr u6_ok               ; $01 as the original left it, then
        sec                     ; C set: the game retries, so a missing name
        rts                     ; hangs visibly instead of loading garbage

;;; ---- ^ a sector the game also writes -----------------------------
!ifndef U6_PART_B {
b_read:
        jsr u6_sector           ; tc_addr: the original
        jsr b_logkey
        jsr b_lookup            ; a logged copy replaces it
        jmp u6_rd_tail          ; and the resident reads it as usual
}

;;; ---- & a write ----------------------------------------------------
!ifndef U6_PART_A {
b_write:
        jsr u6_sector
        lda u6_mlen
        cmp #M_BAM
        bcc b_wr_chunk
!ifdef U6_SESSIONS {
        jsr b_close             ; the save area or a BAM: ends the session
}
        lda u6_mlen
        lsr
        bcc b_wr_ok             ; M_BAM: and goes nowhere (u6.inc)
                                ; M_LOGGED: its own entry --
        jsr u6_dest             ; and only then the source: closing writes an
!ifdef U6_PART_B {
        jsr w_sector            ; (the same as the log's: Z set, not written)
        beq b_wr_ok
}
        jsr b_append            ; entry through tc_dest; b_data <- the page
!ifdef U6_PART_B {
        jsr w_sslot             ; its copy, kept (the count stays as it was
        ldx #REU_STASH          ; until the entry is written, and nothing
        jsr w_page              ; comes between)
}
        jsr b_logkey
        ldx #DATALEN-4          ; the rest of the data zero (b_close may
        lda #$00                ; just have used it for the session's entry)
-       sta b_data+3,x
        dex
        bpl -
        jsr b_entry_write
!ifdef U6_PART_B {
        lda #$01                ; and the copy now stands for the log's
        jsr w_setcount
}
        jmp u6_ok
b_wr_chunk:
!ifdef U6_SESSIONS {
        jsr u6_dest             ; the source
        lda u6_open
        beq +                   ; not after a `!`: nothing owns it, drop it
!ifdef U6_PART_B {
        jmp w_chunk
} else {
        jsr b_append
        inc u6_scount
}
+
}
b_wr_ok:
        jmp u6_ok               ; (no sessions at boot: nothing to own it)
}   ; !ifndef U6_PART_A

;;; ---- ! a file's first track/sector; opens its write session ------
!ifdef U6_SESSIONS {
!ifndef U6_PART_A {
b_find:
        jsr b_key               ; b_keybuf = "!NAME"
        jsr u6_dest
        jsr b_lookup
        bcs b_fail
!ifdef U6_PART_B {
        jsr w_open              ; its slot in the REU (the entry's address
}                               ; and length, unused otherwise: build.py)
        lda tc_dest             ; the two bytes to the caller
        sta b_st+1
        lda tc_dest+1
        sta b_st+2
        lda b_extra
        jsr b_store
        lda b_extra+1
        jsr b_store
        ldx #KEYLEN-1           ; the session's key is "/NAME"
-       lda b_keybuf,x
        sta u6_skey,x
        dex
        bpl -
        lda #$2f
        sta u6_skey
        ldx #$02
-       lda u6_logdata,x
        sta u6_sstart,x
        dex
        bpl -
        inx                     ; (X = $FF)
        stx u6_scount           ; 0
        inx
        stx u6_open             ; 1
        jmp u6_ok

;;; end the write session: one entry for the file, if anything was written
b_close:
        lda u6_open
        beq b_cl_out
        lda #$00
        sta u6_open
!ifdef U6_PART_B {
        lda wc_held             ; nothing written yet: every page the game
        bpl b_cl_out            ; sent is the log's already (u6wc.s)
}
        lda u6_scount
        beq b_cl_out
        ldx #KEYLEN-1
-       lda u6_skey,x
        sta b_keybuf,x
        dex
        bpl -
        ldx #$02
-       lda u6_sstart,x
        sta b_data,x
        dex
        bpl -
        lda u6_scount
        sta b_data+3
        lda #F_LINKS
        sta b_data+5
!ifdef U6_PART_B {
        jsr b_entry_write
        jmp w_close             ; the copy now stands for the log's
} else {
        jmp b_entry_write
}
b_cl_out:
        rts
}   ; !ifndef U6_PART_A
}   ; !ifdef U6_SESSIONS

;;; ==================================================================
;;; helpers
;;; ==================================================================

!ifndef U6_PART_A {
b_store:
b_st:   sta $ffff
        inc b_st+1
        bne +
        inc b_st+2
+       rts
}

;;; the name from the command into b_keybuf, zero padded; the first byte
;;; is in A.  A = the terminator ($00, or $80+) on return.
b_key:
        ldy #$00
-       cmp #$00
        beq +
        cmp #$80
        bcs +
        sta b_keybuf,y
        iny
        jsr u6_cb
        jmp -
+       pha
        lda #$00
-       cpy #KEYLEN
        beq +
        sta b_keybuf,y
        iny
        bne -
+       pla
        rts

;;; b_keybuf <- a logged sector's key: K_SECTOR, disk, track, sector
!if K_SECTOR != 1 { !error "b_logkey makes K_SECTOR with an INY" }
b_logkey:
        ldy #KEYLEN-1
        lda #$00
-       sta b_keybuf,y
        dey
        bne -
        iny                     ; (Y = 0) K_SECTOR
        sty b_keybuf
        lda u6_disk
        sta b_keybuf+1
        lda u6_t
        sta b_keybuf+2
        lda u6_s
        sta b_keybuf+3
        rts

;;; DIR_LOOKUP b_keybuf: in the write log first, whose newest entries come
;;; first, then in the build's own directory.  C clear and tc_addr/tc_len/
;;; b_flags/b_extra set if found; tc_addr untouched if not.
b_lookup:
        ldx #<u6_logdir
        jsr b_dir
        bcc b_lk_out
        ldx #<u6_sdir
b_dir:  stx b_pp+1              ; point the cart at one directory, look up
        jsr tc_enter
        lda #CMD_DIR_SETPARAMS
        jsr tc_sendbyte
        ldy #$00
b_pp:   lda u6_logdir,y         ; patched: address (3), count (2)
        jsr tc_sendbyte
        iny
        cpy #$05
        bne b_pp
        lda #KEYLEN
        jsr tc_sendbyte
        lda #DATALEN
        jsr tc_sendbyte
        lda #CMD_DIR_LOOKUP
        jsr tc_sendbyte
        ldy #$00
-       lda b_keybuf,y
        jsr tc_sendbyte
        iny
        cpy #KEYLEN
        bne -
        jsr tc_getbyte
        bne b_lk_miss
        ldy #$00                ; address (3), length (2) straight into
-       jsr tc_getbyte          ; tc_addr/tc_len, contiguous in tclib
        sta tc_addr,y
        iny
        cpy #$05
        bne -
        ldy #$00                ; then flags and the two extra bytes
-       jsr tc_getbyte
        sta b_reply,y
        iny
        cpy #$03
        bne -
        clc
        !byte $24               ; BIT zp: skip the SEC
b_lk_miss:
        sec
        jmp tc_leave            ; (keeps the carry)
b_lk_out:
        rts
;;; (u6_logdir and u6_sdir must share a page: b_pp patches only the low
;;; byte.  Each file that includes this one checks it at its end.)

;;; the unit at tc_addr to tc_dest, decoded or copied as b_flags says (at
;;; boot everything is raw: U6_ZX is the in-game part's)
!ifndef U6_PART_B {
b_fetch:
!ifdef U6_ZX {
        lda b_flags
        lsr                     ; F_ZX is bit 0
        bcc +
        lda tc_dest
        sta zx_put+1
        lda tc_dest+1
        sta zx_put+2
        jsr tc_stream_open
        jsr zx_unpack
        jmp tc_stream_close
+
}
        jmp tc_read

!ifdef U6_SESSIONS {
;;; a logged file: tc_len pages at tc_addr, each a whole sector with its
;;; link bytes; strip them as the drive would -- 254 data bytes from a
;;; middle sector, bytes 2..link+1 from the last
b_unlink:
        lda tc_len
        sta b_left
        lda tc_dest
        sta b_dst
        lda tc_dest+1
        sta b_dst+1
b_ul_page:
        lda #<b_link            ; the link, then the data after it
        ldx #>b_link
        ldy #$02
        jsr u6_rdsmall
        lda #$02
        sta tc_addr
        lda b_dst
        sta tc_dest
        lda b_dst+1
        sta tc_dest+1
        lda #254
        ldx b_link
        bne +
        ldx b_link+1            ; the last: link+1 - 1 bytes
        dex
        txa
+       sta tc_len
        pha
        lda #$00
        sta tc_len+1
        jsr tc_read
        pla                     ; the destination moves on (tc_read does not)
        clc
        adc b_dst
        sta b_dst
        bcc +
        inc b_dst+1
+       lda #$00                ; the next page
        sta tc_addr
        inc tc_addr+1
        bne +
        inc tc_addr+2
+       dec b_left
        bne b_ul_page
        rts                     ; (with Z set: b_name counts on it)

}   ; !ifdef U6_SESSIONS
}   ; !ifndef U6_PART_B

!ifndef U6_PART_A {
!ifdef U6_SESSIONS {
;;; the log is full: fetch u6pack over this, into the same half, through
;;; the resident's own fetch.  It compacts the log and fetches this back,
;;; which does the command again from its first byte.
b_pack: ldx b_sp
        txs
b_pfl = * + 1                   ; patched by the build: u6pack's flash
        lda #$ff                ; address for this half
        sta tc_addr
        lda #$ff
        sta tc_addr+1
        lda #$ff
        sta tc_addr+2
        lda #>BULK_ORG
        sta tc_dest+1
        jmp u6_bulk_rd
}

;;; append the page at tc_dest to the log; b_page (b_data's address) <- where
;;; it went
b_append:
        ;; Room for this page and an entry below the directory?  Keep two
        ;; pages clear.  If not: in the game, compact the log now (b_pack)
        ;; and do the command again.  At boot -- a fresh log and twelve
        ;; pages of character creation, so it cannot happen -- the log is
        ;; full until the next boot compacts it: drop the write and all
        ;; after it (u6_full).
!ifdef U6_PART_B {
        lda #$02                ; (u6wc.s's flush asks for more)
        jsr b_room
} else {
        lda u6_logdata+1
        clc
        adc #$02
        tax
        lda u6_logdata+2
        adc #$00
        cmp u6_logdir+2
        bcc +
        bne b_full
        cpx u6_logdir+1
        bcc +
!ifdef U6_SESSIONS {
b_full: jmp b_pack
+
} else {
b_full: inc u6_full
+       lda u6_full
        bne b_ap_out
}
}
        ldx #$02
-       lda u6_logdata,x
        sta tc_addr,x
        sta b_page,x
        dex
        bpl -
        lda #$00
        sta tc_len
        lda #$01
        sta tc_len+1
        jsr tc_write
        inc u6_logdata+1
        bne b_ap_out
        inc u6_logdata+2
b_ap_out:
        rts

;;; write b_keybuf + b_data as the log's newest directory entry
b_entry_write:
!ifndef U6_SESSIONS {
        lda u6_full             ; (full: see b_append)
        bne b_ap_out
}
        sec
        lda u6_logdir
        sbc #ENTRYLEN
        sta u6_logdir
        sta tc_addr
        lda u6_logdir+1
        sbc #$00
        sta u6_logdir+1
        sta tc_addr+1
        lda u6_logdir+2
        sbc #$00
        sta u6_logdir+2
        sta tc_addr+2
        lda #<b_keybuf          ; key and data are adjacent below
        sta tc_dest
        lda #>b_keybuf
        sta tc_dest+1
        lda #ENTRYLEN
        sta tc_len
        lda #$00
        sta tc_len+1
        jsr tc_write
        inc u6_dircount         ; every lookup re-issues DIR_SETPARAMS, so
        bne +                   ; this is all it takes
        inc u6_dircount+1
+       rts
}   ; !ifndef U6_PART_A

;;; scratch: lost when the on-demand part's half is overwritten, which is
;;; fine -- nothing here outlives one command
b_term:    !byte 0
b_reply:                        ; the lookup reply's flags and extra (2)
b_flags  = b_reply
b_extra  = b_reply + 1
           !fill 3, 0
!ifdef U6_SESSIONS {
b_sp:      !byte 0
b_link:    !word 0
b_left:    !byte 0
b_dst:     !word 0
}
b_keybuf:  !fill KEYLEN, 0      ; followed by the entry's data
b_data:    !fill DATALEN, 0
b_page = b_data                 ; b_append's: only b_write's own entry uses it
