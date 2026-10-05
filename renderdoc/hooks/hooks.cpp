/******************************************************************************
 * The MIT License (MIT)
 *
 * Copyright (c) 2015-2026 Baldur Karlsson
 * Copyright (c) 2014 Crytek
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 ******************************************************************************/

#include "hooks.h"
#include "common/common.h"
#include "common/threading.h"
#include "common/formatting.h"
#include "os/os_specific.h"
#if defined(_WIN32)
#include <windows.h>
#endif

bool DxClosureEnabled()
{
  static const bool enabled = Process::GetEnvVariable("DCOMP_DX_CLOSURE") == "1";
  return enabled;
}

void DxClosureEvent(const char *kind, const char *site, const void *object, const void *related)
{
  if(!DxClosureEnabled())
    return;
#if defined(_WIN32)
  const DWORD savedError = GetLastError();
#endif
  RDCLOG("[dx-closure] kind=%s site=%s object=%p related=%p", kind, site, object, related);
  // Core's normal debug log is deleted at clean shutdown. Keep an optional independent
  // per-process artifact; no COM references are held by the diagnostic sink.
  static Threading::CriticalSection lock;
  {
    SCOPED_LOCK(lock);
    static FILE *sink = []() -> FILE * {
      rdcstr base = Process::GetEnvVariable("DCOMP_DX_CLOSURE_LOG");
      if(base.empty()) return NULL;
      return FileIO::fopen(StringFormat::Fmt("%s.%u.log", base.c_str(), Process::GetCurrentPID()),
                           FileIO::WriteBinary);
    }();
    if(sink)
    {
      const rdcstr line = StringFormat::Fmt("[dx-closure] kind=%s site=%s object=%p related=%p\n",
                                            kind, site, object, related);
      FileIO::fwrite(line.c_str(), 1, line.size(), sink);
      fflush(sink);
    }
  }
#if defined(_WIN32)
  SetLastError(savedError);
#endif
}

static rdcarray<LibraryHook *> &LibList()
{
  static rdcarray<LibraryHook *> libs;
  return libs;
}

LibraryHook::LibraryHook()
{
  LibList().push_back(this);
}

void LibraryHooks::RegisterHooks()
{
#if defined(DCOMP_DIAGNOSTIC_DISABLE_ALL_HOOKS) && DCOMP_DIAGNOSTIC_DISABLE_ALL_HOOKS
  if(Process::IsDCompDiagnosticTargetProcess())
  {
    RDCLOG("[DCOMP-AB] all library hooks disabled in diagnostic target");
    return;
  }
#endif

  BeginHookRegistration();

  for(LibraryHook *lib : LibList())
    lib->RegisterHooks();

  EndHookRegistration();
}

void LibraryHooks::RemoveHookCallbacks()
{
  for(LibraryHook *lib : LibList())
    lib->RemoveHooks();
}

void LibraryHooks::OptionsUpdated()
{
  for(LibraryHook *lib : LibList())
    lib->OptionsUpdated();
}
