;;; boot_u3.s -- Ultima 3 launcher.
;;;
;;; Replaces the `ultima` boot PRG, which set $01, read three raw chunks with
;;; its own block reader (EXOD, the DOS module, the catalog) and jumped to
;;; $8220.  We do the same from flash, with the DOS module patched and the
;;; catalog rewritten to flash pages, plus the driver itself as a fourth
;;; segment.
;;;
;;; Loaded from disk for now.  It relocates to $8700, immediately above EXOD
;;; ($3000-$86FF) and below anything the boot loads, so it survives its own
;;; segment loading.  It used to sit at $C500-$C9FF, until the decruncher
;;; moved in there -- and a launcher that loads a segment over itself fails
;;; in a way that looks like a bad segment rather than a bad address.

ptr   = $02
ptr2  = $04
namep = $06                     ; self-test scratch (zero page for (ind),y)
entp  = $08
tstptr= $0a
strp  = $0c

RELOC       = $8700
DESC_OFFSET = $000200           ; regions.desc_offset("u3")
DRIVER_INIT = $bc03             ; the driver's "jmp tc_init" entry
ENTRY       = $8220             ; EXOD, as the original boot PRG's final JMP

        * = $0801
        ;; 10 SYS 2061
        !byte $0b,$08,$0a,$00,$9e,$32,$30,$36,$31,$00,$00,$00

        lda #<body_image
        sta ptr
        lda #>body_image
        sta ptr+1
        lda #<RELOC
        sta ptr2
        lda #>RELOC
        sta ptr2+1
        ldx #BODY_PAGES
        ldy #$00
-       lda (ptr),y
        sta (ptr2),y
        iny
        bne -
        inc ptr+1
        inc ptr2+1
        dex
        bne -
        jmp boot

