;;; page_xfer.s -- export and import of a saved game, to and from real disks
;;; in drive 8 -- or 9, 10, 11: D at a disk prompt picks the next, and the
;;; settings page keeps it -- for the launcher's page (included by page.s).
;;;
;;; What a game's saved game is on disk comes from its build (xfer.py): a
;;; table of disks in the order to use them, each recognised by its BAM's
;;; disk name (and ID, and one more byte, where the game checks those), and
;;; per disk the save slots -- raw sectors (block read "U1", block write
;;; "B-P" + "U2") or PRG files (read by name; written the way the games do,
;;; scratch then save).
;;;
;;; Export writes the disk in the order the table gives.  Import reads
;;; everything first, from every disk, and checks it; only then is the cart
;;; touched, so a failed or cancelled import changes nothing.
;;;
;;; Plain KERNAL serial I/O.  The KERNAL enables interrupts in places, which
;;; is safe with the cart held in command mode: its IRQ only starts the tape
;;; motor while $C0 is 0 and the cart holds sense low, and the cart is only
;;; ever busy after a command tclib ended with tc_leave, which sets $C0.

SETLFS = $ffba
SETNAM = $ffbd
OPEN   = $ffc0
CLOSE  = $ffc3
CHKIN  = $ffc6
CHKOUT = $ffc9
CLRCHN = $ffcc
CHRIN  = $ffcf
READST = $ffb7

SET_DRIVE = $10                 ; the settings page's byte for the drive:
                                ; 0 (and so an erased page) is drive 8
DBUF   = $0600                  ; one sector
X_RAW  = 1
X_FILE = 2
H_NONE = 0
H_BYTES = 1
H_BLOCKS = 2
SLOTS_MAX = 16

