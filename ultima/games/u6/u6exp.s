;;; u6exp.s -- the conversations' exp() for the shrines' level check.
;;;
;;; The Talk overlay T4 (1A/1B track 4 sectors 9-20, at $C000) evaluates
;;; the conversation scripts one byte at a time: variables, stack slots and
;;; comparisons are all 8-bit.  Its exp(npc, delta) -- opcode E0, $C650 --
;;; adds delta to a character's 16-bit experience ($585B + 2 x slot) and
;;; returns its LOW BYTE.  The eight shrines grant a level when that is at
;;; least a table entry, `00 64 C8 90 20 40 80 00`: the low bytes of 0,
;;; 100, 200, 400, 800, 1600, 3200, 6400.  So the C64's shrines granted
;;; levels on the low byte alone, too early or too late.
;;;
;;; This one returns experience / 50, at most 199, and build.py makes the
;;; shrines' tables 0, 2, 4 ... 128 -- every threshold is a multiple of 50,
;;; so "exp / 50 >= t / 50" is exactly "exp >= t".  Same entry, same
;;; arguments and exits as the original (the stat slot through $02F0, the
;;; result in the stack slot, INC $9D / DEC $F2), in its 71 bytes.  exp()
;;; is used by the shrines (T191-T198, 3A) and by T001's debug editor only,
;;; whose "Exp =" now shows exp / 50 and whose adds are no longer capped at
;;; 9999 (combat's award caps it again).  $D52A is T4's own temporary.

        * = $c650
        lda $d553,x             ; the character
        jsr $ca99               ; $EB (the one talked to) -> Y = the actor
        jsr $02f0               ; Y = its stat slot, C set if a named one
        bcc done                ; not: A as it is (the original's was
                                ; garbage too)
        tya
        asl
        tay
        lda $585b,y             ; experience += delta
        clc
        adc $d554,x
        sta $585b,y
        pha
        lda $585c,y
        adc #0
        sta $585c,y
        sta $d52a               ; the high byte, counted down
        pla
        ldx #$ff                ; X = how many 50s
loop:   inx
        cpx #199
        bcs out                 ; 199: 9950 and more
        sec
        sbc #50
        bcs loop
        ldy $d52a
        beq out                 ; a borrow out of the high byte: done
        dec $d52a
        bcc loop                ; (C is clear after the borrow)
out:    txa
        ldx $f2
done:   sta $d553,x
        inc $9d
        dec $f2
        rts
end:
!if end > $c697 {
        !error "exp() is longer than the original's 71 bytes"
}
