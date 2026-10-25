;;; efdrv.s -- Ultima VI's EasyFlash driver, run straight from the cart's ROM.
;;;
;;; The game asks for data with command strings (U6 notes 5b) through a few
;;; bytes of its own RAM -- the trampoline in efres.s (in `game`) or efboot.s
;;; (in the boot resident) -- which banks the cart in and calls DRV_ENTRY in
;;; this bank.  Everything else is here, in ROM: parsing, the block maps, the
;;; directories, the write log.  What has to be RAM -- self-modified
;;; operands, code that switches banks or banks the cart out, EAPI and its
;;; callers -- is a handful of primitives in the context's RAM (k_*, e_*),
;;; and the variables (d_*) live there too.  So this file is assembled once
;;; per context, against that context's symbols:
;;;
;;;   EF_GAME   in `game`: chunk files' write sessions, zx02 conversations
;;;   EF_BOOT   in the boot resident: the `#` disk check, the world reset
;;;
;;; The cart is in 16K mode here, $01 = $37: this bank's ROML at $8000 (this
;;; code), its ROMH at $A000 (the static directory), the KERNAL at $E000 --
;;; whose IRQ entry goes through ($0314), which the trampoline points at a
;;; shim for as long as this runs.  Reads never touch zero page and never
;;; self-modify (it is ROM); a copy is k_run, at $01 = $33 so that stores
;;; reach the RAM under I/O and under the ROMs alike.
;;;
;;; THE WRITE LOG is the tapecart build's, unchanged (ultima/games/u6/u6core.s,
;;; asm/init_u6.s): pages appended upward at EF_LOGDATA, a 20-byte directory
;;; entry per logged unit written downward from EF_LOGDIR, newest lowest, so
;;; a scan from EF_LOGDIR meets the newest version of a key first.  Writes go
;;; through EAPI, which lives in the context's slot only while a write runs:
;;; e_begin copies it in from 00:1:1800, e_end puts back what the slot held.

!source "efvars.inc"

        * = $8000
        jmp d_cmd               ; X/Y were the command: k_cb reads it
!ifdef EF_BOOT {
        jmp d_handoff           ; `game` is in: its init copy to INIT_AT
}

;;; ==================================================================
;;; the command
;;; ==================================================================
d_cmd:
        jsr k_cb
        cmp #$5e                ; ^
        bne +
        jmp d_read
+       cmp #$26                ; &
        bne +
        jmp d_write
+
!ifdef EF_GAME {
        pha
        jsr d_close             ; anything but a chunk write ends a session
        pla
        cmp #$21                ; !
        bne d_name
        jmp d_find
} else {
        cmp #$23                ; #
        bne +
        jmp d_id
+       cmp #$2a                ; *
        bne d_name
        jmp d_new
}

;;; ---- a load by name, or a chain of them --------------------------
d_name:
        jsr d_key               ; the name into d_keybuf; A = terminator
        sta d_term
        jsr d_dest
        jsr d_lookup
        bcs d_fail
        lda d_dst
        sta d_rd
        lda d_dst+1
        sta d_rd+1
!ifdef EF_GAME {
        lda d_ent+5             ; a logged chunk file: pages with links
        and #F_LINKS
        beq +
        jsr d_unlink
        jmp d_nnext
+       lda d_ent+5             ; a conversation: zx02
        lsr
        bcc +
        jsr d_unzx
        jmp d_nnext
+
}
        jsr d_entrd
        jsr fl_read
d_nnext:
        lda d_term
        bne d_ok                ; $80+: that was the last
        jsr k_cb                ; another name follows
        jmp d_name
d_ok:   clc
        rts
d_fail: sec                     ; C set: the game retries, so a missing name
        rts                     ; hangs visibly instead of loading garbage

;;; ---- ^ a sector ----------------------------------------------------
d_read:
        jsr d_sector
        lda d_ment+3
        cmp #M_LOGGED
        bne dr_go
        jsr d_logkey            ; one the game writes: the newest copy
        jsr d_logfind
        bcs dr_go
        ldx #$02
-       lda d_ent,x
        sta d_ment,x
        dex
        bpl -
dr_go:  lda d_off               ; pages are page aligned: the offset is
        sta d_ra                ; the low byte
        lda d_ment+1
        sta d_ra+1
        lda d_ment+2
        sta d_ra+2
        lda d_cnt
        sta d_rl
        lda #$00
        sta d_rl+1
        lda d_cnt
        bne +
        inc d_rl+1              ; 0 = the whole sector
+       jsr d_dest
        lda d_dst
        sta d_rd
        lda d_dst+1
        sta d_rd+1
        jsr fl_read
        clc
        rts

;;; ---- & a write -----------------------------------------------------
d_write:
        jsr d_sector
!ifdef EF_BOOT {
        ;; THE WORLD RESET: the game keeps its world in the chunk files and
        ;; never resets them (the manual: play on fresh copies).  Character
        ;; creation's first write of the save area, 1A T6 S9, starts a new
        ;; log, once per boot.
        lda d_disk
        bne +
        lda d_t
        cmp #$06
        bne +
        lda d_s
        cmp #$09
        bne +
        lda EF_FRESH
        bne +
        inc EF_FRESH
        jsr d_reset
        bcc +
        jmp dw_fail
+
}
        lda d_ment+3
        cmp #M_BAM
        bcc dw_chunk
!ifdef EF_GAME {
        jsr d_close             ; the save area or a BAM: ends the session
}
        lda d_ment+3
        lsr
        bcc dw_ok               ; M_BAM: and goes nowhere
        jsr d_src               ; M_LOGGED: its own entry
!ifdef EF_GAME {
        jsr d_same_s            ; unless it is what the sector holds already
        bne +
        jmp dw_ok
+
}
        jsr e_begin
        bcs dw_fail
        jsr d_append            ; d_data <- where the page went
        bcs dw_fail_e
        jsr d_logkey
        ldx #DATALEN-4          ; the rest of the data zero
        lda #$00
-       sta d_data+3,x
        dex
        bpl -
        jsr d_entry
        bcs dw_fail_e
        jsr e_end
