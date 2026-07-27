.386
.model flat
option casemap:none

extern _ResolveExport:proc

.code

D3D12_EXPORT_STUB macro symbol:req, index:req
symbol proc
    pushfd
    pushad
    push index
    call _ResolveExport
    add esp, 4
    mov dword ptr [esp+1ch], eax
    popad
    popfd
    jmp eax
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
D3D12_EXPORT_STUB ProxyExport18, 18

end
