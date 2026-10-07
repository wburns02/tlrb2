; ---------------------------------------------------------------------------
; rookie_fill.bin -- M4 P2 rookie generator + vacancy fill, standalone blob.
; Incbin'ed into DYNASTY.EXE (para-aligned), far-called after the rollover
; pass for one team file. Byte-exact port of team_fill.fill_image +
; rookies.RookieGen.make in the fill-path configuration (our own C4 name
; pools, constant stat lines, C4 graded rating draws; no game data).
;
;   in:  DS:SI = team file image (295 B header + 80 records x 143 B)
;        FS:BX = pointer to one word: xorshift16 RNG state (persisted)
;        AX    = season year byte for record offset 21 (year - 1870)
;   out: AX = rookies written; SI, BX, DS, ES, FS, SS preserved.
;
; Record generation consumes exactly 10 draws in this order (contract C4):
;   last-name (d%128, d = draw() & 0xff), first-name (d%64),
;   age (%100, weighted), throws (%100 < 72), switch (%100 < 16),
;   portrait (%30), exper (%4), consist (%4),
;   grade (d < 154 / < 230, bonus [0,2,4]),
;   then one draw per rating in the C1 order (batters 6, pitchers 3):
;   value = 3 + (d % 5) + bonus, clamped 1..cap (cap = 10 endurance,
;   12 else), written to the FORMATS.md nibbles.
; Constants per position code (pinned against the Python reference):
;   P (0):     salary 255, IP 200, pitch4 135 lo = 4, 136..139=77 140=07
;   batters:   salary 109, AB 40 split by bats, 75 hi = 70, 76 = 78
; Season copy = roster copy with offsets 23,32..36,37..42,49..58,101..102,
; 111..112,121..122,125..126 zeroed (team_fill._SEASON_STAT_OFFSETS).
; Build: nasm -f bin -o rookie_fill.bin rookie_fill.asm
; ---------------------------------------------------------------------------
BITS 16
CPU 386
ORG 0

ENTRY_FILL      equ 0x10
REC             equ 143
HDR             equ 295
SEASON_BASE_OFF equ HDR + 40*REC

OFF_YEAR        equ 21
OFF_SALARY      equ 25
OFF_PORTRAIT    equ 27
OFF_HAND        equ 29
OFF_EXPCONS     equ 30
OFF_POS         equ 31

; offset 0 is a bare retf stub (entry is 0x10 by design; see below).
start:  retf

; ---------------------------------------------------------------------------
; entry (must sit at offset 0x10; the shell and the unicorn harness both
; far-call blob_base:0x10)
; ---------------------------------------------------------------------------
align 16
entry_fill:
        push si
        push bx
        push di
        push bp
        push ds
        push es

        mov [cs:year_byte], al
        mov word [cs:rng_ptr_off], bx

        ; ---- pass 1: position counts + vacancy list ----------------------
        mov di, scan_counts
        mov cx, 16
        xor ax, ax
z_counts:
        mov [cs:di], ax
        add di, 2
        loop z_counts

        xor bp, bp                      ; bp = vacancy count
        xor dx, dx                      ; dx = slot index i
scan_slots:
        cmp dx, 40
        jae scan_done
        ; roster record byte 0
        mov ax, dx
        imul ax, ax, REC
        add ax, HDR                     ; ax = roster offset
        push si
        add si, ax
        mov al, [si]
        mov ah, [si+OFF_POS]
        and ah, 15
        mov ch, [si+OFF_YEAR]           ; remember year byte for season check
        ; season record byte 0
        add si, 40*REC
        mov cl, [si]
        pop si
        or al, al
        jz slot_vacant
        ; active roster player: counts[pos] += 1 (vacancies are NOT counted;
        ; Python counts active players only)
        mov bl, ah
        xor bh, bh
        add bx, bx
        inc word [cs:scan_counts + bx]
        jmp next_slot
slot_vacant:
        or cl, cl
        jnz next_slot                   ; season half active: leave untouched
        ; record vacancy
        mov bx, bp
        add bx, bx
        mov [cs:vac_list + bx], dx
        inc bp
