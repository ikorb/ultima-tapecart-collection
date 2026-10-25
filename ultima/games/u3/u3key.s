;;; u3key.s -- Ultima III: keys typed ahead are kept, and joystick 2 works.
;;;
;;; ULT3's command loops (the surface, combat, the dungeon, "which player?",
;;; two more) and SUBS' key wait ($4E9C) poll the DOS module's $B80C ($B952:
;;; the LAST key queued, $FF if none, nothing removed) and then empty the
;;; queue ($B80F): of keys typed ahead only the last one ever counted -- why
;;; the game feels unresponsive.  Their polls now come here, and their
;;; flushes are a BIT (u3 build.py): the FIRST key, the rest moved up, as
;;; Ultima IV's queue fix (ultima/games/u4/u4key.s) does it.  With none, joystick 2
;;; ($DC00, at most every 5 jiffies): up, down, left, right as the direction
;;; keys @ / : ;, fire as
;;; E on Sosaria, T in a town, A in combat and Ambrosia ($62: 0, positive,
;;; negative).  Returns as $B952 does: the key with bit 7 set, or $FF; X
;;; kept, and the interrupt flag as it was.  (ULT3's own flushes, which it
;;; does before its prompts, stay.)  In the driver's decoder segment.

kb_take:
        php
        sei
        stx kb_x
        ldx $c6
        beq kb_joy
        lda $0277               ; the first key, and the rest moved up
        pha
        ldx #0
-       lda $0278,x
        sta $0277,x
        inx
        cpx $c6
        bne -
        dec $c6
        pla
        ora #$80
        bne kb_out              ; always
kb_joy: lda $a2
        sec
        sbc kb_last
        cmp #5
        bcc kb_none
        lda $a2
        sta kb_last
        lda $dc00
        lsr
        bcc kb_up
        lsr
        bcc kb_down
        lsr
        bcc kb_left
        lsr
        bcc kb_right
        lsr
        bcs kb_none
        lda $62                 ; fire: by where the party is
        bmi kb_fight
        beq kb_enter
        lda #$d4                ; T
        bne kb_out
kb_enter:
        lda #$c5                ; E
        bne kb_out
kb_fight:
        lda #$c1                ; A
        bne kb_out
kb_up:  lda #$c0                ; @
        bne kb_out
kb_down:
        lda #$af                ; /
        bne kb_out
kb_left:
        lda #$ba                ; :
        bne kb_out
kb_right:
        lda #$bb                ; ;
        bne kb_out
kb_none:
        lda #$ff
kb_out: ldx kb_x
        plp
        cmp #$00
        rts
kb_x:    !byte 0
kb_last: !byte 0
