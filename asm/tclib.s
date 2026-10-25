;;; tclib.s -- shared tapecart access library for the Ultima Tapecart Collection
;;;
;;; Assembler: acme.  Include from a wrapper that defines TCLIB_ORG and TCZP,
;;; then !source "tclib.s".
;;;
;;; Protocol per the tapecart project's doc/ProgRef.md.  The byte
;;; transmit/receive sequences are ports of its src-c64/{blockwrite,
;;; getbyte_fast}.s and tapecartif.c (Ingo Korb, BSD 2-clause: NOTICE.md).  The fast-read inner loop is CYCLE EXACT and must not be
;;; "optimised": every access to $00/$01 has to stay on the same cycle
;;; relative to the write line going high, on both PAL and NTSC.
;;;
;;; How this differs from the stock tapecart code, and why:
;;;
;;;  * The stock code hardcodes $01 values ($26/$36/$38...), which also pin the
;;;    banking bits.  We cannot do that -- these routines run inside six games
;;;    that each have their own banking discipline.  Instead everything runs in
;;;    all-RAM banking, which is also what lets a load land under I/O or ROM,
;;;    and the caller's $01 is saved and restored around each operation.
;;;
;;;  * Because all-RAM means no KERNAL, every entry point that touches the bus
;;;    runs with interrupts disabled.  The 1-bit protocol is not timing
;;;    critical, so an interrupt-friendly variant is possible; U6 will need one
;;;    (it plays music from an IRQ while loading).  Not implemented yet.
;;;
;;;  * MOTOR MUST STAY OFF.  $01 bit 5 low drops the cart back to streaming
;;;    mode and costs ~70ms to recover.  Every value written here has bit 5
;;;    set, and the host game must never clear it.

CMD_EXIT              = $00
CMD_READ_DEVICEINFO   = $01
CMD_READ_DEVICESIZES  = $02
CMD_READ_CAPABILITIES = $03
CMD_READ_FLASH        = $10
CMD_READ_FLASH_FAST   = $11
CMD_WRITE_FLASH       = $12
CMD_ERASE_FLASH_64K   = $14
CMD_ERASE_FLASH_BLOCK = $15
CMD_CRC32_FLASH       = $16
CMD_LED_OFF           = $30
CMD_LED_ON            = $31
CMD_DIR_SETPARAMS     = $40
CMD_DIR_LOOKUP        = $41
CMD_LED_OFF           = $30
CMD_LED_ON            = $31

;;; port bit assignments in $00/$01
BIT_WRITE = %00001000
BIT_SENSE = %00010000
BIT_MOTOR = %00100000           ; 1 = motor OFF

;;; The values tc_init derives at run time.  A host whose $00/$01 are known
;;; at build time defines TC_STATIC_01 (its $01, of which only bits 6/7
;;; matter) and TC_STATIC_00 (its DDR): the operands below are then
;;; assembled with the final values and tc_init is left out -- Ultima 6's
;;; in-game driver does, for the 70 bytes.  Otherwise they are placeholders
;;; tc_init overwrites.
!ifdef TC_STATIC_01 {
TC_K_BASE  = (TC_STATIC_01 & %11000000) | BIT_MOTOR
TC_K_NORM  = (TC_STATIC_00 | BIT_MOTOR | BIT_WRITE) & %11101111
TC_K_SOUT  = TC_K_NORM | BIT_SENSE
TC_K_S0    = TC_K_BASE
TC_K_S1    = TC_K_BASE | BIT_SENSE
TC_K_W1    = TC_K_BASE | BIT_WRITE
TC_K_W0    = TC_K_BASE
} else {
TC_K_BASE  = 0                  ; tc_init fills it in
TC_K_NORM  = $2f
TC_K_SOUT  = $3f
TC_K_S0    = $26
TC_K_S1    = $36
TC_K_W1    = $2e
TC_K_W0    = $26
}

;;; Parameters live in the library's own RAM, NOT in zero page.
;;;
;;; They used to sit at TCZP ($f7-$fe), which cost a long debugging session:
;;; Ultima 3's engine uses $f7 and $f8 heavily, so every transfer corrupted
;;; the game's state -- it lost the party's position and stranded it in the
;;; ocean.  There is no run of zero page that is free in all six games, so the
;;; transfer loops use self-modified absolute addressing instead.  That is
;;; also a cycle faster per byte than (zp),y.