next_slot:
        inc dx
        jmp scan_slots
scan_done:
        mov [cs:nvac], bp
        or bp, bp
        jz done_zero

        ; ---- pass 2: ladder -> fill_list ---------------------------------
        mov word [cs:placed], 0
ladder_p:
        mov ax, [cs:scan_counts + 0]    ; pitchers
        cmp ax, 8
        jae ladder_c
        call take_slot
        jc ladder_c
        mov word [cs:di], 0             ; di set by take_slot
        inc word [cs:scan_counts + 0]
        jmp ladder_p
ladder_c:
        mov ax, [cs:scan_counts + 2]    ; catchers
        cmp ax, 2
        jae ladder_if
        call take_slot
        jc ladder_if
        mov word [cs:di], 1
        inc word [cs:scan_counts + 2]
        jmp ladder_c
ladder_if:
        mov cl, 2                       ; code 2..5, target 1 each
if_code:
        mov al, cl
        xor ah, ah
        add ax, ax
        mov bx, ax                      ; bx = counts index = code*2
        mov ax, [cs:scan_counts + bx]
        or ax, ax
        jnz if_next
        call take_slot
        jc if_next
        mov [cs:di], cl
        inc word [cs:scan_counts + bx]
if_next:
        inc cl
        cmp cl, 6
        jb if_code
        ; outfield: aggregate 6+7+8 vs 4, round-robin 6,7,8
        mov ax, [cs:scan_counts + 12]
        add ax, [cs:scan_counts + 14]
        add ax, [cs:scan_counts + 16]
        mov [cs:of_have], ax
        mov word [cs:of_rot], 0
ladder_of:
        cmp word [cs:of_have], 4
        jae ladder_dh
        call take_slot
        jc ladder_dh
        mov ax, [cs:of_rot]
        xor dx, dx
        mov cx, 3
        div cx                          ; ax = quot, dx = rot % 3
        mov ax, dx
        add ax, 6                       ; code 6,7,8
        mov [cs:di], ax
        add ax, ax
        mov di, ax
        inc word [cs:scan_counts + di]
        inc word [cs:of_have]
        inc word [cs:of_rot]
        jmp ladder_of
ladder_dh:
        call take_slot
        jc ladder_done
        mov word [cs:di], 9
        jmp ladder_dh
ladder_done:

        ; ---- pass 3: generate one rookie per vacancy ---------------------
        mov word [cs:vac_idx], 0
gen_loop:
        mov ax, [cs:vac_idx]
        cmp ax, [cs:nvac]
        jae done_count
        ; slot = vac_list[vac_idx], code = fill_list[vac_idx]
        mov bx, ax
        add bx, bx
        mov dx, [cs:vac_list + bx]      ; dx = slot
        mov cx, [cs:fill_list + bx]     ; cx = code
        push cx
        push dx                         ; slot must survive make_rookie
        call make_rookie                ; builds [cs:scratch] (clobbers most)
        pop dx
        pop cx
        ; copy scratch -> roster record
        push cx
        push dx
        call copy_rookie
        pop dx
        pop cx
        ; copy scratch -> season record, then zero the season offsets
        mov ax, dx
        imul ax, ax, REC
        add ax, SEASON_BASE_OFF
        mov di, ax
        call copy_scratch_to_es_di
        mov si, season_zero_list
zero_loop:
        mov al, [cs:si]
        or al, al
        jz zero_done
        xor ah, ah
        mov bx, ax
        mov byte [es:di+bx], 0
        inc si
        jmp zero_loop
zero_done:
        inc word [cs:vac_idx]
        jmp gen_loop

done_count:
        mov ax, [cs:nvac]
        jmp done
done_zero:
        xor ax, ax
done:
        pop es
        pop ds
        pop bp
        pop di
        pop bx
        pop si
        retf

; take_slot: if placed < nvac, set DI = fill_list + placed*2, set CF=0 and
; placed += 1; else CF=1. Clobbers AX.
take_slot:
        mov ax, [cs:placed]
        cmp ax, [cs:nvac]
        jae .full
        shl ax, 1
        add ax, fill_list
        mov di, ax
        inc word [cs:placed]
        clc
        ret
