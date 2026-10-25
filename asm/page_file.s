;;; page_file.s -- a saved game to and from one file on any disk, for the
;;; launcher's page (included by page.s after page_u6x.s, whose drive, table
;;; and log routines it uses).  E and I ask "(D)isks or (F)ile?"; D is the
;;; games' own disks (page_xfer.s, page_u6x.s), F this.
;;;
;;; One SEQ file a game, "ULTIMA IV SAVE" and so on, on whatever disk is in
;;; the drive (8 to 11, page_xfer.s).  It only has to make sense to this page:
;;;
;;;   "UCSV", the game's number (1-6), F_VERSION
;;;   Ultima I-V:  the number of slots in the game's table (xfer.py), then
;;;                per slot, in the table's order: 1 and its length (lo,
;;;                hi) and that many bytes -- what the disk export would
;;;                write there: a raw slot's pages (length 0, pages), a
;;;                file's bytes -- or 0, 0, 0 for a slot with nothing in it
;;;   Ultima VI:   records: 1, a chunk file's three-letter name, n, and its
;;;                n pages as the write log holds them (sectors with their
;;;                links); 2, a save-area sector number (1A T6 S9-20) and
;;;                its 256 bytes; 0 at the end.  Only what the log has: the
;;;                rest of the world is the originals the cart carries.
;;;   two check bytes: s1 = the sum of every byte before them, s2 = the sum
;;;   of the running s1s (each mod 256)
;;;
;;; Import reads and checks the whole file before it changes anything that
;;; counts: Ultima I-V stage every slot (as the disk import does) and write
;;; the cart after the check bytes; Ultima VI writes into the log's other
;;; half as it reads, and makes that half the one in use -- its header --
;;; only after them, so a bad file leaves the log as it was.

F_VERSION = 1

;;; In the page's second piece, at the end of the launcher's PRG: the page
;;; comes here only once x_there (page.s) has found it loaded.
f_export_ask:
        jsr p_area
        jsr pr
        !pet 13," Export to the game's own (D)isks,",13
        !pet " or to a (F)ile on any disk?",13
        !pet " RUN/STOP cancels. ",0
        jsr df_key
        bcc +
        jmp redraw
+       beq +
        jmp f_export
+       ldx gid
        cpx #G_U6
        bne +
        jmp x6_export
+       jmp x_export

f_import_ask:
        jsr p_area
        jsr pr
        !pet 13," Import from the game's own (D)isks,",13
        !pet " or from a (F)ile on any disk?",13
        !pet " RUN/STOP cancels. ",0
        jsr df_key
        bcc +
        jmp redraw
+       beq +
        jmp f_import
+       ldx gid
        cpx #G_U6
        bne +
        jmp x6_import
+       jmp x_import

;;; D: Z set, F: Z clear; C set for RUN/STOP and <-; other keys are not
;;; taken (E or I bouncing must not cancel)
df_key: jsr getkey
        cmp #"D"
        beq +
        cmp #$03                ; RUN/STOP
        beq ++
        cmp #$5f                ; <-
        beq ++
        cmp #"F"
        bne df_key
        lda #$01
+       clc
        rts
++      sec
        rts

;;; ==================================================================
;;; export
;;; ==================================================================
f_export:
        jsr pr
        !pet 13," Export: this overwrites the file",13," ",0
        jsr prfname
        jsr pr
        !pet " on the disk. (Y/N) ",0
        jsr yn_key
        cmp #"Y"
        beq +
        jmp redraw
+       jsr f_disk
        bcc +
        jmp x_cancel
+       tsx
        stx f_sp
        jsr f_name
        jsr c_start             ; scratch it, then open it to write
        lda #<scratch
        ldy #>scratch
        jsr c_str
        lda xs_name
        ldy xs_name+1
        jsr c_str
        jsr d_cmd               ; (1: scratched; 62: there was none)
        cmp #$ff
        bne +
        jmp x_fail
