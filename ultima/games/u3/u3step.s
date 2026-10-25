;;; u3step.s -- the footstep's later clicks played from the IRQ, without the wait.
;;;
;;; A move onto a free square ends in ULT3's $710A-$7135: effect $F6
;;; ($470E -> SUBS $4D3D -> $4E7C, the click), a fixed loop of 41k cycles
;;; ($710F, X = 255 by Y = 32), the click again; on a horse ($0E = $14)
;;; another loop and a third click; then LDA #$00 / RTS.  A click is a burst of
;;; eight toggles of the SID's $D418 bit 7 (the DOS module's $B818, the
;;; Apple speaker), each after a random delay of up to 256 DEX loops
;;; ($D012 + $D41B): about 5k cycles.  So 16% of a step on foot is the
;;; wait, 20% the footstep.
;;;
;;; Here the first click stays where it is ($710C), and build.py makes
;;; $710F JSR st_foot / LDA #$00 / RTS: st_foot leaves the clicks still
;;; to come to the IRQ.  MUSI's IRQ handler ($9A75, which $0314 points at
;;; while the game runs) calls its player with JSR $9A86 at $9A7B; build.py
;;; points that at st_tick, which plays a click every ST_GAP ticks and
;;; goes on at $9A86.  The IRQ is the KERNAL's CIA timer, 60 a second; a
;;; click set for n ticks comes n - 1 to n ticks later, so ST_GAP = 3 puts
;;; the second click 40-56 ms after the first's start (the original: 50-55).
;;;
;;; The original never plays two effects at once: each one blocks.  So
;;; every effect, which goes through SUBS' $470E (JMP $4D3D), comes through
;;; st_fx, which lets the clicks in flight finish first; so does every load
;;; and save (u3_transfer: its SEI would hold them back until it is done).
;;; With interrupts masked there is no tick to wait for, and what is left
;;; of the footstep is dropped.  The burst keeps $B93E, the speaker's
;;; state, as it found it (eight toggles), so a toggle the main program is
;;; part-way through is not upset.  No zero page: $4E7C counts in $15,
;;; which the IRQ must not touch.

ST_GAP = 3                      ; ticks from one click to the next

;;; ULT3 $710F, after the move's first click (A, X free: $7133 is next)
st_foot:
        lda $20                 ; the effects' switch, as $4D3D tests it
        bne +
        ldx #1                  ; the second click
        lda $0e
        cmp #$14                ; $711E: on a horse, a third
        bne ++
        inx
++      lda #ST_GAP
        sta st_clk
        stx st_n                ; last: the IRQ looks at st_n first
+       rts

;;; MUSI $9A7B (JSR $9A86), in the IRQ: A, X and Y are free, the handler
;;; pulls them after the call; decimal mode is off ($9A7A CLD)
st_tick:
        lda st_n
        beq +
        dec st_clk
        bne +
        lda #ST_GAP
        sta st_clk
        jsr st_click
        dec st_n
+       jmp $9a86

;;; effect $F6 ($4E7C) without its zero page: eight toggles, each after
;;; $D012 + $D41B (and the carry) DEX loops; A, X, Y changed
st_click:
        ldy #8
-       lda $d012
        adc $d41b
        tax
--      dex
        bne --
        jsr $b818
        dey
        bne -
        rts

;;; SUBS' $470E (JMP $4D3D), every effect: A, X and Y are its parameters
st_fx:  jsr st_flush
        jmp $4d3d

;;; let the clicks in flight finish, or drop them with interrupts masked;
;;; A, X, Y, the carry and the I flag kept
st_flush:
        pha
-       lda st_n
        beq +
        php
        pla
        and #%00000100
        beq -                   ; the IRQ will play them
        lda #0
        sta st_n
+       pla
        rts

st_n:   !byte 0                 ; clicks still to play: the IRQ's
st_clk: !byte 0                 ; ticks to the next
