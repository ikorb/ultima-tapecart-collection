;;; u2step.s -- the footstep played from the raster IRQ, at most five steps a second.
;;;
;;; A move on foot ends in ULTIMA's $6B01-$6B10: effect $4021 (SUBS $4DD9:
;;; two $40A2 blocks, the second a noise on voice 3 with its gate on, then
;;; the delay $409F with A = $80, 21.3k cycles, and the gate off), a fixed
;;; loop of 42.5k cycles ($6B04, X = 255 by Y = 32), the effect again: two
;;; clicks 66 ms apart, 128k of a step's 222k cycles spent waiting.  On a
;;; horse ($6AF1) one click and the same loop, then the food ($6B94) and
;;; $6BB4's JSR $6B01, the walk's two: three clicks.  The plane's move goes
;;; through $6B94 too ($6B75): the walk's two.  The frigate's has none.
;;;
;;; Here the click's registers are written as $4DD9 writes them (from its
;;; own blocks in SUBS, $4DDE and $4DEA, seven bytes each), and the gate's later changes are
;;; made by the game's raster IRQ: SUBS' two handlers end in the same tail,
;;; $47A9, which counts the frame ($2D/$2E) twice a frame -- build.py
;;; points it at st_tick, which counts it and goes on at $47AF.  A tick is
;;; 9.2k or 10.5k cycles; an event n ticks after the click comes n - 1 to n
;;; ticks later, so the gate goes off 20-30 ms after each click (21.6 in
;;; the original) and the second click comes 60-70 ms after the first (66).
;;;
;;; st_horse plays all three, the second and third where the original's
;;; come (65 and 131 ms), and tells st_foot that the JSR $6B01 to come is
;;; covered.
;;;
;;; Without the waits a step takes ~85k cycles, under the KERNAL's key
;;; repeat (four frames, SUBS sets $028A = $80), so a move waits until
;;; ST_FLOOR ticks (0.2 s) have passed since the last one's click: a key
;;; held down walks five steps a second.  A move after a pause starts at
;;; once.
;;;
;;; The original never plays two effects at once: each one blocks.  So
;;; every effect, which begins with JSR $40A2, reaches the SUBS code
;;; through st_fx, which lets a click in flight finish first; so does every
;;; load and save (u2_enter).  A click with interrupts masked is cut
;;; instead: there is no tick to wait for.  Nothing else writes voice 3
;;; (ULTIMA, INTRO, STARS and DNGNDRAW write only voice 2's control, $D40B)
;;; but the SID clear, $401B, after F1 at ULTIMA $7C06 and a landing's
;;; message at $7D72, nowhere near a step: at most it would silence what is
;;; left of a click.

ST_FLOOR = 20                   ; ticks from one move's click to the next's
SID_CTRL = $d412                ; voice 3's control: $80 noise, $81 + gate

;;; ULTIMA $6AF1 (a horse) and $6B01 (on foot, and the horse's and the
;;; plane's walk): JSR $4021.  $6AF4 and $6B04 jump past the loop
;;; (build.py PATCHES).
st_horse:
        lda #$01
        sta st_skip             ; $6BB4's JSR $6B01 is in this sequence
        ldx #st_thorse - st_tab
        bpl st_click            ; (always)
st_foot:
        lsr st_skip             ; a horse's: played already
        bcs st_rts
        ldx #st_tfoot - st_tab
st_click:
        php
        pla
        and #%00000100
        bne +                   ; interrupts masked: no tick, no floor
-       lda st_since
        cmp #ST_FLOOR
        bcc -
+       lda #$00
        sta st_on               ; the IRQ leaves the SID alone from here
        sta st_since
        sta st_clk
        stx st_x
        lda #$80                ; a new click starts from the gate off
        sta SID_CTRL
        ldy #$00                ; $4DD9's blocks, seven bytes each ($40A2
-       lda $4dde,y             ; copies Y = 3-9): $D415-$D41B, $D40E-$D414
        sta $d415,y             ; (interleaved: the volume, $D418, before
        lda $4dea,y             ; the gate, $D412, and the envelope, $D413
        sta $d40e,y             ; and $D414, after it, as $4DD9 has them).
        iny                     ; $D414 = 0 matters: the other effects leave
        cpy #$07                ; sustain $F and a long release there
        bne -
        inc st_on
st_rts: rts

;;; SUBS $47A9 (INC $2D / BNE $47AF / INC $2E), from the raster IRQ: A and X
;;; are free, the handler restores them
st_tick:
        inc $2d
        bne +
        inc $2e
+       inc st_since            ; counts up to $FF and stays
        bne +
        dec st_since
+       lda st_on
        beq st_t_out
        inc st_clk
        ldx st_x
        lda st_tab,x            ; the next event's tick
        cmp st_clk
        bne st_t_out
        lda st_tab+1,x          ; ... and what goes into the control
        sta SID_CTRL
        inx
        inx
        stx st_x
        lda st_tab,x
        bne st_t_out
        sta st_on               ; the last: done
st_t_out:
        jmp $47af

;;; SUBS' vector $40A2, the SID block writer ($4CBC): the start of every
;;; effect.  The stack is the caller's again when the JMP is made: $4CBC
;;; takes its inline block from it.
st_fx:  jsr st_flush
        jmp $4cbc

;;; let a click in flight finish; A changed, the I flag not (u2_enter keeps
;;; its caller's), nothing else of the flags anyone's
st_flush:
-       lda st_on
        beq ++
        php
        pla
        and #%00000100
        beq -                   ; the IRQ will end it
        lsr st_on               ; interrupts masked: cut it (1 -> 0)
        lda #$80
        sta SID_CTRL
++      rts

;;; per move: (tick, control) pairs after the first click, 0 to end
st_tab:
st_tfoot:  !byte 3, $80, 7, $81, 9, $80, 0
st_thorse: !byte 3, $80, 7, $81, 9, $80, 14, $81, 16, $80, 0

st_on:    !byte 0               ; a click in flight: the IRQ runs st_tab
st_x:     !byte 0               ; its next event
st_clk:   !byte 0               ; ticks since its click
st_since: !byte $ff             ; ticks since the last move's click, at most $FF
st_skip:  !byte 0               ; 1: st_foot's next call is st_horse's
