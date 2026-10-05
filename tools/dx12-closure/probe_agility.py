"""Read-only SDKConfiguration availability check, without loading/injecting dgcore."""
import ctypes
import json
import uuid
import argparse
import os


class GUID(ctypes.Structure):
    _fields_ = [("bytes", ctypes.c_ubyte * 16)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


parser = argparse.ArgumentParser()
parser.add_argument("--core", help="Preload an existing D3D12Core.dll before requesting configuration")
args = parser.parse_args()
library = ctypes.WinDLL("C:\\Windows\\System32\\d3d12.dll")
sdk = ctypes.WinDLL(args.core) if args.core else None
fn = library.D3D12GetInterface
fn.argtypes = [ctypes.POINTER(GUID), ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)]
fn.restype = ctypes.c_long
clsid = GUID.parse("7cda6aca-a03e-49c8-9458-0334d20e07ce")
iid = GUID.parse("e9eb5314-33aa-42b2-a718-d77f58b1f1c7")
obj = ctypes.c_void_p()
hr = fn(ctypes.byref(clsid), ctypes.byref(iid), ctypes.byref(obj))
print(json.dumps({"nativeSDKConfigurationHRESULT": "0x%08x" % (hr & 0xffffffff),
                  "available": hr >= 0 and bool(obj.value), "preloadedCore": args.core}))
if obj.value:
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    qi = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(GUID),
                            ctypes.POINTER(ctypes.c_void_p))(vtable[0])
    iid1 = GUID.parse("8aaf9303-ad25-48b9-9a57-d9c37e009d9f")
    obj1 = ctypes.c_void_p()
    hr1 = qi(obj, ctypes.byref(iid1), ctypes.byref(obj1))
    print(json.dumps({"nativeSDKConfiguration1HRESULT": "0x%08x" % (hr1 & 0xffffffff),
                      "available": hr1 >= 0 and bool(obj1.value)}))
    if obj1.value:
        vt1 = ctypes.cast(obj1, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        if sdk:
            version = ctypes.c_uint.in_dll(sdk, "D3D12SDKVersion").value
            factoryIID = GUID.parse("61f307d3-d34e-4e7c-8374-3ba4de23cccb")
            factory = ctypes.c_void_p()
            create = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_uint,
                                        ctypes.c_char_p, ctypes.POINTER(GUID),
                                        ctypes.POINTER(ctypes.c_void_p))(vt1[4])
            hrFactory = create(obj1, version,
                               os.fsencode(os.path.dirname(args.core) + os.sep),
                               ctypes.byref(factoryIID), ctypes.byref(factory))
            print(json.dumps({"nativeCreateDeviceFactoryHRESULT": "0x%08x" %
                              (hrFactory & 0xffffffff), "sdkVersion": version,
                              "available": hrFactory >= 0 and bool(factory.value)}))
            if factory.value:
                vf = ctypes.cast(factory, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
                ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vf[2])(factory)
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vt1[2])(obj1)
    release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
    release(obj)
