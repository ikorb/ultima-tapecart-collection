;;; armusic.s -- Ultima V's music on a C64, from an Action Replay's RAM.
;;;
;;; The C128 plays 15 songs from RAM bank 1; a C64 has nowhere to put them.
;;; An Action Replay (4.2, 5, 6) has 8 KiB of RAM: at ROML ($8000-$9FFF) while
;;; it is mapped in -- and a store there reaches the C64's RAM as well -- and
;;; its last page at $DF00-$DFFF in the I/O area, where a store does not.
;;; So (armusic.py): the player's code and tables in the RAM from $8000, its
;;; writable state in that last page, songs loaded one at a time from the
;;; cart into the rest.  Ultima V never sets LORAM, so ROML is only ever
;;; seen where this glue maps it in ($01 | %111), and the AR's RAM is only
;;; switched on ($DE00 = AR_ON) inside the glue: whether the card also takes
;;; a store to $8000-$9FFF with ROML *not* selected (VICE's model does), no
;;; store of the game's can reach it.  $DE00 is never read (a read is said
;;; to crash real machines).
;;;
;;; This file is the stage image xyzzy's hook loads to $4000 when it finds an
;;; AR (free then: the game has not loaded anything there yet).  arinit runs
;;; once and puts the pieces where they live:
;;;   $0100-$0122  the player's zero page, swapped in and out every tick,
;;;                the glue's variables and `settle` (the stack's far end,
;;;                as the C128's music API just above it)
;;;   $0123-$0173  the music's API, where the C128 has it -- $0126 mute,
;;;                $0129 unmute -- ar_call and both IRQ paths
;;;   $0200-$0276  the song loader (the C64's BASIC input buffer; a memmap
;;;                of play shows the game never touches it)
;;;   $0335-$037F  the play and restart entries temp.subs jumps to
;;;   AR $8000+    a jump table, the player (armusic.py), ar_ensure
;;;
;;; Defined by build.py: the driver's tclib (TC_*), the player's entries and
;;; addresses (AR_*), and SONGS_FLASH, where the song data is in the cart.
;;;
;;; EF_MUSIC: the same glue for the Ultima VI EasyFlash cart instead of an
;;; AR (build.py build_efmusic; ultima/ef/efu5.s starts Ultima V from the
;;; tapecart with it).  The block is not RAM but one 16 KiB bank of flash,
;;; mapped by the cart's mode register ($DE02 = AR_ON, 16K mode) where the
;;; AR's is switched on, with LORAM and HIRAM set as before, so it holds
;;; the player with all 15 songs after it (armusic.py relocate, resident)
;;; and the player finds them through its header as the original does:
;;; nothing is loaded, `ensure` is an RTS and piece B is not there.  The
;;; player's state goes into the cart's 256 bytes of RAM at $DF00, which
;;; are always there.  The bank ($DE00) is selected by the hook before
;;; arinit runs and never changes after.