dw_ok:  clc
        rts
dw_fail_e:
        jsr e_end
dw_fail:
        sec
        rts
dw_chunk:
!ifdef EF_GAME {
        ;; A chunk file's sector, after its `!`.  While every page so far
        ;; equals the file's newest version, it is held back (only its link
        ;; bytes kept); the first that differs writes the held ones first,
        ;; from that version, so the file's pages stay in a row.
        jsr d_src
        lda EF_OPEN
        bne +
        jmp dw_ok               ; not after a `!`: nothing owns it
+       jsr d_lnk               ; d_link <- the page's link bytes
        lda EF_SCOUNT
        bne dk_write            ; writing already: on
        jsr d_same              ; still holding back: this one too?
        bne dk_flush
        ldx #$00                ; yes: the file's last page if its link's
        lda d_link              ; track is 0
        bne +
        inx
+       stx EF_SLAST
        inc EF_SPAGE
        jmp dw_ok
dk_flush:
        jsr e_begin
        bcs dk_fail
        jsr d_flush             ; the pages held back, first
        bcs dk_fail_e
        jmp dk_app
dk_write:
        jsr e_begin
        bcs dk_fail
dk_app: jsr d_sapp
        bcs dk_fail_e
        jsr e_end
        inc EF_SPAGE
        jmp dw_ok
dk_fail_e:
        jmp dw_fail_e
dk_fail:
        jmp dw_fail
}
        clc                     ; (no sessions at boot: nothing owns it)
        rts

!ifdef EF_GAME {
;;; ---- ! a file's first track/sector; opens its write session --------
d_find:
        jsr d_key               ; "!NAME"
        jsr d_dest
        jsr d_lookup
        bcc +
        rts                     ; (C set: not there)
+       lda #<(d_ent+6)         ; the two bytes to the caller
        sta k_rs+1
        lda #>(d_ent+6)
        sta k_rs+2
        lda d_dst
        sta k_rd+1
        lda d_dst+1
        sta k_rd+2
        lda #$02
        sta k_rn+1
        lda #DRVBANK
        jsr k_run
        ldx #KEYLEN-1           ; the session's key is "/NAME"
-       lda d_keybuf,x
        sta EF_SKEY,x
        dex
        bpl -
        lda #$2f
        sta EF_SKEY
        lda #$00
        sta EF_SCOUNT
        sta EF_SPAGE
        sta EF_SLAST
        jsr d_old
        lda #$01
        sta EF_OPEN
        clc
        rts

;;; end the write session: one entry for the file, if anything was written
;;; -- nothing if every page equalled the newest version to its last
d_close:
        lda EF_OPEN
        beq dc_out
        lda EF_SCOUNT
        bne dc_ent
        lda EF_SPAGE
        beq dc_shut             ; no page at all
        lda EF_SLAST
        bne dc_shut             ; the file as it was: no entry
        jsr e_begin             ; held back, but cut short: write them
        bcs dc_shut
        jsr d_flush
        bcs dc_fail
        jmp dc_ent2
dc_ent: jsr e_begin
        bcs dc_shut
dc_ent2:
        ldx #KEYLEN-1
-       lda EF_SKEY,x
        sta d_keybuf,x
        dex
        bpl -
        ldx #$02
-       lda EF_SSTART,x
        sta d_data,x
        dex
        bpl -
        lda EF_SCOUNT
        sta d_data+3
        lda #$00
        sta d_data+4
        sta d_data+6
        sta d_data+7
        lda #F_LINKS
        sta d_data+5
        jsr d_entry
dc_fail:
        jsr e_end
dc_shut:
        lda #$00
        sta EF_OPEN
dc_out: rts

;;; a logged chunk file: d_ent+3 pages at d_ent, each a whole sector with
;;; its link bytes; strip them as the drive would -- 254 data bytes from a
;;; middle sector, bytes 2..link+1 from the last
d_unlink:
        lda d_ent+3
        sta d_left
        ldx #$02
-       lda d_ent,x
        sta d_pa,x
        dex
        bpl -
du_page:
        lda d_rd                ; (fl_read moves it on)
        sta d_sv
        lda d_rd+1
        sta d_sv+1
        ldx #$02
-       lda d_pa,x
        sta d_ra,x
        dex
        bpl -
        lda #<d_link
        sta d_rd
        lda #>d_link
        sta d_rd+1
        lda #$02
        sta d_rl
        lda #$00
        sta d_rl+1
        jsr fl_read             ; d_ra is now the page + 2
        lda d_sv
        sta d_rd
        lda d_sv+1
        sta d_rd+1
        lda #254
        ldx d_link
        bne +
        ldx d_link+1            ; the last: link+1 - 1 bytes
        dex
        txa
+       sta d_rl
        lda #$00
        sta d_rl+1
        jsr fl_read
        inc d_pa+1
        bne +
        inc d_pa+2
+       dec d_left
        bne du_page
        rts

;;; a conversation: zx02 from d_ent to d_rd, at $01 = $37 (it lands in
;;; plain RAM, $6800 or $C000, which the decoder reads back)
d_unzx:
        lda d_rd
        sta zx_put+1
        lda d_rd+1
        sta zx_put+2
        lda d_ent
        sta k_gbp+1
        lda d_ent+1
        and #$3f
        ora #$80
        sta k_gbp+2
        lda d_ent+2
        sta d_tmp
        lda d_ent+1
        asl
        rol d_tmp
        asl
        rol d_tmp
        lda d_tmp
        sta k_gbank
        jmp k_zx
}   ; EF_GAME

