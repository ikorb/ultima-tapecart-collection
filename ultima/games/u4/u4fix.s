;;; u4fix.s -- helper code for the bug fixes taken from Ultima IV Remastered
;;; (ultima/games/u4/remastered.py), in the dead tail of chunk $5B, game main.
;;;
;;; $86EF-$87FF of chunk $5B is residue -- a stale copy of the end-of-turn
;;; code and filler; the last live routine ends at $86EE -- and the
;;; Remastered kit drops it.  Only chunks $44 and $51 load over it, and both
;;; reload $5B before the game goes on (remastered.py checks the kernel's
;;; chunk table for that), so this is present exactly when the hooks into it
;;; are.  Each routine is the kit's (src/trainer/trainerroutines.s), bar
;;; fx_enter, fx_gate_shrine and fx_top (after Sean Gugler's fixes to the kit).

        * = $86ef

;;; The stack leaks: paths that leave a return address behind, and nothing
;;; ever resets the stack, so it wraps -- and once the ROM IRQ entry's BRK
;;; test reads a stray bit 4 off page 2, an interrupt ends at READY.
fx_attacked:                    ; $670C JMP $4731: attacked by a monster
        pla
        pla
        jmp $4731
fx_trolls:                      ; $62E7 JMP $6EA3: bridge trolls
        pla
        pla
        jmp $6ea3
fx_gate_shrine:                 ; $8698 JMP $5183: a moongate into a shrine,
        pla                     ; from a step's JSR ($448D and its three
        pla                     ; siblings JMP $8676)
        jmp $5183

;;; The command level's stack, reset: every command is entered and left by
;;; JMP from the main loop, so the stack is the same at each: $BE, measured
;;; in VICE at the main loop's key read, cmd_done and combat's
;;; (tools/vice/u4_stack_check.py; the boot set $C0).
;;; The party dead ($83E0 JMP $621E) comes from one to four calls deep -- a
;;; sinking ship through a whirlpool, a twister or a pirate's cannon, or the
;;; turn's end -- and a moongate jump ($86CA JMP $621E) from one.
CMD_SP = $be
fx_top:
        ldx #CMD_SP
        txs
        jmp $621e

;;; Bridge trolls ($62B6 LDA $48 / CMP #$17: the tile under the party a
;;; bridge?) not while flying: Z clear then, so the BNE after goes on to the
;;; flying test at $62EA, which ends the turn's tile effects.
fx_bridge:
        lda $74
        bmi +
        lda $48
        cmp #$17
+       rts

;;; Board ($47B0 JSR $480B): tiles $10-$13 under the party are ships in
;;; Britannia -- and ladders in a dungeon, where B boarded a frigate.
fx_board:
        ldx $1a                 ; not in Britannia: "WHAT?"
        beq +
        pla
        pla
        jmp $4112
+       jmp $480b

;;; Enter ($4FDA): not while flying ($74).  The kit tests the transport,
;;; which kept a landed balloon out as well; the changelog says flying.
fx_enter:
        lda $1a
        ora $74
        beq +
        jmp $4112
+       jmp $4fe1
;;; "EXIT?" at a town's edge (the kit's ask_exit_*, src/trainer/
;;; trainerroutines.s): the four steps in town mode -- $42E1 DEC $11 north,
;;; $43EF INC $11 south, $44B9 DEC $10 west, $4591 INC $10 east, each then
;;; LDA of the same -- become a JSR here.  Only a step off the 32 x 32 map
;;; asks; anything but Y drops this and the step's return address, so the
;;; move is off (a turn still passes).  In capitals, as the game's own
;;; messages are ("NOT HERE!", "WHAT?"); the kit prints "Exit? ".
fx_exit_n:
        lda $11
        bne +
        jsr fx_ask
+       dec $11
        lda $11
        rts
fx_exit_s:
        lda $11
        cmp #$1f
        bne +
        jsr fx_ask
+       inc $11
        lda $11
        rts
fx_exit_w:
        lda $10
        bne +
        jsr fx_ask
+       dec $10
        lda $10
        rts
fx_exit_e:
        lda $10
        cmp #$1f
        bne +
        jsr fx_ask
+       inc $10
        lda $10
        rts
fx_ask: jsr $0821               ; the game's print, the text inline
        !byte $c5, $d8, $c9, $d4, $bf, $a0, 0       ; "EXIT? "
        jsr $8398               ; a key, echoed: 0 if none
        beq fx_no
        cmp #$d9                ; Y
        bne fx_no
        rts
fx_no:  pla
        pla
        pla
        pla
        rts

;;; ---- the launcher's cheats: option patches (build.py) hook these ------
;;; Avoid combat (the kit's trainer_avoid & co): a monster's attack asks
;;; "AVOID?", and Y leaves the fight out -- on the surface, at a bridge's
;;; trolls, in a dungeon.  (Our stack fix fx_attacked is the path the fight
;;; takes; this one returns before it.)
fx_avoid:                       ; $66FB JSR $8357: after "ATTACKED BY", the name
        jsr $8357
        jsr fx_ask_avoid
        bcc +
fx_plapla:
        pla
        pla
+       rts
fx_avoid_trolls:                ; $62D7 LDA #$A4 / STA $40: the trolls
        jsr fx_ask_avoid
        bcc +
        pla
        pla
+       lda #$a4
        sta $40
        rts
fx_avoid_dng:                   ; $6D15 ASL / ADC #$8C of ASL / ASL / ADC / STA $40
        pha
        jsr $0821               ; the surface's message, which a dungeon has not
        !byte $8d, $c1, $d4, $d4, $c1, $c3, $cb, $c5, $c4, $a0, $c2, $d9, $8d, 0
        pla
        asl
        adc #$8c
        pha
        jsr $835c               ; the creature's name
        jsr fx_ask_avoid
        pla
        bcs fx_plapla
        rts
fx_ask_avoid:                   ; C set: Y
        jsr $0821
        !byte $c1, $d6, $cf, $c9, $c4, $bf, $a0, 0  ; "AVOID? "
        jsr $8398
        beq +
        cmp #$d9                ; Y
        bne +
        sec
        rts
+       clc
        rts

;;; Balloon control (the kit's trainer_balloon_*): the four direction
;;; handlers' "DRIFT ONLY!" (JMP $41F7 while the transport is the balloon)
;;; steer it while it flies; landed, still "DRIFT ONLY!".  With subs $0B15
;;; an RTS (the wind's drift), a signature patch of its own.
fx_balloon_n:
        lda $1d
        beq fx_drift
        jsr $8303               ; "NORTH"
        jsr $080f
        jmp $621e
fx_balloon_s:
        lda $1d
        beq fx_drift
        jsr $830e
        jsr $080c
        jmp $621e
fx_balloon_w:
        lda $1d
        beq fx_drift
        jsr $8323
        jsr $0809
        jmp $621e
fx_balloon_e:
        lda $1d
        beq fx_drift
        jsr $8319
        jsr $0806
        jmp $621e
fx_drift:
        jmp $41f7

fx_end:
!if fx_end > $8800 {
        !error "the fixes run past $5B's tail: ", fx_end
}