;;; ==================================================================
;;; export
;;; ==================================================================
x_export:
        lda gid                 ; Ultima IV saved in a dungeon (the Remastered's
        cmp #G_U4               ; Quit there, record $1A's game mode $1B = 3):
        bne +                   ; the original game cannot load that
        lda #<U4_ZP
        ldx #>U4_ZP
        ldy #^U4_ZP
        jsr fread1
        lda BUF+$1b-$10
        cmp #$03
        bne +
        jsr pr
        !pet 13," Saved in a dungeon: the original game",13
        !pet " would start it on the surface.",13,0
+       jsr pr
        !pet 13," Export: this overwrites the saved game",13
        !pet " on the disk. (Y/N) ",0
        jsr yn_key
        cmp #"Y"
        beq +
        jmp redraw
+       jsr xt_start
xe_disk:
        dec xt_disks
        bpl +
        jmp x_done
+       jsr parse_disk
        jsr ask_disk
        bcc +
        jmp x_cancel
+
xe_slot:
        dec xd_slots
        bmi xe_disk
        jsr parse_slot
        jsr ex_slot
        bcc xe_slot
        jmp x_fail

;;; one slot to disk; C set on a drive error
ex_slot:
        jsr slot_data           ; tc_addr: its data; xs_len; C set: empty
        bcc +
        lda #"-"                ; nothing saved in it: leave the disk's
        jsr CHROUT
        clc
        rts
+       lda xs_kind
        cmp #X_FILE
        beq ex_file
        lda #$00                ; raw: a sector at a time
        sta xs_i
-       lda xs_i
        cmp xs_n
        beq ex_ok
        lda #>DBUF
        ldx #$01
        jsr fread_to            ; (tc_read leaves tc_addr: next_page below)
        jsr sector_ts           ; A = t, X = s of sector xs_i
        ldy #>DBUF
        jsr d_bwrite
        bcs ex_out
        jsr dot
        jsr next_page
        inc xs_i
        bne -
ex_file:
        ldx xs_len+1            ; the whole file into BUF
        lda xs_len
        beq +
        inx
+       lda #>BUF
        jsr fread_to
        jsr d_fwrite
        bcs ex_out
        jsr dot
ex_ok:  clc
ex_out: rts

;;; tc_addr += a page (after tc_read, which leaves it)
next_page:
        inc tc_addr+1
        bne +
        inc tc_addr+2
+       rts

;;; ==================================================================
;;; import
;;; ==================================================================
x_import:
        jsr pr
        !pet 13," Import: this replaces the saved game",13
        !pet " on the cartridge. (Y/N) ",0
        jsr yn_key
        cmp #"Y"
        beq +
        jmp redraw
+       lda #>BUF               ; ---- read and check everything first
        sta xs_stage
        lda #$00
        sta xs_idx
        jsr xt_start
xi_disk:
        dec xt_disks
        bmi xi_write
        jsr parse_disk
        jsr ask_disk
        bcc xi_slot
        jmp x_cancel
xi_slot:
        dec xd_slots
        bmi xi_disk
        jsr parse_slot
        jsr im_read
        bcc xi_slot
        jmp x_fail
xi_write:
        lda #$ff                ; no Ultima II log half started (page_u2l.s)
        sta lg_j
        jsr d_close             ; ---- then the cart
        jsr pr
        !pet 13," Writing",0
        lda #$00
        sta xs_idx
        jsr xt_start
xw_disk:
        dec xt_disks
        bmi xw_done
        jsr parse_disk
xw_slot:
        dec xd_slots
        bmi xw_disk
        jsr parse_slot
        jsr im_write
        jmp xw_slot
xw_done:
        jsr lg_done
        jmp x_done2

;;; one slot from disk into the staging area; C set on an error (message
;;; printed)
im_read:
        lda xs_stage            ; the staging area ends below the launcher's
        cmp #$3c                ; screen at $4400
        bcc +
        jmp im_len
+       ldx xs_idx
        lda xs_stage
        sta st_page,x
        lda #$01
        sta st_ok,x
        lda xs_kind
        cmp #X_FILE
        beq im_file
        lda #$00                ; raw: every sector
        sta xs_i
ir_next:
        lda xs_i
        cmp xs_n
        beq ir_done
        jsr sector_ts
        ldy xs_stage
        jsr d_bread
        bcc ir_ok
        rts
ir_ok:  jsr dot
        inc xs_stage
        inc xs_i
        bne ir_next
ir_done:
        ldx xs_idx
        lda #$00
        sta st_lo,x
        lda xs_n
        sta st_hi,x
        jmp im_next
im_file:
        ldy xs_stage
        jsr d_fread             ; A/X = its length (lo, hi); C set: error
        bcc +
        cmp #62                 ; not there: fine if it may be missing
        bne im_err
        lda xs_opt
        beq im_err
        ldx xs_idx
        lda #$00
        sta st_ok,x
        sta st_lo,x
        sta st_hi,x
        jmp im_next
+       ldy xs_idx
        sta st_lo,y
        txa
        sta st_hi,y
        lda st_lo,y             ; lo <= length ...
        cmp xs_lo
        lda st_hi,y
        sbc xs_lo+1
        bcc im_len
        lda xs_hi               ; ... <= hi
        cmp st_lo,y
        lda xs_hi+1
        sbc st_hi,y
        bcc im_len
        lda st_lo,y             ; the stage moves on by its pages
        beq +
        inc xs_stage
+       lda st_hi,y
        clc
        adc xs_stage
        sta xs_stage
        jsr dot
im_next:
        inc xs_idx
        clc
        rts
im_len: jsr pr
        !pet 13," A file has the wrong length.",0
        sec
        rts
im_err: sta d_code
        sec
im_out: rts

;;; one staged slot onto the cart: erase it, the data, the header last
im_write:
        ldx xs_idx
        inc xs_idx
        lda st_lo,x
        sta xs_len
        lda st_hi,x
        sta xs_len+1
        lda st_page,x
        sta xs_stage
        lda st_ok,x
        sta xs_i
        lda xs_hdr
        bpl +
        jmp lg_write            ; Ultima II: into its log
+       lda xs_base             ; erase: the slot's blocks
        sta tc_addr
        lda xs_base+1
        sta tc_addr+1
        lda xs_base+2
        sta tc_addr+2
        jsr slot_blocks         ; A = how many
        sta count
-       jsr tc_erase_block
        lda tc_addr+1
        clc
        adc #$10
        sta tc_addr+1
        bcc +
        inc tc_addr+2
+       dec count
        bne -
        lda xs_i
        bne iw_data
        rts                     ; missing on the disk: stays erased
iw_data:
        lda xs_base             ; the data
        sta tc_addr
        lda xs_base+1
        sta tc_addr+1
        lda xs_base+2
        sta tc_addr+2
        lda xs_hdr
        beq +
        jsr next_page           ; a page behind its header
+       lda #$00
        sta tc_dest
        lda xs_stage
        sta tc_dest+1
        lda xs_len+1            ; the whole pages ...
        sta count
        beq +
-       jsr write_page
        dec count
        bne -
+       lda xs_len              ; ... and the rest, just its bytes, as the
        beq iw_hdr              ; drivers' own saves leave the page
        sta tc_len
        lda #$00
        sta tc_len+1
        jsr tc_write
iw_hdr: lda xs_hdr
        beq iw_out
        lda xs_base             ; the header, last
        sta tc_addr
        lda xs_base+1
        sta tc_addr+1
        lda xs_base+2
        sta tc_addr+2
        lda #$a5
        sta hdrbuf
        lda #$5a
        sta hdrbuf+1
        lda xs_len
        ldx xs_len+1
        ldy xs_hdr
        cpy #H_BLOCKS
        bne +
        txa                     ; A5 5A count 00
        ldx #$00
+       sta hdrbuf+2
        stx hdrbuf+3
        lda #<hdrbuf
        sta tc_dest
        lda #>hdrbuf
        sta tc_dest+1
        lda #$04
        sta tc_len
        lda #$00
        sta tc_len+1
        jsr tc_write
        jsr dot
iw_out: rts

;;; an Ultima II slot: the first starts the log's new half (page_u2l.s)
lg_write:
        lda lg_j
        bpl +
        jsr lg_start
+       lda xs_i
        beq +                   ; missing on the disk: its seed then
        lda xs_hdr
        and #$7f
        jsr lg_put
        jsr dot
+       rts

;;; the slot's erase blocks: its data, and the header page if it has one
slot_blocks:
        lda xs_len+1            ; pages of data
        ldx xs_len
        beq +
        clc
        adc #$01
+       ldx xs_hdr
        beq +
        clc
        adc #$01
+       clc
        adc #$0f
        lsr
        lsr
        lsr
        lsr
        bne +
        lda #$01
+       rts

;;; ==================================================================
;;; Ultima V's C128 launcher (ultima/games/u5/launch128.s) to a disk, as a PRG
;;; that DLOAD and RUN start on a C128 in its own mode.  Written like a
;;; saved-game file: scratched, then saved with its load address.
;;; ==================================================================
x_c128:
        jsr p_area
        jsr pr
        !pet 13," Insert a disk with "
        !byte $30 + C128_BLOCKS        ; (PETSCII digits are ASCII's)
        !pet " blocks free",0
        jsr drive_key
        bcc +
        jmp x_cancel
+       bne x_c128              ; another drive: say so
        lda #<C128_DATA
        sta tc_addr
        lda #>C128_DATA
        sta tc_addr+1
        lda #^C128_DATA
        sta tc_addr+2
        lda #>BUF
        ldx #>(C128_LEN + $ff)
        jsr fread_to
        lda #<c128_name
        sta xs_name
        lda #>c128_name
        sta xs_name+1
        lda #<C128_LOAD
        sta xs_load
        lda #>C128_LOAD
        sta xs_load+1
        lda #<C128_LEN
        sta xs_len
        lda #>C128_LEN
        sta xs_len+1
        jsr d_open
        bcc +
        jmp x_fail
+       jsr pr
        !pet 13," Writing",0
        jsr d_fwrite
        bcc +
        jmp x_fail
+       jsr d_close
        jsr pr
        !pet $93,13," The C128 launcher is on the disk.",13,13
        !pet " On a C128, in its own mode, with the",13
        !pet " cart in the tape port and this disk",13
        !pet " in drive ",0
        jsr prdrive
        jsr pr
        !pet ", after a reset:",13,13
        !pet "   DLOAD",34,"ULTIMA V 128",34,0
        jsr dev_get
        cmp #8
        beq +
        jsr pr
        !pet ",U",0
        jsr prdrive
+       jsr pr
        !pet 13,"   RUN",13,13
        !pet " The saved game is the same one the",13
        !pet " C64 plays.",13,0
        jmp x_key

c128_name: !text "ULTIMA V 128",0

;;; ==================================================================
;;; the end of it
;;; ==================================================================
x_cancel:
        jsr d_close
        sei
        jmp redraw
x_fail: jsr d_close
        jsr pr
        !pet 13," Failed. ",0
        lda d_code
        cmp #$ff
        bne +
        jsr pr_gone
        jmp ++
+       jsr prstatus
++      jmp x_key
x_done: jsr d_close
x_done2:
        jsr pr
        !pet 13," Done.",0
x_key:  sei
        lda #$00                ; whatever was typed meanwhile
        sta $c6
        jsr pr
        !pet 13," Press a key.",0
        jsr getkey
        jmp redraw

;;; ==================================================================
;;; the tables
;;; ==================================================================
xt_start:
        ldx gid
        lda xf_lo,x
        sta xg+1
        lda xf_hi,x
        sta xg+2
        jsr xget
        sta xt_disks
        rts

xget:
xg:     lda $ffff
        inc xg+1
        bne +
        inc xg+2
+       cmp #$00                ; Z and N from the byte, not the pointer
        rts

;;; a disk: its label (for the prompts), name, another edition's name (or
;;; zeros), ID, the extra check, slots
parse_disk:
        lda xg+1
        sta xd_label
        lda xg+2
        sta xd_label+1
-       jsr xget                ; skip the label
        bne -
        ldx #$00
-       jsr xget
        sta xd_name,x
        inx
        cpx #16+16+1+2+4+1      ; name, other name, ID flag, ID, check (t s off val), slots
        bne -
        rts
xd_alt   = xd_name + 16
xd_idf   = xd_name + 32
xd_id    = xd_name + 33
xd_ck    = xd_name + 35
xd_slots = xd_name + 39

;;; a slot: kind, base (3), header kind; then raw: count, sectors -- or
;;; file: the name (NUL), load address, least and most length, optional
parse_slot:
        ldx #$00
-       jsr xget
        sta xs_kind,x
        inx
        cpx #$05
        bne -
        lda xs_kind
        cmp #X_FILE
        beq ps_file
        jsr xget
        sta xs_n
        lda xg+1                ; the sectors are read from the table
        sta xs_secs
        lda xg+2
        sta xs_secs+1
        ldx xs_n
-       jsr xget
        jsr xget
        dex
        bne -
        rts
ps_file:
        lda xg+1
        sta xs_name
        lda xg+2
        sta xs_name+1
-       jsr xget
        bne -
        ldx #$00
-       jsr xget
        sta xs_load,x
        inx
        cpx #$07
        bne -
        rts
xs_base = xs_kind + 1
xs_hdr  = xs_kind + 4
xs_lo   = xs_load + 2
xs_hi   = xs_load + 4
xs_opt  = xs_load + 6

;;; A = track, X = sector of the slot's sector xs_i
sector_ts:
        lda xs_i
        asl
        clc
        adc xs_secs
        sta st_rd+1
        lda xs_secs+1
        adc #$00
        sta st_rd+2
        ldy #$01
        jsr st_rd
        tax
        ldy #$00
st_rd:  lda $ffff,y
        rts

;;; tc_addr = the slot's data, xs_len its length; C set if the slot says
;;; there is nothing in it (a header without its magic)
slot_data:
        lda xs_base
        sta tc_addr
        lda xs_base+1
        sta tc_addr+1
        lda xs_base+2
        sta tc_addr+2
        lda xs_hdr
        bpl +
        and #$7f                ; Ultima II: the unit's newest version
        jsr lg_find
        jmp sd_raw
+       bne sd_hdr
sd_raw: lda #$00                ; no header: raw pages, or a file of the
        sta xs_len              ; most length
        lda xs_n
        ldx xs_kind
        cpx #X_FILE
        bne +
        lda xs_hi
        sta xs_len
        lda xs_hi+1
+       sta xs_len+1
        clc
        rts
sd_hdr: lda #<hdrbuf
        sta tc_dest
        lda #>hdrbuf
        sta tc_dest+1
        lda #$04
        sta tc_len
        lda #$00
        sta tc_len+1
        jsr tc_read
        lda hdrbuf
        cmp #$a5
        bne sd_none
        lda hdrbuf+1
        cmp #$5a
        bne sd_none
        lda hdrbuf+2
        ldx hdrbuf+3
        ldy xs_hdr
        cpy #H_BLOCKS
        bne +
        tax                     ; a block count
        lda #$00
+       sta xs_len
        stx xs_len+1
        lda xs_base             ; the data, a page on
        sta tc_addr
        jsr next_page_from_base
        clc
        rts
sd_none:
        sec
        rts
next_page_from_base:
        lda xs_base+1
        sta tc_addr+1
        lda xs_base+2
        sta tc_addr+2
        jmp next_page

;;; ==================================================================
;;; the disk
;;; ==================================================================

;;; ask for the disk, until it is the right one; C set: cancelled.  With
;;; ad_any set (page_file.s), any disk the drive can read will do.
;;; Every channel is closed while a disk is asked for -- a drive holding a
;;; channel open across a swap may keep the old disk's BAM and write it onto
;;; the new one -- and opened again after, with an "I0" so DOS reads the
;;; new disk's BAM whatever it thinks.
ask_disk:
        jsr d_close
        lda ad_any
        beq +
        jsr pr
        !pet 13,13," Insert the disk for the file",0
        jmp ++
+       jsr pr
        !pet 13,13," Insert the ",0
        jsr prlabel
        jsr pr
        !pet " disk",0
++      jsr drive_key
        bcs ad_cancel
        bne ask_disk            ; another drive: say so
        jsr d_open
        bcc +
        lda d_code
        cmp #$ff
        bne ad_status
        jsr pr
        !pet 13," ",0
        jsr pr_gone
        jmp ask_disk
+       lda ad_any
        bne ad_ok
        jsr check_disk
        bcc ad_ok
        lda d_code
        beq +
ad_status:
        jsr pr
        !pet 13," ",0
        jsr prstatus
        jmp ask_disk
+       jsr pr
        !pet 13," That is not the ",0
        jsr prlabel
        jsr pr
        !pet " disk.",0
        jmp ask_disk
ad_ok:  jsr pr
        !pet 13," ",0
        clc
        rts
ad_cancel:
        sec
        rts

;;; the rest of a disk prompt, and its key: RETURN (C clear, Z set), D --
;;; the next drive, 8 to 11, kept in the settings (C clear, Z clear: prompt
;;; again) -- or RUN/STOP or <- (C set)
drive_key:
        jsr pr
        !pet 13," in drive ",0
        jsr prdrive
        jsr pr
        !pet " and press RETURN,",13
        !pet " D for another drive,",13
        !pet " or RUN/STOP to cancel.",0
-       jsr getkey
        cmp #$03                ; RUN/STOP
        beq ++
        cmp #$5f                ; <-
        beq ++
        cmp #"D"
        beq +
        cmp #13
        bne -
        lda #$00
        clc
        rts
+       jsr dev_get             ; 8, 9, 10, 11, 8 ...
        clc
        adc #$01
        cmp #12
        bcc +
        lda #8
+       cmp #8
        bne +
        lda #$00                ; (8 is the default, stored as 0)
+       sta setbuf+SET_DRIVE
        jsr save_settings
        lda #$01
        clc
        rts
++      sec
        rts

;;; A = the drive (and X)
dev_get:
        lda setbuf+SET_DRIVE
        cmp #9
        bcc +
        cmp #12
        bcc ++
+       lda #8
++      tax
        rts

prdrive:
        jsr dev_get
        cmp #10
        bcc +
        pha
        lda #"1"
        jsr CHROUT
        pla
        sec                     ; (CHROUT returns C clear)
        sbc #10
+       ora #"0"
        jmp CHROUT

pr_gone:
        jsr pr
        !pet "Drive ",0
        jsr prdrive
        jsr pr
        !pet " is not there.",0
        rts

prlabel:
        lda xd_label
        sta ptr
        lda xd_label+1
        sta ptr+1
        ldy #$00
-       lda (ptr),y
        beq +
        jsr CHROUT
        iny
        bne -
+       rts

;;; the BAM's disk name -- or the other edition's -- (and ID) and the
;;; extra byte; C set if wrong
;;; (d_code non-zero: a drive error, not the wrong disk)
check_disk:
        lda #$00
        sta d_code
        lda #18
        ldx #0
        ldy #>DBUF
        jsr d_bread
        bcs cd_bad
        ldx #15
-       lda DBUF+$90,x
        cmp xd_name,x
        bne cd_alt
        dex
        bpl -
        bmi cd_named
cd_alt: lda xd_alt              ; none: zeros
        beq cd_bad
        ldx #15
-       lda DBUF+$90,x
        cmp xd_alt,x
        bne cd_bad
        dex
        bpl -
cd_named:
        lda xd_idf
        beq +
        lda DBUF+$a2
        cmp xd_id
        bne cd_bad
        lda DBUF+$a3
        cmp xd_id+1
        bne cd_bad
+       lda xd_ck               ; one more byte to check?
        beq cd_ok
        ldx xd_ck+1
        ldy #>DBUF
        jsr d_bread
        bcs cd_bad
        ldx xd_ck+2
        lda DBUF,x
        cmp xd_ck+3
        bne cd_bad
cd_ok:  clc
        rts
cd_bad: sec
        rts

;;; ---- the channels ---------------------------------------------------
;;; 15, the command channel -- and "I0" on it, before anything else is open
;;; (a 1541 answers 70, NO CHANNEL to it once a buffer is taken), so DOS
;;; reads the new disk's BAM -- then 2, a buffer for the block commands.
;;; C set if the drive does not answer (d_code $FF) or says no (d_code).
d_open: lda #$00
        sta d_code
        jsr dev_get
        lda #15
        ldy #15
        jsr SETLFS
        lda #$00
        jsr SETNAM
        jsr OPEN
        bcs do_none
        jsr c_start
        lda #<init_cmd
        ldy #>init_cmd
        jsr c_str
        jsr d_cmd
        cmp #$ff
        beq do_none
        cmp #$00
        bne do_no
        jsr dev_get
        lda #2
        ldy #2
        jsr SETLFS
        lda #$01
        ldx #<hash
        ldy #>hash
        jsr SETNAM
        jsr OPEN
        bcs do_none
        jsr d_status
        cmp #$ff
        beq do_none
        clc
        rts
do_none:
        lda #$ff
        sta d_code
do_no:  jsr d_close
        sec
        rts

d_close:
        jsr CLRCHN
        lda #3
        jsr CLOSE
        lda #2
        jsr CLOSE
        lda #15
        jsr CLOSE
        jmp CLRCHN

;;; read the error channel into stbuf; A = its number (0-99), $FF if the
;;; drive is not there.  73 (the power-on message) counts as 0.
d_status:
        ldx #15
        jsr CHKIN
        bcc +
        jmp d_gone              ; no drive: the KERNAL kept the screen/keyboard
+
        ldy #$00
-       jsr CHRIN
        cmp #13
        beq +
        sta stbuf,y
        iny
        cpy #38
        bne -
+       lda #$00
        sta stbuf,y
        jsr CLRCHN
        jsr READST
        and #$80
        bne ds_none
        lda stbuf
        and #$0f
        asl
        sta d_code
        asl
        asl
        clc
        adc d_code
        sta d_code
        lda stbuf+1
        and #$0f
        clc
        adc d_code
        cmp #73
        bne +
        lda #$00
+       sta d_code
        lda d_code              ; Z: success
        rts
ds_none:
        lda #$ff
        sta d_code
        rts

;;; CHKIN/CHKOUT failed (C set, A = 5: DEVICE NOT PRESENT): the channel is
;;; still the keyboard/screen, so nothing may be read or printed through it.
;;; C set, A = d_code = $FF (Z clear): what every caller takes as "not there"
d_gone: jsr CLRCHN
        lda #$ff
        sta d_code
        sec
        rts

prstatus:
        ldy #$00
-       lda stbuf,y
        beq +
        jsr CHROUT
        iny
        cpy #38
        bne -
+       rts

;;; send cmdbuf (cmd_n bytes) on channel 15; A = the drive's answer
d_cmd:  ldx #15
        jsr CHKOUT
        bcc +
        jmp d_gone              ; no drive: the KERNAL kept the screen/keyboard
+
        ldy #$00
-       cpy cmd_n
        beq +
        lda cmdbuf,y
        jsr CHROUT
        iny
        bne -
+       jsr CLRCHN
        jmp d_status

;;; ---- building a command ---------------------------------------------
c_start:
        lda #$00
        sta cmd_n
        rts
c_put:  ldx cmd_n
        sta cmdbuf,x
        inc cmd_n
        rts
;;; A in decimal, no leading zeros
c_dec:  ldx #$00
-       cmp #100
        bcc +
        sbc #100
        inx
        bne -
+       sta c_rest
        stx c_hund
        txa
        beq +
        ora #"0"
        jsr c_put
+       lda c_rest
        ldx #$00
-       cmp #10
        bcc +
        sbc #10
        inx
        bne -
+       sta c_rest
        txa
        bne +                   ; a tens digit
        ldy c_hund              ; zero: only after a hundred
        beq ++
+       ora #"0"
        jsr c_put
++      lda c_rest
        ora #"0"
        jmp c_put
;;; the NUL-terminated string at A/Y (lo, hi)
c_str:  sta cs_rd+1
        sty cs_rd+2
        ldy #$00
cs_rd:  lda $ffff,y
        beq +
        sty c_rest
        jsr c_put
        ldy c_rest
        iny
        bne cs_rd
+       rts
;;; "Un:2 0 t s", n in A
c_user: pha
        jsr c_start
        lda #"U"
        jsr c_put
        pla
        jsr c_put
        lda #<u_mid
        ldy #>u_mid
        jsr c_str
        lda bt
        jsr c_dec
        lda #" "
        jsr c_put
        lda bs
        jmp c_dec

;;; ---- sectors ----------------------------------------------------------
;;; read track A, sector X into page Y; C set on an error (d_code)
d_bread:
        sta bt
        stx bs
        sty db_st+2
        lda #"1"
        jsr c_user
        jsr d_cmd
        bne db_err
        ldx #2
        jsr CHKIN
        bcc +
        jmp d_gone              ; no drive: the KERNAL kept the screen/keyboard
+
        ldy #$00
-       jsr CHRIN
db_st:  sta $ff00,y
        iny
        bne -
        jsr CLRCHN
        clc
        rts
db_err: sec
        rts

;;; write page Y to track A, sector X
d_bwrite:
        sta bt
        stx bs
        sty dw_ld+2
        jsr c_start
        lda #<bp_cmd
        ldy #>bp_cmd
        jsr c_str
        jsr d_cmd
        bne db_err
        ldx #2
        jsr CHKOUT
        bcc +
        jmp d_gone              ; no drive: the KERNAL kept the screen/keyboard
+
        ldy #$00
dw_ld:  lda $ff00,y
        jsr CHROUT
        iny
        bne dw_ld
        jsr CLRCHN
        lda #"2"
        jsr c_user
        jsr d_cmd
        bne db_err
        clc
        rts

;;; ---- files --------------------------------------------------------------
;;; the file name (from the table) and a suffix into cmdbuf, then open 3
;;; (closed first: an open that failed -- file not found -- leaves it open
;;; in the KERNAL's table, and OPEN of an open file does nothing at all)
f_open: pha                     ; A/Y: the suffix
        tya
        pha
        lda #3
        jsr CLOSE
        jsr c_start
        lda xs_name
        ldy xs_name+1
        jsr c_str
        pla
        tay
        pla
        jsr c_str
        jsr dev_get
        lda #3
        ldy #3
        jsr SETLFS
        lda cmd_n
        ldx #<cmdbuf
        ldy #>cmdbuf
        jsr SETNAM
        jsr OPEN
        jmp d_status

;;; scratch the file, then save xs_len bytes of BUF under the table's load
;;; address, as the games do.  C set on an error.
d_fwrite:
        jsr c_start
        lda #<scratch
        ldy #>scratch
        jsr c_str
        lda xs_name
        ldy xs_name+1
        jsr c_str
        jsr d_cmd               ; (1: scratched; 62: there was none)
        cmp #$ff
        beq fw_err
        lda #<pw
        ldy #>pw
        jsr f_open
        bne fw_err
        ldx #3
        jsr CHKOUT
        bcc +
        jmp d_gone              ; no drive: the KERNAL kept the screen/keyboard
+
        lda xs_load
        jsr CHROUT
        lda xs_load+1
        jsr CHROUT
        lda #<BUF
        sta fw_ld+1
        lda #>BUF
        sta fw_ld+2
        lda xs_len
        sta xs_i                ; (a counter: low byte, then pages)
        lda xs_len+1
        sta xs_n
-       lda xs_i
        ora xs_n
        beq +
fw_ld:  lda $ffff
        jsr CHROUT
        inc fw_ld+1
        bne ++
        inc fw_ld+2
++      lda xs_i
        bne ++
        dec xs_n
++      dec xs_i
        jmp -
+       jsr CLRCHN
        lda #3
        jsr CLOSE
        jsr d_status
        bne fw_err
        clc
        rts
fw_err: sec
        rts

;;; read the file into page Y on, header dropped; A/X its length; C set on
;;; an error, A = the drive's number (62: not there)
d_fread:
        sty fr_st+2
        lda #$00
        sta fr_st+1
        sta xs_len
        sta xs_len+1
        lda #<prd
        ldy #>prd
        jsr f_open
        bne fr_err
        ldx #3
        jsr CHKIN
        bcc +
        jmp d_gone              ; no drive: the KERNAL kept the screen/keyboard
+
        jsr CHRIN               ; the load address
        jsr READST
        and #$40
        bne fr_end
        jsr CHRIN
        jsr READST
        and #$40
        bne fr_end
-       jsr CHRIN
fr_st:  sta $ffff
        inc fr_st+1
        bne +
        inc fr_st+2
+       inc xs_len
        bne +
        inc xs_len+1
+       lda xs_len+1            ; no more than the staging area holds
        cmp #$30
        bcs fr_end
        jsr READST
        and #$40
        beq -
fr_end: jsr CLRCHN
        lda #3
        jsr CLOSE
        jsr d_status
        bne fr_err
        lda xs_len
        ldx xs_len+1
        clc
        rts
fr_err: sec
        rts

hash:    !pet "#"
u_mid:   !pet ":2 0 ",0
bp_cmd:  !pet "b-p:2 0",0
scratch: !pet "s0:",0
pw:      !pet ",p,w",0
prd:     !pet ",p,r",0
init_cmd: !pet "i0",0

xt_disks: !byte 0
ad_any:   !byte 0
xd_label: !word 0
xd_name:  !fill 16+16+1+2+4+1, 0
xs_kind:  !fill 5, 0            ; kind, base (3), header kind
xs_n:     !byte 0
xs_secs:  !word 0
xs_name:  !word 0
xs_load:  !fill 7, 0            ; load, least, most (2 each), optional
xs_len:   !word 0
xs_i:     !byte 0
xs_idx:   !byte 0
xs_stage: !byte 0
st_page:  !fill SLOTS_MAX, 0
st_lo:    !fill SLOTS_MAX, 0
st_hi:    !fill SLOTS_MAX, 0
st_ok:    !fill SLOTS_MAX, 0
hdrbuf:   !fill 4, 0
bt:       !byte 0
bs:       !byte 0
d_code:   !byte 0
c_rest:   !byte 0
c_hund:   !byte 0
cmd_n:    !byte 0
cmdbuf:   !fill 40, 0
stbuf:    !fill 40, 0
