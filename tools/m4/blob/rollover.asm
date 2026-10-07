; ---------------------------------------------------------------------------
; rollover.asm - TLRB2 M4 per-player season-rollover core.
; nasm -f bin -o rollover.bin rollover.asm   (BITS 16, ORG 0, flat binary)
; Ported from the Python reference tools/m4/rollover.py with the formulas of
; tools/ratings.py ported verbatim. The unicorn harness
; (work/m4/test_blob_unicorn.py) pins it byte-for-byte against the reference.
;
; ABI:
;   far call to blob_base + ENTRY_ROLL_PLAYER (0x10)
;   in:  DS:SI = roster (career) record, 143 B
;        ES:DI = season record, 143 B
;        FS:BX = pointer to one word: xorshift16 RNG state (persisted by caller)
;        CX    = flags: bit0 = progression, bit1 = retirement
;   out: AX = 1 if retired else 0; every other register preserved.
;   On retire: byte 0 of BOTH records cleared.
; Conventions inside:
;   - BP holds the progression k across target calls (never clobbered).
;   - SI/ESI: SI is the roster pointer at entry level; target functions may use
;     ESI as scratch but must restore the low word (push si / pop si).
;   - DI is the season pointer and is sacred: never clobbered anywhere except
;     apply_delta, which saves/restores it.
;   - All blob-internal data is CS-relative.
; ---------------------------------------------------------------------------

BITS 16
ORG 0

ENTRY_ROLL_PLAYER equ 0x10

OFF_AGE      equ 20
OFF_YEAR     equ 21
OFF_EXP      equ 22
OFF_GAMES    equ 23
OFF_SB       equ 35
OFF_CS       equ 36
OFF_SPEED    equ 29          ; speed = HIGH nibble of byte 29
OFF_POS      equ 31          ; pos1 = LOW nibble of byte 31 (0 = pitcher)
OFF_POWER    equ 74          ; lo
OFF_BUNT     equ 74          ; hi
OFF_HITRUN   equ 75          ; lo
OFF_E1       equ 85
OFF_DP1      equ 87
OFF_ARM      equ 94          ; lo
OFF_RANGE    equ 94          ; hi
OFF_CG       equ 97
OFF_IP10     equ 101
OFF_PO1      equ 77
OFF_A1       equ 81
OFF_CONTROL  equ 134         ; lo
OFF_VELOCITY equ 134         ; hi
OFF_ENDUR    equ 135         ; hi

        jmp short start                 ; offset 0x00
start:  retf

        times (ENTRY_ROLL_PLAYER - 3) db 0x90
entry_roll_player:
        push ds
        push es
        push bx
        push cx
        push dx
        push bp
        push si
        push di

        ; -- 1. both records inactive -> AX = 0
        mov al, [si]
        or al, al
        jnz .active
        mov al, es:[di]
        or al, al
        jz .done0
.active:

        ; -- 2. career merge (saturating add, season -> roster)
        call merge_stats

        ; -- 3. aging, both records
        mov al, [si+OFF_AGE]
        cmp al, 255
        jae .age_done
        inc byte [si+OFF_AGE]
        inc byte es:[di+OFF_AGE]
.age_done:
        mov al, es:[di+OFF_YEAR]
        inc al
        mov [si+OFF_YEAR], al
        mov es:[di+OFF_YEAR], al
        cmp byte es:[di+OFF_GAMES], 0
        je .exp_done
        mov al, [si+OFF_EXP]
        cmp al, 255
        jae .exp_done
        inc byte [si+OFF_EXP]
        inc byte es:[di+OFF_EXP]
.exp_done:

        ; -- 4. progression (CX bit0): aged age, season games > 0, k != 0
        test cx, 1
        jz .no_prog
        cmp byte es:[di+OFF_GAMES], 0
        je .no_prog
        mov bp, 192                     ; >= 35 bucket (and the default)
        mov al, [si+OFF_AGE]
        cmp al, 20
        jbe .k_set                      ; <= 20: 192
        mov bp, 128                     ; 21..24
        cmp al, 24
        jbe .k_set
        mov bp, 64                      ; 25..27
        cmp al, 27
        jbe .k_set
        xor bp, bp                      ; 28
        cmp al, 28
        je .k_set
        mov bp, 224                     ; 29..34
        cmp al, 34
        jbe .k_set
        mov bp, 192                     ; >= 35