body_image:
!pseudopc RELOC {

SEG_COMP = %00000001            ; descriptor segment flag: stored crunched

TCLIB_ORG = RELOC
; TC_NO_CMDMODE deliberately left undefined: the launcher is what enters
; command mode.  Note !ifndef treats a value of 0 as "defined"...
!source "tclib.s"
!source "zxdecr.s"

boot:
        sei
        lda #$2f
        sta $00
        lda #$36                ; BASIC out, KERNAL in, I/O in -- what the
        sta $01                 ; original boot PRG sets, motor bit already set

        jsr tc_init
        jsr tc_cmdmode
        bcc +
        jmp boot_failed
+
        ;; blank before any fast read; tc_blank waits the frame out so the
        ;; DEN clear is actually in effect
        jsr tc_blank

        ;; ---- descriptor --------------------------------------------
        lda #<DESC_OFFSET
        sta tc_addr
        lda #>DESC_OFFSET
        sta tc_addr+1
        lda #^DESC_OFFSET
        sta tc_addr+2
        lda #DESC_SIZE
        sta tc_len
        lda #$00
        sta tc_len+1
        lda #<descbuf
        sta tc_dest
        lda #>descbuf
        sta tc_dest+1
        jsr tc_read_fast

        ;; ---- scatter-load ------------------------------------------
        lda descbuf+2
        sta segcount
        lda #$00
        sta segidx
seg_loop:
        lda segcount
        beq seg_done
        ldx segidx
        lda #$00
        sta tc_addr
        lda descbuf+3,x
        sta tc_addr+1
        lda descbuf+4,x
        sta tc_addr+2
        lda descbuf+5,x
        sta tc_len
        lda descbuf+6,x
        sta tc_len+1
        lda descbuf+7,x
        sta tc_dest
        lda descbuf+8,x
        sta tc_dest+1
        lda descbuf+9,x         ; flags: bit 0 = stored crunched
        and #SEG_COMP
        beq +
        jsr zxd_unpack_sized
        jmp seg_next
+       jsr tc_read_fast
seg_next:
        lda segidx
        clc
        adc #$07
        sta segidx
        dec segcount
        jmp seg_loop
seg_done:

        ;; The driver carries its own copy of tclib; its port values are
        ;; self-modified, so initialise them.
        jsr DRIVER_INIT

        ;; U3 plays with interrupts enabled and the kernal IRQ handler live.
        ;; That handler turns the tape motor on unless $C0 is non-zero, and a
        ;; motor pulse drops the cart out of command mode -- so this has to
        ;; stay set for the whole session.
        lda #$01
        sta $c0

        ;; Put the display back before handing over: the game's own VIC setup
        ;; at $B90D only ORs bitmap mode into $D011, so it would never clear
        ;; our blanking by itself.
        jsr tc_unblank

!ifdef U3_SELFTEST {
        jsr tc_unblank
        jmp selftest
} else {
        cli                     ; the original boot PRG never masked IRQs
        jmp ENTRY
}

boot_failed:
        lda $d011
        ora #%00010000
        sta $d011
        lda #$02
        sta $d020
-       jmp -

!ifdef U3_SELFTEST {
;;; ==================================================================
;;; Round-trip the save path through the replacement dos_transfer.
;;;
;;; The ^D -> catalog_find -> dos_transfer chain is already proven by the
;;; game reaching BOOT, so this drives dos_transfer directly with a parameter
;;; block built from the real catalog entry -- exactly as the dispatcher does
;;; -- and exercises the new code: erase, write, header, read back.
;;;
;;; ROST is 5 blocks; SOSA is 16, which is why save slots are two erase
;;; blocks rather than one.
;;; ==================================================================
CHROUT      = $ffd2
CATALOG     = $b000
CAT_ENTRIES = 94
BA48        = $ba48             ; now JMP <driver>

selftest:
        ;; First: load SOSA out of its seeded slot without saving anything,
        ;; the way ULT3 does at $500B.  If this comes back wrong the overworld
        ;; map is wrong and the party looks like it is in open ocean.
        lda #<m_seed
        ldy #>m_seed
        jsr prtstr
        lda #<n_sosa
        ldy #>n_sosa
        jsr load_only
seed_done:
        ;; Before anything else: is the cart still answering after the
        ;; launcher has run?  Uses the launcher's own tclib, which we know
        ;; works -- it just loaded four segments with it.
        lda #<m_probe0
        ldy #>m_probe0
        jsr prtstr
        lda #$00
        sta tc_addr
        lda #$40
        sta tc_addr+1
        lda #$09
        sta tc_addr+2           ; $094000: any four bytes of flash
        lda #$04
        sta tc_len
        lda #$00
        sta tc_len+1
        lda #<probe
        sta tc_dest
        lda #>probe
        sta tc_dest+1
        jsr tc_read
        ldx #$00
-       lda probe,x
        jsr prthex
        inx
        cpx #$04
        bne -
        lda #$0d
        jsr CHROUT
probe0_done:

        lda #<m_sosm
        ldy #>m_sosm
        jsr prtstr
        lda #<n_sosm
        ldy #>n_sosm
        jsr run_case

        lda #<m_rost
        ldy #>m_rost
        jsr prtstr
        lda #<n_rost
        ldy #>n_rost
        jsr run_case

case2:
        lda #<m_sosa
        ldy #>m_sosa
        jsr prtstr
        lda #<n_sosa
        ldy #>n_sosa
        jsr run_case
st_done:
-       jmp -

;;; A/Y -> a 4-byte catalog name.  Load it and print a 16-bit checksum of
;;; what arrived, so the host can compare against the disk's own bytes.
load_only:
        sta namep
        sty namep+1
        jsr find_entry
        bcc +
        lda #<m_nofind
        ldy #>m_nofind
        jmp prtstr
+       jsr setup_params
        lda #$00                ; wipe first: a no-op load must not pass
        sta seed
        jsr fill_region
        lda #$01                ; load
        sta $bb00
        jsr BA48
        ;; 16-bit sum of the region
        lda #$00
        sta sum
        sta sum+1
        jsr t_reset
-       ldy #$00
        lda (tstptr),y
        clc
        adc sum
        sta sum
        bcc +
        inc sum+1
+       jsr t_next
        bne -
        lda sum+1
        jsr prthex
        lda sum
        jsr prthex
        lda #$0d
        jmp CHROUT

;;; A/Y -> a 4-byte catalog name.  Save a pattern, wipe, load it back, report.
run_case:
        sta namep
        sty namep+1
        jsr find_entry
        bcc +
        lda #<m_nofind
        ldy #>m_nofind
        jmp prtstr
+       jsr setup_params

        lda #$5a
        sta seed
        jsr fill_region

        lda #$02                ; save
        sta $bb00
        jsr BA48
dbg_after_save:

        lda #$00                ; wipe, so a no-op load cannot pass
        sta seed
        jsr fill_region

        lda #$01                ; load
        sta $bb00
        jsr BA48
dbg_after_load:

        lda #$5a
        sta seed
        jsr check_region
        bcc +
        lda #<m_fail
        ldy #>m_fail
        jmp prtstr
+       lda #<m_ok
        ldy #>m_ok
        jmp prtstr

;;; scan the catalog for the 4-char name at namep (stored with bit 7 set).
;;; C clear = found, entp -> entry.
find_entry:
        lda #<CATALOG
        sta entp
        lda #>CATALOG
        sta entp+1
        lda #CAT_ENTRIES
        sta ecount
fe_loop:
        ldy #$03
-       lda (entp),y
        and #$7f
        sta tmp
        lda (namep),y
        cmp tmp
        bne fe_next
        dey
        bpl -
        clc
        rts
fe_next:
        lda entp
        clc
        adc #$08
        sta entp
        bcc +
        inc entp+1
+       dec ecount
        bne fe_loop
        sec
        rts

;;; copy the entry into the parameter block, as the dispatcher does
setup_params:
        ldy #$04
        lda (entp),y
        sta $bb03               ; p_block_lo
        iny
        lda (entp),y
        sta $bb04               ; p_block_hi
        iny
        lda (entp),y
        sta $bb05               ; p_length (writable flag included)
        and #$7f
        sta nblocks
        iny
        lda (entp),y
        sta $bb02               ; p_dest_page
        sta tstbase+1
        lda #$00
        sta $bb01               ; p_dest_lo
        sta tstbase
        rts

fill_region:
        jsr t_reset
-       lda tstidx
        eor tstidx+1
        eor seed
        ldy #$00
        sta (tstptr),y
        jsr t_next
        bne -
        rts

;;; C clear = every byte matches the pattern
check_region:
        jsr t_reset
-       lda tstidx
        eor tstidx+1
        eor seed
        ldy #$00
        cmp (tstptr),y
        bne cr_bad
        jsr t_next
        bne -
        clc
        rts
cr_bad: sec
        rts

t_reset:
        lda tstbase
        sta tstptr
        lda tstbase+1
        sta tstptr+1
        lda #$00
        sta tstidx
        sta tstidx+1
        rts

;; advance; Z set when tstidx reaches nblocks * 256
t_next:
        inc tstptr
        bne +
        inc tstptr+1
+       inc tstidx
        bne +
        inc tstidx+1
+       lda tstidx+1
        cmp nblocks
        bne t_more
        lda tstidx
        bne t_more
        lda #$00
        rts
t_more: lda #$01
        rts

prthex:
        pha
        lsr
        lsr
        lsr
        lsr
        jsr prtnib
        pla
        and #$0f
prtnib:
        cmp #$0a
        bcc +
        adc #$06
+       adc #$30
        jmp CHROUT

prtstr:
        sta strp
        sty strp+1
        ldy #$00
-       lda (strp),y
        beq +
        jsr CHROUT
        iny
        bne -
+       rts

;; find_entry masks the catalog byte with #$7f, so these are plain ASCII --
;; the catalog stores them with bit 7 set ($d2 $cf $d3 $d4 for "ROST")
n_sosm:  !byte $53,$4f,$53,$4d          ; "SOSM", 1 block at $4F00
n_rost:  !byte $52,$4f,$53,$54          ; "ROST"
n_sosa:  !byte $53,$4f,$53,$41          ; "SOSA"
m_seed:  !pet "sosa from seed, checksum: ",0
m_probe0:!pet "cart alive after launcher? ",0
m_sosm:  !pet "sosm  1 blk round trip: ",0
m_rost:  !pet "rost  5 blk round trip: ",0
m_sosa:  !pet "sosa 16 blk round trip: ",0
m_ok:    !pet "ok",13,0
m_fail:  !pet "fail",13,0
m_nofind:!pet "not in catalog",13,0
ecount:  !byte 0
nblocks: !byte 0
seed:    !byte 0
tmp:     !byte 0
tstbase: !byte 0,0
tstidx:  !byte 0,0
sum:     !byte 0,0
probe:   !byte 0,0,0,0
}

segcount:   !byte 0
segidx:     !byte 0

DESC_SIZE = 64
descbuf:    !fill DESC_SIZE, 0
}
body_end:

BODY_PAGES = (descbuf - RELOC + 255) >> 8

;; $C500-$C9FF is the free window the launcher must fit in.  The self-test
;; build is bigger, but it never runs the game, so UPDT's area at $CA00-$CCFF
;; is fair game there.
!ifdef U3_SELFTEST {
BODY_LIMIT = $cd00
} else {
BODY_LIMIT = $ca00
}
!if descbuf + DESC_SIZE > BODY_LIMIT {
        !error "boot body reaches ", descbuf + DESC_SIZE, ", past ", BODY_LIMIT
}