+       lda #<sw
        ldy #>sw
        jsr f_open
        beq +
        jmp x_fail
+       jsr pr
        !pet 13," Writing",0
        lda #$00
        sta f_s1
        sta f_s2
        jsr f_chkout
        ldx #$00
-       stx f_i
        lda f_magic,x
        jsr fput
        ldx f_i
        inx
        cpx #$04
        bne -
        ldx gid                 ; the game's number, 1-6
        lda f_number,x
        jsr fput
        lda #F_VERSION
        jsr fput
        jsr CLRCHN
        lda gid
        cmp #G_U6
        bne +
        jsr f6_out
        jmp ++
+       jsr f_out
++      jsr f_chkout            ; the check bytes, not summed
        lda f_s1
        jsr CHROUT
        lda f_s2
        jsr CHROUT
        jsr CLRCHN
        lda #3
        jsr CLOSE
        jsr d_status
        beq +
        jmp x_fail
+       jmp x_done

;;; Ultima I-V: the slots
f_out:  jsr f_count
        pha
        jsr f_chkout
        pla
        jsr fput
        jsr CLRCHN
        jsr xt_start
fo_disk:
        dec xt_disks
        bmi fo_out
        jsr parse_disk
fo_slot:
        dec xd_slots
        bmi fo_disk
        jsr parse_slot
        jsr slot_data           ; tc_addr: its data; xs_len; C set: empty
        bcc +
        lda #$00
        sta f_lo
        sta f_hi
        jsr f_chkout
        lda #$00
        jsr fput
        jmp fo_len
+       lda #$00                ; raw: its pages, as the disk export writes
        sta f_lo
        lda xs_n
        sta f_hi
        lda xs_kind
        cmp #X_FILE
        bne +
        lda xs_len
        sta f_lo
        lda xs_len+1
        sta f_hi
+       ldx f_hi                ; into BUF
        lda f_lo
        beq +
        inx
+       lda #>BUF
        jsr fread_to
        jsr f_chkout
        lda #$01
        jsr fput
fo_len: lda f_lo
        jsr fput
        lda f_hi
        jsr fput
        lda #>BUF
        jsr f_putbuf
        jsr CLRCHN
        jsr dot
        jmp fo_slot
fo_out: rts

;;; the number of slots in the game's table
f_count:
        lda #$00
        sta f_n
        jsr xt_start
-       dec xt_disks
        bmi ++
        jsr parse_disk
--      dec xd_slots
        bmi -
        jsr parse_slot
        inc f_n
        jmp --
++      lda f_n
        rts

;;; Ultima VI: what the write log has of the chunk files and the save area
f6_out: jsr x6_log
        lda x6_uselog
        bne +
        jmp f6o_end             ; no log: nothing but the originals
+
        lda #$00
        sta x6_disk
f6o_disk:
        jsr x6_setdisk
f6o_file:
        lda x6_left
        beq f6o_next
        jsr x6_name
        jsr x6_logdir
        jsr dlookup
        bcs f6o_skip
        lda reply+5
        and #F6_LINKS
        beq f6o_skip
        lda reply+3             ; pages
        beq f6o_skip
        cmp #MAXSEC+1
        bcs f6o_skip
        sta x6_n
        jsr f_reply_addr
        jsr f_chkout
        lda #$01
        jsr fput
        ldx #$01
-       stx f_i
        lda lkey,x
        jsr fput
        ldx f_i
        inx
        cpx #$04
        bne -
        lda x6_n
        jsr fput
        jsr CLRCHN
-       lda #>DBUF              ; its pages, as they are
        ldx #$01
        jsr fread_to
        jsr next_page
        jsr f_chkout
        jsr f_putpage
        jsr CLRCHN
        dec x6_n
        bne -
        jsr dot
f6o_skip:
        dec x6_left
        jmp f6o_file
f6o_next:
        inc x6_disk
        lda x6_disk
        cmp #$02
        bne f6o_disk
        lda #9                  ; the save area's sectors the log has
        sta x6_sec
