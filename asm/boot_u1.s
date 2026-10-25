;;; boot_u1.s -- Ultima 1 launcher.
;;;
;;; Loaded from disk for now so the build/test loop stays fast; it becomes the
;;; menu's per-game launcher later, at which point the tapecart's own initial
;;; loader fastloads it instead.
;;;
;;; It replaces HELLO entirely.  HELLO's job was to relocate the disk driver,
;;; prompt for a drive type, open the command channel and load LO -- all of
;;; which either has no meaning without a drive or is done here from flash.
;;; What remains of HELLO is the machine setup at $8000-$809D, reproduced in
;;; boot_init below, and the final JMP $0C00 into LO.
;;;
;;; The body relocates itself to $C800 because it loads LO over $0800-$15DA,
;;; which is where a BASIC-loaded program lives.  $C800-$CDFF is free at boot;
;;; the map file MA claims $C700-$CAFF but not until the game asks for it, by
;;; which point this code is dead.

ptr  = $02              ; zero page scratch for the self test
ptr2 = $04

; $9000 is inside the overlay slot ($8C9E-$B407), which nothing occupies until
; the game asks for an overlay -- by then this code is dead.  It used to sit at
; $C600, above the driver image, until the decruncher moved into $CB00 and the
; launcher grew into it; a launcher that loads a segment over itself fails in a
; way that looks like a bad segment rather than a bad address.
RELOC = $9000
!source "u1_init.s"             ; U1_TC_INIT, from ultima/games/u1/build.py
DESC_PAGE = $01                 ; descriptor lives at flash $000100

        * = $0801
        ;; 10 SYS 2061
        !byte $0b,$08,$0a,$00,$9e,$32,$30,$36,$31,$00,$00,$00

        ;; Move the body up out of the way of LO, then enter it.  The page
        ;; count is derived from the code's actual size so the self-test build
        ;; (which is larger) relocates correctly too.  descbuf is page aligned
        ;; and starts zeroed, so there is no need to copy it.
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
!source "tclib.s"
!source "zxdecr.s"

boot:
        sei
        lda #$2f
        sta $00
        lda #$36                ; BASIC out, KERNAL in, I/O in -- U1's steady
        sta $01                 ; state, and motor bit already set

        jsr tc_init

        ;; Blank the display before any fast read: clearing DEN only takes
        ;; effect from the next frame, so tc_blank waits one out.  This also
        ;; hides the BASIC screen while we load.
        jsr tc_blank
        jsr tc_cmdmode
        bcc +
        jmp boot_failed         ; too far for a branch
+

        ;; ---- fetch the game descriptor -----------------------------
        lda #$00
        sta tc_addr
        lda #DESC_PAGE
        sta tc_addr+1
        lda #$00
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

        ;; ---- scatter-load every segment ----------------------------
        lda descbuf+2
        sta segcount
        lda #$00
        sta segidx
seg_loop:
        lda segcount
        beq seg_done
        ldx segidx
        lda #$00
        sta tc_addr             ; segments are page aligned
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

;;; ==================================================================
;;; What HELLO did at $8000-$809D, minus the drive handling.
;;; ==================================================================
boot_init:
        lda #$7f                ; mask both CIAs; U1 runs with interrupts off
        sta $dc0d               ; for its entire life
        sta $dd0d
        lda $dc0d
        lda $dd0d

        lda #$18                ; CHROUT -> CLC/RTS, swallowing kernal messages
        sta $1ffe
        lda #$60
        sta $1fff
        lda #$fe
        sta $0326
        lda #$1f
        sta $0327

        lda #$00                ; NMI -> a bare RTI, disabling RESTORE
        sta $0318
        lda #$ce
        sta $0319
        lda #$40
        sta $ce00

        lda #$00
        sta $d020
        sta $d021

        ldx #$00                ; colour RAM to white
        lda #$01
-       sta $d800,x
        sta $d900,x
        sta $da00,x
        sta $db00,x
        inx
        bne -

        lda #$83                ; vectors HELLO installs before handing over
        sta $0302
        lda #$a4
        sta $0303
        lda #$48
        sta $028f
        lda #$eb
        sta $0290

        lda #$02                ; drive type byte: "no fastloader" in the
        sta $b000               ; original's terms.  Nothing reads it now.

        lda #$17                ; HELLO's screen setup; LO overrides it
        sta $d018
        lda #$08
        sta $d016
        lda #$17
        sta $d011

        ;; the driver carries its own copy of tclib, whose port values are
        ;; self-modified -- initialise them.  Its tc_init is the init stub's
        ;; (TC_INIT_ELSEWHERE; the stub is loaded at $C700 with the rest).
        jsr U1_TC_INIT

!ifdef U1_SELFTEST {
        jmp selftest
} else {
        lda descbuf+1
        sta boot_entry+2
        lda descbuf+0
        sta boot_entry+1
boot_entry:
        jmp $ffff               ; patched to the descriptor's entry address
}

boot_failed:
        ;; no cart, or it would not enter command mode: show a red border
        lda $d011
        ora #%00010000
        sta $d011
        lda #$02
        sta $d020
-       jmp -

