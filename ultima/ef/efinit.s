;;; efinit.s -- the boot's last step before Ultima VI's own cold start, in
;;; RAM at $1000: find the write log, hand its state to the drivers in the
;;; cart's RAM ($DF00, efvars.inc), put the boot resident in place, and jump
;;; to the cold start at $C00C.  (The tapecart build's asm/init_u6.s does the
;;; same; the log's rules are its, see there: two halves, pages up, entries
;;; down, a header with a generation in a compacted half's top slot, the
;;; valid half with the higher generation active.)
;;;
;;; Entered from efstart.s with the cart in 16K mode, $01 = $37, interrupts
;;; off.  Defines from ultima/ef/build.py: the log's halves, the boot segments
;;; (SEGS: linear address, length, destination; SEGN of them), the pokes.

!source "efvars.inc"

HALF     = LOG_MID - LOG_LO
BUF      = $3000                ; one page

        * = $1000
        sei
        lda #$37
        sta $01
        lda #EF_16K
        sta EF_CTRL_REG
        lda #$00                ; a black screen until the opening's first
        sta $d020               ; picture (init_u6.s does the same)
        sta $d021
        ldx #$00
-       sta $d800,x
        sta $d900,x
        sta $da00,x
        sta $dae8,x
        inx
        bne -

        ;; ---- the drivers' state: nothing open, no reset yet -----------
        ldx #EF_STATE_END - EF_LOGDIR - 1
-       sta EF_LOGDIR,x
        dex
        bpl -

        ;; ---- which half ------------------------------------------------
        ldx #$00
        jsr topslot
        sta valid0
        lda tgen
        sta gen
        lda tgen+1
        sta gen+1
        ldx #$03
        jsr topslot
        bne +
        lda valid0              ; half 1 invalid
        bne pick0
        inc nolog               ; neither: a cart that held something else,
        lda #$03                ; or nothing -- half 0 gets a new log once
        sta EF_ACT              ; the boot resident is in (d_new)
        jmp segs_go
+       lda valid0
        beq pick1               ; half 0 invalid
        lda gen+1               ; both: half 1 if its generation is higher
        cmp tgen+1
        bcc pick1
        bne pick0
        lda gen
        cmp tgen
        bcs pick0
pick1:  lda tgen
        sta gen
        lda tgen+1
        sta gen+1
        ldx #$03
        !byte $2c               ; BIT abs: skip the ldx
pick0:  ldx #$00
        stx EF_ACT
        lda gen
        sta EF_GEN
        lda gen+1
        sta EF_GEN+1
        jsr scan

        ;; ---- the boot resident and the pokes ---------------------------
segs_go:
        ldx #$00
seg:    cpx #SEGN * 7
        beq segs_done
        ldy #$00
-       lda segs,x
        sta tc_addr,y
        inx
        iny
        cpy #$07
        bne -
        txa
        pha
        jsr tc_read
        pla
        tax
        jmp seg
segs_done:
        lda nolog
        beq +
        jsr fresh
+       ldx #$00
-       cpx pokes
        beq +
        lda pokes+1,x
        sta pk+1
        lda pokes+2,x
        sta pk+2
        lda pokes+3,x
pk:     sta $ffff
        inx
        inx
        inx
        jmp -
+       lda #EF_OFF             ; the cart out of sight: the game banks as
        sta EF_CTRL_REG         ; it likes
        jmp $c00c               ; the cold start (its drive-code upload gone)

;;; ==================================================================
;;; fresh -- a new, empty log in half 0, through the boot driver's `*`
;;; (efdrv.s d_new: two 64 KiB erases and a header, generation 1).  EAPI's
;;; NMI latch goes through the RAM vector, which nothing has set yet.
;;; ==================================================================
fresh:  lda #<nmi_rti
        sta $fffa
        lda #>nmi_rti
        sta $fffb
        ldx #<star
        ldy #>star
        jsr $c16b
        lda #$37                ; (the loader leaves the cart out, $35)
        sta $01
        lda #EF_16K
        sta EF_CTRL_REG
        rts
nmi_rti:
        rti
star:   !byte $2a, $00

;;; ==================================================================
;;; topslot -- read half X's top slot (X = 0 or 3) into ent.  A = 1 if the
;;; half is valid (Z clear), 0 if not; tgen = its generation.  Valid means
;;; a header, all 20 bytes of it: $FE "LOG", zeros, the generation and its
;;; complement, zeros.  (The tapecart's log also takes a first entry there
;;; as generation 0; here the log banks are not in the CRT, so they hold
;;; whatever the cart held before until a log is made, and only a header
;;; can say one was.)
;;; ==================================================================
topslot:
        lda #$00
        sta tgen
        sta tgen+1
        sec
        lda htop,x
        sbc #ENTRYLEN
        sta tc_addr
        lda htop+1,x
        sbc #$00
        sta tc_addr+1
        lda htop+2,x
        sbc #$00
        sta tc_addr+2
        jsr rdent
        ldx #ENTRYLEN-1
-       lda ent,x
        cmp hdr,x
        beq +
        cpx #KEYLEN             ; (the generation, its complement: below)
        bcc ts_bad
        cpx #KEYLEN+4
        bcs ts_bad
+       dex
        bpl -
        lda ent+KEYLEN
        eor #$ff
        cmp ent+KEYLEN+2
        bne ts_bad              ; a torn header
        lda ent+KEYLEN+1
        eor #$ff
        cmp ent+KEYLEN+3
        bne ts_bad
        lda ent+KEYLEN
        sta tgen
        lda ent+KEYLEN+1
        sta tgen+1
        lda #$01
        rts
