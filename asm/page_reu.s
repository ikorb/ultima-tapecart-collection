;;; page_reu.s -- the launcher's REU line on Ultima VI's page.
;;;
;;; Ultima VI uses a Commodore REU of 256 KB or more when it finds one
;;; (ultima/games/u6/u6reu.s: a read cache; u6wc.s: saves write only what
;;; changed, by the REU's verify command).  In the game that is easy to miss,
;;; so the page says it, below the saved game and a blank line:
;;;
;;;     REU: 512 KB, for loads and saves
;;;     REU: 512 KB, for loads only          (and why, a line further down:
;;;       its verify command failed            the game makes the same test)
;;;     REU: 128 KB, too small to use
;;;
;;; and nothing without one.  The tests are the game's (reu_init): the
;;; address registers hold what is written (an open bus answers itself), a
;;; byte stashed comes back (an Action Replay's RAM at $DF00 holds values
;;; but moves nothing); the size from where the banks wrap; then verify: a
;;; page the same (no error), its last byte different, its first (an error
;;; each).  The REU's contents are the game's to clear: reu_init trusts
;;; nothing in it.
;;;
;;; Not in page.s, which is full: after the menu, in the 512 bytes below the
;;; export tables (launcher.py REU_ORG), in the launcher's PRG.  Uses page.s's pr and
;;; prdec16 (page_reu_syms.inc).  Runs as the page does: KERNAL in, $01 =
;;; $36, so every transfer starts at once (command bit 4 set) and touches
;;; only RAM below $D000.

!source "page_reu_syms.inc"     ; generated: pr, prdec16

REU_STATUS = $df00
REU_CMD    = $df01
REU_REGS   = $df02              ; C64 address (2), REU address (3), length (2)
REU_MASK   = $df09
REU_CTRL   = $df0a
STASH      = $90                ; at once
FETCH      = $91
VERIFY     = $93
VFAIL      = %00100000

        * = REU_ORG
reu_line:
        lda #$00
        sta REU_MASK            ; (no interrupts; both addresses count up)
        sta REU_CTRL
        ldx #$03                ; 1. the address registers hold what is written
-       txa
        eor #$a5
        sta REU_REGS,x
        dex
        bpl -
        ldx #$03
-       txa
        eor #$a5
        cmp REU_REGS,x
        bne rl_none
        dex
        bpl -
        lda #$00                ; 2. bank 0 := 0; then bank n := n, for n = 1, 2,
        sta rl_b                ;    4 .. 128: each must come back, and once bank
        sta rl_v                ;    0 reads n, the REU has n banks
        jsr rl_byte_stash
        lda #$01
        sta rl_n
        bne rl_size             ; (always)
rl_none:
        rts
rl_size:
        lda rl_n
        sta rl_b
        sta rl_v
        jsr rl_byte_stash
        lda #$ff
        sta rl_v
        jsr rl_byte_fetch       ; (bank n into rl_v)
        lda rl_v
        cmp rl_n
        bne rl_none             ; nothing moved: not an REU
        lda #$00
        sta rl_b
        lda #$ff
        sta rl_v
        jsr rl_byte_fetch       ; bank 0
        lda rl_v
        cmp rl_n
        beq rl_sized            ; it wrapped
        asl rl_n
        bne rl_size
rl_sized:                       ; rl_n banks (0: 256 of them, 16 MB)
        jsr pr
        !pet 13,"   REU: ",0                ; a blank line before it
        lda #$00
        sta rl_kb+1
        lda rl_n
        bne +
        inc rl_kb+1             ; 256 banks
+       ldx #$06                ; x 64 KB
-       asl
        rol rl_kb+1
        dex
        bne -
        ldx rl_kb+1
        jsr prdec16
        lda rl_n
        beq rl_big
        cmp #$04
        bcs rl_big
        jsr pr
        !pet " KB, too small to use",13,0
        rts
rl_big: jsr rl_verify
        bcs rl_bad
        jsr pr
        !pet " KB, for loads and saves",13,0
        rts
rl_bad: jsr pr
        !pet " KB, for loads only",13
        !pet "     its verify command failed",13,0
        rts

;;; 3. the verify test, as the game's reu_init makes it: C clear if it works.
;;; This page (its own code, which stays as it is) to REU $000000, then
;;; compared: the same; its last byte different there; its first.
rl_verify:
        lda #STASH
        jsr rl_page
        lda #VERIFY
        jsr rl_page             ; the same: no error
        bne rl_vbad
        lda reu_line+255        ; its last byte different
        eor #$ff
        ldx #$ff
        jsr rl_poke
        lda #VERIFY
        jsr rl_page
        beq rl_vbad             ; no error: broken
        lda reu_line+255        ; back, and its first byte different
        ldx #$ff
        jsr rl_poke
        lda reu_line
        eor #$ff
        ldx #$00
        jsr rl_poke
        lda #VERIFY
        jsr rl_page
        beq rl_vbad
        clc
        rts
rl_vbad:
        sec
        rts

;;; A = the command, for this page and REU $000000; then A = its verify
;;; error bit (Z set: none).  The status is read first, which clears it.
rl_page:
        pha
        lda REU_STATUS
        lda #<reu_line
        sta REU_REGS
        lda #>reu_line
        sta REU_REGS+1
        lda #$00
        sta REU_REGS+2
        sta REU_REGS+3
        sta REU_REGS+4
        sta REU_REGS+5          ; 256 bytes
        lda #$01
        sta REU_REGS+6
        pla
        sta REU_CMD
        lda REU_STATUS
        and #VFAIL
        rts

;;; A to REU $0000xx, X = xx
rl_poke:
        sta rl_v
        stx rl_off
        lda #$00
        sta rl_b
        lda #STASH
        !byte $2c               ; (BIT abs: skip the LDA)
;;; rl_v <-> REU bank rl_b, address 0 (or rl_off's, for rl_poke)
rl_byte_fetch:
        lda #FETCH
        !byte $2c
rl_byte_stash:
        lda #STASH
        pha
        lda #<rl_v
        sta REU_REGS
        lda #>rl_v
        sta REU_REGS+1
        lda rl_off
        sta REU_REGS+2
        lda #$00
        sta rl_off              ; (once)
        sta REU_REGS+3
        sta REU_REGS+6
        lda rl_b
        sta REU_REGS+4
        lda #$01
        sta REU_REGS+5
        pla
        sta REU_CMD
        rts

rl_n:   !byte 0
rl_b:   !byte 0
rl_v:   !byte 0
rl_off: !byte 0
rl_kb:  !word 0
reu_line_end:
!if reu_line_end > REU_ORG + $200 {
        !error "page_reu.s is ", reu_line_end - REU_ORG - $200, " bytes over its room"
}