f6o_sec:
        jsr x6_seckey
        jsr x6_logdir
        jsr dlookup
        bcs +
        jsr f_reply_addr
        lda #>DBUF
        ldx #$01
        jsr fread_to
        jsr f_chkout
        lda #$02
        jsr fput
        lda x6_sec
        jsr fput
        jsr f_putpage
        jsr CLRCHN
        jsr dot
+       inc x6_sec
        lda x6_sec
        cmp #21
        bne f6o_sec
f6o_end:
        jsr f_chkout
        lda #$00
        jsr fput
        jmp CLRCHN

f_reply_addr:
        ldx #$02
-       lda reply,x
        sta tc_addr,x
        dex
        bpl -
        rts

;;; ==================================================================
;;; import
;;; ==================================================================
f_import:
        lda gid
        cmp #G_U6
        bne +
        jsr pr
        !pet 13," Import: this replaces the world",13
        !pet " on the cartridge. (Y/N) ",0
        jmp ++
+       jsr pr
        !pet 13," Import: this replaces the saved game",13
        !pet " on the cartridge. (Y/N) ",0
++      jsr yn_key
        cmp #"Y"
        beq +
        jmp redraw
+       jsr f_disk
        bcc +
        jmp x_cancel
+       tsx
        stx f_sp
        jsr f_name
        lda #<sr
        ldy #>sr
        jsr f_open
        beq +
        jmp x_fail
+       jsr pr
        !pet 13," Reading",0
        lda #$00
        sta f_s1
        sta f_s2
        sta f_eof
        jsr f_chkin
        ldx #$00                ; "UCSV", the game, the version
-       stx f_i
        jsr fget
        ldx f_i
        cmp f_magic,x
        beq +
        jmp f_notours
+       inx
        cpx #$04
        bne -
        jsr fget                ; the game's number
        ldx gid
        cmp f_number,x
        beq +
        jmp f_other
+       jsr fget
        cmp #F_VERSION
        beq +
        jmp f_version
+       lda gid
        cmp #G_U6
        bne +
        jmp f6_in
+       jsr CLRCHN              ; (the tables are no drive business, but the
        jsr f_count             ; channel is set again before each read)
        sta f_n
        jsr f_chkin
        jsr fget
        cmp f_n
        beq +
        jmp f_version
+       lda #>BUF               ; ---- every slot into the staging area
        sta xs_stage
        lda #$00
        sta xs_idx
        jsr xt_start
fi_disk:
        dec xt_disks
        bmi fi_end
        jsr parse_disk
fi_slot:
        dec xd_slots
        bmi fi_disk
        jsr parse_slot
        jsr fi_read
        jmp fi_slot
fi_end: jsr f_check
        jmp xi_write            ; then the cart, as from the disks

;;; one slot from the file into the staging area, checked against the table
fi_read:
        jsr fget
        cmp #$02
        bcc +
        jmp f_damaged
+       sta f_ok
        jsr fget
        sta f_lo
        jsr fget
        sta f_hi
        ldx xs_idx
        lda xs_stage
        sta st_page,x
        lda f_ok
        sta st_ok,x
        lda f_lo
        sta st_lo,x
        lda f_hi
        sta st_hi,x
        lda f_ok
        bne fr_some
        lda f_lo                ; nothing in it: no length either
        ora f_hi
        beq fr_next
        jmp f_damaged
fr_some:
        lda xs_kind
        cmp #X_FILE
        beq fr_file
        lda f_lo                ; raw: exactly its pages
        bne fr_bad
        lda f_hi
        cmp xs_n
        bne fr_bad
        beq fr_room
fr_file:
        lda f_lo                ; lo <= length <= hi
        cmp xs_lo
        lda f_hi
        sbc xs_lo+1
        bcc fr_bad
        lda xs_hi
        cmp f_lo
        lda xs_hi+1
        sbc f_hi
        bcc fr_bad