!ifdef EF_BOOT {
;;; ---- # which disk: SU and DU have sectors, the others are read by name
d_id:   jsr k_cb
        tax
        jsr k_cb                ; the second letter: U for both
        lda #$00
        cpx #$53                ; S
        beq +
        lda #$01
        cpx #$44                ; D
        bne ++
+       sta d_disk
++      clc
        rts

;;; ---- * a cart with no log (efinit: neither half has a header) --------
;;; the reset below, and the world counts as reset for this boot: character
;;; creation's first write need not do it again
d_new:  inc EF_FRESH
        jmp d_reset

;;; ---- the world reset: a new, empty log in the other half --------------
;;; Erase the other half, then write a header with the next generation into
;;; its top slot: from then on it is the active half (init's rule: the valid
;;; half with the higher generation), with nothing in it.  The old half
;;; stays as it is until a compaction erases it as its target.  A power cut
;;; before the header is complete leaves the old world active.
d_reset:
        jsr e_begin
        bcc +
        rts
+
        lda #$00                ; the music silent while the erases hold
        sta $d418               ; interrupts off (a second or more each):
                                ; THEME's player writes the volume every
                                ; frame, so it is back on the first after
                                ; them (else the music hangs on a note at
                                ; the end of creation)
        lda EF_ACT
        eor #$03
        sta d_left              ; the other half
        tax
        lda d_hbank,x           ; its two 64 KiB sectors
        ldy #$80
        jsr e_erase
        bcc +
        jmp drs_fail
+
        ldx d_left
        lda d_hbank,x
        ldy #$e0
        jsr e_erase
        bcc +
        jmp drs_fail
+
        jsr d_hdr
        lda d_data
        sta EF_GEN
        lda d_data+1
        sta EF_GEN+1
        ldx d_left              ; the log is now that half: empty
        stx EF_ACT
        lda d_hbase,x           ; data from its base
        sta EF_LOGDATA
        lda d_hbase+1,x
        sta EF_LOGDATA+1
        lda d_hbase+2,x
        sta EF_LOGDATA+2
        lda d_htop,x            ; entries from its top
        sta EF_LOGDIR
        lda d_htop+1,x
        sta EF_LOGDIR+1
        lda d_htop+2,x
        sta EF_LOGDIR+2
        lda #$00
        sta EF_DIRCOUNT
        sta EF_DIRCOUNT+1
        jsr d_entry             ; the header: count 1
        bcc +
        jmp drs_fail
+
        jsr e_end
        clc
drs_out:
        rts
drs_fail:
        jsr e_end
        sec
        rts

;;; ---- `game` is loaded: its one-time init, copied from flash to INIT_AT
;;; (ultima/games/u6/build.py relocate_init); the trampoline jumps there
d_handoff:
        lda #<INIT_SRC
        sta d_ra
        lda #>INIT_SRC
        sta d_ra+1
        lda #^INIT_SRC
        sta d_ra+2
        lda #<INIT_LEN
        sta d_rl
        lda #>INIT_LEN
        sta d_rl+1
        lda #<INIT_AT
        sta d_rd
        lda #>INIT_AT
        sta d_rd+1
        jsr fl_read
        clc
        rts
}   ; EF_BOOT

;;; ==================================================================
;;; helpers
;;; ==================================================================

;;; the halves, as init's tables: half 0 at +0, half 1 at +3
d_hbase: !24 LOG_LO, LOG_MID
d_htop:  !24 LOG_MID, LOG_HI
d_hbank: !byte LOG_LO >> 14, 0, 0, LOG_MID >> 14

;;; d_keybuf/d_data <- a half's header: $FE "LOG", generation EF_GEN + 1
;;; and its complement (EF_GEN as it was)
d_hdr:  ldx #ENTRYLEN-1
        lda #$00
-       sta d_keybuf,x
        dex
        bpl -
        lda #K_HEADER
        sta d_keybuf
        lda #$4c
        sta d_keybuf+1
        lda #$4f
        sta d_keybuf+2
        lda #$47
        sta d_keybuf+3
        clc
        lda EF_GEN
        adc #$01
        sta d_data
        eor #$ff
        sta d_data+2
        lda EF_GEN+1
        adc #$00
        sta d_data+1
        eor #$ff
        sta d_data+3
        rts

;;; the name from the command into d_keybuf, zero padded; the first byte
;;; is in A.  A = the terminator ($00, or $80+) on return.
d_key:
        ldy #$00
-       cmp #$00
        beq +
        cmp #$80
        bcs +
        sta d_keybuf,y
        iny
        jsr k_cb                ; (keeps Y)
        jmp -
+       pha
        lda #$00
-       cpy #KEYLEN
        beq +
        sta d_keybuf,y
        iny
        bne -
+       pla
        rts

;;; d_dst <- the next two command bytes
d_dest: jsr k_cb
        sta d_dst
        jsr k_cb
        sta d_dst+1
        rts

;;; the write's source, the next two command bytes, into e_write's operand
d_src:  jsr k_cb
        sta d_wsrc
        jsr k_cb
        sta d_wsrc+1
        rts

;;; d_ra/d_rl <- the found entry's address and length
d_entrd:
        ldx #$04
-       lda d_ent,x
        sta d_ra,x              ; (d_ra and d_rl are adjacent)
        dex
        bpl -
        rts

;;; d_keybuf <- a logged sector's key: K_SECTOR, disk, track, sector
d_logkey:
        ldy #KEYLEN-1
        lda #$00
-       sta d_keybuf,y
        dey
        bne -
        lda #K_SECTOR
        sta d_keybuf
        lda d_disk
        sta d_keybuf+1
        lda d_t
        sta d_keybuf+2
        lda d_s
        sta d_keybuf+3
        rts

;;; t, s, off, cnt from the command; d_ment <- the block map's entry: a
;;; page's address (3) and its mark
d_sector:
        jsr k_cb
        sta d_t
        jsr k_cb
        sta d_s
        jsr k_cb
        sta d_off
        jsr k_cb
        sta d_cnt
        ;; The block map is a grid of 21 entries per track (the longest
        ;; track), 4 bytes each: (t * 21 + s) * 4
        lda #$00
        sta d_tmp
        lda d_s
        ldx d_t
-       clc
        adc #21
        bcc +
        inc d_tmp
+       dex
        bne -
        asl
        rol d_tmp
        asl
        rol d_tmp
        ldx d_disk
        clc
        adc d_maplo,x
        sta d_ra
        lda d_mapmid,x
        adc d_tmp
        sta d_ra+1
        lda d_maphi,x
        adc #$00
        sta d_ra+2
        lda #$04
        sta d_rl
        lda #$00
        sta d_rl+1
        lda #<d_ment
        sta d_rd
        lda #>d_ment
        sta d_rd+1
        jmp fl_read

