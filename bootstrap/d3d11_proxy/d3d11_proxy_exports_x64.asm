option casemap:none

extern ResolveExport:proc

.code

D3D11_EXPORT_STUB macro symbol:req, index:req
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

D3D11_EXPORT_STUB ProxyExport0, 0
D3D11_EXPORT_STUB ProxyExport1, 1
D3D11_EXPORT_STUB ProxyExport2, 2
D3D11_EXPORT_STUB ProxyExport3, 3
D3D11_EXPORT_STUB ProxyExport4, 4
D3D11_EXPORT_STUB ProxyExport5, 5
D3D11_EXPORT_STUB ProxyExport6, 6
D3D11_EXPORT_STUB ProxyExport7, 7
D3D11_EXPORT_STUB ProxyExport8, 8
D3D11_EXPORT_STUB ProxyExport9, 9
D3D11_EXPORT_STUB ProxyExport10, 10
D3D11_EXPORT_STUB ProxyExport11, 11
D3D11_EXPORT_STUB ProxyExport12, 12
D3D11_EXPORT_STUB ProxyExport13, 13
D3D11_EXPORT_STUB ProxyExport14, 14
D3D11_EXPORT_STUB ProxyExport15, 15
D3D11_EXPORT_STUB ProxyExport16, 16
D3D11_EXPORT_STUB ProxyExport17, 17
D3D11_EXPORT_STUB ProxyExport18, 18
D3D11_EXPORT_STUB ProxyExport19, 19
D3D11_EXPORT_STUB ProxyExport20, 20
D3D11_EXPORT_STUB ProxyExport21, 21
D3D11_EXPORT_STUB ProxyExport22, 22
D3D11_EXPORT_STUB ProxyExport23, 23
D3D11_EXPORT_STUB ProxyExport24, 24
D3D11_EXPORT_STUB ProxyExport25, 25
D3D11_EXPORT_STUB ProxyExport26, 26
D3D11_EXPORT_STUB ProxyExport27, 27
D3D11_EXPORT_STUB ProxyExport28, 28
D3D11_EXPORT_STUB ProxyExport29, 29
D3D11_EXPORT_STUB ProxyExport30, 30
D3D11_EXPORT_STUB ProxyExport31, 31
D3D11_EXPORT_STUB ProxyExport32, 32
D3D11_EXPORT_STUB ProxyExport33, 33
D3D11_EXPORT_STUB ProxyExport34, 34
D3D11_EXPORT_STUB ProxyExport35, 35
D3D11_EXPORT_STUB ProxyExport36, 36
D3D11_EXPORT_STUB ProxyExport37, 37
D3D11_EXPORT_STUB ProxyExport38, 38
D3D11_EXPORT_STUB ProxyExport39, 39
D3D11_EXPORT_STUB ProxyExport40, 40
D3D11_EXPORT_STUB ProxyExport41, 41
D3D11_EXPORT_STUB ProxyExport42, 42
D3D11_EXPORT_STUB ProxyExport43, 43
D3D11_EXPORT_STUB ProxyExport44, 44
D3D11_EXPORT_STUB ProxyExport45, 45
D3D11_EXPORT_STUB ProxyExport46, 46
D3D11_EXPORT_STUB ProxyExport47, 47
D3D11_EXPORT_STUB ProxyExport48, 48
D3D11_EXPORT_STUB ProxyExport49, 49
D3D11_EXPORT_STUB ProxyExport50, 50

end
