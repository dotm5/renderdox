; aftermath_forward.asm
; Real forwarding exports for GFSDK_Aftermath_Lib.x64.dll.
;
; Each export:
;   1. saves the 4 register argument slots (RCX/RDX/R8/R9) to the stack
;   2. calls LogAftermathCall(index) to record the call timestamp
;   3. restores the argument registers
;   4. jumps to the original function (resolved in g_OrigAftermath[])
;
; x64 ABI: integer/pointer args 1-4 live in RCX/RDX/R8/R9. Aftermath functions
; take only integer/pointer args, so XMM registers need no preservation.
; Stack args (if any) are left untouched above our frame and remain visible to
; the original function after the jmp.

EXTERNDEF LogAftermathCall:PROC
EXTERNDEF g_OrigAftermath:QWORD       ; array of 9 original function pointers

; fnName  = exported symbol
; ord     = index passed to LogAftermathCall
; byteoff = offset into g_OrigAftermath
AFTERMATH_FWD MACRO fnName, ord, byteoff
fnName PROC EXPORT
    sub rsp, 48h                      ; frame = 4 saved regs + 32 shadow (16-aligned for call)
    mov [rsp+00h], rcx
    mov [rsp+08h], rdx
    mov [rsp+10h], r8
    mov [rsp+18h], r9
    mov ecx, ord
    call LogAftermathCall
    mov r9, [rsp+18h]
    mov r8, [rsp+10h]
    mov rdx, [rsp+08h]
    mov rcx, [rsp+00h]
    add rsp, 48h
    mov rax, QWORD PTR [g_OrigAftermath + byteoff]
    test rax, rax
    jz  @@fail                       ; original not resolved -> fail safe
    jmp rax
@@fail:
    xor eax, eax
    ret
fnName ENDP
ENDM

.code

AFTERMATH_FWD GFSDK_Aftermath_DX11_CreateContextHandle, 0, 0
AFTERMATH_FWD GFSDK_Aftermath_DX11_Initialize,          1, 8
AFTERMATH_FWD GFSDK_Aftermath_DX12_CreateContextHandle, 2, 16
AFTERMATH_FWD GFSDK_Aftermath_DX12_Initialize,          3, 24
AFTERMATH_FWD GFSDK_Aftermath_GetData,                  4, 32
AFTERMATH_FWD GFSDK_Aftermath_GetDeviceStatus,          5, 40
AFTERMATH_FWD GFSDK_Aftermath_GetPageFaultInformation,  6, 48
AFTERMATH_FWD GFSDK_Aftermath_ReleaseContextHandle,     7, 56
AFTERMATH_FWD GFSDK_Aftermath_SetEventMarker,           8, 64

END
