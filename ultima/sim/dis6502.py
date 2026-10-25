#!/usr/bin/env python3
"""A small 6502 decoder for the build: instruction lengths and operand kinds of
the documented opcodes, and a recursive-descent walk that tells code from
data by following every path from given entry points."""

# mode -> operand bytes
MODES = {"imp": 0, "acc": 0, "imm": 1, "zp": 1, "zpx": 1, "zpy": 1, "izx": 1, "izy": 1,
         "rel": 1, "abs": 2, "abx": 2, "aby": 2, "ind": 2}
_T = """
00 brk imp 01 ora izx 05 ora zp 06 asl zp 08 php imp 09 ora imm 0a asl acc 0d ora abs 0e asl abs
10 bpl rel 11 ora izy 15 ora zpx 16 asl zpx 18 clc imp 19 ora aby 1d ora abx 1e asl abx
20 jsr abs 21 and izx 24 bit zp 25 and zp 26 rol zp 28 plp imp 29 and imm 2a rol acc 2c bit abs 2d and abs 2e rol abs
30 bmi rel 31 and izy 35 and zpx 36 rol zpx 38 sec imp 39 and aby 3d and abx 3e rol abx
40 rti imp 41 eor izx 45 eor zp 46 lsr zp 48 pha imp 49 eor imm 4a lsr acc 4c jmp abs 4d eor abs 4e lsr abs
50 bvc rel 51 eor izy 55 eor zpx 56 lsr zpx 58 cli imp 59 eor aby 5d eor abx 5e lsr abx
60 rts imp 61 adc izx 65 adc zp 66 ror zp 68 pla imp 69 adc imm 6a ror acc 6c jmp ind 6d adc abs 6e ror abs
70 bvs rel 71 adc izy 75 adc zpx 76 ror zpx 78 sei imp 79 adc aby 7d adc abx 7e ror abx
81 sta izx 84 sty zp 85 sta zp 86 stx zp 88 dey imp 8a txa imp 8c sty abs 8d sta abs 8e stx abs
90 bcc rel 91 sta izy 94 sty zpx 95 sta zpx 96 stx zpy 98 tya imp 99 sta aby 9a txs imp 9d sta abx
a0 ldy imm a1 lda izx a2 ldx imm a4 ldy zp a5 lda zp a6 ldx zp a8 tay imp a9 lda imm aa tax imp ac ldy abs ad lda abs ae ldx abs
b0 bcs rel b1 lda izy b4 ldy zpx b5 lda zpx b6 ldx zpy b8 clv imp b9 lda aby ba tsx imp bc ldy abx bd lda abx be ldx aby
c0 cpy imm c1 cmp izx c4 cpy zp c5 cmp zp c6 dec zp c8 iny imp c9 cmp imm ca dex imp cc cpy abs cd cmp abs ce dec abs
d0 bne rel d1 cmp izy d5 cmp zpx d6 dec zpx d8 cld imp d9 cmp aby dd cmp abx de dec abx
e0 cpx imm e1 sbc izx e4 cpx zp e5 sbc zp e6 inc zp e8 inx imp e9 sbc imm ea nop imp ec cpx abs ed sbc abs ee inc abs
f0 beq rel f1 sbc izy f5 sbc zpx f6 inc zpx f8 sed imp f9 sbc aby fd sbc abx fe inc abx
"""
OPS = {}
_w = _T.split()
for i in range(0, len(_w), 3):
    OPS[int(_w[i], 16)] = (_w[i + 1], _w[i + 2])
WRITES = {"sta", "stx", "sty", "inc", "dec", "asl", "lsr", "rol", "ror"}


def decode(mem, base, pc):
    """(mnemonic, mode, length, operand) at pc, or None for an undocumented opcode."""
    op = mem[pc - base]
    if op not in OPS:
        return None
    mn, mode = OPS[op]
    n = MODES[mode]
    arg = 0
    for k in range(n):
        arg |= mem[pc - base + 1 + k] << (8 * k)
    return mn, mode, 1 + n, arg


def walk(mem, base, entries, stop=()):
    """Every instruction reachable from `entries`: {pc: (mn, mode, len, arg)}.
    Raises on an undocumented opcode or an indirect jump (a path it cannot
    follow statically), so a walk that returns has seen all of the code."""
    code, todo = {}, list(entries)
    end = base + len(mem)
    while todo:
        pc = todo.pop()
        while base <= pc < end and pc not in code and pc not in stop:
            ins = decode(mem, base, pc)
            if ins is None:
                raise ValueError(f"undocumented opcode ${mem[pc - base]:02x} at ${pc:04x}")
            code[pc] = ins
            mn, mode, n, arg = ins
            if mode == "rel":
                todo.append((pc + 2 + (arg - 256 if arg & 0x80 else arg)) & 0xFFFF)
            if mn == "jsr":
                todo.append(arg)
            if mn == "jmp":
                if mode == "ind":
                    raise ValueError(f"indirect jump at ${pc:04x}")
                todo.append(arg)
                break
            if mn in ("rts", "rti", "brk"):
                break
            pc += n
    return code
