;;; u4pw.s -- Ultima IV Remastered's "ingame keys": T teleports, B brings a
;;; transport (the kit's trainer_teleport and trainer_board,
;;; src/trainer/trainerroutines.s), in Britannia, when the launcher's option
;;; is on (pw_on, which its launch pokes).  The hooks are always there (build:
;;; remastered.py code_fixes) -- the options byte is full -- and with pw_on
;;; clear T is Talk and B on nothing "WHAT?", as the original.
;;;
;;; Two pieces, in the two gaps of page 2 and 3 the kit keeps code in too:
;;; $02A7-$0313 (BASIC's vectors from $0300, which nothing uses once a game
;;; runs) and the tape buffer $0334-$03FF (only the title, chunk $51, touches
;;; page 3, and only $0314/$0315; our init stub at $0200 ends before $02A7).
;;; acme emits one blob from $02A7; build.py slices off the gap $0314-$0333,
;;; the KERNAL's vectors, which must stay empty.

game_mode        = $1b
current_location = $1a
player_xpos      = $10
player_ypos      = $11
balloon_flying   = $1d
player_transport = $1e
tile_north       = $49
movement_mode    = $74
map_status       = $ac00        ; the object tables: the monsters' cleared
object_tile      = $ac60        ; for a teleport
j_waitkey        = $0800
j_player_teleport = $0803
j_primm          = $0821
j_console_out    = $0824
cmd_unknown      = $4112
print_only_on_foot = $4139
print_not_here   = $4178
cmd_done         = $621e
getandprintkey   = $8398
towne_xpos       = $519e
towne_ypos       = $51be
dungeon_xpos     = $51aa
dungeon_ypos     = $51ca
shrine_xpos      = $51b2
shrine_ypos      = $51d2
location_xpos    = $519a
location_ypos    = $51ba

        * = $02a7

pw_on:  !byte 0                 ; the launcher's option: set = on

;;; B on nothing ($47AB JMP $4112, "WHAT?"): in Britannia, "WHAT?" asks
;;; H(orse), S(hip: deep water next to the party) or B(alloon, flying).
pw_board:
        lda pw_on
        beq pw_what
        lda current_location
        beq +
        jmp print_not_here
+       jsr j_primm
        !byte $d7, $c8, $c1, $d4, $bf, $a0, 0       ; "WHAT? "
        jsr getandprintkey
        beq pw_done
        ldx #$1f                ; (on foot)
        cmp #$c8                ; H
        bne +
        ldx #$14
+       cmp #$d3                ; S
        beq pw_ship
        cmp #$c2                ; B
        bne +
        lda #$ff
        sta balloon_flying
        sta movement_mode
        ldx #$18
+       stx player_transport
pw_done:
        jmp cmd_done
pw_ship:
        ldx #3
-       lda tile_north,x
        cmp #2                  ; deep water beside the party?
        bcc +
        dex
        bpl -
        jmp print_not_here
+       ldx #$10
        stx player_transport
        jmp cmd_done
pw_what:
        jmp cmd_unknown

;;; the new position ($10 = A, $11 = Y), the monsters gone, redrawn
pw_go:  sta player_xpos
        sty player_ypos
        ldx #7                  ; Britannia's monsters, slots 0-7, as the skull
        lda #0                  ; clears them: transports and chests stay
-       sta object_tile,x
        sta map_status,x
        dex
        bpl -
        jsr j_player_teleport
        jmp cmd_done
pt_kind: !byte 0
pt_y:    !byte 0
pt_hi:   !byte 0
pw_end_a:
!if pw_end_a > $0314 {
        !error "u4pw.s: $02A7's piece runs into the KERNAL's vectors by ", pw_end_a - $0314
}

        * = $0334

;;; T ($59CE JSR $0821 "Talk-"): in Britannia, on foot or on horse,
;;; "TELEPORT-" (T)owne, (D)ungeon, (S)hrine, (L)ocation 1-8, or (C)oordinates
;;; as four letters A-P.  Elsewhere, or with the option off, on to the print
;;; with the text still as its return address: Talk, as it was.
pw_teleport:
        lda pw_on
        beq +
        lda game_mode
        cmp #1
        beq ++
+       jmp j_primm
++      pla                     ; the "Talk-" return address
        pla
        lda player_transport
        cmp #$14
        bcs +
        jmp print_only_on_foot
+       jsr j_primm
        !byte $d4, $c5, $cc, $c5, $d0, $cf, $d2, $d4, $ad, 0    ; "TELEPORT-"
        jsr getandprintkey
        beq pt_done
        ldx #0                  ; which table: 0 T, 1 D, 2 S, 3 L
        cmp #$d4                ; T
        beq pt_table
        inx
        cmp #$c4                ; D
        beq pt_table
        inx
        cmp #$d3                ; S
        beq pt_table
        inx
        cmp #$cc                ; L
        beq pt_table
        cmp #$c3                ; C
        beq pt_coord
pt_done:
        jmp cmd_done
pt_table:
        stx pt_kind
        jsr j_primm
        !byte $a3, 0            ; "#"
        jsr pt_num              ; 0-7
        ldx pt_kind
        cpx #3
        bne +
        cmp #4                  ; locations 5-8 are the table's 12-15
        bcc +
        adc #7                  ; (C set: +8)
+       clc
        adc pt_base,x
        tax
        lda $5100 + $20,x       ; the y table is $20 after the x table
        tay
        lda $5100,x
        jmp pw_go
pt_coord:                       ; latitude, then longitude, as the sextant has them
        lda #$a8                ; "("
        jsr j_console_out
        jsr pt_pair
        sta pt_y
        lda #$ac                ; ","
        jsr j_console_out
        jsr pt_pair
        pha
        lda #$a9                ; ")"
        jsr j_console_out
        pla
        ldy pt_y
        jmp pw_go
pt_pair:                        ; two letters A-P: a coordinate 0-255
        jsr pt_letter
        asl
        asl
        asl
        asl
        sta pt_hi
        jsr pt_letter
        ora pt_hi
        rts
pt_letter:
        jsr j_waitkey
        beq pt_abort
        pha
        jsr j_console_out
        pla
        sec
        sbc #$c1                ; A
        bmi pt_abort
        cmp #$10
        bcs pt_abort
        rts
pt_num:
        jsr getandprintkey
        beq pt_abort
        sec
        sbc #$b1                ; 1
        bmi pt_abort
        cmp #8
        bcs pt_abort
        rts
pt_abort:
        pla
        pla
        jmp cmd_done
pt_base: !byte <towne_xpos, <dungeon_xpos, <shrine_xpos, <location_xpos
pw_end_b:
!if pw_end_b > $0400 {
        !error "u4pw.s: $0334's piece runs into the screen by ", pw_end_b - $0400
}
!if >towne_xpos != $51 or >location_xpos != $51 or >dungeon_xpos != $51 or >shrine_xpos != $51 {
        !error "the position tables are not all in page $51"
}
!if towne_ypos - towne_xpos != $20 or dungeon_ypos - dungeon_xpos != $20 or shrine_ypos - shrine_xpos != $20 or location_ypos - location_xpos != $20 {
        !error "the y tables are not $20 after the x tables"
}