d_maplo:  !byte <MAP0, <MAP1
d_mapmid: !byte >MAP0, >MAP1
d_maphi:  !byte ^MAP0, ^MAP1

;;; ---- the directories ---------------------------------------------------
;;; d_keybuf: in the write log first, whose newest entries come first, then
;;; in the build's own.  C clear and d_ent (address 3, length 2, flags,
;;; extra 2) set if found.
d_lookup:
        jsr d_logfind
        bcc +
        jmp d_sfind
+       rts

d_logfind:
        ldx #$02
-       lda EF_LOGDIR,x
        sta d_w,x
        dex
        bpl -
        lda EF_DIRCOUNT
        sta d_n
        lda EF_DIRCOUNT+1
        sta d_n+1
lf_loop:
        lda d_n
        ora d_n+1
        bne +
        sec
        rts
+       jsr d_wkey
        beq lf_hit
        clc                     ; the next older entry
        lda d_w
        adc #ENTRYLEN
        sta d_w
        bcc +
        inc d_w+1
        bne +
        inc d_w+2
+       lda d_n
        bne +
        dec d_n+1
+       dec d_n
        jmp lf_loop
lf_hit: clc                     ; its data: 8 bytes after the key
        lda d_w
        adc #KEYLEN
        sta d_ra
        lda d_w+1
        adc #$00
        sta d_ra+1
        lda d_w+2
        adc #$00
        sta d_ra+2
d_getent:
        lda #DATALEN
        sta d_rl
        lda #$00
        sta d_rl+1
        lda #<d_ent
        sta d_rd
        lda #>d_ent
        sta d_rd+1
        jsr fl_read
        clc
        rts

;;; compare the key at the linear address d_w with d_keybuf: Z set if equal
d_wkey:
        lda d_w
        sta k_cp+1
        lda d_w+1
        and #$3f
        ora #$80
        sta k_cp+2
        cmp #$bf                ; within KEYLEN of the bank's end?
        bne +
        lda d_w
        cmp #$100-KEYLEN+1
        bcs dw_slow
+       lda d_w+2
        sta d_tmp
        lda d_w+1
        asl
        rol d_tmp
        asl
        rol d_tmp
        lda d_tmp
        jmp k_cmp
dw_slow:                        ; the key spans two banks: read it, compare
        ldx #$02                ; here
-       lda d_w,x
        sta d_ra,x
        dex
        bpl -
        lda #KEYLEN
        sta d_rl
        lda #$00
        sta d_rl+1
        lda #<d_kt
        sta d_rd
        lda #>d_kt
        sta d_rd+1
        jsr fl_read
        ldy #KEYLEN-1
-       lda d_keybuf,y
        cmp d_kt,y
        bne +
        dey
        bpl -
        lda #$00                ; Z set: equal
+       rts

;;; the static directory: sorted by key, SCOUNT entries at SDIR in this
;;; bank's ROMH -- a binary search
d_sfind:
        lda #$00
        sta d_lo
        sta d_lo+1
        lda #<SCOUNT
        sta d_hi
        lda #>SCOUNT
        sta d_hi+1
sf_loop:
        lda d_lo                ; lo < hi?
        cmp d_hi
        lda d_lo+1
        sbc d_hi+1
        bcc +
        rts                     ; no: not there (C set)
+       clc                     ; mid = (lo + hi) / 2
        lda d_lo
        adc d_hi
        sta d_mid
        lda d_lo+1
        adc d_hi+1
        ror
        sta d_mid+1
        ror d_mid
        lda d_mid               ; its entry: SDIR + mid * 20
        asl
        sta d_t4
        lda d_mid+1
        rol
        sta d_t4+1
        asl d_t4
        rol d_t4+1              ; mid * 4
        lda d_t4
        asl
        sta d_p
        lda d_t4+1
        rol
        sta d_p+1
        asl d_p
        rol d_p+1               ; mid * 16
        clc
        lda d_p
        adc d_t4
        sta d_p
        lda d_p+1
        adc d_t4+1
        sta d_p+1
        clc
        lda d_p
        adc #<SDIR
        sta d_p
        sta k_cp+1
        lda d_p+1
        adc #>SDIR
        sta d_p+1
        sta k_cp+2
        lda #DRVBANK
        jsr k_cmp
        beq sf_hit
        bcc sf_lower            ; the key is below this entry
        clc
        lda d_mid
        adc #$01
        sta d_lo
        lda d_mid+1
        adc #$00
        sta d_lo+1
        jmp sf_loop
sf_lower:
        lda d_mid
        sta d_hi
        lda d_mid+1
        sta d_hi+1
        jmp sf_loop
sf_hit: clc                     ; its data, read as any flash: this bank's
        lda d_p                 ; ROMH is linear DRVBANK * $4000 + $2000
        adc #KEYLEN
        sta d_ra
        lda d_p+1
        adc #$00
        and #$3f
        ora #<(DRVBANK << 6)
        sta d_ra+1
        lda #(DRVBANK >> 2)
        sta d_ra+2
        jmp d_getent

;;; ---- the flash -----------------------------------------------------------
;;; d_rl bytes from the linear address d_ra to d_rd -- anywhere in RAM but the
;;; cart's own $DE00-$DFFF -- in runs that never cross a source page; all
;;; three move on
fl_read:
fr_loop:
        lda d_rl
        ora d_rl+1
        bne +
        rts
+       sec                     ; to the page's end (0 = 256)
        lda #$00
        sbc d_ra
        sta d_run
        lda d_rl+1
        bne fr_go               ; 256 or more left: to the page's end
        lda d_run
        beq fr_rl               ; a whole page and less than that left
        cmp d_rl
        bcc fr_go
fr_rl:  lda d_rl
        sta d_run