!ifdef U1_SELFTEST {
;;; ==================================================================
;;; Drive the driver's own entry points through a save/load round trip.
;;;   $C483 save by save-index (0=DD 1=RO 2=P0 ...)
;;;   $C486 load by file index (16=DD 17=RO 18=P0 ...)
;;; ==================================================================
CHROUT = $ffd2
RO_ADDR = $b000
RO_LEN  = 64
P0_ADDR = $81e2
P0_LEN  = 458

selftest:
        jsr tc_unblank          ; put the display back so we can see results
        ;; boot_init pointed CHROUT at HELLO's CLC/RTS stub to swallow kernal
        ;; messages, which would swallow ours too.  Put it back.
        lda #$ca
        sta $0326
        lda #$f1
        sta $0327

        ;; ---- how long does a real overlay load take? --------------
        ;; index 0 = TC, ~7.5 KB of charset and tile data, the biggest single
        ;; unit the game loads.  Timed through the game's own entry point.
        lda #<m_load
        ldy #>m_load
        jsr prtstr
        jsr timer_start
        ldx #$00
        jsr $c486
        jsr timer_stop
        lda thi+1
        jsr prthex
        lda thi
        jsr prthex
        lda tlo+1
        jsr prthex
        lda tlo
        jsr prthex
        lda #$0d
        jsr CHROUT

        ;; an unwritten slot must report "no save"
        lda #<m_empty
        ldy #>m_empty
        jsr prtstr
        ldx #$13                ; file index 19 = P1, never written
        jsr $c486
        bcs +
        jsr say_fail
        jmp st_ro
+       jsr say_ok

        ;; ---- RO: 64 bytes at $B000 (RAM under BASIC) ----------------
st_ro:
        lda #<m_ro
        ldy #>m_ro
        jsr prtstr
        ldx #$00
-       txa
        eor #$3c
        sta RO_ADDR,x
        inx
        cpx #RO_LEN
        bne -
        ldx #$01                ; save-index 1 = RO
        jsr $c483
        ldx #$00                ; wipe, so a no-op load cannot pass
        lda #$00
-       sta RO_ADDR,x
        inx
        cpx #RO_LEN
        bne -
        ldx #$11                ; file index 17 = RO
        jsr $c486
        bcc +
        jsr say_fail
        jmp st_p0
+       ldx #$00
-       txa
        eor #$3c
        cmp RO_ADDR,x
        bne ro_bad
        inx
        cpx #RO_LEN
        bne -
        jsr say_ok
        jmp st_p0
ro_bad: jsr say_fail

        ;; ---- P0: 458 bytes at $81E2 ---------------------------------
st_p0:
        lda #<m_p0
        ldy #>m_p0
        jsr prtstr
        jsr fill_p0
        ldx #$02                ; save-index 2 = P0
        jsr $c483
        lda #<P0_ADDR
        sta ptr
        lda #>P0_ADDR
        sta ptr+1
        jsr wipe_p0
        ldx #$12                ; file index 18 = P0
        jsr $c486
        bcc +
        jsr say_fail
        jmp st_done
+       jsr check_p0
st_done:
-       jmp -

;; fill $81E2.. with (i ^ $c3), 458 bytes
fill_p0:
        jsr p0_reset
-       ldy #$00
        lda cnt
        eor cnt+1
        eor #$c3
        sta (ptr),y
        jsr p0_next
        bne -
        rts

wipe_p0:
        jsr p0_reset
-       ldy #$00
        lda #$00
        sta (ptr),y
        jsr p0_next
        bne -
        rts

check_p0:
        jsr p0_reset
-       ldy #$00
        lda cnt
        eor cnt+1
        eor #$c3
        cmp (ptr),y
        bne +
        jsr p0_next
        bne -
        jmp say_ok
+       jmp say_fail

p0_reset:
        lda #<P0_ADDR
        sta ptr
        lda #>P0_ADDR
        sta ptr+1
        lda #$00
        sta cnt
        sta cnt+1
        rts

;; advance ptr and cnt; returns Z set when cnt reaches P0_LEN
p0_next:
        inc ptr
        bne +
        inc ptr+1
+       inc cnt
        bne +
        inc cnt+1
+       lda cnt
        cmp #<P0_LEN
        bne p0_more
        lda cnt+1
        cmp #>P0_LEN
        bne p0_more
        lda #$00                ; Z set: done
        rts
p0_more:
        lda #$01                ; Z clear: keep going
        rts

say_ok:
        lda #<m_ok
        ldy #>m_ok
        jmp prtstr
say_fail:
        lda #<m_fail
        ldy #>m_fail
        jmp prtstr

timer_start:
        lda #$00
        sta $dd0e
        sta $dd0f
        lda #$ff
        sta $dd04
        sta $dd05
        sta $dd06
        sta $dd07
        lda #%01000001
        sta $dd0f
        lda #%00000001
        sta $dd0e
        rts

timer_stop:
        lda #$00
        sta $dd0e
        sta $dd0f
        sec
        lda #$ff
        sbc $dd04
        sta tlo
        lda #$ff
        sbc $dd05
        sta tlo+1
        sec
        lda #$ff
        sbc $dd06
        sta thi
        lda #$ff
        sbc $dd07
        sta thi+1
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
        sta ptr2
        sty ptr2+1
        ldy #$00
-       lda (ptr2),y
        beq +
        jsr CHROUT
        iny
        bne -
+       rts

m_empty: !pet "unwritten slot reads empty: ",0
m_ro:    !pet "ro  64b round trip: ",0
m_p0:    !pet "p0 458b round trip: ",0
m_ok:    !pet "ok",13,0
m_fail:  !pet "fail",13,0
m_load:  !pet "tc 7.5k load, cia2 cycles: ",0
cnt:     !byte 0,0
tlo:     !byte 0,0
thi:     !byte 0,0
}

segcount:   !byte 0
segidx:     !byte 0

DESC_SIZE = 64                  ; 3 header bytes + up to 8 segments of 7
descbuf:    !fill DESC_SIZE, 0
}
body_end:

;;; everything up to descbuf has to be relocated; descbuf itself is scratch
BODY_PAGES = (descbuf - RELOC + 255) >> 8

!if descbuf + DESC_SIZE > $ce00 {
        !error "boot body reaches ", descbuf + DESC_SIZE, ", overrunning the NMI stub at $CE00"
}
