;;; page_u6x.s -- Ultima VI's world to and from its disks 1A and 1B, for the
;;; launcher's page (included by page.s after page_xfer.s, whose drive and
;;; table routines it uses).
;;;
;;; A saved game of Ultima VI is the whole world: 84 chunk files, rewritten
;;; wherever the BAM has room every time the game saves, and the save area,
;;; 1A T6 S9-20.  So:
;;;
;;; EXPORT writes every chunk file -- the write log's newest, else the
;;; original -- through a fresh chain taken from a pool the build worked out
;;; (the files' own sectors, then what the BAM has free), then the save area,
;;; then a BAM that says exactly that.  Whatever copy of the disks it is
;;; given, played or not, ends up consistent.
;;;
;;; IMPORT follows every chunk file's chain on the disks, and logs only the
;;; ones that differ from the original, and the save area's sectors that do.
;;; It writes into the log's other half and makes it the active one last --
;;; the header, as the compaction does -- so an import that fails half way
;;; leaves the log as it was.  Then the old half is erased.

BAMBUF  = $0500                 ; the export's BAM
ORIG    = $1c00                 ; an original chunk file, to compare with
MAXSEC  = 20                    ; a chunk file's most sectors (the originals'
                                ; most are 9 and 5); BUF's 20 pages and ORIG's
                                ; 20 x 254 bytes stay below the launcher's
                                ; screen at $4400 (menu.s)
F6_ZX   = %00000001
F6_LINKS = %00000010

;;; ==================================================================
;;; export
;;; ==================================================================
x6_export:
        jsr pr
        !pet 13," Export: this overwrites the world",13
        !pet " on the disks. (Y/N) ",0
        jsr yn_key
        cmp #"Y"
        beq +
        jmp redraw
+       jsr x6_log
        jsr xt_start
        lda #$00
        sta x6_disk
x6e_disk:
        lda x6_disk
        cmp #$02
        bne +
        jmp x_done
+       jsr parse_disk
        jsr ask_disk
        bcc +
        jmp x_cancel
+       jsr x6_setdisk
x6e_file:
        lda x6_left
        beq x6e_save
        jsr x6_name
        lda #>BUF
        sta x6_dpage
        jsr x6_content          ; the newest, into BUF
        bcc +
        jmp x6_missing
+       jsr x6_chain            ; onto the disk
        bcc +
        jmp x_fail
+       dec x6_left
        jmp x6e_file
x6e_save:
        lda x6_disk             ; the save area: 1A only
        bne x6e_bam
        lda #9
        sta x6_sec
-       jsr x6_newest_sector    ; into DBUF
        lda #6
        ldx x6_sec
        ldy #>DBUF
        jsr d_bwrite
        bcc +
        jmp x_fail
+       jsr dot
        inc x6_sec
        lda x6_sec
        cmp #21
        bne -
x6e_bam:
        lda #18                 ; and the BAM that says so, last
        ldx #0
        ldy #>BAMBUF
        jsr d_bwrite
        bcc +
        jmp x_fail
+       inc x6_disk
        jmp x6e_disk

x6_missing:
        jsr d_close
        jsr pr
        !pet 13," Failed: a chunk file is not on the cart.",0
        jmp x_key

;;; disk x6_disk: its BAM into BAMBUF, its pool and files
x6_setdisk:
        ldx x6_disk
        lda u6x_bam_lo,x
        sta xsd_rd+1
        lda u6x_bam_hi,x
        sta xsd_rd+2
        ldy #$00
xsd_rd: lda $ffff,y
        sta BAMBUF,y
        iny
        bne xsd_rd
        lda u6x_pool_lo,x
        sta x6_pool
        lda u6x_pool_hi,x
        sta x6_pool+1
        lda u6x_npool,x
        sta x6_pleft
        lda u6x_files_lo,x
        sta x6_file
        lda u6x_files_hi,x
        sta x6_file+1
        lda u6x_nfiles,x
        sta x6_left
        rts

