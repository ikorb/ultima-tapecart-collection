;;; u6walk.s -- the object pool walk, `game`'s $27CE, faster.
;;;
;;; A chunk fetch ($2699, four to a chunk boundary, every 8th step) puts the
;;; objects that lie in its 8 x 8 box on the tile layers ($273E): it walks
;;; the pool's linked list from the head, node after node, asking of each
;;; "is it in the box?" ($33/$34 the box's corner, $80/$81 its size) and
;;; "is it the end of the list?" (a node whose first byte is $FF).  The
;;; original did it with three calls a node ($27E3 for the end test, $252B
;;; for the link: ~110 cycles a node, 610 nodes a walk, 218k cycles of a
;;; 680k step).  The same logic, in line: ~64.
;;;
;;; Same contract as the original, registers and flags included: carry
;;; clear with A = the node's first byte, Y = 0 at a node in the box; carry
;;; set (A = $FF, Y = 0) at the end of the list; $4E/$4F are the node the
;;; walk has left, as $252B leaves them.  The old routine has two more entry
;;; points with callers outside it (tests/test_u6_chunk.py's scan): $27E3, the end
;;; test, is the jump table's $02BA, which the Use overlays $00 and $10 call;
;;; $27EA, "on to the next node, then on with the walk", is the jump table's
;;; $02D5 (overlays $08 and $18, Look) and is called by $338B (`JSR $27EA /
;;; BNE $338B`, from $32E2 and $336C).  Both are re-pointed at
;;; the same paths here: w_hit is $27E3's code byte for byte, w_miss is
;;; $27EA's but for a link of page 0 (the original ran into data).

        * = $27ce
w_jump: jmp w_walk
w_jump_end:
        * = $02ba
w_tab:  jmp w_hit               ; the jump table's entry, was JMP $27E3
w_tab_end:
        * = $02d5
w_tab2: jmp w_miss              ; the jump table's entry, was JMP $27EA
w_tab2_end:
        * = $338b
w_call: jsr w_miss              ; was JSR $27EA
w_call_end:

w_walk  = $038f
        * = w_walk
        ldy #$01
        lda ($50),y
        sec
        sbc $33
        cmp $80
        bcs w_miss              ; x outside the box
        iny
        lda ($50),y
        sec
        sbc $34
        cmp $81
        bcs w_miss              ; y outside it
w_hit:  ldy #$00
        lda ($50),y
        cmp #$ff                ; C set if this is the end of the list
w_rts:  rts
w_miss: ldy #$00
        lda ($50),y
        cmp #$ff
        bcs w_rts               ; the end
        lda $50                 ; on to the next node: $4E/$4F = this one,
        sta $4e                 ; $50/$51 = its link (bytes 6 and 7)
        lda $51
        sta $4f
        ldy #$06
        lda ($4e),y
        sta $50
        iny
        lda ($4e),y
        sta $51
        bne w_walk
        rts                     ; (a link of page 0: the original ran into data here)
w_end:
!if w_end > $03fc {
        !error "u6walk.s runs into the main loop's entry by ", w_end - $03fc
}