fr_go:  ldx #$00                ; does the run touch page 3 (KERNAL's
        lda d_rd+1              ; vectors, see k_run)?
        cmp #$03
        beq fr_hz
        cmp #$02
        bne fr_nohz
        lda d_run               ; from page 2 into page 3?
        beq +
        clc
        adc d_rd
        bcc fr_nohz
        bcs fr_hz
+       lda d_rd                ; (a whole page: unless it starts at $0200)
        beq fr_nohz
fr_hz:  inx
fr_nohz:
        stx k_hz
        lda d_run
        sta k_rn+1
        lda d_ra
        sta k_rs+1
        lda d_ra+1
        and #$3f
        ora #$80
        sta k_rs+2
        lda d_rd
        sta k_rd+1
        lda d_rd+1
        sta k_rd+2
        lda d_ra+2
        sta d_tmp
        lda d_ra+1
        asl
        rol d_tmp
        asl
        rol d_tmp
        lda d_tmp
        jsr k_run
        lda d_run
        bne fr_part
        inc d_ra+1              ; a whole page
        bne +
        inc d_ra+2
+       inc d_rd+1
        dec d_rl+1
        jmp fr_loop
fr_part:
        clc
        adc d_ra
        sta d_ra
        bcc +
        inc d_ra+1
        bne +
        inc d_ra+2
+       clc
        lda d_run
        adc d_rd
        sta d_rd
        bcc +
        inc d_rd+1
+       sec
        lda d_rl
        sbc d_run
        sta d_rl
        bcs +
        dec d_rl+1
+       jmp fr_loop

;;; ---- the log: writes through EAPI --------------------------------------
;;; EAPI into the slot and initialised; C set if that failed (EF_ERR says
;;; why), the slot already put back
e_begin:
        lda #<EAPI_LIN
        sta d_ra
        lda #>EAPI_LIN
        sta d_ra+1
        lda #^EAPI_LIN
        sta d_ra+2
        lda #<EAPI_SIZE
        sta d_rl
        lda #>EAPI_SIZE
        sta d_rl+1
        lda #<EAPI_SLOT
        sta d_rd
        lda #>EAPI_SLOT
        sta d_rd+1
        jsr fl_read
        jsr e_init
        bcc +
        sta EF_ERR
        jsr e_end
        sec
+       rts

;;; the slot as it was: what the context had there, from its file in flash
e_end:
        lda #<SLOT_SRC
        sta d_ra
        lda #>SLOT_SRC
        sta d_ra+1
        lda #^SLOT_SRC
        sta d_ra+2
        lda #<EAPI_SIZE
        sta d_rl
        lda #>EAPI_SIZE
        sta d_rl+1
        lda #<EAPI_SLOT
        sta d_rd
        lda #>EAPI_SLOT
        sta d_rd+1
        jmp fl_read

;;; the page at d_wsrc to the log; d_data (3) <- where it went.  C set if
;;; the log is full or the write failed.  In the game a full log is
;;; compacted first (d_pack), once; at boot it cannot be full -- the only
;;; writes there are character creation's, into the log its reset began.
d_append:
        jsr da_room
        bcc da_go
!ifdef EF_GAME {
        jsr d_pack
        bcs da_full
        jsr da_room
        bcc da_go
}
da_full:
        sec
        rts
da_go:  ldx #$02
-       lda EF_LOGDATA,x
        sta d_wa,x
        sta d_data,x
        dex
        bpl -
        lda #$00                ; 256 bytes
        sta d_wn
        jsr e_put
        bcs +
        inc EF_LOGDATA+1
        bne +
        inc EF_LOGDATA+2
+       rts

;;; C clear if a page and an entry fit below the directory: two pages kept
;;; clear, so the entries that close a save always do
da_room:
        lda EF_LOGDATA+1
        clc
        adc #$02
        tax
        lda EF_LOGDATA+2
        adc #$00
        cmp EF_LOGDIR+2
        bcc +
        bne ++
        cpx EF_LOGDIR+1
        bcc +
++      sec
        rts
+       clc
        rts

;;; d_keybuf + d_data as the log's newest directory entry
d_entry:
        sec
        lda EF_LOGDIR
        sbc #ENTRYLEN
        sta EF_LOGDIR
        sta d_wa
        lda EF_LOGDIR+1
        sbc #$00
        sta EF_LOGDIR+1
        sta d_wa+1
        lda EF_LOGDIR+2
        sbc #$00
        sta EF_LOGDIR+2
        sta d_wa+2
        lda #<d_keybuf          ; key and data are adjacent
        sta d_wsrc
        lda #>d_keybuf
        sta d_wsrc+1
        lda #ENTRYLEN
        sta d_wn
        jsr e_put
        bcs +
        inc EF_DIRCOUNT
        bne +
        inc EF_DIRCOUNT+1
+       rts

;;; d_wn bytes (0 = 256) from d_wsrc in RAM to the linear address d_wa
e_put:
        lda d_wsrc
        sta e_ws+1
        lda d_wsrc+1
        sta e_ws+2
        lda d_wn
        sta e_wn+1
        lda d_wa+2
        sta d_tmp
        lda d_wa+1
        asl
        rol d_tmp
        asl
        rol d_tmp
        lda d_wa+1
        and #$3f
        ora #$80
        tay
        ldx d_wa
        lda d_tmp
        jmp e_write

