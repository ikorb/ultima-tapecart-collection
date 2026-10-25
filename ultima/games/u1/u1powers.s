;;; u1powers.s -- F1 tells where the party is, F7 teleports, B brings a
;;; transport: the launcher's X for U1.
;;;
;;; As Ultima II's (u2powers.s), after the trainer keys of Ultima III Gold,
;;; outdoors: OU's command loop and its Board are hooked at build time
;;; (build.py POWER_HOOKS), and with pw_on ($80, the launch's poke):
;;;   F7: a land (0-3, OU's $81E4: Lord British, the Feudal Lords, the Dark
;;;       Unknown, Danger and Despair) and X and Y, two digits each, 00-63
;;;       (each land is 64 x 64) -- and the party is there, through what a
;;;       step off a land's edge runs ($983D: the monsters gone, the land's
;;;       map decoded at $6400 and its vehicles put on it).  Anything else,
;;;       "Huh?" on the next line and the game's buzz.  The turn ends as
;;;       after an unknown key.  The square is not checked: a frigate can
;;;       land on a mountain (X-it, $9688, needs water, grass or forest).
;;;   F1: "Position land-0 X-30 Y-31": where the party is, as F7 takes it (off
;;;       the map, in the ten squares of sea around it, -10 to 73).  No turn
;;;       passes: back to the loop's top ($8CFB, which resets the stack).
;;;   B:  where there is nothing to board, "(H)orse,(C)art,(R)aft," and
;;;       "(F)rigate,(A)ircar-" on two lines, then H, C, R, F or A: the
;;;       party is in it ($81F1, as Board leaves it after taking a vehicle
;;;       off the map; X-it puts it on the map as any other).  No shuttle
;;;       and no time machine: Board launches those at once.  Any other key,
;;;       the buzz.
;;; Without the option the original's way.  Text is ASCII, U1's font; the
;;; message window is 29 columns.
;;; In its own segment at $CE01, with the options' table (u1drv.s).

ou_command = $85fd              ; MI: a key into a command, C set if none
ou_loop    = $8cfb              ; OU: the command loop's top, the prompt
ou_land    = $983d              ; OU: a land entered (its map, its vehicles)
ou_tile    = $9e0b              ; OU: the party's tile for $81F1
ou_board   = $90b2              ; OU: Board's end, the vehicle on the stack
print      = $848e              ; MI: the inline string after the JSR
print_a    = $83d7              ; MI: A's glyph, the column on
print_num  = $8582              ; MI: A in decimal, without leading zeros
                                ; unless the fill (below) is a glyph
num_fill   = $85be              ; MI: that fill; callers set it or rely on it
new_line   = $83f3              ; MI: the next line, column 1
column_1   = $83f6              ; MI: column 1 of this line
buzz       = $8772              ; MI: the error sound, the keys dropped
get_key    = $1676              ; ST: wait for a key, A (bit 7 clear)
draw_view  = $166a              ; ST: the view around the party
party_x    = $20
party_y    = $21
land       = $81e4
vehicle    = $81f1

pw_on:  !byte 0                 ; the launcher's option: $80 = on (a launch poke)

;;; OU $8D31's JSR $85FD, A = the key.  C set: no command, and the loop
;;; goes on to the monsters' turn, as after "Huh?".
pw_key: bit pw_on
        bpl +
        cmp #$08                ; F7 ($88, bit 7 cleared)
        beq pw_teleport
        cmp #$05                ; F1 ($85)
        beq pw_where
+       jmp ou_command

pw_where:
        jsr print
        !text "Position land-", 0
        lda land
        ora #$30
        jsr print_a
        jsr print
        !text " X-", 0
        lda party_x
        jsr pw_coord
        jsr print
        !text " Y-", 0
        lda party_y
        jsr pw_coord
        jmp ou_loop

;;; A, -10 to 73, in decimal
pw_coord:
        bpl +
        pha
        lda #"-"
        jsr print_a
        pla
        eor #$ff
        clc
        adc #1
+       tay
        lda num_fill            ; (kept for its other callers)
        pha
        lda #0
        sta num_fill
        tya
        jsr print_num
        pla
        sta num_fill
        rts

pw_teleport:
        jsr print
        !text "Teleport land-", 0
        jsr pw_digit
        bcs pw_huh
        cmp #4
        bcs pw_huh
        sta pw_l
        jsr print
        !text " X-", 0
        jsr pw_number
        bcs pw_huh
        sta pw_x
        jsr print
        !text " Y-", 0
        jsr pw_number
        bcs pw_huh
        sta party_y
        lda pw_x
        sta party_x
        lda pw_l
        sta land
        jsr ou_land
        sec
        rts
pw_huh: jsr print               ; (a line of its own: "Y-64" ends in column 25)
        !byte $7e
        !text "Huh?", 0
        jsr buzz
        sec
        rts

;;; two digits, at most 63: A and C clear; anything else C set
pw_number:
        jsr pw_digit
        bcs ++
        asl                     ; x 10 (C clear: at most 90)
        sta pw_t
        asl
        asl
        adc pw_t
        sta pw_t
        jsr pw_digit
        bcs ++
        adc pw_t                ; (C clear)
        cmp #64
++      rts

;;; a key: a digit, printed, as 0-9 and C clear; else C set
pw_digit:
        jsr get_key
        cmp #"0"
        bcc +
        cmp #$3a                ; (past "9")
        bcs +
        pha
        jsr print_a
        pla
        and #$0f
        clc
        rts
+       sec
        rts

;;; OU $9082's JSR $83F6, before "nothing to Board!": called as that JSR,
;;; so without the option the message goes on as before
pw_board:
        bit pw_on
        bmi +
        jmp column_1
+       pla                     ; not coming back to the message
        pla
        jsr print
        !byte $7e               ; (a new line, column 1)
        !text "(H)orse,(C)art,(R)aft,"
        !byte $7e
        !text "(F)rigate,(A)ircar-", 0
        jsr get_key
        ldx #4
-       cmp pw_keys,x
        beq +
        dex
        bpl -
        jmp buzz                ; none of them
+       inx                     ; 1 horse, 2 cart, 3 raft, 4 frigate, 5 aircar
        stx vehicle
        txa
        pha                     ; for Board's end
        jsr ou_tile
        jsr draw_view
        jsr new_line
        lda vehicle
        cmp #3
        bcc +                   ; (a horse or a cart: Board's end says "Mount ")
        jsr print
        !text "Board ", 0
+       jmp ou_board            ; the vehicle's name

pw_keys: !text "HCRFA"
pw_l:   !byte 0
pw_x:   !byte 0
pw_t:   !byte 0
