;;; efu5.s -- the launcher's 5: Ultima V from the tapecart, with its music
;;; and 2-bit reads from this cart (ultima/games/u5/armusic.s EF_MUSIC).
;;;
;;; efpage.s reads this to U5L_ORG and calls it after tx_open: the tapecart
;;; answers, it is in command mode, and its settings page says "UCFG" and
;;; this build's LAYOUT.  Back with C set: refused, and said why; nothing
;;; has been changed.  Otherwise it does not come back.
;;;
;;; The game is the tapecart's own, so its driver's tables -- the directory,
;;; the block maps, the save slots -- are always that cart's.  What is read
;;; from it is checked to be the build this cart was made with
;;; (ultima/games/u5/build.py build_efmusic):
;;;
;;;   - U5's descriptor page, as the menu would read it;
;;;   - its journal: a save a power cut interrupted is finished by the
;;;     tapecart's first stage at power-on, which does not run here -- with
;;;     one waiting, the slot may hold half a save, so nothing starts;
;;;   - the four boot segments (xyzzy, temp.subs, the driver, the init
;;;     stub), read to SEGBUF and compared byte for byte with this cart's
;;;     copy of them.
;;;
;;; Then the segments go where the menu puts them, the patches are made
;;; (the driver's two writes of the AR's register become the EasyFlash's,
;;; xyzzy's AR hook becomes efhook.s), the options byte is poked from the
;;; tapecart's settings as the page and launch128.s do, the machine is put
;;; as the KERNAL has it, the music's bank is selected and the init stub
;;; runs.  The cart stays off ($DE02 = EF_OFF) but for the glue.
;;;
;;; Memory: this at U5L_ORG, above EAPI's slot; eftc.s at TCX_ORG; the
;;; segments read to SEGBUF, the launcher's transfer buffers (efpage.s BUF:
;;; RAM whatever $01 says, and clear of every segment's place).  The cart's
;;; window ($8000-$BFFF) is mapped only for single reads, and for the
;;; patches, whose targets are all below it.  The segments' places
;;; ($0200-$0276, $2000, $6C00-$7AFF) hold the launcher, which is done with
;;; by then.
;;;
;;; Defined by ultima/ef/build.py: U5L_ORG, TCX_ORG, TCX_PARM, SEGBUF,
;;; U5_BANK, COPY_BANK, COPY_ROM, PATCH_ROM, SEG_TOTAL, OPT_AT, CAPS,
;;; PT_OPTS, ENTRY; efu5_data.s: the descriptor and the rows (r_set, r_desc,
;;; r_jn, r_segs) and where the segments go (copies).

!source "efvars.inc"

CHROUT = $ffd2
IOINIT = $ff84
RESTOR = $ff8a
CINT   = $ff81
TC_READ = TCX_ORG + 3

ptr  = $fb
ptr2 = $fd

        * = U5L_ORG
        sei
        jsr pr
        !pet 13," Ultima V",0
        ;; the options, as the page pokes them: U5's byte in the settings
        ;; ("UCFG" there: tx_open has checked it)
        ldx #r_set + 6 - rows
        jsr tread
        lda SEGBUF+OPT_AT
        and #CAPS
        sta opts
        ;; its descriptor page
        ldx #r_desc + 6 - rows
        jsr tread
        ldx #desc_end - desc - 1
-       lda SEGBUF,x
        cmp desc,x
        beq +
        jmp other
+       dex
        bpl -
        ;; a save a power cut interrupted (asm/boot.s jn_one: anything but
        ;; $FF $FF at the journal's start has to be seen to first)
        ldx #r_jn + 6 - rows
        jsr tread
        lda SEGBUF
        and SEGBUF+1
        cmp #$ff
        beq +
        jmp waiting
        ;; the segments, one after the other
+       ldx #r_segs + 6 - rows
-       stx sx
        jsr tread
        lda sx
        clc
        adc #7
        tax
        cpx #r_segs_end + 6 - rows
        bcc -
        ;; and this build's, byte for byte (the cart mapped for each read)
        lda #COPY_BANK
        sta EF_BANK_REG
        lda #<SEGBUF
        sta ptr
        lda #>SEGBUF
        sta ptr+1
        lda #<COPY_ROM
        sta ptr2
        lda #>COPY_ROM
        sta ptr2+1
        lda #<SEG_TOTAL
        sta cnt
        lda #>SEG_TOTAL
        sta cnt+1
        ldy #$00
cmp_next:
        ldx #EF_16K
        stx EF_CTRL_REG
        lda (ptr2),y            ; this build's
        ldx #EF_OFF
        stx EF_CTRL_REG
        cmp (ptr),y             ; the tapecart's, the cart off again
        beq +
        jmp other
+       inc ptr
        bne +
        inc ptr+1
+       inc ptr2
        bne +
        inc ptr2+1
+       lda cnt
        bne +
        dec cnt+1
+       dec cnt
        lda cnt
        ora cnt+1
        bne cmp_next
        jsr cheats

        ;; ---- from here on, the launcher is overwritten ---------------------
        ;; the segments to their places
        ldx #0
-       stx sx
        lda copies,x
        sta ptr
        lda copies+1,x
        sta ptr+1
        lda copies+2,x
        sta cnt
        lda copies+3,x
        sta cnt+1
        lda copies+4,x
        sta ptr2
        lda copies+5,x
        sta ptr2+1
        ldy #$00
--      lda (ptr),y
        sta (ptr2),y
        inc ptr
        bne +
        inc ptr+1
+       inc ptr2
        bne +
        inc ptr2+1
+       lda cnt
        bne +
        dec cnt+1
+       dec cnt
        lda cnt
        ora cnt+1
        bne --
        lda sx
        clc
        adc #6
        tax
        cpx #copies_end - copies
        bcc -
        ;; the patches: count, address, the new bytes; a count of 0 ends.
        ;; The cart in for all of it (the list is in the bank, every target
        ;; below $8000)
        lda #<PATCH_ROM
        sta ptr2
        lda #>PATCH_ROM
        sta ptr2+1
        lda #EF_16K
        sta EF_CTRL_REG
pa_next:
        ldy #$00
        lda (ptr2),y
        beq pa_done
        tax
        iny
        lda (ptr2),y
        sta ptr
        iny
        lda (ptr2),y
        sta ptr+1
        lda ptr2
        clc
        adc #3
        sta ptr2
        bcc +
        inc ptr2+1
+       ldy #$00
-       lda (ptr2),y
        sta (ptr),y
        iny
        dex
        bne -
        tya
        clc
        adc ptr2
        sta ptr2
        bcc pa_next
        inc ptr2+1
        bne pa_next
pa_done:
        lda #EF_OFF
        sta EF_CTRL_REG
        lda opts
        sta PT_OPTS
        ;; the machine as the KERNAL has it, as efpage.s's L leaves it for
        ;; Ultima VI; CIA 2's NMI latch (efpage.s, for EAPI) released
        jsr IOINIT
        jsr RESTOR
        jsr CINT
        sei
        bit $dd0d
        lda #$00                ; xyzzy's C128 test (asm/menu.s): EAPI's
        sta $c024               ; bytes are there
        lda #U5_BANK            ; the music's (efhook.s selects it again)
        sta EF_BANK_REG
        lda #EF_OFF
        sta EF_CTRL_REG
        jmp ENTRY

;;; tc_read on the tapecart (eftc.s) by the row whose last byte is rows + X:
;;; tc_addr, tc_len, tc_dest
tread:  ldy #6
-       lda rows,x
        sta TCX_PARM,y
        dex
        dey
        bpl -
        jmp TC_READ

;;; " Cheats: " and the page's keys for those on (asm/page.s o_f, o_u, o_m,
;;; o_x5), or "none"
cheats: jsr pr
        !pet 13," Cheats:",0
        ldx #0
        stx sx
-       lda ch_bit,x
        and opts
        beq +
        lda #" "
        jsr CHROUT
        ldx sx
        lda ch_key,x
        jsr CHROUT
+       inc sx
        ldx sx
        cpx #ch_key - ch_bit
        bcc -
        lda opts
        bne +
        jsr pr
        !pet " none",0
+       rts
ch_bit: !byte %00000001, %00010000, %00100000, %00000100
ch_key: !pet "F", "U", "M", "X"
!if ch_key - ch_bit != 4 { !error "a cheat without its key" }

other:  jsr pr
        !pet ": the tapecart holds another",13
        !pet " build's. Flash both carts from the",13
        !pet " same build.",0
        sec
        rts

waiting:
        jsr pr
        !pet ": a save on the tapecart was cut",13
        !pet " short. Start the tapecart on its own",13
        !pet " once to finish it.",0
        sec
        rts

;;; the zero-terminated string after the JSR
pr:     pla
        sta ptr2
        pla
        sta ptr2+1
-       inc ptr2
        bne +
        inc ptr2+1
+       ldy #$00
        lda (ptr2),y
        beq +
        jsr CHROUT
        jmp -
+       lda ptr2+1
        pha
        lda ptr2
        pha
        rts

sx:     !byte 0
cnt:    !word 0
opts:   !byte 0

!source "efu5_data.s"           ; desc, rows (r_desc, r_jn, r_segs), copies
efu5_end:
