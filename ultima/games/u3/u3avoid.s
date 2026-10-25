;;; u3avoid.s -- "AVOID?" when a fight starts, the launcher's A for U3.
;;;
;;; Ultima IV Remastered's cheat (U4's AVOID), for Ultima III: a fight the
;;; party did not start asks first, and Y does not have it.  ULT3 starts one
;;; in two places (found by the CON@ load at $7E9C and its callers):
;;;   - a monster that moves onto the party ($78AF, the monsters' turn, X =
;;;     $50 the monster: $78D5 JMP $5249, which is Attack's own way in -- on
;;;     the surface, in towns and in Ambrosia).  Avoided, the monsters' turn
;;;     goes on with the next one ($78B3); the monster stays where it was.
;;;   - a dungeon's random encounter ($8DF4: on an empty square a roll
;;;     against the level, BMI $8E01).  $8E01's LDA $23 / CLC is a JSR here,
;;;     before anything is changed; avoided, the turn goes on as without one
;;;     ($8B2B, the roll's other way).
;;; The hooks are always in (build.py AVOID_HOOKS); without the option, the
;;; original's way at once.  The question is Gold's EXIT?'s ($93DA): SUBS'
;;; print and key wait.  In the driver's decoder segment.

AV_OPT  = $40                   ; patches.AVOID, in the options byte

;;; $78D5's JMP $5249, X = the monster
av_monster:
        txa
        pha
        jsr av_ask
        pla
        tax
        bcs +
        jmp $5249               ; the fight
+       jmp $78b3               ; the next monster

;;; $8E01's LDA $23 / CLC (then ADC #$02: what the encounter is)
av_dungeon:
        jsr av_ask
        bcc +
        pla                     ; not coming back
        pla
        jmp $8b2b
+       lda $23
        clc
        rts

;;; C set: avoided
av_ask: lda pt_opts
        and #AV_OPT
        beq +                   ; the option off: the fight, C clear
        jsr $46c3
        !byte $c1, $d6, $cf, $c9, $c4, $bf, $ff, 0      ; "AVOID?"
        jsr $4711
        cmp #$d9                ; Y
        beq ++
+       clc
        rts
++      sec
        rts
