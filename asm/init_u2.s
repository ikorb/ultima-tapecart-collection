;;; init_u2.s -- Ultima 2 machine setup, run by the menu after loading.
;;;
;;; Replaces the `ULT` boot PRG ($02DA) and the first 37 bytes of `INTRO`.
;;; ULT only blanked the screen and KERNAL-loaded INTRO to $C000; INTRO's
;;; $C000-$C024 only KERNAL-loads SUBS to $4000.  Both files are segments in
;;; flash now, so all that is left is the machine setup and a jump to $C025,
;;; which is where INTRO's own work starts.
;;;
;;; $01 = $36 is the important part.  The original boots at $37, with BASIC
;;; ROM over $A000-$BFFF, and only reaches $36 when the map cache first runs
;;; ($6809).  The driver lives at $B100, so it has to be RAM from the start.
;;; The game itself never puts $01 back to $37 -- there are exactly four
;;; writes to it in the whole game and all four are $36.

        * = $0200

        sei
        lda #$2f
        sta $00
        lda #$36                ; BASIC out (the driver is at $B100),
        sta $01                 ; KERNAL in, I/O in; motor bit set

        lda #$00
        sta $d011               ; blank while loading, as ULT does at $02DC

        lda #$00                ; suppress kernal messages, as INTRO does
        jsr $ff90
        lda #$93                ; clear screen, as INTRO does
        jsr $ffd2

        lda #$00                ; drop the keypress that chose this game
        sta $c6

        ;; Shift+C= would flip the KERNAL's character set ($D018) until the
        ;; game's raster split put it back, a visible glitch; MODE bit 7
        ;; locks it.  Nothing in U2 calls CINT or
        ;; writes $0291 (every file scanned), so this holds all game long.
        lda #$80
        sta $0291

        ;; The kernal IRQ handler starts the tape motor unless $C0 is
        ;; non-zero, and a motor pulse drops the cart out of command mode.
        ;; tclib re-arms this on every exit; set it before the first CLI.
        lda #$01
        sta $c0

        jsr $b100               ; the driver's "jmp tc_init" entry

        cli                     ; INTRO runs with interrupts enabled
        jmp $c025               ; INTRO, just past its kernal load of SUBS