.k_set:
        or bp, bp
        jz .no_prog
        mov al, [si+OFF_POS]            ; pitcher decision on ROSTER pos1
        and al, 15
        or al, al
        jz .prog_pitcher
        call t_power
        call apply_delta_lo74
        call t_bunt
        call apply_delta_hi74
        call t_hitrun
        call apply_delta_lo75
        call t_speed
        call apply_delta_hi29
        call t_arm
        call apply_delta_lo94
        call t_range
        call apply_delta_hi94
        jmp .no_prog
.prog_pitcher:
        call t_control
        call apply_delta_lo134
        call t_velocity
        call apply_delta_hi134
        call t_endur
        call apply_delta_hi135
.no_prog:

        ; -- 5. retirement (CX bit1)
        test cx, 2
        jz .not_retire
        mov al, [si+OFF_AGE]
        cmp al, 41
        jae .retire
        cmp al, 36
        jb .endur_check
        call xorshift16                 ; AX = new state (stored back at FS:BX)
        mov dl, al                      ; low byte of the draw
        mov al, [si+OFF_AGE]            ; aged age == age2 (xorshift16 clobbered AX)
        mov ah, 0
        sub al, 35
        mov cl, 20
        mul cl                          ; AX = (age-35)*20
        cmp dl, al
        jb .retire
        jmp .not_retire
.endur_check:
        mov al, [si+OFF_POS]
        and al, 15
        or al, al
        jnz .not_retire                 ; batter: no endurance/arm branch
        mov al, [si+OFF_ENDUR]
        shr al, 4                       ; endurance = high nibble
        cmp al, 3
        jae .not_retire
        mov al, [si+OFF_ARM]
        and al, 15                      ; arm = low nibble
        cmp al, 3
        jae .not_retire
.retire:
        mov byte [si], 0
        mov byte es:[di], 0
        mov ax, 1
        jmp .out
.not_retire:
        xor ax, ax
        jmp .out
.done0:
        xor ax, ax
.out:
        pop di
        pop si
        pop bp
        pop dx
        pop cx
        pop bx
        pop es
        pop ds
        retf

; ---------------------------------------------------------------------------
; merge_stats: roster = sat_add(roster, season) for every stat field.
merge_stats:
        push ax
        push bx
        push cx
        mov bx, u8_table
        mov cx, cs:[bx]
        add bx, 2
.ms_u8:
        push bx
        mov bx, cs:[bx]                 ; field offset
        mov al, [si+bx]                 ; roster (DS:SI + off)
        add al, es:[di+bx]              ; season (ES:DI + off)
        jnc .ms_u8_store
        mov al, 255
.ms_u8_store:
        mov [si+bx], al
        pop bx
        add bx, 2
        loop .ms_u8
        mov bx, u16_table
        mov cx, cs:[bx]
        add bx, 2
.ms_u16:
        push bx
        mov bx, cs:[bx]
        mov ax, [si+bx]
        add ax, es:[di+bx]
        jnc .ms_u16_store
        mov ax, 0xFFFF
.ms_u16_store:
        mov [si+bx], ax
        pop bx
        add bx, 2
        loop .ms_u16
        pop cx
        pop bx
        pop ax
        ret

; ---------------------------------------------------------------------------
; xorshift16: state word at FS:BX. Returns AX = new state, state stored back.
xorshift16:
        push bx
        push cx
        push dx
        mov ax, [fs:bx]
        mov dx, ax
        mov cx, 7
        shl dx, cl                      ; (s << 7) & 0xffff
        xor ax, dx
        mov dx, ax
        mov cx, 9
        shr dx, cl                      ; s >> 9
        xor ax, dx
        mov dx, ax
        mov cx, 8
        shl dx, cl                      ; (s << 8) & 0xffff
        xor ax, dx
        mov [fs:bx], ax
        pop dx
        pop cx
        pop bx
        ret

; ---------------------------------------------------------------------------
; apply_delta: progress one roster nibble toward the target in AX.
;   DH = byte offset, DL = 1 high nibble / 0 low nibble, BP = k (signed byte).
;   new = clamp(1..15, old + ((ks*(target-old)+128) sar 8)).
;   Clobbers AX, CX, DX; preserves BX, SI, DI, BP, DS, ES, FS.
apply_delta:
        push bx
        push cx
        push dx
        push di
        push dx                         ; selector (DH/DL) survives; DX is scratch below
        mov di, ax                      ; DI = target
        xor bh, bh
        mov bl, dh
        add bx, si                      ; BX = roster + off
        mov al, [bx]
        or dl, dl
        jz .lo_nib
        mov cl, 4
        shr al, cl                      ; high nibble
