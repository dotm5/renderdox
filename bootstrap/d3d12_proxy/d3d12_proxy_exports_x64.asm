option casemap:none

extern ResolveExport:proc

.code

D3D12_EXPORT_STUB macro symbol:req, index:req
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

D3D12_EXPORT_STUB ProxyExport0, 0
D3D12_EXPORT_STUB ProxyExport1, 1
D3D12_EXPORT_STUB ProxyExport2, 2
D3D12_EXPORT_STUB ProxyExport3, 3
D3D12_EXPORT_STUB ProxyExport4, 4
D3D12_EXPORT_STUB ProxyExport5, 5
D3D12_EXPORT_STUB ProxyExport6, 6
D3D12_EXPORT_STUB ProxyExport7, 7
D3D12_EXPORT_STUB ProxyExport8, 8
D3D12_EXPORT_STUB ProxyExport9, 9
D3D12_EXPORT_STUB ProxyExport10, 10
D3D12_EXPORT_STUB ProxyExport11, 11
D3D12_EXPORT_STUB ProxyExport12, 12
D3D12_EXPORT_STUB ProxyExport13, 13
D3D12_EXPORT_STUB ProxyExport14, 14
D3D12_EXPORT_STUB ProxyExport15, 15
D3D12_EXPORT_STUB ProxyExport16, 16
D3D12_EXPORT_STUB ProxyExport17, 17

end