.full:
        stc
        ret

; copy_scratch_to_es_di: ES:DI already set; copy 143 bytes from cs:scratch.
; DI is preserved (callers reuse it as the record base after the copy).
copy_scratch_to_es_di:
        push si
        push cx
        push di
        push ds
        mov ax, cs
        mov ds, ax
        mov si, scratch
        mov cx, REC
        rep movsb
        pop ds
        pop di
        pop cx
        pop si
        ret

; copy_rookie: cx = code, dx = slot; roster offset = HDR + slot*REC.
; ES must be the shell data segment; rebuilds DS = CS for the scratch read
; and restores DS = shell afterwards.
copy_rookie:
        push ax
        mov ax, dx
        imul ax, ax, REC
        add ax, HDR
        mov di, ax
        call copy_scratch_to_es_di
        pop ax
        ret

; make_rookie: cx = position code; builds the 143-byte record at cs:scratch.
; Consumes the 10 C4 draws. Clobbers AX, DX, SI, DI, BP.
make_rookie:
        push si                         ; SI = team image base, sacred
        push cx                         ; position code; popped mid-way below
        ; zero the scratch record
        push es
        push di
        push cx
        push ax
        mov ax, cs
        mov es, ax
        mov di, scratch
        xor ax, ax
        mov cx, REC
        rep stosb
        pop ax
        pop cx
        pop di
        pop es

        ; d0: last name (C4: index = d % 128, d = draw() & 0xff)
        call randbyte                   ; ax = 0..255
        and ax, 127                     ; d % 128 (128 is a power of two)
        mov dx, ax
        mov si, last_names
        mov ax, dx
        mov cl, 12
        mul cl                          ; ax = idx*12
        add si, ax
        mov di, scratch
        mov cx, 12
cp_last:
        mov al, [cs:si]
        mov [cs:di], al
        inc si
        inc di
        loop cp_last
        ; d1: first name (C4: index = d % 64, d = draw() & 0xff)
        call randbyte                   ; ax = 0..255
        and ax, 63                      ; d % 64 (64 is a power of two)
        mov dx, ax
        mov si, first_names
        mov ax, dx
        mov cl, 8
        mul cl                          ; ax = idx*8
        add si, ax
        mov di, scratch + 12
        mov cx, 8
cp_first:
        mov al, [cs:si]
        mov [cs:di], al
        inc si
        inc di
        loop cp_first
        ; d2: age via cumulative weights [4,10,24,26,22,14]
        mov cx, 100
        call randmod
        cmp ax, 4
        jb age18
        cmp ax, 14
        jb age19
        cmp ax, 38
        jb age20
        cmp ax, 64
        jb age21
        cmp ax, 86
        jb age22
        mov byte [cs:scratch+20], 23
        jmp age_done
age18:  mov byte [cs:scratch+20], 18
        jmp age_done
age19:  mov byte [cs:scratch+20], 19
        jmp age_done
age20:  mov byte [cs:scratch+20], 20
        jmp age_done
age21:  mov byte [cs:scratch+20], 21
        jmp age_done
age22:  mov byte [cs:scratch+20], 22
age_done:
        mov al, [cs:year_byte]
        mov [cs:scratch+OFF_YEAR], al
        ; bytes 22 (exp), 23 (games), 24 stay 0
        ; d3+d4: hand nibble
        mov cx, 100
        call randmod
        cmp ax, 72
        jb throw_r
        xor bx, bx                      ; throws left
        jmp bats_pick
throw_r:
        mov bx, 8                       ; bit3 set
bats_pick:
        mov [cs:hand_base], bx
        mov cx, 100
        call randmod
        cmp ax, 16
        jb is_switch
        ; no switch: bats = throws_r ? 1 : 0
        cmp word [cs:hand_base], 0
        je bats_l
        mov word [cs:bats_code], 1
        jmp bats_set
bats_l:
        mov word [cs:bats_code], 0
        jmp bats_set