.lo_nib:
        and ax, 0x000F                  ; AX = old
        mov dx, ax                      ; DX = old
        mov ax, bp                      ; k unsigned byte
        cmp al, 128
        jbe .k_pos                      ; 128 is the positive pivot (ref: ks = k-256 only if k > 128)
        mov ah, 0xFF                    ; sign-extend -> signed word
.k_pos:
        mov cx, di                      ; target
        sub cx, dx                      ; target - old
        imul cx, ax                     ; ks * (target - old)
        add cx, 128
        sar cx, 8
        mov ax, dx
        add ax, cx                      ; old + delta
        cmp ax, 1
        jge .min_ok
        mov ax, 1
.min_ok:
        cmp ax, 15
        jle .max_ok
        mov ax, 15
.max_ok:
        pop dx                          ; restore selector for the write-back branch
        mov cl, [bx]
        or dl, dl
        jz .wr_lo
        and cl, 0x0F                    ; keep low nibble
        mov ch, al
        shl ch, 4
        or cl, ch
        jmp .wr
.wr_lo:
        and cl, 0xF0                    ; keep high nibble
        or cl, al
.wr:
        mov [bx], cl
        pop di
        pop dx
        pop cx
        pop bx
        ret

; each stub: DH = byte offset, DL = 1 high nibble / 0 low nibble
apply_delta_lo74:
        mov dh, OFF_POWER
        mov dl, 0
        jmp apply_delta
apply_delta_hi74:
        mov dh, OFF_BUNT
        mov dl, 1
        jmp apply_delta
apply_delta_lo75:
        mov dh, OFF_HITRUN
        mov dl, 0
        jmp apply_delta
apply_delta_hi29:
        mov dh, OFF_SPEED
        mov dl, 1
        jmp apply_delta
apply_delta_lo94:
        mov dh, OFF_ARM
        mov dl, 0
        jmp apply_delta
apply_delta_hi94:
        mov dh, OFF_RANGE
        mov dl, 1
        jmp apply_delta
apply_delta_lo134:
        mov dh, OFF_CONTROL
        mov dl, 0
        jmp apply_delta
apply_delta_hi134:
        mov dh, OFF_VELOCITY
        mov dl, 1
        jmp apply_delta
apply_delta_hi135:
        mov dh, OFF_ENDUR
        mov dl, 1
        jmp apply_delta

; ---------------------------------------------------------------------------
; season-record stat helpers (ES:DI record; result in EAX; ESI/EBX/ECX/EDX
; are caller-saved EXCEPT that these push/pop EDX internally only as scratch
; they own: treat EAX as the only survivor; BX must hold the field offset in).
s2sum:                                  ; EAX = u16(BX) + u16(BX+2)
        push dx
        movzx eax, word es:[bx+di]
        movzx edx, word es:[bx+di+2]
        add eax, edx
        pop dx
        ret
b2sum:                                  ; EAX = byte(BX) + byte(BX+1)
        push dx
        movzx eax, byte es:[bx+di]
        movzx edx, byte es:[bx+di+1]
        add eax, edx
        pop dx
        ret
outs_of:                                ; EAX = (ip10/10)*3 + ip10%10
        push ecx
        push edx
        movzx eax, word es:[di+OFF_IP10]
        xor edx, edx
        mov ecx, 10
        div ecx                         ; eax = ip10/10, edx = ip10%10
        lea eax, [eax + eax*2]          ; *3
        add eax, edx
        pop edx
        pop ecx
        ret

