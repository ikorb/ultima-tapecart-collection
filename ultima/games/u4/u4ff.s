;;; u4ff.s -- Ultima IV Remastered's save in a dungeon, resident at $FF00.
;;;
;;; $FF00-$FFF9, the RAM under the KERNAL: nothing loads there, every
;;; absolute reference into it on the four disks is a JSR $FFxx to the KERNAL
;;; (run with the ROM in) or data (docs/reversing-notes/u4-remastered.md),
;;; and the kit keeps this very code there.  So only callable at $01 =
;;; $35 -- which game main's Quit and its load path run at.  (Our driver's
;;; NMI redirect is $FFFA/$FFFB, just above.)  A boot segment (build.py).
;;; The routines are the kit's (src/trainer/trainerroutines.s), but for the
;;; save: the kit calls its loader's cache of chunk $7E; ours is the driver's
;;; (u4drv.s), which S $7F flushes, so this is S $7F, S $80, S $1A through
;;; the kernel's $A100 as the original Quit does ($5840).

j_fileio        = $a100
j_request_disk  = $0842         ; our u4_setdisk, through the swap overlay's slot
j_update_status = $0845
cmd_done        = $621e
print_not_here  = $4178
music_ctl       = $af20
music_irq       = $ec89         ; chunk $55, the music: its IRQ handler,
music_next      = $ecc2         ; and where it goes on to ($A116 before it)
game_mode       = $1b

        * = $ff00

;;; ---- fixes from Sean Gugler's continuation of the kit ------------------
;;; (remastered.py fork_fixes hooks these; all from game main or its
;;; overlays, at $01 = $35)

;;; Attacking a horse ($4733 via u4a0.s fx_attack, which jumps here: pinned
;;; at $FF00): one facing east fights as one facing west, whose frames the
;;; combat animation steps through -- east's flickered.
fx_horse:
        cmp #$15                ; a horse facing east
        bne +
        lda #$14                ; facing west
+       rts

;;; Attacking a townsperson costs virtues ($4720/$4727/$472E JSR $8472);
;;; after the third, the status (the ankh's eighths) is drawn again.
fx_ankh:
        jsr $8472
        jmp j_update_status

;;; A townsperson killed drops a chest in their slot ($767B JMP $76D6):
;;; their conversation goes with them ($ACE0,X), so the chest says nothing.
fx_loot:
        lda #$00
        sta $ace0,x
        jmp $76d6

;;; X-it ($5C36-$5C49): the transport left behind takes a free object slot,
;;; searched from 31 down to 8 -- below are Britannia's monsters, but in a
;;; town they are people, and with no free slot from 8 up a random one of
;;; 16-31 was taken, a person gone.  Now down to 0 in a town.  X: the slot.
fx_free_slot:
        ldy #$08
        lda game_mode
        cmp #$01                ; Britannia
        beq +
        ldy #$00
+       sty ff_floor
        ldx #$1f
-       lda $ac60,x
        beq ++
        dex
        bmi +
        cpx ff_floor
        bcs -
+       jsr $084e               ; none free: a random one of 16-31, as before
        and #$0f
        ora #$10
        tax
++      rts
ff_floor: !byte 0

;;; Katrina's "Thou art not humble enough": the talk code's humility reason
;;; (chunk $78, $8D62 JSR $0821 "HUMBLE") had no RTS and ran on into
;;; "EXPERIENCED".  Its JSR comes here, an RTS follows it.  In the case the
;;; talk code's text has (remastered.py MIXED_CASE).
fx_humble:
        jsr $0821
        !byte $e8, $f5, $ed, $e2, $ec, $e5, 0       ; "humble"
        rts

;;; Quit & save ($582A LDA $1A / BEQ / JMP $4178, "NOT HERE!" outside
;;; Britannia): in a dungeon too.  Towns still say "NOT HERE!".
dg_save:
        lda game_mode
        cmp #$03
        beq +
        jmp print_not_here
+       lda #$02                ; the Britannia disk: the save's
        jsr j_request_disk
        lda #$d3                ; 'S'
        ldx #$7f
        jsr j_fileio
        ldx #$80
        jsr j_fileio
        ldx #$1a
        jsr j_fileio
        lda #$04                ; the dungeon's again
        jsr j_request_disk
        jmp cmd_done

;;; A game loaded ($405C, after L $1A / L $7F / L $80): on the surface, the
;;; balloon as it was saved (the fix that was in place here) and A = 0 for
;;; the stores after; saved in a dungeon, the dungeon's code and level, as
;;; entering one does ($5082-$50A7), and on into the main loop.
dg_load:
        lda game_mode
        cmp #$03
        beq +
        lda $1d                 ; flying as saved
        sta $74
        lda #$00
        rts
+       pla
        pla
        lda #$00
        sta $74
        sta $75
        lda #$04
        jsr j_request_disk
        lda #$cc                ; 'L'
        ldx #$95                ; the dungeon's code
        jsr j_fileio
        jsr j_update_status
        jsr $50ad               ; the level's map
        lda #$ff
        sta $4d
        lda #$c4                ; its music
        jsr music_ctl
        jmp cmd_done

;;; Journey Onward in the title's menu with no saved game: "NO ACTIVE
;;; GAME!" ($4038), then $404D JMP $404D -- a hang (the kit's
;;; initiate_new_game is the same hang, its way out left commented out).
;;; Now two seconds to read it, then the title again: disk 1, 'R' chunk $50,
;;; as that commented-out code would -- with the music unhooked first.
ff_nogame:
        ldy #100                ; frames
ff_frame:
        lda $d012
        cmp #$fb
        bne ff_frame
ff_line:
        lda $d012
        cmp #$fb
        beq ff_line
        dey
        bne ff_frame
        sei                     ; the title's music off the interrupt chain:
        lda $a116               ; the title loads it again ($676C), over the
        cmp #<music_irq         ; handler, which is still hooked in -- with
        bne +                   ; interrupts on through loads it runs half
        lda $a117               ; replaced, and its init would chain it to
        cmp #>music_irq         ; itself ($EC1F keeps $A116 in $ECC2).
        bne +
        lda music_next
        sta $a116
        lda music_next+1
        sta $a117
        lda #$00
        sta $d418               ; silent until it starts again
+       cli
        lda #$00
        sta game_mode
        lda #$01
        jsr j_request_disk
        lda #$d2                ; 'R': load and run
        ldx #$50                ; the title
        jmp j_fileio

ff_end:
!if ff_end > $fffa {
        !error "u4ff.s runs into the vectors at $FFFA: ", ff_end
}