;;; the next file: lkey = "/NAME", x6_t/x6_s its first sector
x6_name:
        lda x6_file
        sta xn_rd+1
        lda x6_file+1
        sta xn_rd+2
        lda #"/"
        sta lkey
        ldy #$00
-       jsr xn_rd
        sta lkey+1,y
        iny
        cpy #$03
        bne -
        jsr xn_rd
        sta x6_t
        iny
        jsr xn_rd
        sta x6_s
        lda #$00
        ldx #KEYLEN-1
-       sta lkey,x
        dex
        cpx #$03
        bne -
        lda x6_file
        clc
        adc #$05
        sta x6_file
        bcc +
        inc x6_file+1
+       rts
xn_rd:  lda $ffff,y
        rts

;;; the file lkey names into page x6_dpage on: the log's newest if there is
;;; a log and it has one (x6_uselog), else the original.  x6_len its length;
;;; C set if neither has it.
x6_content:
        lda x6_uselog
        beq xc_static
        jsr x6_logdir
        jsr dlookup
        bcs xc_static
        lda reply+5
        and #F6_LINKS
        beq xc_static
        lda reply+3             ; pages, each a sector with its links
        beq xc_static
        cmp #MAXSEC+1
        bcs xc_static
        sta x6_n
        ldx #$02
-       lda reply,x
        sta tc_addr,x
        dex
        bpl -
        lda #$00
        sta x6_len
        sta x6_len+1
        sta xc_wr+1
        lda x6_dpage
        sta xc_wr+2
xc_page:
        lda #>DBUF
        ldx #$01
        jsr fread_to
        jsr next_page
        lda #254                ; a middle sector's 254 bytes, the last's
        ldx DBUF                ; link+1 - 1 (bytes 2..link+1)
        bne +
        ldx DBUF+1
        dex
        txa
+       sta x6_cnt
        ldy #$00
-       cpy x6_cnt
        beq +
        lda DBUF+2,y
xc_wr:  sta $ffff
        inc xc_wr+1
        bne ++
        inc xc_wr+2
++      iny
        bne -
+       lda x6_len
        clc
        adc x6_cnt
        sta x6_len
        bcc +
        inc x6_len+1
+       dec x6_n
        bne xc_page
        clc
        rts
xc_static:
        jsr x6_sdir
        jsr dlookup
        bcc +
        rts
+       ldx #$02
-       lda reply,x
        sta tc_addr,x
        dex
        bpl -
        lda reply+3
        sta tc_len
        sta x6_len
        lda reply+4
        sta tc_len+1
        sta x6_len+1
        lda #$00
        sta tc_dest
        lda x6_dpage
        sta tc_dest+1
        lda reply+5
        and #F6_ZX
        beq +
        jsr zxd_unpack          ; its length is where the decoder stopped
        lda zx_put+1
        sta x6_len
        lda zx_put+2
        sec
        sbc x6_dpage
        sta x6_len+1
        clc
        rts
+       jsr tc_read
        clc
        rts

;;; x6_len bytes of BUF onto the disk as a chain from x6_t/x6_s, the rest of
;;; it from the pool (marked used in BAMBUF).  C set on a drive error, or an
;;; empty pool (d_code 72: disk full).
x6_chain:
        lda #<BUF
        sta xch_rd+1
        lda #>BUF
        sta xch_rd+2
x6ch_sec:
        lda x6_len+1            ; more than one sector's worth left?
        bne +
        lda x6_len
        cmp #255
        bcc x6ch_last
+       jsr pool_take           ; the next one, linked
        bcc +
        rts
+       lda #254
        sta x6_cnt
        jmp x6ch_fill
x6ch_last:
        lda #$00
        sta x6_nt
        lda x6_len
        sta x6_cnt
        clc
        adc #$01
        sta x6_ns