; per_mille32: EAX = ((num & 0xffff)*1000 + (den & 0xffff)//2) // den, den==0 -> 0
; in EAX = num, ECX = den; out EAX; EBX/ECX/EDX preserved.
per_mille32:
        push ebx
        push ecx
        push edx
        and eax, 0xFFFF
        and ecx, 0xFFFF
        jecxz .zero
        mov ebx, eax
        mov eax, 1000
        mul ebx                         ; edx:eax = num * 1000
        mov ebx, ecx
        shr ebx, 1                      ; den // 2
        add eax, ebx
        adc edx, 0
        mov ebx, ecx                    ; divisor = den
        div ebx
        jmp .out
.zero:
        xor eax, eax
.out:
        pop edx
        pop ecx
        pop ebx
        ret

; ladder32: AX = 1 + count(x >= t) over CS table at BX (db n; dw t1..tn).
; in EAX = x, BX = table offset; out AX; EBX/ECX/EDX preserved.
ladder32:
        push bx
        push cx
        push dx
        xor cx, cx
        movzx dx, byte cs:[bx]
        inc bx
.ld_loop:
        or dx, dx
        jz .ld_done
        push bx
        mov bx, cs:[bx]
        cmp eax, ebx
        jb .ld_next
        inc cx
.ld_next:
        pop bx
        add bx, 2
        dec dx
        jmp .ld_loop
.ld_done:
        mov ax, cx
        inc ax
        pop dx
        pop cx
        pop bx
        ret

; field_class: AX = POS_CLASS row (0..5) for the SEASON pos1, or -1 if none.
field_class:
        push bx
        push cx
        mov al, es:[di+OFF_POS]
        and al, 15
        cmp al, 8
        ja .fc_none
        xor ah, ah
        mov bx, ax
        mov cl, cs:[bx+pos_class_tbl]
        xor ch, ch
        mov ax, cx
        jmp .fc_out
.fc_none:
        mov ax, -1
.fc_out:
        pop cx
        pop bx
        ret

; ---------------------------------------------------------------------------

; ---------------------------------------------------------------------------
; TARGET RATINGS (all read the SEASON record at ES:DI; result 1..12 in AX).
; Locals: ESI/EBX/ECX/EDX free; SI pushed/popped as table-walk scratch;
; DI/BP/DS/ES/FS preserved.

t_power:                                ; ladder(per_mille(H+D+2T3+3HR, AB))
        push ebx
        push ecx
        push edx
        push si
        mov bx, 37
        call s2sum                      ; AB
        mov esi, eax
        mov bx, 41
        call s2sum                      ; H
        mov ecx, eax
        mov bx, 45
        call s2sum                      ; D
        add ecx, eax
        mov bx, 49
        call b2sum                      ; T3
        add eax, eax                    ; 2*T3
        add ecx, eax
        mov bx, 51
        call b2sum                      ; HR
        lea eax, [eax + eax*2]          ; 3*HR
        add ecx, eax                    ; num
        mov eax, ecx
        mov ecx, esi                    ; den = AB
        call per_mille32
        mov bx, thr_power
        call ladder32
        pop si
        pop edx
        pop ecx
        pop ebx
        ret

t_hitrun:                               ; 1 + (x != 0) + count(x > t)
        push ebx
        push ecx
        push edx
        push si
        mov bx, 37
        call s2sum                      ; AB
        mov esi, eax
        mov bx, 53
        call s2sum                      ; BB
        mov ebx, eax
        lea edx, [esi + ebx]            ; AB + BB
        and edx, 0xFFFF                 ; pa (EDX live)
        mov bx, 41
        call s2sum                      ; H
        shl eax, 2                      ; 4*H
        lea eax, [eax + ebx*2]          ; + 2*BB
        and eax, 0xFFFF                 ; a (EAX live)
        mov ebx, eax                    ; a (EBX live)
        mov bx, 57
        call s2sum                      ; SO
        lea eax, [eax + eax*2]          ; 3*SO
        and eax, 0xFFFF                 ; c
        cmp ebx, eax                    ; a vs c
        ja .hr_have_c
        mov eax, ebx                    ; a <= c: c = a
.hr_have_c:
        mov ecx, eax                    ; c
        mov eax, ebx
        sub eax, ecx                    ; delta = a - c (>= 0)
        mov esi, eax                    ; esi = delta (AB long gone)
        mov ecx, 10
        mul ecx                         ; delta * 10
        mov esi, eax                    ; esi = delta*10
        mov ecx, edx                    ; pa
        jecxz .hr_nopa
        mov eax, esi
        xor edx, edx
        div ecx                         ; x = delta*10 / pa
        mov esi, eax
        jmp .hr_have_x
.hr_nopa:
        mov esi, eax                    ; wait: eax holds delta*10 still
.hr_have_x:
        ; rating = 1 + (x != 0) + count(x > t)
        mov eax, 1
        or esi, esi
        jz .hr_walk
        inc ax
.hr_walk:
        mov edx, esi                    ; x (esi about to become the walk ptr)
        mov si, thr_hr
        movzx cx, byte cs:[si]
        inc si
.hr_lp:
        or cx, cx
        jz .hr_done
        mov bx, cs:[si]
        cmp edx, ebx
        jle .hr_next
        inc ax
.hr_next:
        add si, 2
        dec cx
        jmp .hr_lp
.hr_done:
        pop si
        pop edx
        pop ecx
        pop ebx
        ret

t_bunt:                                 ; ladder((s10 - sub)*20 / pa)
        push ebx
        push ecx
        push edx
        push si
        mov bx, 41
        call s2sum                      ; H
        mov esi, eax
        mov bx, 45
        call s2sum                      ; D
        sub esi, eax
        mov bx, 49
        call b2sum                      ; T3
        sub esi, eax
        mov bx, 51
        call b2sum                      ; HR
        sub esi, eax                    ; singles
        mov eax, esi
        mov ecx, 10
        mul ecx
        mov esi, eax                    ; s10
        mov bx, 57
        call s2sum                      ; SO
        lea edx, [eax + eax*2]          ; 3*SO (EDX live)
        mov bx, 51
        call b2sum                      ; HR
        lea ebx, [eax + eax*2]          ; 3*HR
        add ebx, ebx                    ; 6*HR
        mov eax, edx
        add eax, ebx                    ; 3*SO + 6*HR
        and eax, 0xFFFF
        cmp eax, esi                    ; min(cand, s10)
        jbe .bu_have_sub
        mov eax, esi
.bu_have_sub:
        sub esi, eax                    ; s10 - sub
        mov eax, esi
        mov ecx, 20
        mul ecx                         ; * 20
        mov esi, eax                    ; x (pre-div)
        mov bx, 37
        call s2sum                      ; AB
        mov ecx, eax
        mov bx, 53
        call s2sum                      ; BB
        lea ecx, [ecx + eax]            ; AB + BB
        and ecx, 0xFFFF                 ; pa
        mov eax, esi
        jecxz .bu_ladder
        xor edx, edx
        div ecx
.bu_ladder:
        mov bx, thr_bunt
        call ladder32
        pop si
        pop edx
        pop ecx
        pop ebx
        ret

t_speed:
        push ebx
        push ecx
        push edx
        push si
        movzx eax, byte es:[di+OFF_SB]
        movzx edx, byte es:[di+OFF_CS]
        add edx, edx                    ; 2*CS
        sub eax, edx
        jns .sp_pos
        xor eax, eax
.sp_pos:
        mov ecx, 1000
        mul ecx
        mov esi, eax                    ; x
        mov bx, 41
        call s2sum                      ; H
        mov edx, eax
        mov bx, 53
        call s2sum                      ; BB
        add edx, eax
        mov bx, 45
        call s2sum                      ; D
        sub edx, eax
        mov bx, 49
        call b2sum                      ; T3
        sub edx, eax
        mov bx, 51
        call b2sum                      ; HR
        sub edx, eax                    ; den (>= 0)
        mov eax, edx
        shr eax, 1                      ; den >> 1
        add esi, eax
        mov ecx, edx                    ; den
        jecxz .sp_noden
        mov eax, esi
        xor edx, edx
        div ecx                         ; x //= den
        mov esi, eax
.sp_noden:
        mov bx, 49
        call b2sum                      ; T3
        mov ecx, 1000
        mul ecx
        mov ecx, eax                    ; y = T3 * 1000
        mov bx, 45
        call s2sum                      ; D
        mov ebx, 30
        mul ebx
        mov ebx, eax                    ; den2 = D * 30
        mov eax, ebx
        shr eax, 1                      ; den2 >> 1
        add ecx, eax                    ; y += ...
        or ebx, ebx
        jz .sp_no2
        mov eax, ecx
        xor edx, edx
        div ebx                         ; y //= den2
        mov ecx, eax
.sp_no2:
        mov eax, esi
        add eax, ecx
        mov bx, thr_speed
        call ladder32
        pop si
        pop edx
        pop ecx
        pop ebx
        ret

t_range:
        push ebx
        push ecx
        push edx
        push si
        call field_class                ; AX = row or -1
        cmp ax, -1
        je .rg_none
        mov bx, ax
        imul bx, bx, 10
        add bx, field_w_tbl             ; row base
        movzx ecx, byte es:[di+OFF_GAMES]   ; g
        movzx eax, word es:[di+OFF_PO1]     ; po1
        movzx edx, word cs:[bx]             ; w0
        mul edx
        mov esi, eax
        movzx eax, word es:[di+OFF_A1]      ; a1
        movzx edx, word cs:[bx+2]           ; w1
        mul edx
        add esi, eax
        movzx eax, byte es:[di+OFF_DP1]     ; dp1
        movzx edx, word cs:[bx+4]           ; w2
        mul edx
        add esi, eax
        movzx eax, byte es:[di+OFF_E1]      ; e1
        imul eax, eax, 100
        sub esi, eax
        jns .rg_ns
        xor esi, esi
.rg_ns:
        mov eax, ecx
        imul eax, eax, 100
        shr eax, 1                          ; g*100//2
        add esi, eax
        jecxz .rg_nodiv
        imul ecx, ecx, 100
        mov eax, esi
        xor edx, edx
        div ecx
        mov esi, eax
.rg_nodiv:
        cmp esi, 1
        jge .rg_min
        mov esi, 1
        jmp .rg_out
.rg_min:
        cmp esi, 12
        jle .rg_out
        mov esi, 12
.rg_out:
        mov ax, si
        jmp .rg_ret
.rg_none:
        mov ax, 7
.rg_ret:
        pop si
        pop edx
        pop ecx
        pop ebx
        ret

t_arm:
        push ebx
        push ecx
        push edx
        push si
        call field_class
        cmp ax, -1
        je .ar_none
        mov bx, ax
        imul bx, bx, 10
        add bx, field_w_tbl
        movzx ecx, byte es:[di+OFF_GAMES]
        movzx eax, word es:[di+OFF_A1]      ; a1
        movzx edx, word cs:[bx+6]           ; w3 (arm A weight)
        mul edx
        mov esi, eax
        movzx eax, byte es:[di+OFF_DP1]     ; dp1
        movzx edx, word cs:[bx+8]           ; w4 (arm DP weight)
        mul edx
        add esi, eax
        movzx eax, byte es:[di+OFF_E1]
        imul eax, eax, 100
        sub esi, eax
        jns .ar_ns
        xor esi, esi
.ar_ns:
        mov eax, ecx
        imul eax, eax, 50
        shr eax, 1                          ; g*50//2
        add esi, eax
        jecxz .ar_nodiv
        imul ecx, ecx, 50
        mov eax, esi
        xor edx, edx
        div ecx
        mov esi, eax
.ar_nodiv:
        cmp esi, 1
        jge .ar_min
        mov esi, 1
        jmp .ar_out
.ar_min:
        cmp esi, 12
        jle .ar_out
        mov esi, 12
.ar_out:
        mov ax, si
        jmp .ar_ret
.ar_none:
        mov ax, 7
.ar_ret:
        pop si
        pop edx
        pop ecx
        pop ebx
        ret

t_control:
        push ebx
        push ecx
        push edx
        push si
        call outs_of                        ; o
        mov esi, eax
        mov bx, 121
        call s2sum                          ; BB
        mov ecx, eax
        imul ecx, ecx, 999                  ; bb*999
        mov ebx, esi
        imul ebx, ebx, 10                   ; o*10
        add ecx, ebx                        ; x
        mov ebx, esi
        jecxz .ct_no                        ; o == 0 keeps x
        test esi, esi
        jz .ct_no
        mov eax, ecx
        imul ebx, ebx, 20                   ; o*20
        xor edx, edx
        div ebx
        mov ecx, eax
.ct_no:
        cmp ecx, 2
        jae .ct_min2
        mov ecx, 2
.ct_min2:
        cmp ecx, 14
        jae .ct_one
        mov ax, 14
        sub ax, cx                          ; 14 - x
        jmp .ct_ret
.ct_one:
        mov ax, 1
.ct_ret:
        pop si
        pop edx
        pop ecx
        pop ebx
        ret

t_velocity:
        push ebx
        push ecx
        push edx
        push si
        call outs_of                        ; o
        mov esi, eax
        mov bx, 111
        call s2sum                          ; h (hits allowed)
        mov ecx, eax
        mov bx, 125
        call s2sum                          ; so (strikeouts)
        mov edx, eax
        mov eax, esi
        imul eax, eax, 507                  ; o*507
        mov ebx, eax
        mov eax, edx
        imul eax, eax, 540                  ; so*540
        add ebx, eax                        ; x
        mov eax, ecx
        imul eax, eax, 1080                 ; h*1080
        cmp eax, ebx
        jae .vl_zero
        sub ebx, eax
        jmp .vl_have
.vl_zero:
        xor ebx, ebx
.vl_have:
        mov eax, esi
        imul eax, eax, 20                   ; o*20
        add ebx, eax
        test esi, esi
        jz .vl_nodiv
        mov eax, esi
        imul eax, eax, 40                   ; o*40
        mov ecx, eax
        mov eax, ebx
        xor edx, edx
        div ecx
        mov ebx, eax
.vl_nodiv:
        or ebx, ebx
        jnz .vl_min
        mov ax, 1
        jmp .vl_ret
.vl_min:
        cmp ebx, 12
        jle .vl_ok
        mov ebx, 12
.vl_ok:
        mov ax, bx
.vl_ret:
        pop si
        pop edx
        pop ecx
        pop ebx
        ret

t_endur:
        push ebx
        push ecx
        push edx
        push si
        movzx esi, byte es:[di+OFF_GAMES]   ; g
        movzx eax, byte es:[di+OFF_CG]      ; cg
        cmp eax, 20
        jbe .en_cg
        mov eax, 20
.en_cg:
        mul esi                             ; eax = cg*g
        mov ecx, eax
        movzx eax, word es:[di+OFF_IP10]
        mov ebx, eax                        ; ip10
        push ecx                            ; save cg*g
        push ebx                            ; save ip10
        mov ecx, 10
        div ecx                             ; edx = ip10 % 10
        mov ebx, edx                        ; r
        pop eax                             ; eax = ip10  (div clobbered eax)
        pop ecx                             ; ecx = cg*g
        add ecx, ebx
        add ecx, ebx                        ; cg*g + 2*r
        add ecx, eax                        ; + ip10
        mov eax, ecx
        mov edx, 10
        mul edx                             ; * 10
        mov ecx, eax
        test esi, esi
        jz .en_nodiv
        mov eax, ecx
        xor edx, edx
        div esi                             ; // g
        mov ecx, eax
.en_nodiv:
        mov eax, ecx
        add eax, 50
        mov ebx, 100
        xor edx, edx
        div ebx                             ; (x + 50) // 100
        mov ecx, eax
        cmp ecx, 10
        jle .en_min
        mov ecx, 10
.en_min:
        or ecx, ecx
        jnz .en_out
        mov ecx, 1
.en_out:
        mov ax, cx
        pop si
        pop edx
        pop ecx
        pop ebx
        ret

; ---------------------------------------------------------------------------
; data tables (CS-relative)
pos_class_tbl:  db 0,0,1,2,4,3,5,5,5    ; pos code 0..8 -> FIELD_W row (3B<->SS swapped per game)
field_w_tbl:    dw 140,200,0,500,2500 \
              , 67,250,300,200,340 \
              , 270,100,100,50,450 \
              , 320,130,100,133,100 \
              , 600,200,200,200,300 \
              , 350,0,100,4000,3000
thr_power:      db 11
                dw 250,275,300,325,350,375,425,450,500,575,700
thr_hr:         db 10
                dw 1,2,3,4,5,6,7,8,10,12
thr_bunt:       db 11
                dw 4,8,12,16,19,21,23,27,31,35,40
thr_speed:      db 11
                dw 1,2,4,6,9,15,20,25,90,150,240
u8_table:       dw 29
                dw 32,33,34,35,36
                dw 49,50,51,52
                dw 71,72,73
                dw 85,86,87,88,89
                dw 95,96,97,98,99,100
                dw 119,120
                dw 129,130,131,132
u16_table:      dw 34
                dw 37,39,41,43,45,47
                dw 53,55,57,59
                dw 61,63,65,67,69
                dw 77,79,81,83
                dw 90,92
                dw 101,103,105,107,109,111,113,115,117
                dw 121,123,125,127
