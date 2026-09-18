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

#pragma once

// Adapter around the inline-hook engine (SafetyHook, see third_party/safetyhook).
//
// The engine headers require C++23, which the rest of the core does not build
// with, so only the implementation translation unit consumes them. This header
// deliberately exposes handles and plain pointers so callers keep building with
// the project default and do not inherit the engine's headers or standard.
//
// The API keeps the ordering the hook layer relies on: a hook is created
// disabled, the caller publishes the trampoline to every visitor-visible slot,
// and only then is the detour enabled. That way the first intercepted call can
// always continue into the original implementation.

struct Win32InlineHook;

// Creates a hook on `target` that starts disabled. On success `*trampoline`
// receives the address that continues into the original implementation.
// Returns NULL after logging when the engine refuses the hook.
Win32InlineHook *Win32CreateInlineHook(void *target, void *detour, void **trampoline);

// Enables a hook created above. Returns false after logging when the engine
// refuses, leaving the hook disabled.
bool Win32EnableInlineHook(Win32InlineHook *hook);

// Unhooks and releases the handle. Safe to call with NULL.
void Win32DestroyInlineHook(Win32InlineHook *hook);
