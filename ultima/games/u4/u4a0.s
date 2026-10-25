;;; u4a0.s -- more of Ultima IV Remastered's features, resident at $A006.
;;;
;;; $A006-$A0FF: after the kernel's parameter block, where the kit keeps its
;;; loader's tail and this very code.  Nothing loads there, no unit points
;;; into it (docs/reversing-notes/u4-remastered.md), and a memmap
;;; of play saw no access.  A boot segment (build.py), there all game --
;;; which the SUBS-side hook needs.  The routines are the kit's
;;; (src/trainer/trainerroutines.s); hooks in remastered.py code_fixes.

object_tile   = $ac60
player_tile   = $ada0
monster_sleep = $ad70
party_size    = $1f
currplayer    = $54
j_primm       = $0821
j_console_out = $0824
j_update_view = $084b
j_clearkbd    = $a112
cmd_unknown   = $4112
cmd_done      = $621e
combat_check_sleep = $714e
check_awake   = $7daf
fx_horse      = $ff00           ; u4ff.s's (build.py asserts it)

        * = $a006

;;; ---- the active character in combat (1-8; 0: the party) ---------------
;;; Combat's start ($7097 JSR $A112) clears it; each round ($709D LDA #1 /
;;; STA $54) starts with it if it is set and awake, else the party; each
;;; player's turn ($70C2 JSR $084B) is skipped unless it is theirs; and a
;;; digit, which combat's commands did not know ($7131 JMP $4112), picks one.
ac_start:
        lda #$00
        sta ac_char
        jmp j_clearkbd

ac_turn:
        lda ac_char
        bne ac_sel
ac_none:
        lda #$00
        sta ac_char
        lda #$01
        sta currplayer
        rts
ac_sel: sta currplayer
        jsr ac_awake
        bne ac_none
        lda currplayer
        rts

ac_check:
        lda ac_char
        beq ac_play
        cmp currplayer
        beq ac_play
        jsr ac_awake
        beq ac_skip
        lda #$00
        sta ac_char
        beq ac_play             ; always
ac_skip:
        pla
        pla
        jmp combat_check_sleep
ac_play:
        jmp j_update_view

ac_key:
        cmp #$b0                ; '0'-'8'
        bcc ac_unknown
        cmp #$b9
        bcs ac_unknown
        and #$0f
        beq ac_party
        cmp party_size
        bcc +
        bne ac_party
+       pha
        jsr check_awake
        bne ac_asleep
        pla
        sta ac_char
        ora #$b0
        jsr j_console_out
        jsr j_primm
        !byte $a0, $c1, $c3, $d4, $c9, $d6, $c5, $8d, 0     ; " ACTIVE"
        pha
ac_asleep:
        pla
        jmp cmd_done
ac_party:
        lda #$00
        sta ac_char
        jsr j_primm
        !byte $d0, $c1, $d2, $d4, $d9, $a0, $cd, $cf, $c4, $c5, $8d, 0  ; "PARTY MODE"
        jmp cmd_done
ac_unknown:
        jmp cmd_unknown

;;; A = a player: 0 if that one is awake and there (Z), else not
ac_awake:
        ldx currplayer
        stx ac_keep
        sta currplayer
        jsr check_awake
        sta ac_res
        ldx currplayer
        lda player_tile - 1,x
        beq ac_out              ; left the fight
        cmp #$38                ; asleep
        bne ac_back
ac_out: lda #$ff
        sta ac_res
ac_back:
        ldx ac_keep
        stx currplayer
        lda ac_res
        rts
ac_keep: !byte 0
ac_res:  !byte 0
ac_char: !byte 0

;;; ---- attacking what is not a monster -------------------------------------
;;; Attack ($4733 LDA $AC60,X, the object that becomes the foe): a sick or
;;; sleeping person fights as a beggar, the water as deep water, the lords
;;; (the Avatar's tile) as a knight -- no more glitch monsters.  Its check
;;; ($46E1, the same load, before CMP #$8C/#$8E "can't"): a chest cannot be
;;; attacked.  Combat's animation (SUBS $0B6D LDA $AD70,X, asleep?): the
;;; ankh and a camp fire keep still.  The game main side runs at $01 = $35,
;;; so fx_attack goes on under the KERNAL (u4ff.s fx_horse).
fx_attack:
        lda object_tile,x
        cmp #$38                ; sick, sleeping
        bne +
        lda #$58                ; a beggar
+       cmp #$02                ; water
        bne +
        lda #$01                ; deep water
+       cmp #$1f                ; the Avatar's tile
        bne +
        lda #$2a                ; a knight
+       jmp fx_horse            ; (u4ff.s: a horse faces west)

fx_attackable:
        lda object_tile,x
        cmp #$3c                ; a chest
        bne +
        lda #$8c                ; which cannot be attacked
+       rts

fx_animate:
        cmp #$3d                ; the ankh
        beq +
        cmp #$4b                ; a camp fire
        beq +
        lda monster_sleep,x
        rts
+       lda #$01
        rts

;;; ---- X in combat: every foe gone (the launcher's X, with T and B) ---------
;;; Combat's letter table ($779A) sends X, which it does not know, to "WHAT?"
;;; ($4112); now here.  With the option (u4pw.s pw_on, the launch's poke) the
;;; sixteen foes' tiles go (a foe killed is $AD50,X = 0, $745E) and the turn
;;; ends: the end of every player's turn ($716C JSR $7514) finds none left
;;; and goes to "VICTORY!" ($75FF), whose chest and the rest are the game's.
;;; (In a dungeon room, $1B = $81, $7514 does not ask: the party walks out.)
pw_on = $02a7                   ; u4pw.s's (build.py asserts it)
pw_win: lda pw_on
        beq +
        ldx #$0f
        lda #$00
-       sta $ad50,x
        dex
        bpl -
        jmp cmd_done
+       jmp cmd_unknown

a0_end:
!if a0_end > $a100 {
        !error "u4a0.s runs into the kernel at $A100: ", a0_end
}