fr_room:
        ldx f_hi                ; its pages, below the launcher's screen
        lda f_lo
        beq +
        inx
+       txa
        clc
        adc xs_stage
        cmp #$3c+1
        bcs fr_bad
        pha
        lda xs_stage
        jsr f_getbuf
        pla
        sta xs_stage
        jsr dot
fr_next:
        inc xs_idx
        rts
fr_bad: jmp f_damaged

;;; Ultima VI: into the log's other half, record by record
f6_in:  jsr CLRCHN
        jsr x6_begin            ; (" Clearing")
        jsr pr
        !pet 13," Reading",0
f6i_rec:
        jsr f_chkin
        jsr fget
        bne +
        jmp f6i_end
+       cmp #$01
        beq f6i_file
        cmp #$02
        beq f6i_sec
        jmp f_damaged
f6i_file:
        lda #"/"
        sta lkey
        ldx #$01
-       stx f_i
        jsr fget
        ldx f_i
        sta lkey,x
        inx
        cpx #$04
        bne -
        lda #$00
-       sta lkey,x
        inx
        cpx #KEYLEN
        bne -
        jsr fget
        sta x6_n
        sta f_hi
        cmp #$00
        beq f6_bad
        cmp #MAXSEC+1
        bcs f6_bad
        lda #$00
        sta f_lo
        lda #>BUF
        jsr f_getbuf
        jsr CLRCHN
        jsr x6_sdir             ; one of the game's chunk files?
        jsr dlookup
        bcs f6_bad
        jsr x6_logfile          ; (x6_n pages of BUF)
        jmp f6i_rec
f6i_sec:
        jsr fget
        sta x6_sec
        cmp #9
        bcc f6_bad
        cmp #21
        bcs f6_bad
        lda #$00
        sta f_lo
        lda #$01
        sta f_hi
        lda #>DBUF
        jsr f_getbuf
        jsr CLRCHN
        jsr x6_seckey
        lda #>DBUF
        ldx #$01
        jsr x6_logpages
        lda #$00
        sta x6_n
        jsr x6_entry
        jmp f6i_rec
f6_bad: jmp f_damaged
f6i_end:
        jsr f_check
        jsr d_close
        jsr pr
        !pet 13," Writing",0
        jsr x6_commit
        jmp x_done2

;;; the check bytes, and nothing after them
f_check:
        lda f_s1
        sta f_e1
        lda f_s2
        sta f_e2
        jsr fget
        cmp f_e1
        bne +
        jsr fget
        cmp f_e2
        bne +
        lda f_eof
        beq +
        jmp CLRCHN
+       jmp f_damaged

;;; ==================================================================
;;; the file
;;; ==================================================================
;;; xs_name = this game's file name
f_name: ldx gid
        lda f_names_lo,x
        sta xs_name
        lda f_names_hi,x
        sta xs_name+1
        rts

;;; "the name", in capitals on the page's mixed-case screen
prfname:
        jsr f_name
        lda #34
        jsr CHROUT
        lda xs_name
        sta pf_rd+1
        lda xs_name+1
        sta pf_rd+2
        ldy #$00
pf_rd:  lda $ffff,y
        beq +
        cmp #"A"                ; (ASCII capitals: the screen's lower case)
        bcc ++
        cmp #$5b                ; "Z" + 1
        bcs ++
        ora #$80
++      jsr CHROUT
        iny
        bne pf_rd
+       lda #34
        jmp CHROUT

;;; any disk in the drive, channels 15 and 2 open (ask_disk); C set: cancelled
f_disk: lda #$01
        sta ad_any
        jsr ask_disk
        lda #$00                ; (C kept)
        sta ad_any
        rts

f_chkout:
        ldx #3
        jsr CHKOUT
        bcs f_gone
        rts
f_chkin:
        ldx #3
        jsr CHKIN
        bcs f_gone
        rts
f_gone: jsr d_gone              ; no drive: the KERNAL kept the screen/keyboard
        ldx f_sp
        txs
        jmp x_fail

