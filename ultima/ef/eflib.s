;;; eflib.s -- flash access for code that runs in RAM with the machine to
;;; itself (the boot's init, the launcher): tclib's parameter block and
;;; entry names (asm/tclib.s), over the EasyFlash.  Assembled into its user.
;;;
;;;   tc_read   tc_len bytes from the linear flash address tc_addr to
;;;             tc_dest.  tc_addr and tc_dest are left as they were and
;;;             tc_len is consumed -- tclib's own contract.
;;;
;;; Every call masks interrupts for itself (an IRQ at $01 = $33 would find
;;; no I/O), maps the cart in 16K mode, and leaves it as el_idle says: $07
;;; for efinit (which runs with the cart in), EF_OFF for the launcher.  $01
;;; is $37 between calls; the copy runs at $33 (stores reach the RAM under
;;; I/O and the ROMs).
;;;
;;; EFLIB_WRITE (the launcher) adds the rest of what the tapecart page's
;;; transfer code (page_xfer.s, page_u6x.s, page_file.s) asks of tclib:
;;;
;;;   ef_init   EAPI from 00:1:1800 into EL_SLOT, CIA 2's NMI latched, and
;;;             EAPIInit; C set if this flash is not one EAPI knows
;;;   tc_write  tc_len bytes from tc_dest to tc_addr, through EAPI (lhlh:
;;;             the pointer runs on across chips and banks as the linear
;;;             address does).  tc_dest advances, tc_len is consumed,
;;;             tc_addr is left.  A byte that will not program sets
;;;             el_werr, and from then on every write and erase is refused
;;;             (C set) until the launcher has said so and cleared it: an
;;;             import that fails half way never writes its header, nor
;;;             erases the old half, so the log stays as it was.
;;;   tc_erase_block
;;;             tclib erases 4 KiB blocks; the EasyFlash has 64 KiB sectors,
;;;             and a log half is two of them (ROML and ROMH of eight banks).
;;;             The one caller (page_u6x.s erase_half) walks a half from its
;;;             base in 4 KiB steps: the block at a half's base erases the
;;;             whole half, every other block is left alone.
;;;   tc_enter, tc_sendbyte, tc_getbyte, tc_leave
;;;             the cart's DIR_SETPARAMS and DIR_LOOKUP (tapecart ProgRef),
;;;             answered here from the flash: a directory of KEYLEN + DATALEN
;;;             byte entries, the first whose key matches; status 0 and its
;;;             data, or status 1.  Anything else sent is ignored.
;;;
;;; EFLIB_TC (the launcher, with EFLIB_WRITE) adds el_dev: with its bit 7
;;; set, every name above is the tapecart's instead -- a real tclib
;;; (eftc.s) at TCX_ORG, its parameter block at TCX_PARM -- so the same
;;; transfer code reads and writes Ultima VI's log on the tapecart's
;;; collection.  eflib's own reads (EAPI, the lookup) are always el_read.

tc_addr:  !fill 3, 0            ; tc_addr, tc_len, tc_dest: adjacent, in
tc_len:   !word 0               ; this order (a segment table row is the
tc_dest:  !word 0               ; same seven bytes)
el_idle:  !byte EF_16K          ; $DE02 between calls

tc_read:
!ifdef EFLIB_TC {
        bit el_dev
        bpl +
        jmp tx_read
+
}
el_read:
        php
        sei
        lda #EF_16K
        sta EF_CTRL_REG
        ldx #$02
-       lda tc_addr,x
        sta el_a,x
        dex
        bpl -
        lda tc_dest
        sta el_d+1
        lda tc_dest+1
        sta el_d+2
el_loop:
        lda tc_len
        ora tc_len+1
        bne +
        lda el_idle
        sta EF_CTRL_REG
        plp
        rts
+       jsr el_bank             ; the bank, and the address in it
        lda el_a
        sta el_s+1
        sec                     ; a run: to the source page's end at most
        lda #$00
        sbc el_a
        sta el_n                ; (0 = 256)
        lda tc_len+1
        bne el_go
        lda el_n
        beq el_rl
        cmp tc_len
        bcc el_go
el_rl:  lda tc_len
        sta el_n
el_go:  lda el_n
        sta el_c+1
        lda #$33
        sta $01
        ldy #$00
el_s:   lda $ffff,y
el_d:   sta $ffff,y
        iny
el_c:   cpy #$00
        bne el_s
        lda #$37
        sta $01
        lda el_n
        bne el_part
        inc el_a+1              ; a whole page
        bne +
        inc el_a+2
+       inc el_d+2
        dec tc_len+1
        jmp el_loop
el_part:
        clc
        adc el_a
        sta el_a
        bcc +
        inc el_a+1
        bne +
        inc el_a+2
+       clc
        lda el_n
        adc el_d+1
        sta el_d+1
        bcc +
        inc el_d+2
+       sec
        lda tc_len
        sbc el_n
        sta tc_len
        bcs +
        dec tc_len+1
+       jmp el_loop

;;; the bank of el_a into $DE00 (and A), the address in it into el_s's
;;; operand's high byte
el_bank:
        lda el_a+2
        sta el_t
        lda el_a+1
        asl
        rol el_t
        asl
        rol el_t
        lda el_a+1
        and #$3f
        ora #$80
        sta el_s+2
        lda el_t
        sta EF_BANK_REG
        rts

el_a:   !fill 3, 0
el_t:   !byte 0
el_n:   !byte 0

!ifdef EFLIB_WRITE {
CMD_DIR_SETPARAMS = $40         ; tclib's values
CMD_DIR_LOOKUP    = $41

;;; ---- EAPI -------------------------------------------------------------
ef_init:
        php
        sei
        lda #<EAPI_LIN
        sta tc_addr
        lda #>EAPI_LIN
        sta tc_addr+1
        lda #^EAPI_LIN
        sta tc_addr+2
        lda #<EAPI_SIZE
        sta tc_len
        lda #>EAPI_SIZE
        sta tc_len+1
        lda #<EL_SLOT
        sta tc_dest
        lda #>EL_SLOT
        sta tc_dest+1
        jsr el_read
        ;; CIA 2's NMI, latched: one timer underflow, never acknowledged,
        ;; holds the line low, so neither it nor RESTORE can raise another
        ;; while EAPI's Ultimax windows are open (their vectors would come
        ;; from whatever bank is selected).  The one it raises goes to an
        ;; RTI: the KERNAL's own handler would read $DD0D and let go.
        lda #<el_rti
        sta $0318
        lda #>el_rti
        sta $0319
        lda #$7f
        sta $dd0d
        lda $dd0d
        lda #$01
        sta $dd04
        lda #$00
        sta $dd05
        lda #$81
        sta $dd0d
        lda #$19                ; force load, one shot, start
        sta $dd0e
        nop
        nop
        nop
        nop
        lda #EF_16K
        sta EF_CTRL_REG
        jsr EL_SLOT + EAPI_INIT_OFF
        php
        lda el_idle
        sta EF_CTRL_REG
        lda #$00
        rol                     ; (C: EAPIInit's answer)
        sta el_nope
        plp
        bcs +
        plp
        clc
        rts
+       plp
        sec
        rts
el_rti: rti

tc_write:
!ifdef EFLIB_TC {
        bit el_dev
        bpl +
        jmp tx_write
+
}
        php
        sei
        lda el_nope
        ora el_werr
        bne ew_fail
        lda #EF_16K_LED
        sta EF_CTRL_REG
        ldx #$02
-       lda tc_addr,x
        sta el_a,x
        dex
        bpl -
        jsr el_bank             ; (A = the bank)
        jsr EAPI_SETBANK
        ldx el_a
        ldy el_s+2
        lda #EAPI_LHLH
        jsr EAPI_SETPTR
        lda tc_dest
        sta ew_s+1
        lda tc_dest+1
        sta ew_s+2
ew_loop:
        lda tc_len
        ora tc_len+1
        beq ew_done
        lda #$34                ; the source as RAM, wherever it is
        sta $01
ew_s:   lda $ffff
        ldx #$37
        stx $01
        jsr EAPI_WRITEINC
        bcs ew_fail
        inc ew_s+1
        bne +
        inc ew_s+2
+       lda tc_len
        bne +
        dec tc_len+1
+       dec tc_len
        jmp ew_loop
ew_done:
        lda ew_s+1
        sta tc_dest
        lda ew_s+2
        sta tc_dest+1
        lda el_idle
        sta EF_CTRL_REG
        plp
        clc
        rts
ew_fail:
        inc el_werr
        lda el_idle
        sta EF_CTRL_REG
        plp
        sec
        rts

tc_erase_block:
!ifdef EFLIB_TC {
        bit el_dev
        bpl +
        jmp tx_erase
+
}
        lda tc_addr                     ; a half's base?
        bne ee_out
        lda tc_addr+1
        bne ee_out
        lda tc_addr+2
        and #$01
        bne ee_out
        lda tc_addr+2
        cmp #^LOG_LO
        bcc ee_out
        cmp #^LOG_HI
        bcs ee_out
        php
        sei
        lda el_nope
        ora el_werr
        bne +
        lda #EF_16K_LED
        sta EF_CTRL_REG
        lda tc_addr+2           ; its first bank: (addr >> 16) * 4
        asl
        asl
        sta el_t
        ldy #$80                ; ROML
        jsr el_erase
        ldy #$e0                ; ROMH
        jsr el_erase
        lda el_idle
        sta EF_CTRL_REG
        plp
ee_out: rts
+       inc el_werr
        plp
        rts

;;; one sector (bank el_t, Y = $80 or $E0), tried twice: EAPI gives up on
;;; an erase after its own timeout, and a sector can take longer
el_erase:
        sty el_n
        lda el_t
        jsr EAPI_ERASE
        bcc +
        ldy el_n
        lda el_t
        jsr EAPI_ERASE
        bcc +
        inc el_werr
+       lda #EF_16K_LED
        sta EF_CTRL_REG
        rts

el_nope:  !byte 0               ; EAPIInit said no: nothing is written
el_werr:  !byte 0               ; a write or erase failed

;;; ---- DIR_LOOKUP, answered here ----------------------------------------
tc_enter:
!ifdef EFLIB_TC {
        bit el_dev
        bpl +
        jmp TCX_ORG + 12
+
}
        lda #$00
        sta el_cn
        sta el_rn
        rts
tc_leave:
!ifdef EFLIB_TC {
        bit el_dev
        bpl +
        jmp TCX_ORG + 21
+
}
        rts

;;; (keeps Y, as tclib's does)
tc_sendbyte:
!ifdef EFLIB_TC {
        bit el_dev
        bpl +
        jmp TCX_ORG + 15
+
}
        ldx el_cn
        cpx #1 + KEYLEN
        bcs +
        sta el_cmd,x
        inc el_cn
+       lda el_cmd
        ldx el_cn
        cmp #CMD_DIR_SETPARAMS
        bne +
        cpx #$08                ; address (3), count (2), key and data length
        bne es_out
        ldx #$04
-       lda el_cmd+1,x
        sta el_dir,x
        dex
        bpl -
        bmi es_next
+       cmp #CMD_DIR_LOOKUP
        bne es_next             ; nothing else is answered
        cpx #1 + KEYLEN
        bne es_out
        tya
        pha
        jsr el_lookup
        pla
        tay
es_next:
        lda #$00
        sta el_cn
        sta el_rn
es_out: rts

;;; (keeps Y; N and Z from the byte)
tc_getbyte:
!ifdef EFLIB_TC {
        bit el_dev
        bpl +
        jmp TCX_ORG + 18
+
}
        ldx el_rn
        inc el_rn
        lda el_reply,x
        rts

;;; the key at el_cmd+1 in the directory at el_dir: el_reply <- 0 and its
;;; data, or 1
el_lookup:
        php
        sei
        lda #EF_16K
        sta EF_CTRL_REG
        ldx #$02
-       lda el_dir,x
        sta el_a,x
        dex
        bpl -
        lda el_dir+3
        sta el_k
        lda el_dir+4
        sta el_k+1
lk_loop:
        lda el_k
        ora el_k+1
        bne +
        lda #$01                ; not there
        sta el_reply
        jmp lk_out
+       jsr el_bank
        lda el_s+2              ; KEYLEN bytes within the bank?
        cmp #$bf
        bne lk_fast
        lda el_a
        cmp #$100 - KEYLEN + 1
        bcs lk_slow
lk_fast:
        lda el_a
        sta lk_c+1
        lda el_s+2
        sta lk_c+2
        ldy #KEYLEN-1
-       lda el_cmd+1,y
lk_c:   cmp $ffff,y
        bne lk_next
        dey
        bpl -
        jmp lk_hit
lk_slow:                        ; across the bank's end: read it, compare
        jsr lk_rd
        lda #KEYLEN
        sta tc_len
        lda #<el_kt
        sta tc_dest
        lda #>el_kt
        sta tc_dest+1
        jsr el_read             ; (which moves el_a on: put it back)
        ldx #$02
-       lda tc_addr,x
        sta el_a,x
        dex
        bpl -
        lda #EF_16K
        sta EF_CTRL_REG
        ldy #KEYLEN-1
-       lda el_cmd+1,y
        cmp el_kt,y
        bne lk_next
        dey
        bpl -
lk_hit: clc                     ; its data, after the key
        lda el_a
        adc #KEYLEN
        sta el_a
        bcc +
        inc el_a+1
        bne +
        inc el_a+2
+       jsr lk_rd
        lda #DATALEN
        sta tc_len
        lda #<(el_reply+1)
        sta tc_dest
        lda #>(el_reply+1)
        sta tc_dest+1
        jsr el_read
        lda #$00
        sta el_reply
lk_out: lda el_idle
        sta EF_CTRL_REG
        plp
        rts
lk_next:
        clc
        lda el_a
        adc #KEYLEN + DATALEN
        sta el_a
        bcc +
        inc el_a+1
        bne +
        inc el_a+2
+       lda el_k
        bne +
        dec el_k+1
+       dec el_k
        jmp lk_loop

;;; tc_addr <- el_a (tc_len's high byte 0)
lk_rd:  ldx #$02
-       lda el_a,x
        sta tc_addr,x
        dex
        bpl -
        lda #$00
        sta tc_len+1
        rts

el_cn:    !byte 0
el_rn:    !byte 0
el_cmd:   !fill 1 + KEYLEN, 0
el_dir:   !fill 5, 0
el_k:     !word 0
el_kt:    !fill KEYLEN, 0
el_reply: !fill 1 + DATALEN, 0

!ifdef EFLIB_TC {
;;; ---- the tapecart ----------------------------------------------------------
;;; With el_dev's bit 7 set, every tc_* name above is the tapecart's: eftc.s,
;;; read to TCX_ORG (efpage.s tx_open), whose jump table is three bytes an
;;; entry.  Reads, writes and erases hand it the parameter block and take it
;;; back -- tclib's contract is the one above, but for tc_write leaving
;;; tc_dest where it was, which no caller relies on -- with the caller's
;;; interrupt flag put back (tclib's tc_enter sets it, tc_leave leaves it).
!if <TCX_ORG != 0 {
        !error "TCX_ORG must be page aligned: the jump table's offset is its low byte"
}
el_dev:   !byte 0

tx_read:  lda #3
        bne tx_call
tx_write: lda #6
        bne tx_call
tx_erase: lda #9
tx_call:  sta tx_j+1
        php
        ldx #6
-       lda tc_addr,x
        sta TCX_PARM,x
        dex
        bpl -
tx_j:   jsr TCX_ORG
        ldx #6
-       lda TCX_PARM,x
        sta tc_addr,x
        dex
        bpl -
        plp
        clc
        rts
}   ; EFLIB_TC
}   ; EFLIB_WRITE