!ifdef EF_GAME {
;;; ==================================================================
;;; in the game: pages compared, held back, written; the compaction
;;; ==================================================================
;;; The buffers are the idle half of the sprite double buffer, $D800 or
;;; $DC00 ($27 bit 4 names the half on screen): the tapecart build runs its
;;; on-demand driver there during every command but a sector read (U6 notes),
;;; and nothing draws into it meanwhile.  Under I/O, so only k_run (at $33
;;; or $34), k_eq and e_write touch it.  Buffer A is its first page (a page
;;; compared or held back), B its second (the compaction's copies), and the
;;; spinner's cell is kept in its last eight bytes.

;;; P_BUF and A <- the idle half's first page
d_buf:  lda $27
        and #$10
        lsr
        lsr
        eor #$dc
        sta P_BUF
        rts

;;; d_rd/d_rl <- buffer A, a page
d_bufa: jsr d_buf
        ldx #$00
        beq +
;;; ... buffer B
d_bufb: jsr d_buf
        ldx #$01
+       stx d_tmp
        clc
        adc d_tmp
        sta d_rd+1
        lda #$00
        sta d_rd
        sta d_rl
        lda #$01
        sta d_rl+1
        rts

;;; Z set if A bytes (0 = 256) of the page at d_wsrc equal buffer A's
d_cmpa: sta k_qn+1
        lda d_wsrc
        sta k_qa+1
        lda d_wsrc+1
        sta k_qa+2
        lda #$00
        sta k_qb+1
        lda P_BUF
        sta k_qb+2
        jmp k_eq

;;; d_link <- the first two bytes of the page at d_wsrc (perhaps under I/O)
d_lnk:  lda d_wsrc
        sta k_rs+1
        lda d_wsrc+1
        sta k_rs+2
        lda #<d_link
        sta k_rd+1
        lda #>d_link
        sta k_rd+2
        lda #$02
        sta k_rn+1
        lda #$34
        sta k_rp+1
        lda #$00
        sta k_hz
        lda #DRVBANK
        jsr k_run
        lda #$33
        sta k_rp+1
        rts

;;; Z set if the save-area sector at d_wsrc equals its newest version: the
;;; log's, or the block map's page (d_ment)
d_same_s:
        jsr d_logkey
        jsr d_logfind
        bcs +
        ldx #$02
-       lda d_ent,x
        sta d_ment,x
        dex
        bpl -
+       ldx #$02
-       lda d_ment,x
        sta d_ra,x
        dex
        bpl -
        jsr d_bufa
        jsr fl_read
        lda #$00
        jmp d_cmpa

;;; the session's file, its newest version: EF_OADDR/OLEN/OFLAG, from the
;;; log (pages with their links: F_LINKS) or the build (raw), or EF_OFLAG
;;; = $FF if it has none
d_old:  ldx #KEYLEN-1
-       lda EF_SKEY,x
        sta d_keybuf,x
        dex
        bpl -
        jsr d_lookup
        lda #$ff
        bcs +
        ldx #$02
-       lda d_ent,x
        sta EF_OADDR,x
        dex
        bpl -
        lda d_ent+3
        sta EF_OLEN
        lda d_ent+4
        sta EF_OLEN+1
        lda d_ent+5
+       sta EF_OFLAG
        rts

;;; Z set if the page at d_wsrc (its links in d_link) equals page EF_SPAGE
;;; of the file's newest version -- its whole page if logged; if raw, the
;;; bytes the drive would give for it, links and all, and only the last
;;; page may say it is the last.  Its links are kept in d_links either way.
ds_ne0: lda #$01                ; Z clear
        rts
d_same:
        lda EF_SPAGE
        cmp #MAXHOLD
        bcs ds_ne0              ; no room to hold it back
        asl
        tax
        lda d_link
        sta d_links,x
        lda d_link+1
        sta d_links+1,x
        lda EF_OFLAG
        cmp #$ff
        beq ds_ne               ; a file new to this world
        and #F_LINKS
        beq ds_raw
        lda EF_OLEN+1           ; logged: so many pages?
        bne +
        lda EF_SPAGE
        cmp EF_OLEN
        bcs ds_ne
+       lda EF_SPAGE
        jsr d_oldpg
        lda #$00                ; the whole page
        jmp d_cmpa
ds_raw: lda EF_SPAGE            ; raw: its bytes from page * 254
        jsr d_off254
        lda d_link
        beq ds_last
        clc                     ; a middle page: the file goes on after it
        lda d_p
        adc #254
        tax
        lda d_p+1
        adc #$00
        cpx EF_OLEN
        sbc EF_OLEN+1
        bcs ds_ne
        lda EF_SPAGE
        jsr d_oldpg
        lda #$00
        jmp d_cmpa
ds_last:
        lda d_link+1            ; the last: bytes 2..s, so the file ends
        cmp #$02                ; at page * 254 + s - 1
        bcc ds_ne
        sbc #$01                ; (C set)
        clc
        adc d_p
        tax
        lda d_p+1
        adc #$00
        cpx EF_OLEN
        bne ds_ne
        cmp EF_OLEN+1
        bne ds_ne
        lda EF_SPAGE
        jsr d_oldpg
        lda d_link+1            ; s + 1 bytes (s = 255: 0, the page)
        clc
        adc #$01
        jmp d_cmpa
ds_ne:  lda #$01                ; Z clear
        rts

;;; d_p <- A * 254 (A < 128)
d_off254:
        sta d_p+1
        asl
        sta d_tmp
        lda #$00
        sec
        sbc d_tmp
        sta d_p
        bcs +
        dec d_p+1
+       rts

;;; buffer A <- page A of the session file's newest version: logged, the
;;; page itself; raw, the links it was held back with and 254 bytes of
;;; the file
d_oldpg:
        sta d_j2
        jsr d_bufa
        lda EF_OFLAG
        and #F_LINKS
        beq og_raw
        lda EF_OADDR
        sta d_ra
        clc
        lda EF_OADDR+1
        adc d_j2
        sta d_ra+1
        lda EF_OADDR+2
        adc #$00
        sta d_ra+2
        jmp fl_read
og_raw: lda d_j2
        asl
        clc
        adc #<d_links
        sta k_rs+1
        lda #>d_links
        adc #$00
        sta k_rs+2
        lda #$00
        sta k_rd+1
        sta k_hz
        lda P_BUF
        sta k_rd+2
        lda #$02
        sta k_rn+1
        lda #DRVBANK
        jsr k_run
        lda d_j2
        jsr d_off254
        clc
        lda EF_OADDR
        adc d_p
        sta d_ra
        lda EF_OADDR+1
        adc d_p+1
        sta d_ra+1
        lda EF_OADDR+2
        adc #$00
        sta d_ra+2
        lda #$02
        sta d_rd
        lda #254
        sta d_rl
        lda #$00
        sta d_rl+1
        jmp fl_read

;;; the EF_SPAGE pages held back, from the newest version, into the log
;;; (EAPI in); d_wsrc kept.  C set if a write failed.
d_flush:
        lda d_wsrc
        pha
        lda d_wsrc+1
        pha
        lda #$00
        sta d_j
df_loop:
        lda d_j
        cmp EF_SPAGE
        bcs df_done
        jsr d_oldpg
        lda #$00
        sta d_wsrc
        lda P_BUF
        sta d_wsrc+1
        jsr d_sapp
        bcs df_out
        inc d_j
        jmp df_loop
df_done:
        clc
df_out: pla
        sta d_wsrc+1
        pla
        sta d_wsrc
        rts

;;; the page at d_wsrc into the log as the session's next; the first one
;;; is where its pages start
d_sapp: jsr d_append
        bcs ++
        lda EF_SCOUNT
        bne +
        ldx #$02
-       lda d_data,x
        sta EF_SSTART,x
        dex
        bpl -
+       inc EF_SCOUNT
        clc
++      rts

;;; ---- the compaction -------------------------------------------------
;;; The log is full (d_append, EAPI in): copy the newest version of every
;;; key into the other half, the open session's pages after them, write
;;; the header (generation + 1) last.  From then on that half is the
;;; active one; the old stays as it is, the next compaction's target (a
;;; power cut anywhere before the header leaves the log as it was).  An
;;; entry is live if no newer one with its key has been copied yet: the
;;; walk goes newest first, and looks the key up in the new directory.
;;; d_wsrc is kept, d_keybuf/d_data are not.  C set if a write failed.
d_pack: lda d_wsrc
        sta P_WSRC
        lda d_wsrc+1
        sta P_WSRC+1
        jsr d_buf
        jsr sp_save
        lda EF_ACT
        eor #$03
        sta P_TGT
        tax
        lda d_hbank,x           ; the other half, erased
        ldy #$80
        jsr e_erase
        bcc +
        jmp pk_fail
+
        jsr sp_turn
        ldx P_TGT
        lda d_hbank,x
        ldy #$e0
        jsr e_erase
        bcc +
        jmp pk_fail
+
        ldx P_TGT
        ldy #$00
-       lda d_hbase,x
        sta P_NDATA,y
        lda d_htop,x
        sta P_NDIR,y
        inx
        iny
        cpy #$03
        bne -
        jsr pk_down             ; the header's slot: the entries below it
        lda #$00
        sta P_NLIVE
        sta P_NLIVE+1
        ldx #17
-       sta P_SEEN,x
        dex
        bpl -
        ldx #$04                ; the walk: EF_LOGDIR (3), EF_DIRCOUNT (2)
-       lda EF_LOGDIR,x
        sta P_WALK,x
        dex
        bpl -
pk_walk:
        lda P_LEFT
        ora P_LEFT+1
        bne +
        jmp pk_sess
+       jsr sp_turn
        ldx #$02                ; the entry, into d_keybuf/d_data
-       lda P_WALK,x
        sta d_ra,x
        dex
        bpl -
        lda #ENTRYLEN
        sta d_rl
        lda #$00
        sta d_rl+1
        lda #<d_keybuf
        sta d_rd
        lda #>d_keybuf
        sta d_rd+1
        jsr fl_read
        lda d_keybuf
        cmp #K_HEADER
        beq pk_next
        jsr pk_bit              ; copied already, a newer version?
        bcs pk_find
        sta d_tmp
        and P_SEEN,x
        bne pk_next
        lda d_tmp
        ora P_SEEN,x
        sta P_SEEN,x
        jmp pk_live
pk_find:                        ; (no key the game logs: the slow way)
        ldx #$02
-       lda P_NDIR,x
        sta d_w,x
        dex
        bpl -
        lda P_NLIVE
        sta d_n
        lda P_NLIVE+1
        sta d_n+1
        jsr lf_loop
        bcc pk_next
pk_live:
        ldx #$01                ; live: its pages, a file's count or one
        ldy #$00
        lda d_data+5
        and #F_LINKS
        beq +
        ldx d_data+3
        ldy d_data+4
+       stx P_NPAGES
        sty P_NPAGES+1
        ldx #$02                ; from where they are to the new half,
-       lda d_data,x            ; which is the entry's new address
        sta P_SRC,x
        lda P_NDATA,x
        sta d_data,x
        dex
        bpl -
        jsr pk_copy
        bcs pk_fail
        jsr pk_down
        jsr pk_ent
        bcs pk_fail
        inc P_NLIVE
        bne pk_next
        inc P_NLIVE+1
pk_next:
        clc
        lda P_WALK
        adc #ENTRYLEN
        sta P_WALK
        bcc +
        inc P_WALK+1
        bne +
        inc P_WALK+2
+       lda P_LEFT
        bne +
        dec P_LEFT+1
+       dec P_LEFT
        jmp pk_walk
pk_fail:
        sec
        jmp pk_out
pk_sess:                        ; the open session's pages follow
        lda EF_OPEN
        beq pk_head
        lda EF_SCOUNT
        beq pk_head
        sta P_NPAGES
        lda #$00
        sta P_NPAGES+1
        ldx #$02
-       lda EF_SSTART,x
        sta P_SRC,x
        lda P_NDATA,x
        sta EF_SSTART,x
        dex
        bpl -
        jsr pk_copy
        bcs pk_fail
pk_head:                        ; the header, last
        jsr d_hdr
        ldx P_TGT
        sec
        lda d_htop,x
        sbc #ENTRYLEN
        sta d_wa
        lda d_htop+1,x
        sbc #$00
        sta d_wa+1
        lda d_htop+2,x
        sbc #$00
        sta d_wa+2
        jsr pk_put
        bcs pk_fail
        ldx #$02                ; the log goes on in the new half
-       lda P_NDIR,x
        sta EF_LOGDIR,x
        lda P_NDATA,x
        sta EF_LOGDATA,x
        dex
        bpl -
        clc
        lda P_NLIVE
        adc #$01
        sta EF_DIRCOUNT
        lda P_NLIVE+1
        adc #$00
        sta EF_DIRCOUNT+1
        lda P_TGT
        sta EF_ACT
        lda d_data
        sta EF_GEN
        lda d_data+1
        sta EF_GEN+1
        lda EF_OPEN             ; the session's file has moved
        beq +
        jsr d_old
+       clc
pk_out: php
        jsr sp_rest
        lda P_WSRC
        sta d_wsrc
        lda P_WSRC+1
        sta d_wsrc+1
        plp
        rts

;;; P_NPAGES pages from P_SRC to P_NDATA, both moving on, through buffer B
pk_copy:
        lda P_NPAGES
        ora P_NPAGES+1
        bne +
        clc
        rts
+       jsr sp_turn
        ldx #$02
-       lda P_SRC,x
        sta d_ra,x
        lda P_NDATA,x
        sta d_wa,x
        dex
        bpl -
        jsr d_bufb
        jsr fl_read
        lda #$00
        sta d_wsrc
        sta d_wn
        ldx P_BUF
        inx
        stx d_wsrc+1
        jsr e_put
        bcs ++
        inc P_SRC+1
        bne +
        inc P_SRC+2
+       inc P_NDATA+1
        bne +
        inc P_NDATA+2
+       lda P_NPAGES
        bne +
        dec P_NPAGES+1
+       dec P_NPAGES
        jmp pk_copy
++      rts

;;; d_keybuf's key as a bit of P_SEEN: X its byte, A its mask; C set if
;;; it is none of the keys the game logs -- a chunk file "/" [SD] [A-H]
;;; [A-H] (0-127) or a save-area sector 1, 0, 6, 9-20 (128-139)
pk_bit: ldx #KEYLEN-1
-       lda d_keybuf,x
        bne pb_no
        dex
        cpx #$03
        bne -
        lda d_keybuf
        cmp #K_SECTOR
        beq pb_sec
        cmp #$2f                ; /
        bne pb_no
        ldy #$00
        lda d_keybuf+1
        cmp #$53                ; S
        beq +
        ldy #$40
        cmp #$44                ; D
        bne pb_no
+       sty d_tmp
        lda d_keybuf+2
        sec
        sbc #$41                ; A
        cmp #$08
        bcs pb_no
        asl
        asl
        asl
        ora d_tmp
        sta d_tmp
        lda d_keybuf+3
        sec
        sbc #$41
        cmp #$08
        bcs pb_no
        ora d_tmp
        jmp pb_idx
pb_sec: lda d_keybuf+1
        bne pb_no
        lda d_keybuf+2
        cmp #$06
        bne pb_no
        lda d_keybuf+3
        sec
        sbc #$09
        cmp #$0c
        bcs pb_no
        ora #$80
pb_idx: pha
        lsr
        lsr
        lsr
        tax
        pla
        and #$07
        tay
        lda pb_mask,y
        clc
        rts
pb_no:  sec
        rts
pb_mask: !byte $01, $02, $04, $08, $10, $20, $40, $80

;;; P_NDIR -= ENTRYLEN
pk_down:
        sec
        lda P_NDIR
        sbc #ENTRYLEN
        sta P_NDIR
        lda P_NDIR+1
        sbc #$00
        sta P_NDIR+1
        lda P_NDIR+2
        sbc #$00
        sta P_NDIR+2
        rts

;;; d_keybuf/d_data to P_NDIR (pk_ent) or to d_wa (pk_put)
pk_ent: ldx #$02
-       lda P_NDIR,x
        sta d_wa,x
        dex
        bpl -
pk_put: lda #<d_keybuf
        sta d_wsrc
        lda #>d_keybuf
        sta d_wsrc+1
        lda #ENTRYLEN
        sta d_wn
        jmp e_put

;;; ---- the spinner: one character cell of the game's bitmap turns while
;;; the compaction runs (the tapecart build's u6pack does the same), the
;;; cell kept and put back.  The bitmap ($E000) and its colours ($CC00) are
;;; RAM; a store reaches it with the KERNAL in, a read needs $01 = $34.
SPIN_BM = $e000 + 23 * 320 + 23 * 8     ; the cursor's cell, after the prompt `>`
SPIN_SC = $cc00 + 23 * 40 + 23          ; (at row 23 col 22: read from the bitmap)

sp_save:
        lda SPIN_SC
        sta P_SC
        lda #$10                ; white on black, in either bitmap mode
        sta SPIN_SC
        lda #<SPIN_BM
        sta k_rs+1
        lda #>SPIN_BM
        sta k_rs+2
        lda #$f8
        sta k_rd+1
        ldx P_BUF
        inx
        inx
        inx
        stx k_rd+2
        jmp sp_cp
sp_rest:
        lda P_SC
        sta SPIN_SC
        lda #$f8
        sta k_rs+1
        ldx P_BUF
        inx
        inx
        inx
        stx k_rs+2
        lda #<SPIN_BM
        sta k_rd+1
        lda #>SPIN_BM
        sta k_rd+2
sp_cp:  lda #$08
        sta k_rn+1
        lda #$34
        sta k_rp+1
        lda #$00
        sta k_hz
        lda #DRVBANK
        jsr k_run
        lda #$33
        sta k_rp+1
        rts

;;; the spinner's next frame
sp_turn:
        inc P_FRAME
        lda P_FRAME
        and #$03
        asl
        asl
        asl
        tax
        ldy #$00
-       lda sp_frames,x
        sta SPIN_BM,y
        inx
        iny
        cpy #$08
        bne -
        rts
sp_frames:                      ; a bar turning, in %01 pixel pairs
        !byte $14, $14, $14, $14, $14, $14, $14, $14        ; |
        !byte $01, $01, $04, $04, $10, $10, $40, $40        ; /
        !byte $00, $00, $00, $55, $55, $00, $00, $00        ; -
        !byte $40, $40, $10, $10, $04, $04, $01, $01        ; \\
}   ; EF_GAME

drv_end:
!if drv_end > $a000 {
        !error "the driver runs into this bank's ROMH by ", drv_end - $a000
}