;;; A out on the file, summed
fput:   sta f_b
        jsr CHROUT
        lda f_b
        clc
        adc f_s1
        sta f_s1
        clc
        adc f_s2
        sta f_s2
        rts

;;; the next byte of the file, summed; a file cut short or a drive error
;;; ends the import
fget:   lda f_eof
        beq +
        jmp f_damaged
+
        jsr CHRIN
        sta f_b
        jsr READST
        sta f_st
        and #%10111111
        beq +
        jmp f_ioerr
+       lda f_st
        and #%01000000
        sta f_eof
        lda f_b
        clc
        adc f_s1
        sta f_s1
        clc
        adc f_s2
        sta f_s2
        lda f_b
        rts

;;; f_lo/f_hi bytes out from page A on
f_putbuf:
        sta fb_ld+2
        lda #$00
        sta fb_ld+1
        lda f_lo
        sta f_cl
        lda f_hi
        sta f_ch
-       lda f_cl
        ora f_ch
        beq ++
fb_ld:  lda $ffff
        jsr fput
        inc fb_ld+1
        bne +
        inc fb_ld+2
+       lda f_cl
        bne +
        dec f_ch
+       dec f_cl
        jmp -
++      rts

;;; DBUF's 256 bytes out
f_putpage:
        lda #$00
        sta f_lo
        lda #$01
        sta f_hi
        lda #>DBUF
        jmp f_putbuf

;;; f_lo/f_hi bytes in, to page A on
f_getbuf:
        sta gb_st+2
        lda #$00
        sta gb_st+1
        lda f_lo
        sta f_cl
        lda f_hi
        sta f_ch
-       lda f_cl
        ora f_ch
        beq ++
        jsr fget
gb_st:  sta $ffff
        inc gb_st+1
        bne +
        inc gb_st+2
+       lda f_cl
        bne +
        dec f_ch
+       dec f_cl
        jmp -
++      rts

;;; ---- what can be wrong with a file: nothing on the cart changed yet --
f_notours:
        jsr pr
        !pet 13," That is not a saved game file.",0
        jmp f_abort
f_other:
        jsr pr
        !pet 13," That file is another game's.",0
        jmp f_abort
f_version:
        jsr pr
        !pet 13," That file is from another version.",0
        jmp f_abort
f_damaged:
        jsr pr
        !pet 13," The file is damaged.",0
        jmp f_abort
f_ioerr:
        jsr CLRCHN
        jsr d_status
        ldx f_sp
        txs
        jmp x_fail
f_abort:
        ldx f_sp
        txs
        jsr d_close
        jmp x_key

f_magic: !text "UCSV"
sw:      !pet ",s,w",0
sr:      !pet ",s,r",0
f_number:   !byte 1, 3, 2, 4, 5, 6      ; by gid, the descriptor order
f_names_lo: !byte <fn_u1, <fn_u3, <fn_u2, <fn_u4, <fn_u5, <fn_u6
f_names_hi: !byte >fn_u1, >fn_u3, >fn_u2, >fn_u4, >fn_u5, >fn_u6
fn_u1:   !text "ULTIMA I SAVE",0
fn_u2:   !text "ULTIMA II SAVE",0
fn_u3:   !text "ULTIMA III SAVE",0
fn_u4:   !text "ULTIMA IV SAVE",0
fn_u5:   !text "ULTIMA V SAVE",0
fn_u6:   !text "ULTIMA VI SAVE",0

f_sp:    !byte 0
f_s1:    !byte 0
f_s2:    !byte 0
f_e1:    !byte 0
f_e2:    !byte 0
f_b:     !byte 0
f_st:    !byte 0
f_eof:   !byte 0
f_i:     !byte 0
f_n:     !byte 0
f_ok:    !byte 0
f_lo:    !byte 0
f_hi:    !byte 0
f_cl:    !byte 0
f_ch:    !byte 0
