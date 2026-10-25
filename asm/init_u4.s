;;; init_u4.s -- Ultima 4 machine setup, run by the menu after loading.
;;;
;;; Mirrors what the original `ULTIMA` boot PRG does at $0810-$0838 before it
;;; paints its title screen, copies the resident kernel to $A100-$A6FF and
;;; jumps to $A429.  We load the kernel straight out of flash as a segment
;;; instead, so only the machine setup is left.
;;;
;;; The title screen with the credits is the boot PRG's own painter, loaded
;;; at its address (build.py): chunk $4F loads over it afterwards, as it did.
;;;
;;; Loaded as an ordinary segment.  $0200 is the BASIC input buffer -- free
;;; once past BASIC, and clear of every page U4's loader writes.  It must
;;; stay shorter than $86 bytes so it does not run into $0286, the text
;;; colour, which this code itself sets.

        * = $0200

        sei
        lda #$2f
        sta $00
        lda #$36                ; BASIC out, KERNAL in, I/O in; motor bit set
        sta $01
        ldx #$c0                ; the game runs with the stack moved down
        txs

        lda #$00
        sta $d020
        sta $d021
        ldx #$17                ; silence the SID
-       sta $d400,x
        dex
        bpl -
        lda #$0f
        sta $d418
        sta $a126               ; ...and the kernel's own volume mirror

        lda #$0e                ; light blue text, as the boot PRG sets
        sta $0286
        lda #$93                ; clear screen
        jsr $ffd2

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

        lda #$00                ; drop the keypress that chose this game
        sta $c6

        ;; U4 plays with interrupts enabled and the kernal IRQ handler live
        ;; behind its trampoline.  That handler starts the tape motor unless
        ;; $C0 is non-zero, and a motor pulse drops the cart out of command
        ;; mode.  tclib re-arms this on every exit; set it here too, before
        ;; $A429's BANKOUT does its CLI.
        lda #$01
        sta $c0

        jsr U4_INIT             ; the driver's u4_init (build.py passes it):
                                ; tc_init, with the RAM under I/O banked in
        jmp $a429               ; the kernel's BOOT: bank out, load the
                                ; resident set, run chunk $50