is_switch:
        mov word [cs:bats_code], 2
bats_set:
        mov ax, [cs:bats_code]
        shl ax, 1
        or ax, [cs:hand_base]
        mov [cs:hand_nib], ax           ; bit0 set later by portrait
        ; d5: portrait
        mov cx, 30
        call randmod
        mov dx, ax                      ; face
        mov [cs:scratch+OFF_PORTRAIT], al
        mov byte [cs:scratch+OFF_PORTRAIT+1], 0
        cmp dx, 15
        jb face_lo
        mov ax, [cs:hand_nib]
        or ax, 1
        mov [cs:hand_nib], ax
        jmp face_done
face_lo:
        mov ax, [cs:hand_nib]
        and ax, 0xFFFE
        mov [cs:hand_nib], ax
face_done:
        mov al, [cs:hand_nib]
        mov [cs:scratch+OFF_HAND], al
        ; d6+d7: exper / consist
        mov cx, 4
        call randmod
        mov cl, 4
        shl al, cl                      ; exper to the high nibble
        mov [cs:scratch+OFF_EXPCONS], al
        mov cx, 4
        call randmod
        or [cs:scratch+OFF_EXPCONS], al
        ; position + salary
        pop cx                          ; cx = code
        mov [cs:scratch+OFF_POS], cl
        cmp cx, 0
        jne sal_min
        mov word [cs:scratch+OFF_SALARY], 255
        jmp sal_done
sal_min:
        mov word [cs:scratch+OFF_SALARY], 109
sal_done:
        ; stat-line constants (the WIP blob's fixed values; ratings drawn
        ; below per C4)
        cmp cx, 0
        jne batter_rec
        ; pitcher: IP 200, pitch4 type 4 (135 lo), personality block.
        ; 135 hi (endurance) and 134 hi/lo are drawn below.
        mov word [cs:scratch+101], 200
        or byte [cs:scratch+135], 0x04
        mov byte [cs:scratch+136], 0x77
        mov byte [cs:scratch+137], 0x77
        mov byte [cs:scratch+138], 0x77
        mov byte [cs:scratch+139], 0x77
        mov byte [cs:scratch+140], 0x07
        jmp ratings_c4
batter_rec:
        ; AB 40 split by bats code
        cmp word [cs:bats_code], 2
        je ab_switch
        cmp word [cs:bats_code], 0
        je ab_left
        mov word [cs:scratch+37], 4     ; right-handed: 4/36
        mov word [cs:scratch+39], 36
        jmp ab_set
ab_switch:
        mov word [cs:scratch+37], 20
        mov word [cs:scratch+39], 20
        jmp ab_set
ab_left:
        mov word [cs:scratch+37], 34
        mov word [cs:scratch+39], 6
ab_set:
        or byte [cs:scratch+75], 0x70   ; streak: letter A (7)
        mov byte [cs:scratch+76], 0x78  ; day/night 7, clutch 8
ratings_c4:
        ; ---- C4: grade draw, then one draw per rating -------------------
        ; grade: d = draw() & 0xff; 0 if d < 154, 1 if d < 230, else 2;
        ; bonus = grade * 2
        call randbyte                   ; ax = d & 0xff
        xor dx, dx                      ; dx = grade
        cmp ax, 154
        jb grade_set
        mov dx, 1
        cmp ax, 230
        jb grade_set
        mov dx, 2
grade_set:
        shl dx, 1                       ; dx = bonus
        mov bp, dx                      ; bp = bonus (dead in pass 3)
        ; table + count: pitchers 3 ratings, batters 6 (C1 order); the
        ; position code is already stored at scratch+OFF_POS
        mov bx, ratings_batter
        mov cx, 6
        cmp byte [cs:scratch+OFF_POS], 0
        jne c4_next
        mov bx, ratings_pitcher
        mov cx, 3
c4_next:
        call randbyte                   ; ax = d & 0xff
        xor ah, ah
        push bx
        mov bx, 5
        xor dx, dx
        div bx                          ; ax = d/5 (junk), dx = d % 5
        pop bx
        mov ax, dx
        add ax, 3                       ; base
        add ax, bp                      ; + bonus
        mov si, [cs:bx+4]               ; cap
        cmp ax, si
        jbe c4_cap_ok
        mov ax, si
