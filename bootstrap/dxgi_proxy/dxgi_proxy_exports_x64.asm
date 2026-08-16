option casemap:none

extern ResolveExport:proc

.code

DXGI_EXPORT_STUB macro symbol:req, index:req
symbol proc frame
    sub rsp, 0a8h
    .allocstack 0a8h
    .endprolog

    mov qword ptr [rsp+20h], rcx
    mov qword ptr [rsp+28h], rdx
    mov qword ptr [rsp+30h], r8
    mov qword ptr [rsp+38h], r9
    movdqu xmmword ptr [rsp+40h], xmm0
    movdqu xmmword ptr [rsp+50h], xmm1
    movdqu xmmword ptr [rsp+60h], xmm2
    movdqu xmmword ptr [rsp+70h], xmm3

    mov ecx, index
    call ResolveExport
    mov r11, rax

    mov rcx, qword ptr [rsp+20h]
    mov rdx, qword ptr [rsp+28h]
    mov r8, qword ptr [rsp+30h]
    mov r9, qword ptr [rsp+38h]
    movdqu xmm0, xmmword ptr [rsp+40h]
    movdqu xmm1, xmmword ptr [rsp+50h]
    movdqu xmm2, xmmword ptr [rsp+60h]
    movdqu xmm3, xmmword ptr [rsp+70h]

    add rsp, 0a8h
    jmp r11
symbol endp
endm

DXGI_EXPORT_STUB ProxyExport0, 0
DXGI_EXPORT_STUB ProxyExport1, 1
DXGI_EXPORT_STUB ProxyExport2, 2
DXGI_EXPORT_STUB ProxyExport3, 3
DXGI_EXPORT_STUB ProxyExport4, 4
DXGI_EXPORT_STUB ProxyExport5, 5
DXGI_EXPORT_STUB ProxyExport6, 6
DXGI_EXPORT_STUB ProxyExport7, 7
DXGI_EXPORT_STUB ProxyExport8, 8
DXGI_EXPORT_STUB ProxyExport9, 9
DXGI_EXPORT_STUB ProxyExport10, 10
DXGI_EXPORT_STUB ProxyExport11, 11
DXGI_EXPORT_STUB ProxyExport12, 12
DXGI_EXPORT_STUB ProxyExport13, 13
DXGI_EXPORT_STUB ProxyExport14, 14
DXGI_EXPORT_STUB ProxyExport15, 15
DXGI_EXPORT_STUB ProxyExport16, 16
DXGI_EXPORT_STUB ProxyExport17, 17
DXGI_EXPORT_STUB ProxyExport18, 18
DXGI_EXPORT_STUB ProxyExport19, 19

end
