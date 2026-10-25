;;; u6scan.s -- `game`'s keyboard scan, smaller, and in the room it leaves a
;;; latch for the direction keys and the joystick.
;;;
;;; The scan ($28CE-$2988, called once a frame by the IRQ's input handler at
;;; $1F6E) is rewritten to do exactly what it did in 140 of its 187 bytes:
;;; all rows down and read until two reads agree, nothing if $FF; the
;;; modifier into $48 by the original's priority (CTRL 4, RUN/STOP 3, C= 2,
;;; either shift 1, none 0; row 7 bits $04 $80 $20, row 1 $80, row 6 $10);
;;; then rows 7 to 0, bit 0 up, each row read twice and skipped if the reads
;;; differ, the first key down that is not a modifier decoded through the
;;; KERNAL's table for $48 ($EB81 $EBC2 $EC03 $EB81 $EC78), $FF meaning none.
;;; The original found a modifier key by decoding it (the unshifted table
;;; gives them 1-4) and went on from the next bit; here they are masked out of
;;; the row first (s_mods: the same five places), and the key's index is
;;; counted as the bits are, instead of being rebuilt from saved state.  The
;;; rows' select values are `game`'s own inverted masks at $0225.  The last
;;; $DC00 written is the original's.  tests/test_u6_input.py runs both over
;;; every key with every modifier and over random matrices.
;;;
;;; The latch (without it taps are lost, on the original too).
;;; The direction keys are not queued: the IRQ builds $47 every frame from
;;; the joystick port and the direction keys held, and the main loop's wait
;;; $0449 copies it to $46 once a pass (9 frames at least, a step 13-16), so a
;;; tap that comes and goes between two such reads is never seen.  Now the
;;; input handler ends here ($1FB7 jumps to s_latch, its own tail moved along):
;;; the first direction newly pressed since the last read is kept (a press:
;;; it was not down the frame before, so a key held through a read and then
;;; let go leaves nothing behind), and while no direction or fire is held,
;;; $47 shows it, so $0449 reads it as if it were still down.  $0449 is not
;;; changed: the first IRQ after a read sees $FC at 7 (the read reloads it
;;; with 8, the IRQ counts it down before getting here; nothing else writes
;;; $FC), and that empties the slot.  Fire is not latched (Return is in the
;;; key queue already).  One entry, first press wins: tapping ahead moves at
;;; most one step more, and two taps never merge into a diagonal.

        * = $28ce
s_scan: stx $dc02               ; X = $FF: port A drives the rows
        inx
        stx $dc03               ; port B reads
        stx $48                 ; no modifier
        stx $dc00               ; every row
-       ldx $dc01
        cpx $dc01
        bne -
        inx
        beq s_none              ; $FF: nothing down
        ldy #$05                ; the modifiers, by priority
-       lda s_mrow-1,y
        sta $dc00
        lda $dc01
        and s_mbit-1,y
        beq s_mod
        dey
        bne -
        beq s_mset              ; Y = 0: none
s_mod:  dey                     ; 5-2 -> CTRL 4 .. left shift 1; 1 -> right
        bne s_mset              ; shift 0, which is 1 too
        iny
s_mset: sty $48
        ldx #$07                ; rows 7 to 0
s_row:  txa
        asl
        asl
        asl
        tay                     ; Y = the row's first key
        lda $0225,x
        sta $dc00
        lda $dc01
        cmp $dc01
        bne s_next              ; changing: not this row
        ora s_mods,x            ; the modifier keys are not keys
        cmp #$ff
        beq s_next
-       lsr                     ; bit 0 up: a key down is a 0
        bcc s_key
        iny
        bne -
s_next: dex
        bpl s_row
s_none: lda #$00
        rts
s_key:  ldx $48
        lda s_tlo,x
        sta s_tab+1
        lda s_thi,x
        sta s_tab+2
s_tab:  lda $eb81,y
        cmp #$ff
        beq s_none
        rts
s_mrow: !byte $bf, $fd, $7f, $7f, $7f       ; right shift, left shift, C=, STOP, CTRL
s_mbit: !byte $10, $80, $20, $80, $04
s_mods: !byte $00, $80, $00, $00, $00, $00, $10, $a4
s_tlo:  !byte $81, $c2, $03, $81, $78       ; by $48: none, shift, C=, STOP, CTRL
s_thi:  !byte $eb, $eb, $ec, $eb, $ec
s_scan_end:

;;; ------------------------------------------------------------------
;;; the latch: the end of the IRQ's input handler, $47 complete
;;; ------------------------------------------------------------------
s_latch:
        lda $fc
        eor #$07
        bne +
        sta s_sl+1              ; read since the last frame: the slot spent
+       lda $47
        and #$0f
        tax                     ; X = the directions down now
s_pv:   eor #$00                ; (the directions down the frame before)
        stx s_pv+1
        and s_pv+1
        beq +                   ; none newly pressed
        lda s_sl+1
        bne +                   ; the slot holds an earlier one
        stx s_sl+1
+       lda $47
        bne +                   ; something held: as it always was
s_sl:   lda #$00
        sta $47
+       ldx #$be                ; the handler's own tail: the next raster
        ldy #$1f                ; routine $1FBE, at line 4
        lda #$04
        rts
s_end:
!if s_end > $2989 {
        !error "u6scan.s runs into the loader at $2989 by ", s_end - $2989
}

        * = $1fb7
s_hook: jmp s_latch
s_hook_end:

;;; ------------------------------------------------------------------
;;; Return counts as fire when the read takes it from the queue (else
;;; selecting is unresponsive with the keyboard).  Return is the
;;; tenth "direction" key: held, it sets the fire bit in $47 ($206D,9 = $10),
;;; and it is also queued.  But the confirms test the fire bit only -- $2F45
;;; (a target or an item chosen: the dispatcher's $2D3B and the waits $0495,
;;; $04A5, $309C, $33F8) and the "space or fire" wait at $1D43 -- and in the
;;; dispatcher a queued Return comes to nothing outside combat ($2D50).  So a
;;; tapped Return confirmed only if still down at the read.  Now the read
;;; $0449, as it pops a Return into $44, sets fire in $46 too: a tap looks
;;; like a Return held over the read, which the game always handled (a held
;;; Return gives both at once).  The joystick's fire button is as it was.
;;; Every caller of $0449 (and of $032C, its jump-table entry, from the
;;; overlays) reloads A and the flags after it, so its new flags do not
;;; matter.  Room: $2084 in the init's room (u6chunk.s's byte variable went
;;; into an immediate), $27ED (after u6chunk.s's k_end); the branch for "not
;;; Return" goes to the RTS at $2061, the end of an IRQ raster routine
;;; (build.py checks it is one).
;;; ------------------------------------------------------------------
        * = $046c                ; $0449's end: was STA $44 / RTS
s_pop:  jmp s_ret
s_pop_end:

        * = $2084
s_ret:  sta $44                 ; the key, or 0
        cmp #$0d
        bne $2061               ; not Return: an RTS
        jmp s_fire
s_ret_end:
!if s_ret_end > $208d {
        !error "u6scan.s's s_ret runs out of the init's room by ", s_ret_end - $208d
}

        * = $27ed
s_fire: lda #$10                ; Return: fire, as if held at the read
        ora $46
        sta $46
        rts
s_fire_end:
!if s_fire_end > $27f4 {
        !error "u6scan.s's s_fire runs into $27F4's table by ", s_fire_end - $27f4
}
