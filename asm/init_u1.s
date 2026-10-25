;;; init_u1.s -- Ultima 1 machine setup, run by the menu after loading.
;;;
;;; This is everything HELLO did at $8000-$809D apart from the drive
;;; handling, which has no meaning without a drive.  It is loaded as an
;;; ordinary segment and the boot descriptor's entry address points here, so
;;; the menu itself stays completely game-agnostic.
;;;
;;; It runs at $C700, where TW and CA put MA, the settlements' glyph set,
;;; later: nothing loads there before LO runs, which is all it needs.  (It
;;; was at $0200, the BASIC input buffer, until tc_init moved here from the
;;; driver -- TC_INIT_ELSEWHERE -- and made it too long for page 2, whose
;;; KERNAL variables from $0281 on it would have overwritten.)

        * = $c700

        sei
        lda #$2f
        sta $00
        lda #$36                ; BASIC out, KERNAL in, I/O in; motor bit set

        sta $01

        lda #$7f                ; mask both CIAs -- U1 runs with interrupts
        sta $dc0d               ; off for its entire life
        sta $dd0d
        lda $dc0d
        lda $dd0d

        ;; CIA 2's clocks, which the game leaves alone (its interrupts are
        ;; masked above): timer A runs out once a frame on a PAL machine
        ;; ($02A6 = 1), every 1/50 s on NTSC, and timer B counts it down from
        ;; $FFFF, the outdoor animation's ticks (u1view.s); the time of day
        ;; counts the mains' 50 Hz on PAL, 60 on NTSC, the outdoor idle turn's
        ;; seconds (u1idle.s)
        lda #<(19656 - 1)       ; PAL: a frame's cycles
        ldy #>(19656 - 1)
        ldx $02a6
        bne +
        lda #<(20455 - 1)       ; NTSC: 1/50 s
        ldy #>(20455 - 1)
+       sta $dd04
        sty $dd05
        lda #$ff
        sta $dd06
        sta $dd07
        lda #$51                ; B: started, loaded, counts A's underflows
        sta $dd0f               ; (bit 7 clear: the time of day, not its alarm)
        lda #$11                ; A: started, loaded, continuous, phi2
        cpx #$00
        beq +
        ora #$80                ; the time of day's 50 Hz
+       sta $dd0e

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

        lda #$02                ; drive type byte, in the original's terms
        sta $b000

        lda #$17                ; HELLO's screen setup; LO overrides it
        sta $d018
        lda #$08
        sta $d016
        lda #$17
        sta $d011

        jsr tc_init             ; the driver's port values (asm/tcinit.s, below)
        jmp $0c00               ; LO's entry, as HELLO's final JMP

!source "u1_tcinit.s"           ; the driver's symbols (build.py, tcsyms.py)
!source "tcinit.s"
