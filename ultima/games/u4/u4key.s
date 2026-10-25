;;; u4key.s -- the keyboard queue fix and the joystick, from Ultima IV
;;; Remastered (fixed_getkey, src/trainer/trainerroutines.s), in SUBS' dead
;;; disk-swap prompt (chunk $4F; $1914 is our JMP u4_setdisk, so $1917 on
;;; is never reached -- ultima/games/u4/remastered.py checks the JMP).  From $192A:
;;; the prompt's first 20 bytes stay, the pattern by which build.py finds all
;;; three swap overlays; $19B7 on is left alone.
;;;
;;; SUBS' key read ($157E) took $0277, the first key queued, and then
;;; emptied the queue ($159D JSR $15A1): every key typed ahead was lost.
;;; This takes one key and moves the rest up.  With none, it reads joystick
;;; 2 ($DC00, at most every 5 jiffies): up, down, left, right as the four
;;; direction keys @ / : ;, fire as E in Britannia, T in a town, A in
;;; combat, nothing in a dungeon.  A = the key (not yet ORed with $80) or 0.
;;; The kit copies the direction keys from the KERNAL's key table at start
;;; (for other KERNALs' layouts); this is the stock KERNAL's, fixed.

        * = $192a
kb_get: sei
        ldy $c6
        beq kb_joy
        ldy $0277               ; the first key, and the rest moved up
        ldx #0
-       lda $0278,x
        sta $0277,x
        inx
        cpx $c6
        bne -
        dec $c6
kb_trans:
        tya
        ldy #3
-       cmp kb_tab,y
        beq +
        dey
        bpl -
        bmi ++
+       lda kb_dirs,y
++      cli
        rts
kb_dirs: !byte $40, $2f, $3a, $3b
kb_tab:  !byte $40, $2f, $3a, $3b

kb_joy: lda $a2                 ; (Y = 0: no key)
        sec
        sbc kb_last
        cmp #5
        bcc kb_trans
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
        bcs kb_trans
        lda $1b                 ; fire: by the mode
        bmi kb_combat
        cmp #1
        beq kb_brit
        cmp #2
        beq kb_town
        ldy #$00                ; a dungeon, or anything else: nothing
        !byte $2c
kb_brit:
        ldy #$45                ; E
        !byte $2c
kb_town:
        ldy #$54                ; T
        !byte $2c
kb_combat:
        ldy #$41                ; A
        !byte $2c
kb_up:  ldy #$40
        !byte $2c
kb_down:
        ldy #$2f
        !byte $2c
kb_left:
        ldy #$3a
        !byte $2c
kb_right:
        ldy #$3b
        jmp kb_trans
kb_last: !byte 0
kb_end:
!if kb_end > $19b7 {
        !error "the keyboard fix runs into $19B7: ", kb_end
}
