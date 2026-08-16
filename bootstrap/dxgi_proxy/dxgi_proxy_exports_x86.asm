.386
.model flat
option casemap:none

extern _ResolveExport:proc

.code

DXGI_EXPORT_STUB macro symbol:req, index:req
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