c4_cap_ok:
        cmp ax, 1
        jae c4_clamped
        mov ax, 1
c4_clamped:
        mov di, [cs:bx]                 ; di = record byte offset
        cmp word [cs:bx+2], 0
        jne c4_hi
        ; lo nibble: byte = (old & 0xF0) | v
        mov ah, [cs:scratch+di]
        and ah, 0xF0
        or al, ah
        mov [cs:scratch+di], al
        jmp c4_adv
c4_hi:
        ; hi nibble: byte = (old & 0x0F) | (v << 4)
        mov ah, [cs:scratch+di]
        and ah, 0x0F
        mov dl, al
        shl dl, 1
        shl dl, 1
        shl dl, 1
        shl dl, 1                       ; dl = v << 4 (cx untouched)
        or ah, dl
        mov [cs:scratch+di], ah
c4_adv:
        add bx, 6                       ; next entry (off, shift, cap)
        loop c4_next

rec_done:
        pop si
        ret

; randmod: CX = modulus; returns AX = xorshift16 draw % CX.
; Clobbers DX. Preserves BX, SI, DI, BP.
randmod:
        push bx
        push bp
        mov bp, cx
        call xorshift16
        xor dx, dx
        div bp                          ; ax = quot, dx = rem
        mov ax, dx
        pop bp
        pop bx
        ret

; randbyte: returns AX = d = xorshift16 draw & 0xff (contract C4 byte draw).
; Clobbers DX. Preserves BX, SI, DI, BP.
randbyte:
        push bx
        push cx
        push dx
        call xorshift16
        and ax, 0xff
        pop dx
        pop cx
        pop bx
        ret

xorshift16:
        push bx
        push cx
        push dx
        mov bx, [cs:rng_ptr_off]        ; BX is scratch in this blob's callers;
        mov ax, [fs:bx]                 ; the saved pointer is authoritative
        mov dx, ax
        mov cx, 7
        shl dx, cl
        xor ax, dx
        mov dx, ax
        mov cx, 9
        shr dx, cl
        xor ax, dx
        mov dx, ax
        mov cx, 8
        shl dx, cl
        xor ax, dx
        mov [fs:bx], ax
        pop dx
        pop cx
        pop bx
        ret

; ---------------------------------------------------------------------------
; data (all CS-relative)
; ---------------------------------------------------------------------------
season_zero_list:
        db 23, 32, 33, 34, 35, 36
        db 37, 38, 39, 40, 41, 42
        db 49, 50, 51, 52, 53, 54, 55, 56, 57, 58
        db 101, 102, 111, 112, 121, 122, 125, 126
        db 0

%include "rookie_names.inc"

; C4 rating tables: 3 words per entry (record byte offset, nibble shift
; 0 = lo / 4 = hi, clamp cap), C1 draw order (notes/M4_CONTRACT.md).
ratings_batter:
        dw 74, 0, 12                    ; power (74 lo)
        dw 74, 4, 12                    ; bunt (74 hi)
        dw 75, 0, 12                    ; hit_run (75 lo)
        dw 29, 4, 12                    ; speed (29 hi)
        dw 94, 4, 12                    ; range (94 hi)
        dw 94, 0, 12                    ; arm (94 lo)
ratings_pitcher:
        dw 134, 0, 12                   ; control (134 lo)
        dw 134, 4, 12                   ; velocity (134 hi)
        dw 135, 4, 10                   ; endurance (135 hi)

scan_counts:    dw 16 dup(0)
vac_list:       dw 40 dup(0)
fill_list:      dw 40 dup(0)
nvac:           dw 0
placed:         dw 0
vac_idx:        dw 0
of_have:        dw 0
of_rot:         dw 0
hand_base:      dw 0
bats_code:      dw 0
hand_nib:       dw 0
year_byte:      db 0
rng_ptr_off:    dw 0

scratch:        db REC dup(0)