;;; Two knobs for a host that is not a C64 (Ultima V's C128 launcher): which
;;; bits of the caller's $01 the transfers keep, and which tc_cmdmode sets to
;;; see CIA 1.  On a C64 bits 0-2 are the banking, so transfers clear them
;;; (all RAM) and the handshake sets LORAM+CHAREN (I/O); on a C128 in its own
;;; mode the MMU banks, and bits 0-2 pick the colour RAM bank the CPU and the
;;; VIC see and the VIC's character ROM -- clearing them shows the other
;;; colour bank for as long as a transfer runs.
!ifndef TC_KEEP_01 {
TC_KEEP_01 = %11000000
}
!ifndef TC_IO_01 {
TC_IO_01 = %00000101
}

;;; TC_GUARD -- the 2-bit read with the screen on.  Only ~53 cycles of a
;;; READ_FLASH_FAST byte are timed, from the C64's start signal to its last
;;; port write: the C64 starts every byte, and the firmware waits for that
;;; start without a timeout (src-firmware/avr/bitbanging.S fast_sendbyte).
;;; So tc_getbyte_guard reads the raster before each byte and starts only
;;; where the timed part cannot meet a badline (see there) -- no blanking.
;;; Sprite DMA it does not dodge: tc_read and tc_stream_open use the 1-bit
;;; read whenever a sprite is enabled, so those transfers cost what they
;;; always did.  With TC_IRQ_ON the check and the timed part of each byte
;;; run with interrupts masked (an interrupt waits at most a line or so);
;;; every IRQ handler must then keep $01's bits 3-5.  The check needs
;;; tc_init.
;;; TC_FAST2 is "the timed receive is assembled", by either option.
!ifndef TC_NO_FAST {
TC_FAST2 = 1
}
!ifdef TC_GUARD {
!ifndef TC_FAST2 {
TC_FAST2 = 1
}
!ifdef TC_STATIC_01 {
!error "TC_GUARD needs tc_init, not TC_STATIC_01"
}
!ifdef TC_IRQ_ON {              ; tcguard.s masks interrupts for each byte's
!ifndef TC_F_PLP { TC_F_PLP = 1 }       ; check and timed part, tcfast.s
}                               ; unmasks (tcguard.s sets it too, for a copy
                                ; assembled before this file: TC_GUARD_ELSEWHERE)
!ifdef TC_IRQ_ON {
!ifndef TC_NO_FAST {
!error "TC_GUARD with TC_IRQ_ON needs TC_NO_FAST: tc_getbyte_fast has no PHP"
}
}
}

;;; TC_PICK = 1: the host's tc_host_pick makes the choice tc_pick makes for
;;; TC_GUARD, its own way: tc_read and tc_stream_open call it after
;;; tc_enter, and it returns the read command in A and has pointed tc_fetch
;;; and tc_sb_call at the matching receive (or left them at tc_getbyte, as
;;; assembled).  Ultima 5 does, to read through the Action Replay's RAM.
!ifdef TC_PICK {
!ifdef TC_GUARD {
!error "TC_PICK and TC_GUARD are two ways of doing the same"
}
}
;;; TC_FETCH = where tc_fetch and tc_sb_call go as assembled (tc_getbyte):
;;; Ultima 5's C128 build points them into bank 1 for good, and its pick
;;; there chooses.
!ifndef TC_FETCH {
TC_FETCH = tc_getbyte
}

;;; TC_NMI_HOLD -- no NMI while the cart talks (needs TC_GUARD).  RESTORE's
;;; NMI inside a timed byte would corrupt it, and an NMI cannot be masked;
;;; it is edge triggered, though, and CIA 2 holds its line low until its
;;; interrupt is acknowledged.  So tc_enter lets CIA 2's timer A run out once
;;; with its NMI on and leaves it unacknowledged: no RESTORE pulse can make
;;; an edge until tc_leave reads $DD0D.  The one NMI that is taken, timer
;;; A's, goes through the RAM's vector at $FFFA (the ROMs are out) to an
;;; RTI; the vector is put back straight after, before anything is loaded,
;;; since no other NMI can get in (a load may well land on $FFFA).  Before,
;;; a RESTORE during a transfer jumped through whatever that RAM held.  For
;;; a game that leaves CIA 2's timer A and interrupt mask alone.
!ifdef TC_NMI_HOLD {
!ifndef TC_GUARD {
!error "TC_NMI_HOLD needs TC_GUARD"
}
}

        * = TCLIB_ORG

;;; TC_EXTRAS_ONLY assembles just the stream API, erase and write -- the
;;; routines built on the core below -- for a host whose core lives elsewhere:
;;; Ultima 6's on-demand driver part, which links against the resident one's.
!ifndef TC_EXTRAS_ONLY {
;;; ==================================================================
;;; tc_init -- derive our port/DDR values from the caller's $00/$01.
;;; Call once, early.  Clobbers A.
;;; ==================================================================
!ifndef TC_STATIC_01 {
!ifndef TC_INIT_ELSEWHERE {
!source "tcinit.s"
}
}   ; !ifndef TC_STATIC_01

tc_addr:    !byte 0,0,0        ; flash offset, little endian
tc_len:     !byte 0,0          ; byte count
tc_dest:    !byte 0,0          ; C64 destination (or source, for writes)
tc_tmp:     !byte 0            ; bit shifter
!ifndef TC_STATIC_01 {
tc_v_base:  !byte TC_K_BASE
} else {
!ifndef TC_NO_CMDMODE {
tc_v_base:  !byte TC_K_BASE     ; (static builds read it as an immediate)
}
}
tc_save01:  !byte 0
!ifndef TC_NO_CMDMODE {
tc_ctr:     !byte 0             ; loop counter that survives tc_delay
tc_tohi:    !byte 0             ; timeout high byte
}

;;; ==================================================================
;;; Two options for hosts with their own interrupt handling (Ultima 6):
;;;   TC_IRQ_ON  -- tc_enter does not SEI.  Only the 1-bit protocol is safe
;;;                 with interrupts on, and only if every IRQ handler leaves
;;;                 $01 bits 3/4 (cassette write/sense) alone -- U6's write
;;;                 $35, which clears bit 3, and are patched for this.
;;;   TC_NO_C0   -- tc_leave does not re-arm $C0.  That is the KERNAL's tape
;;;                 interlock and only matters under the KERNAL IRQ; in U6's
;;;                 game $C0 is inside a zero-page object list at $B6,X.
;;; ==================================================================
;;; tc_enter / tc_leave -- bracket every bus operation.
;;; tc_enter saves $01, disables interrupts and selects all-RAM banking.
;;;
;;; THE LED.  The cart lights its LED on entering command mode, and command
;;; mode is held for the whole session, so it would glow throughout.  Instead
;;; tc_enter turns it on and tc_leave off: lit while data moves, dark
;;; otherwise, like a drive's.  Two one-byte commands per operation, a few
;;; hundred cycles; TC_NO_LED leaves them out (the timing probes).  Both
;;; still keep X, Y and the carry, as they always have.
;;;
;;; TC_SCREEN_LED -- a screen byte that is a second LED, for a game whose
;;; waits are long and whose cart may be out of sight (U6): tc_enter stores
;;; TC_SCREEN_ON there, tc_leave TC_SCREEN_OFF (constants, so a pair that
;;; does not match cannot leave it lit).  It must be RAM in all-RAM banking
;;; and nothing the game itself ever changes.  Ten bytes, ~12 cycles.
;;; ==================================================================
tc_enter:
!ifndef TC_IRQ_ON {
        sei
}
        lda $01
        sta tc_save01
!ifdef TC_NMI_HOLD {
        lda tc_v_gio+1          ; I/O in, and the RAM under the ROMs
        sta $01
        lda $fffa
        sta tc_nmiv
        lda $fffb
        sta tc_nmiv+1
        lda #<tc_rti
        sta $fffa
        lda #>tc_rti
        sta $fffb
        lda #$01                ; timer A from 1, one shot, its NMI on
        sta $dd04
        lda #$00
        sta $dd05
        lda #$81
        sta $dd0d
        lda #$19
        sta $dd0e
        nop                     ; it runs out ~3 cycles on, and the NMI is
        nop                     ; taken at the next instruction's end
        nop
        nop
        nop
        lda tc_nmiv             ; nothing else can get in now
        sta $fffa
        lda tc_nmiv+1
        sta $fffb
}
!ifdef TC_STATIC_01 {
        lda #TC_K_BASE
} else {
        lda tc_v_base
}
        sta $01
tc_d_norm:
        lda #TC_K_NORM          ; patched
        sta $00
!ifdef TC_SCREEN_LED {
        lda #TC_SCREEN_ON
        sta TC_SCREEN_LED
}
!ifndef TC_NO_LED {
        lda #CMD_LED_ON
        jmp tc_led
} else {
        rts
}

tc_leave:
!ifdef TC_SCREEN_LED {
        lda #TC_SCREEN_OFF
        sta TC_SCREEN_LED
}
!ifndef TC_NO_LED {
        lda #CMD_LED_OFF
        jsr tc_led
}
tc_leave_quiet:                 ; (tc_cmdmode: a cart that may not be in
                                ; command mode must not be sent anything)
        ;; Re-arm the kernal's tape motor interlock before anyone can CLI.
        ;; The kernal IRQ handler CLEARS $C0 whenever sense is high, so
        ;; setting it once at boot is not enough: after a write or erase the
        ;; cart holds sense low while it is busy, and an IRQ arriving in that
        ;; window with $C0 == 0 does AND #$1F on $01 -- motor on -- which
        ;; drops the cart straight back to streaming mode.  ProgRef says to
        ;; set it "after transmitting a byte but before re-enabling
        ;; interrupts"; here is the one place that is always true.
!ifndef TC_NO_C0 {
        lda #$01
        sta $c0
}
!ifdef TC_NMI_HOLD {
        lda tc_v_gio+1
        sta $01
        lda #$01                ; timer A's NMI off, and acknowledged:
        sta $dd0d               ; the line goes high
        lda $dd0d
}
        lda tc_save01
        ora #BIT_MOTOR          ; never hand back a motor-on value
        sta $01
        rts

!ifdef TC_NMI_HOLD {
tc_nmiv:    !word 0
tc_rti:     rti
}

!ifndef TC_NO_LED {
;;; send the one-byte command in A, keeping X, Y and the flags
tc_led: php
        stx tc_ledx
        jsr tc_sendbyte
        ldx tc_ledx
        plp
        rts
tc_ledx:    !byte 0
}

;;; ==================================================================
;;; Command mode entry, and the only routines that need it.  Once entered,
;;; command mode persists until the motor line goes active, so a program that
;;; is launched by something which has already entered it does not need this
;;; code.  Define TC_NO_CMDMODE to leave it out -- the Ultima 1 driver does,
;;; which buys back ~200 bytes of the space the old fastloader freed.
;;; ==================================================================
!ifndef TC_NO_CMDMODE {

;;; ==================================================================
;;; tc_cmdmode -- streaming mode -> command mode.
;;; C clear = success, C set = timeout.  Leaves interrupts disabled and the
;;; caller's banking restored.  Polls CIA1 ICR, so it banks I/O in for that.
;;; ==================================================================
tc_cmdmode:
        sei
        lda $01
        sta tc_save01
        lda tc_d_norm+1
        sta $00

        ;; I/O visible (for $dc0d), motor off, write low, sense low
        lda tc_v_base
        ora #TC_IO_01           ; CHAREN + LORAM -> I/O at $d000
        sta tc_v_io
        sta $01

        ;; make sure we are in streaming mode: motor on
        and #%11011111        ; clear BIT_MOTOR (motor ON)
        sta $01
        jsr tc_delay

        jsr tc_wait_sense_lo
        bcs tc_cm_fail

        lda tc_v_io             ; motor off again
        sta $01
        jsr tc_delay

        ;; clock out $fce2, MSB first, sampled on each motor rising edge
        lda #$fc
        sta tc_tmp
        lda #$e2
        sta tc_magic_lo
        lda #16
        sta tc_ctr
tc_cm_bits:
        asl tc_magic_lo
        rol tc_tmp
        lda tc_v_io
        bcc tc_cm_zero
        ora #BIT_WRITE
tc_cm_zero:
        sta $01                 ; set the write level first...
        jsr tc_delay
        and #%11011111        ; clear BIT_MOTOR (motor ON)
        sta $01                 ; ...then raise motor; the cart samples here
        jsr tc_delay
        ora #BIT_MOTOR
        sta $01
        dec tc_ctr
        bne tc_cm_bits

        jsr tc_delay
        lda tc_v_io
        ora #BIT_WRITE
        sta $01

        jsr tc_wait_sense_hi
        bcs tc_cm_fail

        ;; wait for 100 pulses on the read line (CIA1 ICR bit 4)
        jsr tc_delay
        lda #100
        sta tc_ctr
tc_cm_pulse:
        lda $dc0d               ; clear latched flags
        ldy #$00
        sty tc_tohi
tc_cm_pw:
        lda $dc0d
        and #%00010000
        bne tc_cm_gotpulse
        dey
        bne tc_cm_pw
        dec tc_tohi
        bne tc_cm_pw
        beq tc_cm_fail          ; always: timed out waiting for a pulse
tc_cm_gotpulse:
        dec tc_ctr
        bne tc_cm_pulse

        lda tc_v_io             ; write low, still I/O in
        sta $01
        lda #$01
        sta $c0                 ; stop the kernal IRQ from starting the motor
        jsr tc_leave_quiet      ; (the LED stays as entering lit it, until
        clc                     ; the first transfer's tc_leave)
        rts

tc_cm_fail:
        jsr tc_leave_quiet
        sec
        rts

tc_v_io:    !byte 0
tc_magic_lo:!byte 0

;;; ------------------------------------------------------------------
;;; helpers.  tc_delay preserves X and Y; the cmdmode loops depend on it.
;;; ------------------------------------------------------------------
tc_delay:
        stx tc_dsave
        ldx #$00
tc_delay_l:
        dex
        nop
        bne tc_delay_l
        ldx tc_dsave
        rts
tc_dsave:   !byte 0

tc_wait_sense_lo:
        ldy #$00
        sty tc_tohi
tc_wsl:
        lda $01
        and #BIT_SENSE
        beq tc_ws_ok
        dey
        bne tc_wsl
        dec tc_tohi
        bne tc_wsl
        sec
        rts

tc_wait_sense_hi:
        ldy #$00
        sty tc_tohi
tc_wsh:
        lda $01
        and #BIT_SENSE
        bne tc_ws_ok
        dey
        bne tc_wsh
        dec tc_tohi
        bne tc_wsh
        sec
        rts

tc_ws_ok:
        clc
        rts

}   ; !ifndef TC_NO_CMDMODE

;;; ==================================================================
;;; tc_sendbyte -- A = byte.  Clobbers A, X.  Port of blockwrite.s.
;;; Assumes tc_enter has run.
;;; ==================================================================
tc_sendbyte:
        sta tc_tmp
        lda #BIT_SENSE          ; wait until the cart is ready (sense high)
tc_sb_rdy:
        bit $01
        beq tc_sb_rdy

tc_d_sout:
        lda #TC_K_SOUT          ; patched: sense as output
        sta $00

        ldx #$08
tc_sb_bit:
        asl tc_tmp
        bcs tc_sb_one
tc_v_s0:
        lda #TC_K_S0            ; patched: sense low, write low
        bcc tc_sb_out           ; always (carry is clear here)
tc_sb_one:
tc_v_s1:
        lda #TC_K_S1            ; patched: sense high, write low
tc_sb_out:
        sta $01
        ora #BIT_WRITE          ; write high -- the cart samples sense now
        sta $01
        dex
        bne tc_sb_bit

        lda tc_v_s0+1           ; write low again, finishing the last bit
        sta $01
        lda tc_v_s1+1           ; sense high
        sta $01
        lda tc_v_s0+1           ; sense low
        sta $01
tc_d_norm2:
        lda #TC_K_NORM          ; patched: sense back to input
        sta $00
        nop                     ; give the cart time to turn its pin around
        rts

;;; ==================================================================
;;; tc_getbyte -- 1-bit receive, returns the byte in A.  Clobbers A, X.
;;;
;;; Each bit: write low (the cart puts the bit on sense when it sees the
;;; edge), write high 5 cycles later, sense read 8 cycles after the low edge,
;;; write high for 19 more: 24 cycles a bit.  Measured with a timing probe
;;; on a release (Cortex-M0, 48 MHz) and a DIY (AVR, 8 MHz) cart: reads 8 and
;;; even 6 cycles after the edge, low phases
;;; of 5 and 3, no errors in 5 x 32 KiB each.  The phases can only get longer
;;; in a game (badlines, sprites, interrupts all stretch them): the protocol
;;; is clocked by the C64.
;;; ==================================================================
tc_getbyte:
        lda #BIT_SENSE
tc_gb_rdy:
        bit $01
        beq tc_gb_rdy

        lda tc_v_w1+1           ; write high: the start
        sta $01
tc_v_w0:
        ldx #TC_K_W0            ; patched: write low
        lda #$01                ; the shifter, with a stop bit that comes
        sta tc_tmp              ; out of it after the eighth bit
tc_gb_bit:
        stx $01                 ; write low: the cart puts the bit out
tc_v_w1:
        lda #TC_K_W1            ; patched: write high
        sta $01
        lda $01                 ; 8 cycles after the low edge
        and #BIT_SENSE
        cmp #BIT_SENSE          ; C = the bit
        rol tc_tmp
        bcc tc_gb_bit
        stx $01                 ; write low
        lda tc_tmp
        rts

;;; The 2-bit path: tc_getbyte_fast, tc_read_fast, tc_blank/tc_unblank.
;;; Define TC_NO_FAST to leave all of it out -- Ultima 4 used to, when every
;;; byte it had was needed for the decruncher; TC_GUARD brings back the
;;; timed receive alone, without the blanking.
!ifdef TC_FAST2 {
!ifndef TC_NO_FAST {
;;; ==================================================================
;;; tc_getbyte_fast -- 2-bit receive, ~9500 bytes/s.
;;; CYCLE EXACT.  The screen must be blank and no sprites active, or a
;;; badline will stretch the timing and corrupt the byte.
;;; Clobbers A, X.  Preserves Y.
;;; ==================================================================
tc_getbyte_fast:
        ;; ready when sense is HIGH -- the opposite of loader mode
        lda #BIT_SENSE
tc_gf_rdy:
        bit $01
        beq tc_gf_rdy
!ifdef TC_GUARD {
        jmp tc_v_fstart         ; the body is tcguard.s's
} else {
!source "tcfast.s"
}
}
!ifdef TC_GUARD {
!ifndef TC_GUARD_ELSEWHERE {
!source "tcguard.s"
}
}
}   ; !ifdef TC_FAST2

!ifdef TC_GUARD {
;;; ==================================================================
;;; tc_pick -- after tc_enter: point tc_read's and tc_stream_byte's fetch
;;; at the guarded 2-bit receive, or at the 1-bit one if a sprite is
;;; enabled, and return the matching read command in A.  Keeps Y.
;;; ==================================================================
tc_pick:
        jsr tc_sprites
        bne tc_pick_1
        lda #<tc_getbyte_guard
        ldx #>tc_getbyte_guard
        jsr tc_pick_set
        lda #CMD_READ_FLASH_FAST
        rts
tc_pick_1:
        lda #<tc_getbyte
        ldx #>tc_getbyte
        jsr tc_pick_set
        lda #CMD_READ_FLASH
        rts
tc_pick_set:
!ifndef TC_EXTRAS_ONLY {
        sta tc_fetch+1
        stx tc_fetch+2
}
!ifndef TC_NO_STREAM {
        sta tc_sb_call+1
        stx tc_sb_call+2
}
        rts
}

;;; ==================================================================
;;; tc_send_addr_len -- push tc_addr (3 bytes) then tc_len (2 bytes)
;;; ==================================================================
tc_send_addr_len:
        lda tc_addr
        jsr tc_sendbyte
        lda tc_addr+1
        jsr tc_sendbyte
        lda tc_addr+2
        jsr tc_sendbyte
        lda tc_len
        jsr tc_sendbyte
        lda tc_len+1
        jmp tc_sendbyte

;;; ==================================================================
;;; tc_read      -- READ_FLASH      (1-bit), tc_len bytes tc_addr -> tc_dest
;;; tc_read_fast -- READ_FLASH_FAST (2-bit), same; screen must be blank
;;; Both consume tc_len and leave tc_dest as it was.  Both bracket with
;;; tc_enter/tc_leave, so the destination may sit under I/O or ROM.
;;; ==================================================================
tc_read:
        jsr tc_enter
!ifdef TC_GUARD {
        jsr tc_pick             ; 2 bits unless a sprite is on
        jmp tc_xfer_go
} else {
!ifdef TC_PICK {
        jsr tc_host_pick        ; the host's choice
        jmp tc_xfer_go
} else {
        lda #CMD_READ_FLASH
        ldx #<tc_getbyte
        ldy #>tc_getbyte
        bne tc_xfer             ; always ($10 != 0)
}
}

!ifndef TC_NO_FAST {
tc_read_fast:
        jsr tc_enter
        lda #CMD_READ_FLASH_FAST
        ldx #<tc_getbyte_fast
        ldy #>tc_getbyte_fast
}

;;; A = command, X/Y = byte-fetch routine
tc_xfer:
        stx tc_fetch+1
        sty tc_fetch+2
tc_xfer_go:
        jsr tc_sendbyte
        jsr tc_send_addr_len

        lda tc_dest             ; the store below is self-modified rather
        sta tc_store+1          ; than indexed through zero page
        lda tc_dest+1
        sta tc_store+2

        ldy #$00
tc_xfer_loop:
        lda tc_len
        ora tc_len+1
        beq tc_xfer_done
tc_fetch:
        jsr TC_FETCH            ; patched
tc_store:
        sta $ffff               ; patched
        inc tc_store+1
        bne tc_xfer_nc
        inc tc_store+2
tc_xfer_nc:
        lda tc_len
        bne tc_xfer_nb
        dec tc_len+1
tc_xfer_nb:
        dec tc_len
        jmp tc_xfer_loop

tc_xfer_done:
        jmp tc_leave
}   ; !ifndef TC_EXTRAS_ONLY

;;; ==================================================================
;;; Streaming read.  tc_stream_open starts a READ_FLASH of tc_len bytes at
;;; tc_addr and leaves the transfer open; tc_stream_byte hands back one byte
;;; per call; tc_stream_close drains whatever the caller did not take and
;;; releases the bus.
;;;
;;; This is what lets a compressed unit decrunch straight out of flash with
;;; no staging buffer: the zx02 decoders pull their input through a
;;; callback whose contract is "byte in A, X and Y untouched, carry and
;;; overflow untouched" -- which is exactly what tc_stream_byte provides.  tc_getbyte clobbers X and the flags, so both
;;; are saved around it.
;;;
;;; tc_len doubles as the remaining-bytes counter (tc_send_addr_len only
;;; reads it).  Reading past the end hands back $FF instead of hanging on a
;;; cart that has nothing left to send -- a decruncher fed a truncated
;;; stream should produce garbage, not a locked machine.
;;;
;;; Only the decruncher needs this; define TC_NO_STREAM to leave it out.
;;; Ultima 5 does, because it stores nothing crunched and needs the 64 bytes.
;;; ==================================================================
!ifndef TC_NO_STREAM {

tc_stream_open:
        jsr tc_enter
!ifdef TC_GUARD {
        jsr tc_pick             ; 2 bits unless a sprite is on
} else {
!ifdef TC_PICK {
        jsr tc_host_pick        ; the host's choice
} else {
        lda #CMD_READ_FLASH
}
}
        jsr tc_sendbyte
        jmp tc_send_addr_len

!ifndef TC_STREAM_EXACT {
tc_stream_byte:
        php
        stx tc_sx
        lda tc_len
        bne tc_sb_go
        lda tc_len+1
        beq tc_sb_empty
        dec tc_len+1            ; borrow; the dec below wraps tc_len to $ff
tc_sb_go:
        dec tc_len
tc_sb_call:
        jsr TC_FETCH            ; TC_GUARD: patched by tc_pick
        ldx tc_sx
        plp
        rts
tc_sb_empty:
        lda #$ff
        ldx tc_sx
        plp
        rts

tc_stream_close:
-       lda tc_len
        ora tc_len+1
        beq +
        jsr tc_stream_byte
        jmp -
+       jmp tc_leave
} else {
;;; TC_STREAM_EXACT: for a caller that always takes exactly tc_len bytes --
;;; a zx02 decoder ends on its own end marker, which is the stream's last
;;; byte -- no bookkeeping and nothing to drain.  Reading past the end hangs
;;; on a cart with nothing left to send instead of returning $FF.
tc_stream_byte:
        php
        stx tc_sx
tc_sb_call:
        jsr TC_FETCH            ; TC_GUARD: patched by tc_pick
        ldx tc_sx
        plp
        rts
tc_stream_close = tc_leave
}

}   ; !ifndef TC_NO_STREAM

tc_sx:      !byte 0

!ifndef TC_NO_ERASE {
;;; ==================================================================
;;; tc_erase_block -- erase the 4 KiB block containing tc_addr.
;;; The cart holds sense low while it is busy; the next tc_sendbyte waits
;;; for sense high, so callers self-synchronise with no explicit delay.
;;; ==================================================================
tc_erase_block:
        jsr tc_enter
        lda #CMD_ERASE_FLASH_BLOCK
        jsr tc_sendbyte
tc_send_addr:
        lda tc_addr
        jsr tc_sendbyte
        lda tc_addr+1
        jsr tc_sendbyte
        lda tc_addr+2
        jsr tc_sendbyte
        jmp tc_leave
}   ; !ifndef TC_NO_ERASE -- Ultima 6's in-game driver never erases

!ifndef TC_NO_WRITE {
;;; ==================================================================
;;; tc_write -- WRITE_FLASH of tc_len bytes from tc_dest to tc_addr.
;;; tc_dest is the SOURCE here.  The target must already be erased, and
;;; partial pages leave the rest of the page undefined -- write whole
;;; 256-byte pages.  Consumes tc_len and leaves tc_dest as it was.
;;; ==================================================================
tc_write:
        jsr tc_enter
        lda #CMD_WRITE_FLASH
        jsr tc_sendbyte
        jsr tc_send_addr_len

        lda tc_dest             ; self-modified source, see tc_xfer
        sta tc_fetchbyte+1
        lda tc_dest+1
        sta tc_fetchbyte+2

        ldy #$00                ; tc_sendbyte preserves Y
tc_wr_loop:
        lda tc_len
        ora tc_len+1
        beq tc_wr_done
tc_fetchbyte:
        lda $ffff               ; patched
        jsr tc_sendbyte
        inc tc_fetchbyte+1
        bne +
        inc tc_fetchbyte+2
+       lda tc_len
        bne ++
        dec tc_len+1
++      dec tc_len
        jmp tc_wr_loop

tc_wr_done:
        jmp tc_leave
}   ; !ifndef TC_NO_WRITE

!ifndef TC_NO_FAST {
;;; ==================================================================
;;; tc_blank / tc_unblank -- make the display safe for the fast protocol.
;;;
;;; READ_FLASH_FAST is cycle exact, so any VIC cycle stealing corrupts it.
;;; Two sources: badlines and sprite DMA.
;;;
;;; Clearing DEN ($d011 bit 4) is NOT enough on its own.  The VIC decides
;;; whether badlines may occur in a frame by sampling DEN during raster line
;;; $30; clearing it after that line has passed leaves badlines running for
;;; the rest of the current frame.  So we must wait for a full frame before
;;; the transfer starts -- which is what ProgRef means by "blank the screen
;;; and wait for 20ms", and why the stock loader gets away with it (its
;;; handshake takes ~50ms).
;;;
;;; The wait keys on raster line $f8, which occurs exactly once per frame on
;;; both PAL (312 lines) and NTSC (262), so no $d011 bit 8 test is needed.
;;;
;;; The caller must have I/O banked in.  Clobbers A.
;;; ==================================================================
tc_blank:
        lda $d011
        sta tc_save_d011
        lda $d015
        sta tc_save_d015
        lda #$00
        sta $d015               ; no sprite DMA either
        lda tc_save_d011
        and #%11101111          ; DEN off
        sta $d011

        ;; wait one full frame so the DEN clear is actually in effect
-       lda $d012
        cmp #$f8
        bne -
-       lda $d012
        cmp #$f8
        beq -                   ; leave the line
-       lda $d012
        cmp #$f8
        bne -                   ; and see it come round again
        rts

tc_unblank:
        lda tc_save_d011
        sta $d011
        lda tc_save_d015
        sta $d015
        rts

tc_save_d011: !byte 0
tc_save_d015: !byte 0
}   ; !ifndef TC_NO_FAST