x6ch_fill:
        lda x6_nt
        sta DBUF
        lda x6_ns
        sta DBUF+1
        ldy #$00
-       cpy x6_cnt
        beq +
xch_rd: lda $ffff
        sta DBUF+2,y
        inc xch_rd+1
        bne ++
        inc xch_rd+2
++      iny
        bne -
+       lda #$00                ; a clean tail
-       cpy #254
        beq +
        sta DBUF+2,y
        iny
        bne -
+       lda x6_t
        ldx x6_s
        ldy #>DBUF
        jsr d_bwrite
        bcc +
        rts
+       jsr dot
        lda x6_len              ; left -= this sector's
        sec
        sbc x6_cnt
        sta x6_len
        lda x6_len+1
        sbc #$00
        sta x6_len+1
        lda x6_nt
        beq +                   ; that was the last
        sta x6_t
        lda x6_ns
        sta x6_s
        jmp x6ch_sec
+       clc
        rts

;;; the pool's next sector into x6_nt/x6_ns, marked used in BAMBUF
pool_take:
        lda x6_pleft
        bne +
        lda #72
        sta d_code
        sec
        rts
+       dec x6_pleft
        lda x6_pool
        sta pt_rd+1
        lda x6_pool+1
        sta pt_rd+2
        ldy #$00
        jsr pt_rd
        sta x6_nt
        iny
        jsr pt_rd
        sta x6_ns
        lda x6_pool
        clc
        adc #$02
        sta x6_pool
        bcc +
        inc x6_pool+1
+       lda x6_nt               ; BAM: track t's entry at 4t; its count,
        asl                     ; then a bit per sector, set = free
        asl
        tax
        dec BAMBUF,x
        lda x6_ns
        lsr
        lsr
        lsr
        sta x6_cnt
        txa
        clc
        adc x6_cnt
        tax
        lda x6_ns
        and #$07
        tay
        lda bits,y
        eor #$ff
        and BAMBUF+1,x
        sta BAMBUF+1,x
        clc
        rts
pt_rd:  lda $ffff,y
        rts
bits:   !byte $01, $02, $04, $08, $10, $20, $40, $80

;;; 1A T6 S(x6_sec) as the cart has it -- the log's, else the original --
;;; into DBUF
x6_newest_sector:
        lda x6_uselog
        beq +
        jsr x6_seckey
        jsr x6_logdir
        jsr dlookup
        bcs +
        ldx #$02
-       lda reply,x
        sta tc_addr,x
        dex
        bpl -
        jmp ++
+       jsr x6_origsec
++      lda #>DBUF
        ldx #$01
        jmp fread_to

;;; tc_addr = the original page of 1A T6 S(x6_sec)
x6_origsec:
        lda x6_sec
        sec
        sbc #9
        sta x6_cnt
        asl
        adc x6_cnt              ; x 3
        tax
        lda u6x_save,x
        sta tc_addr
        lda u6x_save+1,x
        sta tc_addr+1
        lda u6x_save+2,x
        sta tc_addr+2
        rts

x6_seckey:
        ldx #KEYLEN-1
        lda #$00
-       sta lkey,x
        dex
        bpl -
        lda #$01                ; $01, disk 0, track 6, the sector
        sta lkey
        lda #$06
        sta lkey+2
        lda x6_sec
        sta lkey+3
        rts

;;; ==================================================================
;;; import
;;; ==================================================================
x6_import:
        jsr pr
        !pet 13," Import: this replaces the world",13
        !pet " on the cartridge. (Y/N) ",0
        jsr yn_key
        cmp #"Y"
        beq +
        jmp redraw
+       jsr x6_begin
        lda #$00
        sta x6_disk
        jsr xt_start
        jmp x6i_disk

;;; a new log half to import into: the other one, erased, its pointers set;
;;; x6_uselog = 0 (the originals only, from here on)
x6_begin:
        jsr u6_find_log         ; the half in use now, if any
        lda #$00
        sta x6_had
        bcs +
        inc x6_had
