; aftermath_forward.asm
; Forward unchanged to the renamed original. On the first call, resolution
; happens outside DllMain. The resolver is called with its own 32-byte shadow
; space; original argument registers are saved above it. The frame has unwind
; metadata so an exception while loading the original can be unwound correctly.

EXTERNDEF ResolveAftermathExport:PROC
EXTERNDEF g_OrigAftermath:QWORD
EXTERNDEF g_ResolutionReady:DWORD

AFTERMATH_FWD MACRO fnName, ord, byteoff
fnName PROC FRAME
    sub rsp, 88h
    .allocstack 88h
    .endprolog
    cmp DWORD PTR [g_ResolutionReady], 1
    jne @@resolve
    mov rax, QWORD PTR [g_OrigAftermath + byteoff]
    test rax, rax
    jnz @@forward
@@resolve:
    mov [rsp+20h], rcx
    mov [rsp+28h], rdx
    mov [rsp+30h], r8
    mov [rsp+38h], r9
    movdqu XMMWORD PTR [rsp+40h], xmm0
    movdqu XMMWORD PTR [rsp+50h], xmm1
    movdqu XMMWORD PTR [rsp+60h], xmm2
    movdqu XMMWORD PTR [rsp+70h], xmm3
    mov ecx, ord
    call ResolveAftermathExport
    movdqu xmm3, XMMWORD PTR [rsp+70h]
    movdqu xmm2, XMMWORD PTR [rsp+60h]
    movdqu xmm1, XMMWORD PTR [rsp+50h]
    movdqu xmm0, XMMWORD PTR [rsp+40h]
    mov r9, [rsp+38h]
    mov r8, [rsp+30h]
    mov rdx, [rsp+28h]
    mov rcx, [rsp+20h]
@@forward:
    add rsp, 88h
    jmp rax
    ret
fnName ENDP
ENDM

.code

AFTERMATH_FWD GFSDK_Aftermath_DX11_CreateContextHandle      ,  0,   0
AFTERMATH_FWD GFSDK_Aftermath_DX11_Initialize               ,  1,   8
AFTERMATH_FWD GFSDK_Aftermath_DX12_CreateContextHandle      ,  2,  16
AFTERMATH_FWD GFSDK_Aftermath_DX12_Initialize               ,  3,  24
AFTERMATH_FWD GFSDK_Aftermath_DX12_RegisterResource         ,  4,  32
AFTERMATH_FWD GFSDK_Aftermath_DX12_UnregisterResource       ,  5,  40
AFTERMATH_FWD GFSDK_Aftermath_DisableGpuCrashDumps          ,  6,  48
AFTERMATH_FWD GFSDK_Aftermath_EnableGpuCrashDumps           ,  7,  56
AFTERMATH_FWD GFSDK_Aftermath_GetContextError               ,  8,  64
AFTERMATH_FWD GFSDK_Aftermath_GetCrashDumpStatus            ,  9,  72
AFTERMATH_FWD GFSDK_Aftermath_GetData                       , 10,  80
AFTERMATH_FWD GFSDK_Aftermath_GetDeviceStatus               , 11,  88
AFTERMATH_FWD GFSDK_Aftermath_GetPageFaultInformation       , 12,  96
AFTERMATH_FWD GFSDK_Aftermath_GetShaderDebugInfoIdentifier  , 13, 104
AFTERMATH_FWD GFSDK_Aftermath_GetShaderDebugName            , 14, 112
AFTERMATH_FWD GFSDK_Aftermath_GetShaderDebugNameSpirv       , 15, 120
AFTERMATH_FWD GFSDK_Aftermath_GetShaderHash                 , 16, 128
AFTERMATH_FWD GFSDK_Aftermath_GetShaderHashForShaderInfo    , 17, 136
AFTERMATH_FWD GFSDK_Aftermath_GetShaderHashSpirv            , 18, 144
AFTERMATH_FWD GFSDK_Aftermath_GpuCrashDump_CreateDecoder    , 19, 152
AFTERMATH_FWD GFSDK_Aftermath_GpuCrashDump_DestroyDecoder   , 20, 160
AFTERMATH_FWD GFSDK_Aftermath_GpuCrashDump_GenerateJSON     , 21, 168
AFTERMATH_FWD GFSDK_Aftermath_GpuCrashDump_GetActiveShadersInfo, 22, 176
AFTERMATH_FWD GFSDK_Aftermath_GpuCrashDump_GetActiveShadersInfoCount, 23, 184
AFTERMATH_FWD GFSDK_Aftermath_GpuCrashDump_GetBaseInfo      , 24, 192
AFTERMATH_FWD GFSDK_Aftermath_GpuCrashDump_GetDescription   , 25, 200
AFTERMATH_FWD GFSDK_Aftermath_GpuCrashDump_GetDescriptionSize, 26, 208
AFTERMATH_FWD GFSDK_Aftermath_GpuCrashDump_GetDeviceInfo    , 27, 216
AFTERMATH_FWD GFSDK_Aftermath_GpuCrashDump_GetEventMarkersInfo, 28, 224
AFTERMATH_FWD GFSDK_Aftermath_GpuCrashDump_GetEventMarkersInfoCount, 29, 232
AFTERMATH_FWD GFSDK_Aftermath_GpuCrashDump_GetGpuInfo       , 30, 240
AFTERMATH_FWD GFSDK_Aftermath_GpuCrashDump_GetGpuInfoCount  , 31, 248
AFTERMATH_FWD GFSDK_Aftermath_GpuCrashDump_GetJSON          , 32, 256
AFTERMATH_FWD GFSDK_Aftermath_GpuCrashDump_GetPageFaultInfo , 33, 264
AFTERMATH_FWD GFSDK_Aftermath_GpuCrashDump_GetSystemInfo    , 34, 272
AFTERMATH_FWD GFSDK_Aftermath_ReleaseContextHandle          , 35, 280
AFTERMATH_FWD GFSDK_Aftermath_SetEventMarker                , 36, 288
AFTERMATH_FWD GFSDK_Aftermath_SetShaderDebugInfoPaths       , 37, 296
AFTERMATH_FWD GetShaderDebugName                            , 38, 304
AFTERMATH_FWD GetShaderDebugNameSpirv                       , 39, 312
AFTERMATH_FWD GetShaderHashForShaderInfo                    , 40, 320
AFTERMATH_FWD GetShaderHashSpirv                            , 41, 328
AFTERMATH_FWD queryWrapper                                  , 42, 336

END
