;;; init_u3.s -- Ultima 3 machine setup, run by the menu after loading.
;;;
;;; Mirrors what the original `ultima` boot PRG does at $0810-$0824 before it
;;; paints its title screen and loads the three chunks.  Everything else is
;;; done by the game itself.
;;;
;;; Loaded as an ordinary segment, with the boot descriptor's entry address
;;; pointing here.  $0200 is the BASIC input buffer -- free once past BASIC,
;;; and clear of every segment either game loads.

        * = $0200

        sei
        lda #$2f
        sta $00

        ;; The original clears the screen through CHROUT while the kernal is
        ;; still banked in the way BASIC left it, then switches $01.
        lda #$93                ; clear screen
        jsr $ffd2

        lda #$00                ; suppress kernal messages, as the original's
        jsr $ff90               ; chunk loader does before each load

        lda #$36                ; BASIC out, KERNAL in, I/O in; motor bit set
        sta $01

        ;; The original boot PRG blacks both of these at $081D-$0824.  Leaving
        ;; them alone is what made the border stay BASIC light-blue.
        lda #$00
        sta $d020
        sta $d021

;;; The boot PRG's credits (build.py loads its painter and text at CREDITS,
;;; ending in an RTS): shown on a launch that is not Journey onward, as the
;;; original showed them while it loaded, and held about four seconds --
;;; the loads are done, so they would flash by -- or until a key.  With
;;; interrupts off, the keyboard is read straight off the CIA; $DC00 goes
;;; back to $7F, as the KERNAL's scan leaves it (U4 reads the joystick there).
        lda PT_OPTS
        and #$04                ; patches.JOURNEY: straight to the saved game
        bne cr_done
        jsr CREDITS
        ldy #200                ; frames: 4 s at 50 Hz, 3.3 s at 60
cr_frame:
        lda $d012               ; line $FB comes once a frame, PAL and NTSC
        cmp #$fb
        bne cr_frame
cr_line:
        lda $d012
        cmp #$fb
        beq cr_line
        lda #$00                ; any key?
        sta $dc00
        lda $dc01
        ldx #$7f
        stx $dc00
        cmp #$ff
        bne cr_done
        dey
        bne cr_frame
cr_done:

        ;; consume a pending keypress, as the original does at $0910
        ldx $c6
        beq +
        lda $0276,x
        dec $c6
+
        jsr $bc03               ; the driver's "jmp tc_init" entry

        ;; U3 plays with interrupts enabled and the kernal IRQ handler live.
        ;; That handler starts the tape motor unless $C0 is non-zero, and a
        ;; motor pulse drops the cart out of command mode.  tclib re-arms this
        ;; on every exit; set it here too before the first CLI.
        lda #$01
        sta $c0

        cli                     ; the original boot PRG never masked IRQs
        jmp $8220               ; EXOD's entry