+       lda x6_had
        bne +
        lda #$03                ; none: write half 0, generation 0
        sta act
        lda #$ff
        sta gen
        sta gen+1
+       lda act                 ; the other half
        eor #$03
        sta x6_to
        jsr pr
        !pet 13," Clearing",0
        ldx x6_to
        jsr erase_half
        ldx x6_to               ; pages from its base up, entries from one
        lda u6_bases,x          ; slot below its top down (the top slot is
        sta x6_wd               ; the header's, written last)
        lda u6_bases+1,x
        sta x6_wd+1
        lda u6_bases+2,x
        sta x6_wd+2
        lda u6_tops,x
        sta x6_we
        lda u6_tops+1,x
        sta x6_we+1
        lda u6_tops+2,x
        sta x6_we+2
        jsr we_down             ; (the top slot)
        jsr we_down             ; the first entry's
        lda #$00
        sta x6_uselog           ; originals only, from here on
        rts

x6i_disk:
        lda x6_disk
        cmp #$02
        bne +
        jmp x6i_done
+       jsr parse_disk
        jsr ask_disk
        bcc +
        jmp x_cancel
+       jsr x6_setdisk
x6i_file:
        lda x6_left
        bne +
        jmp x6i_save
+       jsr x6_name
        jsr x6_readchain        ; the disk's, as sectors, into BUF on
        bcc +
        jmp x_fail
+       lda #>ORIG              ; the original, to compare with
        sta x6_dpage
        jsr x6_content
        bcc +
        jmp x6_missing
+       jsr x6_same
        bcc +                   ; the same: nothing to log
        jsr x6_logfile
+       dec x6_left
        jmp x6i_file
x6i_save:
        lda x6_disk
        bne x6i_next
        lda #9
        sta x6_sec
-       lda #6
        ldx x6_sec
        ldy #>DBUF
        jsr d_bread
        bcc +
        jmp x_fail
+       jsr dot
        jsr x6_origsec          ; the original, into ORIG
        lda #>ORIG
        ldx #$01
        jsr fread_to
        ldy #$00
--      lda DBUF,y
        cmp ORIG,y
        bne +
        iny
        bne --
        beq ++                  ; the same
+       jsr x6_seckey
        lda #>DBUF
        ldx #$01
        jsr x6_logpages
        lda #$00
        sta x6_n
        jsr x6_entry
++      inc x6_sec
        lda x6_sec
        cmp #21
        bne -
x6i_next:
        inc x6_disk
        jmp x6i_disk
x6i_done:
        jsr d_close
        jsr x6_commit
        jmp x_done2

;;; the new half made the one in use, and the old one erased
x6_commit:
        ;; the header, in the half's top slot: from now on this half is the
        ;; one in use (init_u6.s: the valid half with the higher generation)
        ldx #ENTRY-1
        lda #$00
-       sta ent,x
        dex
        bpl -
        lda #$fe
        sta ent
        ldx #$02
-       lda log_name,x
        sta ent+1,x
        dex
        bpl -
        lda gen
        clc
        adc #$01
        sta ent+KEYLEN
        eor #$ff
        sta ent+KEYLEN+2
        lda gen+1
        adc #$00
        sta ent+KEYLEN+1
        eor #$ff
        sta ent+KEYLEN+3
        ldx x6_to
        lda u6_tops,x
        sta x6_we
        lda u6_tops+1,x
        sta x6_we+1
        lda u6_tops+2,x
        sta x6_we+2
        jsr we_down
        jsr we_addr
        lda #<ent
        sta tc_dest
        lda #>ent
        sta tc_dest+1
        lda #ENTRY
        sta tc_len
        lda #$00
        sta tc_len+1
        jsr tc_write
        lda x6_had              ; and the old half goes
        beq +
        ldx act
        jsr erase_half
+       rts

;;; the chain from x6_t/x6_s into BUF, a sector a page: x6_n of them.
;;; C set on a drive error, a bad link or one too many.
x6_readchain:
        lda #$00
        sta x6_n
        lda x6_t
        sta x6_nt
        lda x6_s
        sta x6_ns
-       lda x6_n
        cmp #MAXSEC
        bcs xr_bad
        clc
        adc #>BUF
        sta xr_l0+2
        sta xr_l1+2
        tay
        lda x6_nt
        ldx x6_ns
        jsr d_bread
        bcc +
        rts
+       jsr dot
        inc x6_n
xr_l0:  lda $ff00
        sta x6_nt
xr_l1:  lda $ff01
        sta x6_ns
        lda x6_nt
        beq +                   ; the last
        cmp #36
        bcs xr_bad
        bcc -
+       clc
        rts
xr_bad: lda #$00
        sta d_code
        jsr pr
        !pet 13," A chunk file's chain is broken.",0
        sec
        rts

;;; C clear if the chain in BUF holds exactly the x6_len bytes at ORIG
x6_same:
        lda #<ORIG
        sta xs_q+1
        lda #>ORIG
        sta xs_q+2
        lda x6_len
        sta x6_rl
        lda x6_len+1
        sta x6_rl+1
        lda #>BUF
        sta xs_p+2
        sta xs_c0+2
        sta xs_c1+2
        lda x6_n
        sta x6_cnt2
xs_page:
xs_c0:  lda $ff00               ; this sector's bytes
        bne +
xs_c1:  ldx $ff01
        dex
        txa
        jmp ++
+       lda #254
++      sta x6_cnt
        lda x6_rl+1             ; more than is left of the original?
        bne +
        lda x6_rl
        cmp x6_cnt
        bcc xs_diff
+       ldy #$00
-       cpy x6_cnt
        beq +
xs_p:   lda $ff02,y
xs_q:   cmp $ffff
        bne xs_diff
        inc xs_q+1
        bne ++
        inc xs_q+2
++      iny
        bne -
+       lda x6_rl
        sec
        sbc x6_cnt
        sta x6_rl
        lda x6_rl+1
        sbc #$00
        sta x6_rl+1
        inc xs_p+2
        inc xs_c0+2
        inc xs_c1+2
        dec x6_cnt2
        bne xs_page
        lda x6_rl               ; and nothing of the original left over
        ora x6_rl+1
        bne xs_diff
        clc
        rts
xs_diff:
        sec
        rts

;;; log the chain in BUF as the file lkey names
x6_logfile:
        lda #>BUF
        ldx x6_n
        jsr x6_logpages
        lda #F6_LINKS
        sta x6_flags
        jmp x6_entry_f

;;; X pages from page A on to the log's data pointer; x6_page = where
x6_logpages:
        sta tc_dest+1
        stx x6_cnt
        lda #$00
        sta tc_dest
        ldx #$02
-       lda x6_wd,x
        sta x6_page,x
        sta tc_addr,x
        dex
        bpl -
-       jsr write_page
        inc x6_wd+1
        bne +
        inc x6_wd+2
+       dec x6_cnt
        bne -
        rts

;;; the entry for lkey: x6_page, x6_n pages (0: a sector), x6_flags
x6_entry:
        lda #$00
        sta x6_flags
x6_entry_f:
        ldx #KEYLEN-1
-       lda lkey,x
        sta ent,x
        dex
        bpl -
        ldx #$02
-       lda x6_page,x
        sta ent+KEYLEN,x
        dex
        bpl -
        lda x6_n
        sta ent+KEYLEN+3
        lda #$00
        sta ent+KEYLEN+4
        sta ent+KEYLEN+6
        sta ent+KEYLEN+7
        lda x6_flags
        sta ent+KEYLEN+5
        jsr we_addr
        lda #<ent
        sta tc_dest
        lda #>ent
        sta tc_dest+1
        lda #ENTRY
        sta tc_len
        lda #$00
        sta tc_len+1
        jsr tc_write
        jsr we_down
        jmp dot

we_addr:
        ldx #$02
-       lda x6_we,x
        sta tc_addr,x
        dex
        bpl -
        rts
;;; x6_we -= one entry
we_down:
        sec
        lda x6_we
        sbc #ENTRY
        sta x6_we
        lda x6_we+1
        sbc #$00
        sta x6_we+1
        lda x6_we+2
        sbc #$00
        sta x6_we+2
        rts

;;; erase half X (0 or 3): 32 blocks
erase_half:
        lda u6_bases,x
        sta tc_addr
        lda u6_bases+1,x
        sta tc_addr+1
        lda u6_bases+2,x
        sta tc_addr+2
        lda #(U6_MID - U6_LO) / $1000
        sta x6_cnt
-       jsr tc_erase_block
        lda tc_addr+1
        clc
        adc #$10
        sta tc_addr+1
        bcc +
        inc tc_addr+2
+       lda x6_cnt
        and #$03
        bne +
        jsr dot
+       dec x6_cnt
        bne -
        rts

;;; ---- the directories ---------------------------------------------------
;;; x6_log: find the log; x6_uselog says whether there is one
x6_log: lda #$00
        sta x6_uselog
        jsr u6_find_log
        bcs +
        inc x6_uselog
+       rts
x6_logdir:
        ldx #$04
-       lda ep,x                ; address and count, adjacent
        sta dparm,x
        dex
        bpl -
        rts
x6_sdir:
        lda #<U6_SDIR
        sta dparm
        lda #>U6_SDIR
        sta dparm+1
        lda #^U6_SDIR
        sta dparm+2
        lda #<U6_SCOUNT
        sta dparm+3
        lda #>U6_SCOUNT
        sta dparm+4
        rts

;;; DIR_LOOKUP lkey in the directory dparm says (address, count): C clear
;;; and reply (8 bytes) if it is there
dlookup:
        jsr tc_enter
        lda #CMD_DIR_SETPARAMS
        jsr tc_sendbyte
        ldy #$00                ; (Y: tc_sendbyte and tc_getbyte keep
-       lda dparm,y             ; only Y)
        jsr tc_sendbyte
        iny
        cpy #$05
        bne -
        lda #KEYLEN
        jsr tc_sendbyte
        lda #DATALEN
        jsr tc_sendbyte
        lda #CMD_DIR_LOOKUP
        jsr tc_sendbyte
        ldy #$00