!ifdef EF_MUSIC {
AR_REG   = $de02                ; the EasyFlash's mode register
AR_ON    = $07                  ; 16K: ROML and ROMH (LORAM and HIRAM set)
AR_OFF   = $04                  ; off: no ROM ($DF00's RAM stays)
} else {
AR_REG   = $de00                ; the AR's register: written, never read
AR_ON    = $20                  ; the RAM at ROML and $DF00, 8K game mode
AR_OFF   = $0a                  ; off, as the AR's fastload install leaves it
}
MAP      = %00000111            ; LORAM, HIRAM, CHAREN: ROML, I/O, KERNAL
CMD_READ_FLASH = $10
STAGE    = $4000

;;; the AR jump table at $8000: the player's entries (armusic.py), then ours
AR_J_INIT   = AR_BASE + 0
AR_J_TICK   = AR_BASE + 3
AR_J_MUTE   = AR_BASE + 6
AR_J_UNMUTE = AR_BASE + 9
AR_J_SWAP   = AR_BASE + 12
AR_J_ENSURE = AR_BASE + 15
AR_J_REST   = AR_BASE + 18
AR_J_IRQ    = AR_BASE + 21
AR_J_NEXT   = AR_BASE + 24      ; (the player's own, from a song's end)
AR_J_GET    = AR_BASE + 27      ; the driver's 2-bit receive (u5drv.s u5_arget)
AR_J_PICK   = AR_BASE + 30      ; and its choice (u5drv.s tc_host_pick)
CMD_READ_FLASH_FAST = $11

        * = STAGE
;;; ==================================================================
;;; once, from xyzzy's hook, with $01 = $26 and interrupts on
;;; ==================================================================
arinit:
        sei
        lda $01
        pha
        ora #MAP
        sta $01
        lda #AR_ON
        sta AR_REG
!ifndef EF_MUSIC {              ; (on the EasyFlash the block is in the bank)
        ;; the AR's block to $8000: the C64's RAM under it, which the store
        ;; reaches too, holds nothing of the game's yet
        ldx #>(ar_block_end - ar_block + $ff)
        ldy #$00
ai_from:
        lda ar_block,y
ai_to:  sta AR_BASE,y
        iny
        bne ai_from
        inc ai_from + 2
        inc ai_to + 2
        dex
        bne ai_from
}
        ;; the player's variables: zero, as in `m`
        lda #$00
        tay
-       sta $df00,y
        iny
        bne -
        ;; and its own init, around the zero-page swap as the C128 does it
        jsr AR_J_SWAP
        jsr AR_J_INIT
        jsr AR_J_SWAP
        lda #AR_OFF
        sta AR_REG
        pla
        sta $01
        ;; the glue into low RAM
        ldx #piece_a_end - piece_a - 1
-       lda piece_a,x
        sta PIECE_A,x
        dex
        bpl -
!ifndef EF_MUSIC {
        ldx #piece_b_end - piece_b - 1
-       lda piece_b,x
        sta PIECE_B,x
        dex
        bpl -
}
        ldx #piece_c_end - piece_c - 1
-       lda piece_c,x
        sta PIECE_C,x
        dex
        bpl -
        ldx #piece_d_end - piece_d - 1
-       lda piece_d,x
        sta PIECE_D,x
        dex
        bpl -
        ;; both IRQ paths: the KERNAL's, and the game's own at $0380 (its
        ;; JSR SCNKEY / LDA $DC0D become a JSR to ours)
        lda #<kirq
        sta $0314
        lda #>kirq
        sta $0315
        lda #$78                ; SEI (its $6C03 did a CLI), JSR airq
        sta $038c
        lda #$20
        sta $038d
        lda #<airq
        sta $038e
        lda #>airq
        sta $038f
        lda #$ea
        sta $0390
        sta $0391
        ;; CIA 1 timer B: the player's tick, at the rate it sets per song
        lda #$9a
        sta $dc06
        lda #$42
        sta $dc07
        lda #$11                ; load, run continuously
        sta $dc0f
        lda #$82                ; its interrupt on
        sta $dc0d
        ;; the flags the game tests: the music there ($C8 bit 6, which a
        ;; C128 sets too), and on ($79 bit 7, the "Volume" toggle)
        lda $c8
        ora #$40
        sta $c8
        lda #$80
        sta $79
        cli
        rts

;;; ==================================================================
;;; piece A, at $0123: the API and the interrupts
;;; ==================================================================
piece_a:
!pseudopc PIECE_A {
        rts                     ; $0123: the C128's init (nothing calls it)
        nop
        nop
        ldy #<AR_J_MUTE         ; $0126
        !byte $2c               ; (BIT abs: over the next LDY)
        ldy #<AR_J_UNMUTE       ; $0129
;;; call the AR's entry whose low byte is in Y, with its RAM in view; keeps X.
;;; Interrupts off *before* the operand is set: the IRQ has its own ar_call,
;;; and one landing in between left the game's unmute calling the tick.
ar_call:
        php
        sei
        sty arc + 1
        lda $01
        pha
        ora #MAP
        sta $01
        lda #AR_ON
        sta AR_REG
arc:    jsr AR_BASE
        lda #AR_OFF
        sta AR_REG
        pla
        sta $01
        plp
ac_rts: rts

;;; the KERNAL's IRQ path, $0314 (the KERNAL in, A, X and Y pushed)
kirq:   jsr irq
        bcs +
        jmp $ea81               ; not timer A: just return
+       jmp $ea31               ; timer A: the KERNAL's own work

;;; the game's own IRQ handler at $0380, after its $6C03 (I/O and KERNAL in,
;;; and a CLI -- so a pending interrupt may already have gone through kirq).
;;; arinit puts an SEI in front of the JSR to it: a second interrupt inside a
;;; load (through kirq) found the song marked in, cleared `need`, and the
;;; load and the unmute never happened.  The handler's RTI puts I back.
airq:   jsr irq
        bcc +
        jsr $ff9f               ; timer A: the keyboard, as it did
+       rts

;;; both: the song the player is about to start into the AR first -- at a
;;; song's end it asks for the one the title walk or the ending selected
;;; ($03CD) by itself (armusic.py NEXT_SONG) -- then acknowledge and, on
;;; timer B, tick.  C = timer A.
irq:    lda $03cc
        and #$7f                ; (bit 7 is a flag)
        tax
        beq +
        jsr ensure              ; (a load only at a song boundary)
        jsr settle
+       ldy #<AR_J_IRQ
        jsr ar_call
        lsr irqf
        rts
}
piece_a_end:
!if PIECE_A + piece_a_end - piece_a > $0174 {
        !error "piece A runs into $0174, the stack: ", PIECE_A + piece_a_end - piece_a
}
!if AR_J_MUTE & $ff != (AR_J_UNMUTE & $ff) - 3 {
        !error "the jump table's layout changed"
}

