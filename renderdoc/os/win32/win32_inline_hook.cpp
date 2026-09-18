/******************************************************************************
 * The MIT License (MIT)
 *
 * Copyright (c) 2026 DComp contributors
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

// This is the only translation unit that consumes the SafetyHook headers. They
// require C++23, so it is compiled with /std:c++latest while the rest of the
// core keeps the project default - see win32_inline_hook.h for the contract.

#include "os/win32/win32_inline_hook.h"

#if defined(DCOMP_INLINE_GRAPHICS_HOOKS) && DCOMP_INLINE_GRAPHICS_HOOKS

#include <safetyhook.hpp>

#include <cstdint>
#include <utility>

#include "common/common.h"

struct Win32InlineHook
{
  safetyhook::InlineHook hook;
};

static void LogInlineHookError(void *target, const safetyhook::InlineHook::Error &error)
{
  switch(error.type)
  {
    case safetyhook::InlineHook::Error::BAD_ALLOCATION:
      RDCERR("Inline hook at %p: the engine could not allocate the trampoline", target);
      break;
    case safetyhook::InlineHook::Error::FAILED_TO_DECODE_INSTRUCTION:
      RDCERR("Inline hook at %p: could not decode the instruction at %p", target, error.ip);
      break;
    case safetyhook::InlineHook::Error::SHORT_JUMP_IN_TRAMPOLINE:
      RDCERR("Inline hook at %p: the trampoline contains a short jump at %p", target, error.ip);
      break;
    case safetyhook::InlineHook::Error::IP_RELATIVE_INSTRUCTION_OUT_OF_RANGE:
      RDCERR("Inline hook at %p: the IP-relative instruction at %p is out of range", target,
             error.ip);
      break;
    case safetyhook::InlineHook::Error::UNSUPPORTED_INSTRUCTION_IN_TRAMPOLINE:
      RDCERR("Inline hook at %p: unsupported instruction in the trampoline at %p", target, error.ip);
      break;
    case safetyhook::InlineHook::Error::FAILED_TO_UNPROTECT:
      RDCERR("Inline hook at %p: the target page could not be made writable", target);
      break;
    case safetyhook::InlineHook::Error::NOT_ENOUGH_SPACE:
      RDCERR("Inline hook at %p: not enough space at the target to install the hook", target);
      break;
    default:
      RDCERR("Inline hook at %p: the hook engine reported error %u", target, (uint32_t)error.type);
      break;
  }
}

Win32InlineHook *Win32CreateInlineHook(void *target, void *detour, void **trampoline)
{
  if(target == NULL || detour == NULL || trampoline == NULL)
  {
    RDCERR("Inline hook request is incomplete: target %p, detour %p, trampoline %p", target, detour,
           trampoline);
    return NULL;
  }

  auto created =
      safetyhook::InlineHook::create(target, detour, safetyhook::InlineHook::StartDisabled);
  if(!created)
  {
    LogInlineHookError(target, created.error());
    return NULL;
  }

  Win32InlineHook *handle = new Win32InlineHook{std::move(*created)};

  // The trampoline is built when the hook is created, so it is valid to publish
  // before the detour is enabled.
  *trampoline = (void *)handle->hook.trampoline().address();

  return handle;
}

bool Win32EnableInlineHook(Win32InlineHook *hook)
{
  if(hook == NULL)
    return false;

  auto enabled = hook->hook.enable();
  if(!enabled)
  {
    LogInlineHookError((void *)hook->hook.target(), enabled.error());
    return false;
  }

  return true;
}

void Win32DestroyInlineHook(Win32InlineHook *hook)
{
  if(hook == NULL)
    return;

  // Unhooks the target and releases the trampoline the engine allocated.
  hook->hook.reset();

  delete hook;
}

#endif