ts_bad: lda #$00
        rts

rdent:  lda #<ent               ; ENTRYLEN bytes from tc_addr
        ldx #>ent
        ldy #ENTRYLEN
rdsmall:
        sta tc_dest
        stx tc_dest+1
        sty tc_len
        lda #$00
        sta tc_len+1
        jmp tc_read

;;; ==================================================================
;;; scan -- the active half's directory: count it, and find the next
;;; free page
;;; ==================================================================
scan:
        lda #$00
        sta EF_DIRCOUNT
        sta EF_DIRCOUNT+1
        ldx EF_ACT
        ldy #$00
-       lda htop,x              ; nothing found yet: an empty half
        sta EF_LOGDIR,y
        lda hbase,x
        sta EF_LOGDATA,y
        inx
        iny
        cpy #$03
        bne -
sc_next:
        sec
        lda EF_LOGDIR
        sbc #ENTRYLEN
        sta tc_addr
        lda EF_LOGDIR+1
        sbc #$00
        sta tc_addr+1
        lda EF_LOGDIR+2
        sbc #$00
        sta tc_addr+2
        lda #<ent
        ldx #>ent
        ldy #$01
        jsr rdsmall
        lda ent
        cmp #$ff                ; no key starts with $FF: the end
        beq sc_end
        ldx #$02
-       lda tc_addr,x
        sta EF_LOGDIR,x
        dex
        bpl -
        inc EF_DIRCOUNT
        bne sc_next
        inc EF_DIRCOUNT+1
        jmp sc_next

        ;; the next free page: where the newest entry's pages end -- the
        ;; newest that makes sense, so a torn entry cannot send it astray
sc_end: ldx #$02
-       lda EF_LOGDIR,x
        sta walk,x
        dex
        bpl -
        lda EF_DIRCOUNT
        sta left
        lda EF_DIRCOUNT+1
        sta left+1
sc_ent: lda left
        ora left+1
        beq sc_done             ; none: the half's base
        ldx #$02
-       lda walk,x
        sta tc_addr,x
        dex
        bpl -
        jsr rdent
        lda ent
        cmp #K_HEADER           ; a header has no pages
        beq sc_older
        jsr pagesof
        clc                     ; its end, in pages
        lda ent+KEYLEN+1
        adc npages
        sta endp
        lda ent+KEYLEN+2
        adc npages+1
        sta endp+1
        bcs sc_older
        ldx EF_ACT
        lda ent+KEYLEN+1        ; start >= the half's base ...
        cmp hbase+1,x
        lda ent+KEYLEN+2
        sbc hbase+2,x
        bcc sc_older
        lda EF_LOGDIR+1         ; ... and end <= the directory
        cmp endp
        lda EF_LOGDIR+2
        sbc endp+1
        bcc sc_older
        lda endp
        sta EF_LOGDATA+1
        lda endp+1
        sta EF_LOGDATA+2
        jmp sc_done
sc_older:
        jsr walk_up
        jmp sc_ent
sc_done:
        ;; skip pages a torn save left behind (never into the directory)
sk_loop:
        lda EF_LOGDATA+1
        cmp EF_LOGDIR+1
        lda EF_LOGDATA+2
        sbc EF_LOGDIR+2
        bcs sk_out
        ldx #$02
-       lda EF_LOGDATA,x
        sta tc_addr,x
        dex
        bpl -
        lda #<BUF
        ldx #>BUF
        ldy #$00
        sta tc_dest
        stx tc_dest+1
        sty tc_len
        iny
        sty tc_len+1
        jsr tc_read
        ldy #$00
-       lda BUF,y
        cmp #$ff
        bne sk_dirty
        iny
        bne -
sk_out: rts                     ; erased: the log goes on from here
sk_dirty:
        inc EF_LOGDATA+1
        bne sk_loop
        inc EF_LOGDATA+2
        jmp sk_loop

;;; walk += ENTRYLEN, left -= 1: the next older entry in flash
walk_up:
        clc
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
        rts

;;; npages <- the pages of the entry in ent: a file (F_LINKS) its count,
;;; a sector one
pagesof:
        ldx #$01
        ldy #$00
        lda ent+KEYLEN+5
        and #F_LINKS
        beq +
        ldx ent+KEYLEN+3
        ldy ent+KEYLEN+4
+       stx npages
        sty npages+1
        rts

;;; ---- the halves, little endian: half 0 at +0, half 1 at +3 -----------
hbase:  !24 LOG_LO, LOG_MID
htop:   !24 LOG_MID, LOG_HI

hdr:    !byte K_HEADER, $4c, $4f, $47
        !fill ENTRYLEN - 4, 0
valid0: !byte 0
nolog:  !byte 0
gen:    !word 0
tgen:   !word 0
npages: !word 0
endp:   !word 0
left:   !word 0
walk:   !fill 3, 0
ent:    !fill ENTRYLEN, 0

!source "eflib.s"

;;; the boot segments: linear address (3), length (2), destination (2)
segs:   !fill SEGN * 7, $ff     ; filled in by ultima/ef/build.py
;;; the pokes: count, then address (2) and value
pokes:  !byte 0
        !fill 3 * 4, 0

init_end:
!if init_end > BUF {
        !error "efinit runs into its buffer by ", init_end - BUF
}