;;; ==================================================================
;;; piece B, at $0200: the song loader (none on the EasyFlash: every song
;;; is in the bank)
;;; ==================================================================
!ifdef EF_MUSIC {
ensure = ac_rts
} else {
piece_b:
!pseudopc PIECE_B {
;;; song X (1-15) into the AR's RAM, unless it is there; keeps X.  With
;;; interrupts off: the callers make it and what follows one step.
ensure: ldy #<AR_J_ENSURE       ; the bookkeeping, in the AR: sets `need`,
        jsr ar_call             ; tc_addr, tc_len and the loader's target
        lda need
        beq +
        jsr aload               ; (tclib's transfers clobber X)
        ldx es_x
+       rts

;;; tc_len bytes from tc_addr into the AR's RAM at al_a's operand.  Each
;;; byte is stored with ROML and the AR's RAM in, which puts it in the C64's
;;; RAM under it as well, then the C64's own byte is put back with the AR
;;; off.  $01's bits 3-5 are the cart's lines: only bits 0-2 change.
aload:  jsr tc_enter
        lda #CMD_READ_FLASH
        jsr tc_sendbyte
        jsr tc_send_addr_len
        ldy #$00                ; tc_getbyte keeps Y
al_next:
        lda tc_len
        ora tc_len+1
        beq al_done
        jsr tc_getbyte
        sta al_b
al_c:   lda $ffff,y             ; the C64's byte (tclib banks all RAM)
        pha
        lda $01
        ora #MAP
        sta $01
        lda #AR_ON
        sta AR_REG
        lda al_b
al_a:   sta $ffff,y             ; the AR's RAM, and through to the C64's
        lda #AR_OFF
        sta AR_REG
        pla
al_k:   sta $ffff,y             ; the C64's byte back
        lda $01
        and #$ff - MAP
        sta $01
        iny
        bne +
        inc al_c + 2
        inc al_a + 2
        inc al_k + 2
+       lda tc_len
        bne +
        dec tc_len+1
+       dec tc_len
        jmp al_next
al_done:
        jmp tc_leave
es_p:   !word 0                 ; (ar_ensure's: the song playing, where it
es_n:   !word 0                 ; is and its length)
}
piece_b_end:
!if PIECE_B + piece_b_end - piece_b > $0277 {
        !error "piece B runs past $0276: ", PIECE_B + piece_b_end - piece_b
}
}

;;; ==================================================================
;;; piece C, at $0335: play and restart
;;; ==================================================================
piece_c:
!pseudopc PIECE_C {
;;; $6C40 (temp.subs $76B8 jumps here): play song X, as subs.128's $7912
aplay:  php                     ; the load, the request and the mute's
        sei                     ; return as one: the IRQ has its own
        txa                     ; (and its own use of `need`)
        beq +                   ; 0 is silence: nothing to load
        jsr ensure
+       stx $03cd
        stx $03cc
        jsr settle
        plp
        lda $79
        bpl ++
        ldy #$ff
        tya
-       cpx $03ce               ; until the player has it
        beq ++
        dey
        bne -
        sbc #$01                ; the carry is CPX's: 1 or 2 a round, and
        bcs -                   ; the borrow ends it either way (BNE never
++                              ; did from $FF in steps of 2: a hang on a
        rts                     ; C64 when the player does not take it up)

;;; $6C46 (temp.subs $76BF): the selected song again -- which may have been
;;; dropped from the cache since.  Keeps X and Y, as the original did.
arestart:
        txa
        pha
        tya
        pha
        php
        sei
        ldx $03cd
        beq +
        jsr ensure
+       lda $03cd
        sta $03cc
        jsr settle
        plp
        pla
        tay
        pla
        tax
        lda $03cd
        rts


;;; the AR side's scratch (C64 RAM: a store to the AR's own would reach the
;;; game's RAM under it, and the window is full)
es_l:   !word 0                 ; `loaded` before a flush
es_t:   !word 0                 ; bitof's result
es_c:   !byte 0                 ; the song playing
}
piece_c_end:
!if PIECE_C + piece_c_end - piece_c > $0380 {
        !error "piece C runs into $0380, the IRQ handler: ", PIECE_C + piece_c_end - piece_c
}

;;; ==================================================================
;;; piece D, at $0100: the player's zero page, the glue's variables, settle
;;; ==================================================================
piece_d:
!pseudopc PIECE_D {
zpsave: !fill 11, 0             ; the player's $50-$5A, between ticks
need:   !byte 0
al_b:   !byte 0
loaded: !word 0                 ; a bit per song, 1-15
alloc:  !word SONGS_AR          ; where the next song goes
oldmute: !byte 0
es_x:   !byte 0
es_m:   !word 0
es_e:   !byte 0
irqf:   !byte 0                 ; $DC0D, as ar_irq read it
;;; after a load, and only once the player has been asked for the new song:
;;; the mute as it was.  Unmuted earlier, the next tick would play on in the
;;; old song -- whose data the load may just have overwritten.
settle: lsr need                ; (0 or 1: C = it, and it is 0 again)
        bcc +
        ldy #<AR_J_REST
        jmp ar_call
+       rts
}
piece_d_end:
!if PIECE_D + piece_d_end - piece_d > $0123 {
        !error "piece D runs into $0123"
}

;;; ==================================================================
;;; the AR's block: the player, then ar_ensure -- run with the AR mapped
;;; ==================================================================
ar_block:
!pseudopc AR_BASE {
        jmp AR_P_INIT
        jmp AR_P_TICK
        jmp AR_P_MUTE
        jmp AR_P_UNMUTE
        jmp AR_P_SWAP
        jmp ar_ensure
        jmp ar_rest
        jmp ar_irq
        jmp ar_next
        jmp tc_getbyte_guard
        jmp ar_pick
!if * != AR_CODE {
        !error "the player's code is assembled for ", AR_CODE, ", not ", *
}
!ifdef EF_MUSIC {
!binary "efplayer.bin"          ; the player and all 15 songs (armusic.py, resident)
ar_ensure:                      ; (nothing to load: the jump table's entry stays)
        rts
} else {
!binary "arplayer.bin"
;;; X = the song.  Loaded: need = 0.  Not: make room, point the player
;;; at where it goes, mute it for the load, and set the loader up; need = 1.
;;; Making room: when the rest of the RAM is too small, every song is
;;; dropped but the one playing ($03CE), which the player is in the middle
;;; of, and the new one goes before it or after it -- with the longest song
;;; 1100 bytes and 5 KiB of room, one of the two always fits.  Keeps X.
ar_ensure:
        stx es_x
        lda #$00
        sta need
        jsr bitof
        lda es_t
        and loaded
        bne es_have
        lda es_t + 1
        and loaded + 1
        beq es_load
es_have:
        jmp es_out
es_load:
        lda es_t
        sta es_m
        lda es_t + 1
        sta es_m + 1
        ;; its offset and length, from the header's big-endian offsets
        ldx es_x
        jsr lenof
        sta tc_len
        stx tc_len + 1
        ldx es_x
        txa
        asl
        tay
        clc
        lda AR_HEADER + 1,y
        adc #<SONGS_FLASH
        sta tc_addr
        lda AR_HEADER + 0,y
        adc #>SONGS_FLASH
        sta tc_addr + 1
        lda #^SONGS_FLASH
        adc #$00
        sta tc_addr + 2
        ;; room?
        clc
        lda alloc
        adc tc_len
        sta es_e
        lda alloc + 1
        adc tc_len + 1
        cmp #>AR_TOP
        bcc es_fits
        bne es_full
        lda es_e
        cmp #<AR_TOP
        beq es_fits
        bcc es_fits
es_full:
        jsr es_keep
es_fits:
        ;; the player's pointer for it, and the loader's target
        lda es_x
        asl
        tay
        lda alloc
        sta AR_POINTERS,y
        sta al_c + 1
        sta al_a + 1
        sta al_k + 1
        lda alloc + 1
        sta AR_POINTERS + 1,y
        sta al_c + 2
        sta al_a + 2
        sta al_k + 2
        clc
        lda alloc
        adc tc_len
        sta alloc
        lda alloc + 1
        adc tc_len + 1
        sta alloc + 1
        lda loaded
        ora es_m
        sta loaded
        lda loaded + 1
        ora es_m + 1
        sta loaded + 1
        ;; quiet while the cart holds the machine: mute, remembering how it was
        lda AR_MUTEB
        sta oldmute
        jsr AR_J_MUTE
es_muted:
        inc need
es_out: ldx es_x
        rts

;;; drop every song but the one playing; alloc: where the new one goes
es_keep:
        lda loaded
        sta es_l
        lda loaded + 1
        sta es_l + 1
        lda #$00
        sta loaded
        sta loaded + 1
        lda #<SONGS_AR
        sta alloc
        lda #>SONGS_AR
        sta alloc + 1
        ldx $03ce
        beq ek_out
        cpx es_x
        beq ek_out
        stx es_c
        jsr bitof
        lda es_t
        and es_l
        sta loaded
        lda es_t + 1
        and es_l + 1
        sta loaded + 1
        ora loaded
        beq ek_out              ; not in (then there is nothing to keep)
        ldx es_c
        jsr lenof
        sta es_n
        stx es_n + 1
        lda es_c
        asl
        tay
        lda AR_POINTERS,y
        sta es_p
        lda AR_POINTERS + 1,y
        sta es_p + 1
        ;; before it, if the new one fits between the start and it
        sec
        lda es_p
        sbc #<SONGS_AR
        tax
        lda es_p + 1
        sbc #>SONGS_AR
        cmp tc_len + 1
        bcc ek_after
        bne ek_out
        cpx tc_len
        bcs ek_out
ek_after:
        clc                     ; else after it
        lda es_p
        adc es_n
        sta alloc
        lda es_p + 1
        adc es_n + 1
        sta alloc + 1
ek_out: rts

;;; es_t = 1 << (X - 1); X is 1-15
bitof:  lda #$00
        sta es_t
        sta es_t + 1
        sec
-       rol es_t
        rol es_t + 1
        dex
        bne -
        rts

;;; A/X = the length of song X: the next offset less its own
lenof:  txa
        asl
        tay
        sec
        lda AR_HEADER + 3,y
        sbc AR_HEADER + 1,y
        pha
        lda AR_HEADER + 2,y
        sbc AR_HEADER + 0,y
        tax
        pla
        rts
}

;;; a song's end, from the player's tick ($7887, armusic.py NEXT_SONG), A =
;;; $03CC = the song to play now.  The one that just ended, again: at once,
;;; as the original did -- it is in the RAM.  Another: on the next tick,
;;; once the IRQ has made sure it is loaded.
ar_next:
        cmp $03ce
        bne +
        jmp AR_P_START
+       rts

;;; the interrupt: timer B running again, acknowledge, keep what it was,
;;; tick on timer B.  The KERNAL's serial routines ($ED94, $EE22) use timer
;;; B as a one-shot for the IEC timeout -- and startup's drive check at the
;;; main menu ($8417, between a mute and an unmute) runs them: the timer
;;; stopped after one underflow and so did the music, and the next song
;;; request waited for a tick that never came (the hang at Create and
;;; Journey Onward).  Continuous again, without a force-load, costs one
;;; interrupt of timer A at most, and nothing while the timer is ours.
ar_irq: lda #$01                ; running, continuous
        sta $dc0f
        lda $dc0d
        sta irqf
        and #$02
        beq +
        jmp AR_J_TICK
+       rts

ar_rest:
        lda oldmute
        sta AR_MUTEB
        rts

;;; ==================================================================
;;; The driver's 2-bit reads (u5drv.s): it has no room for them, so they
;;; are here, and its trampolines map the AR in around each call ($01 =
;;; $27, so ROML is seen; $DE00 = AR_ON) and out again after.
;;;
;;; ar_pick, from tc_host_pick after tc_enter: with a sprite enabled the
;;; reads stay 1-bit (TC_GUARD dodges badlines, not sprite DMA): tclib's
;;; fetches back at tc_getbyte and A's READ_FLASH kept.  Otherwise both at
;;; the driver's u5_arget, and READ_FLASH_FAST.
;;; ==================================================================

;;; The receive: TC_GUARD's, with its port values fixed for $01 bits 0-2 =
;;; %111 throughout (tcfast.s TC_F_*): nothing patches this copy, and the
;;; ROML it runs from needs LORAM and HIRAM.  Those two bits, read back in
;;; the second read of each pair, flip bits 0 and 1 of each nibble: the
;;; table takes them out (TC_F_XOR).  Same cycles as tclib's, and the same
;;; badline check; tests/test_tc_guard.py runs both.
TC_GUARD      = 1
TC_GUARD_BARE = 1
BIT_SENSE     = $10
TC_GIO        = $27             ; ROML, I/O, KERNAL; write low
TC_F_START    = $3f             ; ... write high, sense high: the start
TC_F_DFAST    = $27             ; U5's DDR $2F, write as an input
TC_F_DFEND    = $2f
TC_F_END      = $37             ; write low again
TC_F_XOR      = %00000011
!source "tcguard.s"

ar_pick:
        ldx $d015
        bne ap_slow
        lda #<u5_arget
        ldx #>u5_arget
        jsr ap_set
        lda #CMD_READ_FLASH_FAST
        rts
ap_slow:
        lda #<tc_getbyte
        ldx #>tc_getbyte
        jsr ap_set
        lda #CMD_READ_FLASH
        rts
ap_set: sta tc_fetch + 1
        stx tc_fetch + 2
        sta tc_sb_call + 1
        stx tc_sb_call + 2
        rts
}
ar_block_end:
SONGS_AR = AR_BASE + ar_block_end - ar_block    ; the songs go after it