-       lda lkey,y
        jsr tc_sendbyte
        iny
        cpy #KEYLEN
        bne -
        jsr tc_getbyte
        bne dl_miss
        ldy #$00
-       jsr tc_getbyte
        sta reply,y
        iny
        cpy #DATALEN
        bne -
        jsr tc_leave
        clc
        rts
dl_miss:
        jsr tc_leave
        sec
        rts

u6_bases: !byte <U6_LO, >U6_LO, ^U6_LO, <U6_MID, >U6_MID, ^U6_MID

x6_disk:  !byte 0
x6_left:  !byte 0
x6_file:  !word 0
x6_pool:  !word 0
x6_pleft: !byte 0
x6_t:     !byte 0
x6_s:     !byte 0
x6_nt:    !byte 0
x6_ns:    !byte 0
x6_n:     !byte 0
x6_cnt:   !byte 0
x6_cnt2:  !byte 0
x6_len:   !word 0
x6_rl:    !word 0
x6_sec:   !byte 0
x6_dpage: !byte 0
x6_uselog: !byte 0
x6_had:   !byte 0
x6_to:    !byte 0
x6_flags: !byte 0
x6_wd:    !fill 3, 0            ; the import's next page ...
x6_we:    !fill 3, 0            ; ... and next entry
x6_page:  !fill 3, 0
dparm:    !fill 5, 0
lkey:     !fill KEYLEN, 0
