/******************************************************************************
 * The MIT License (MIT)
 *
 * Copyright (c) 2017-2026 Baldur Karlsson
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

#include <condition_variable>
#include <cstdlib>
#include <mutex>
#include <new>
#include "lz4io.h"

static const uint64_t lz4BlockSize = 1024 * 1024;

// One fixed slot per worker, six registered input pages, and producer-only ordered drain.
// Page registration owns allocations; writable/slot/free pointers are non-owning aliases.
struct LZ4Compressor::ParallelState
{
  enum : uint32_t { PageCount = 6 };
  struct Slot
  {
    byte *allocation = NULL; // private dictionary followed by output
    byte *input = NULL;
    LZ4_stream_t *state = NULL;
    Threading::ThreadHandle thread = 0;
    int inputSize = 0, dictionarySize = 0, compressedSize = 0;
    bool pending = false, done = false;
  } slots[4];
  byte *pages[PageCount] = {};
  byte *freePages[PageCount] = {};
  byte lastDict[65536]; // producer-only history, independent of returned input pages
  uint32_t freeCount = 0, count = 0;
  uint64_t submitted = 0, completed = 0;    // completed means successfully output/drained
  bool stop = false;
  std::mutex mutex;
  std::condition_variable ready;

  ~ParallelState()
  {
    {
      std::lock_guard<std::mutex> lock(mutex);
      stop = true;
    }
    ready.notify_all();
    for(Slot &slot : slots)
    {
      if(slot.thread)
      {
        Threading::JoinThread(slot.thread);
        Threading::CloseThread(slot.thread);
      }
      LZ4_freeStream(slot.state);
      free(slot.allocation);
    }
    // All workers have joined. Each allocation is freed exactly once via registration.
    for(byte *page : pages)
      free(page);
  }

  void Run(uint32_t index)
  {
    Slot &slot = slots[index];
    for(;;)
    {
      std::unique_lock<std::mutex> lock(mutex);
      ready.wait(lock, [this, &slot]() { return stop || slot.pending; });
      if(stop)
        return;
      lock.unlock();
      LZ4_loadDict(slot.state, (const char *)slot.allocation, slot.dictionarySize);
      slot.compressedSize = LZ4_compress_fast_continue(
          slot.state, (const char *)slot.input, (char *)slot.allocation + 65536, slot.inputSize,
          (int)LZ4_COMPRESSBOUND(lz4BlockSize), 20);
      lock.lock();
      // LZ4 retains pointer values in state, but next loadDict resets it without reading the
      // old input. No consumer reads this page after the compression call has returned.
      // A failed block keeps its input for the producer's exact-input synchronous retry.
      if(slot.compressedSize > 0)
      {
        RDCASSERT(freeCount < uint32_t(PageCount) && slot.input != NULL);
        freePages[freeCount++] = slot.input;
        slot.input = NULL;
      }
      slot.pending = false;
      slot.done = true;
      lock.unlock();
      ready.notify_all();
    }
  }
};

void LZ4Compressor::ConfigureParallelCompression(uint32_t workers)
{
  // Configure once, before input. No pool, state, or lock is added to the default path.
  if(m_Parallel || m_InputStarted || m_Finished || m_Failed)
    return;
  if(workers <= 1)
    return;
  ParallelState *parallel = new(std::nothrow) ParallelState;
  bool success = parallel != NULL;
  if(parallel)
  {
    parallel->count = RDCMIN(workers, 4U);
    for(uint32_t i = 0; success && i < ParallelState::PageCount; ++i)
    {
      parallel->pages[i] = (byte *)malloc(size_t(lz4BlockSize));
      success = parallel->pages[i] != NULL;
      if(success)
        parallel->freePages[parallel->freeCount++] = parallel->pages[i];
    }
    for(uint32_t i = 0; success && i < parallel->count; ++i)
    {
      ParallelState::Slot &slot = parallel->slots[i];
      slot.allocation = (byte *)malloc(size_t(65536 + LZ4_COMPRESSBOUND(lz4BlockSize)));
      slot.state = LZ4_createStream();
      success = slot.allocation && slot.state;
    }
    for(uint32_t i = 0; success && i < parallel->count; ++i)
    {
      parallel->slots[i].thread = Threading::CreateThread([parallel, i]() { parallel->Run(i); });
      success = parallel->slots[i].thread != 0;
    }
  }
  if(!success)
  {
    delete parallel;
    RDCWARN("Parallel LZ4 worker setup failed; using sequential compression");
    return;
  }
  // Commit ownership only after every allocation and worker has succeeded, before any input.
  FreeAlignedBuffer(m_Page[0]);
  FreeAlignedBuffer(m_Page[1]);
  m_Page[1] = NULL;
  {
    std::lock_guard<std::mutex> lock(parallel->mutex);
    m_Page[0] = parallel->freePages[--parallel->freeCount];
  }
  m_Parallel = parallel;
}

bool LZ4Compressor::DrainParallelBlock()
{
  ParallelState &parallel = *m_Parallel;
  if(parallel.completed == parallel.submitted)
    return true;
  ParallelState::Slot &slot = parallel.slots[parallel.completed % parallel.count];
  {
    std::unique_lock<std::mutex> lock(parallel.mutex);
    parallel.ready.wait(lock, [&slot]() { return slot.done; });
  }
  byte *output = slot.allocation + 65536;
  if(slot.compressedSize <= 0)
  {
    LZ4_loadDict(m_LZ4Comp, (const char *)slot.allocation, slot.dictionarySize);
    slot.compressedSize =
        LZ4_compress_fast_continue(m_LZ4Comp, (const char *)slot.input, (char *)output,
                                   slot.inputSize, (int)LZ4_COMPRESSBOUND(lz4BlockSize), 20);
    {
      std::lock_guard<std::mutex> lock(parallel.mutex);
      RDCASSERT(parallel.freeCount < uint32_t(ParallelState::PageCount) && slot.input != NULL);
      parallel.freePages[parallel.freeCount++] = slot.input;
      slot.input = NULL;
    }
  }
  if(slot.compressedSize <= 0)
  {
    m_Failed = true;
    SET_ERROR_RESULT(m_Error, ResultCode::CompressionFailed, "Parallel LZ4 compression failed");
    return false;
  }
  const int32_t compressedSize = slot.compressedSize;
  const bool success = m_Write->Write(compressedSize) && m_Write->Write(output, compressedSize);
  if(!success)
  {
    m_Error = m_Write->GetError();
    m_Failed = true;
    return false;
  }
  {
    std::lock_guard<std::mutex> lock(parallel.mutex);
    slot.done = false;
  }
  ++parallel.completed;
  return true;
}

bool LZ4Compressor::SubmitParallelBlock()
{
  ParallelState &parallel = *m_Parallel;
  if(parallel.submitted - parallel.completed == parallel.count && !DrainParallelBlock())
    return false;
  ParallelState::Slot &slot = parallel.slots[parallel.submitted % parallel.count];
  slot.inputSize = (int)m_PageOffset;
  slot.dictionarySize = parallel.submitted ? 65536 : 0;
  if(slot.dictionarySize)
    memcpy(slot.allocation, parallel.lastDict, 65536);
  // Only Finish can submit a short page, and there is no subsequent block after Finish.
  if(m_PageOffset >= 65536)
    memcpy(parallel.lastDict, m_Page[0] + m_PageOffset - 65536, 65536);
  {
    std::lock_guard<std::mutex> lock(parallel.mutex);
    // At most count slots plus one producer page are owned: six pages guarantee a filler.
    RDCASSERT(parallel.freeCount > 0 && !slot.pending && !slot.done && slot.input == NULL);
    slot.input = m_Page[0];
    m_Page[0] = parallel.freePages[--parallel.freeCount];
    slot.pending = true;
    ++parallel.submitted;
  }
  parallel.ready.notify_all();
  m_PageOffset = 0;
  return true;
}

LZ4Compressor::LZ4Compressor(StreamWriter *write, Ownership own) : Compressor(write, own)
{
  m_Page[0] = AllocAlignedBuffer(lz4BlockSize);
  m_Page[1] = AllocAlignedBuffer(lz4BlockSize);
  m_CompressBuffer = AllocAlignedBuffer(LZ4_COMPRESSBOUND(lz4BlockSize));

  m_PageOffset = 0;

  m_LZ4Comp = LZ4_createStream();
}

LZ4Compressor::~LZ4Compressor()
{
  if(m_Parallel)
    m_Page[0] = NULL; // pool registration, not the writable alias, owns this page
  delete m_Parallel;
  FreeAlignedBuffer(m_Page[0]);
  FreeAlignedBuffer(m_Page[1]);
  FreeAlignedBuffer(m_CompressBuffer);
  LZ4_freeStream(m_LZ4Comp);
}

bool LZ4Compressor::Write(const void *data, uint64_t numBytes)
{
  if(m_Finished)
  {
    m_Failed = true;
    SET_ERROR_RESULT(m_Error, ResultCode::CompressionFailed, "LZ4 Write after Finish");
    return false;
  }
  if(m_Failed || !m_CompressBuffer)
    return false;

  if(numBytes == 0)
    return true;

  // The basic plan is:
  // Write into page N incrementally until it is completely full. When full, flush it out to lz4 and
  // swap pages.
  // This keeps lz4 happy with 1 block of history each time it compresses.
  // If we are writing some data the crosses the boundary between pages, we write the part that will
  // fit on one page, flush & swap, write the rest into the next page.

  m_InputStarted = true;

  if(m_PageOffset + numBytes <= lz4BlockSize)
  {
    // simplest path, no page wrapping/spanning at all
    memcpy(m_Page[0] + m_PageOffset, data, (size_t)numBytes);
    m_PageOffset += numBytes;

    return true;
  }
  else
  {
    // do partial copies that span pages and flush as necessary

    const byte *src = (const byte *)data;

    // copy whatever will fit on this page
    {
      uint64_t firstBytes = lz4BlockSize - m_PageOffset;
      memcpy(m_Page[0] + m_PageOffset, src, (size_t)firstBytes);

      m_PageOffset += firstBytes;
      numBytes -= firstBytes;
      src += firstBytes;
    }

    bool success = true;

    while(success && numBytes > 0)
    {
      // flush and swap pages
      success &= FlushPage0();

      if(!success)
        return success;

      // how many bytes can we copy in this page?
      uint64_t partialBytes = RDCMIN(lz4BlockSize, numBytes);
      memcpy(m_Page[0], src, (size_t)partialBytes);

      // advance the source pointer, dest offset, and remove the bytes we read
      m_PageOffset += partialBytes;
      numBytes -= partialBytes;
      src += partialBytes;
    }

    return success;
  }
}

bool LZ4Compressor::Finish()
{
  // This function just writes the current page and closes lz4. Since we assume all blocks are
  // uniform in size
  // only the last one can be smaller, so we only write a partial page when finishing.
  // Calling Write() after Finish() is illegal
  if(m_Finished)
    return !m_Failed;
  m_Finished = true;
  bool success = !m_Failed && FlushPage0();
  if(m_Parallel)
    while(success && m_Parallel->completed < m_Parallel->submitted)
      success = DrainParallelBlock();
  m_Failed = !success;

  return success;
}

bool LZ4Compressor::FlushPage0()
{
  // if we encountered a stream error this will be NULL
  if(m_Failed || !m_CompressBuffer)
    return false;

  if(m_Parallel)
    return SubmitParallelBlock();

  // m_PageOffset is the amount written, usually equal to lz4BlockSize except the last block.
  int32_t compSize =
      LZ4_compress_fast_continue(m_LZ4Comp, (const char *)m_Page[0], (char *)m_CompressBuffer,
                                 (int)m_PageOffset, (int)LZ4_COMPRESSBOUND(lz4BlockSize), 20);

  if(compSize <= 0)
  {
    FreeAlignedBuffer(m_Page[0]);
    FreeAlignedBuffer(m_Page[1]);
    FreeAlignedBuffer(m_CompressBuffer);
    m_Page[0] = m_Page[1] = m_CompressBuffer = NULL;
    m_Failed = true;
    SET_ERROR_RESULT(m_Error, ResultCode::CompressionFailed, "LZ4 compression failed: %i", compSize);
    return false;
  }

  bool success = true;

  success &= m_Write->Write(compSize);
  if(!success)
    m_Error = m_Write->GetError();
  if(success)
    success = m_Write->Write(m_CompressBuffer, compSize);
  if(!success)
    m_Error = m_Write->GetError();

  if(!success)
  {
    m_Failed = true;
    return false;
  }

  // swap pages
  std::swap(m_Page[0], m_Page[1]);

  // start writing to the start of the page again
  m_PageOffset = 0;

  return success;
}

LZ4Decompressor::LZ4Decompressor(StreamReader *read, Ownership own) : Decompressor(read, own)
{
  m_Page[0] = AllocAlignedBuffer(lz4BlockSize);
  m_Page[1] = AllocAlignedBuffer(lz4BlockSize);
  m_CompressBuffer = AllocAlignedBuffer(LZ4_COMPRESSBOUND(lz4BlockSize));

  m_PageOffset = 0;
  m_PageLength = 0;

  m_LZ4Decomp = LZ4_createStreamDecode();

  LZ4_setStreamDecode(m_LZ4Decomp, NULL, 0);
}

LZ4Decompressor::~LZ4Decompressor()
{
  FreeAlignedBuffer(m_Page[0]);
  FreeAlignedBuffer(m_Page[1]);
  FreeAlignedBuffer(m_CompressBuffer);

  LZ4_freeStreamDecode(m_LZ4Decomp);
}

bool LZ4Decompressor::Recompress(Compressor *comp)
{
  bool success = true;

  while(success && !m_Read->AtEnd())
  {
    success &= FillPage0();
    if(success)
    {
      success &= comp->Write(m_Page[0], m_PageLength);

      if(!success)
        m_Error = comp->GetError();
    }
  }
  success &= comp->Finish();

  return success;
}

bool LZ4Decompressor::Read(void *data, uint64_t numBytes)
{
  // if we encountered a stream error this will be NULL
  if(!m_CompressBuffer)
    return false;

  if(numBytes == 0)
    return true;

  // At any point, m_Page[0] contains the current window with uncompressed bytes.
  // If we can satisfy a read from it, then we just memcpy and increment m_PageOffset.
  // When we wrap around, we do a partial memcpy from m_Page[0], then swap the pages and
  // decompress some more bytes into m_Page[0]. Thus, m_Page[1] contains the history (if
  // it exists)

  // if we already have all the data in-memory, just copy and return
  uint64_t available = m_PageLength - m_PageOffset;

  if(numBytes <= available)
  {
    memcpy(data, m_Page[0] + m_PageOffset, (size_t)numBytes);
    m_PageOffset += numBytes;
    return true;
  }

  byte *dst = (byte *)data;

  // copy what remains in m_Page[0]
  memcpy(dst, m_Page[0] + m_PageOffset, (size_t)available);

  // adjust what needs to be copied
  dst += available;
  numBytes -= available;

  bool success = true;

  while(success && numBytes > 0)
  {
    success &= FillPage0();

    if(!success)
      return success;

    // if we can now satisfy the remainder of the read, do so and return
    if(numBytes <= m_PageLength)
    {
      memcpy(dst, m_Page[0], (size_t)numBytes);
      m_PageOffset += numBytes;
      return success;
    }

    // otherwise copy this page in and continue
    memcpy(dst, m_Page[0], (size_t)m_PageLength);
    dst += m_PageLength;
    numBytes -= m_PageLength;
  }

  return success;
}

bool LZ4Decompressor::FillPage0()
{
  // swap pages
  std::swap(m_Page[0], m_Page[1]);

  int32_t compSize = 0;

  bool success = true;

  success &= m_Read->Read(compSize);
  if(!success || compSize < 0 || compSize > (int)LZ4_COMPRESSBOUND(lz4BlockSize))
  {
    FreeAlignedBuffer(m_Page[0]);
    FreeAlignedBuffer(m_Page[1]);
    FreeAlignedBuffer(m_CompressBuffer);
    m_Page[0] = m_Page[1] = m_CompressBuffer = NULL;

    if(success)
    {
      m_Error = m_Read->GetError();
    }
    else
    {
      SET_ERROR_RESULT(m_Error, ResultCode::CompressionFailed,
                       "LZ4 decompression encountered invalid compressed block size: %i", compSize);
    }
    return false;
  }

  success &= m_Read->Read(m_CompressBuffer, compSize);

  if(!success)
  {
    FreeAlignedBuffer(m_Page[0]);
    FreeAlignedBuffer(m_Page[1]);
    FreeAlignedBuffer(m_CompressBuffer);
    m_Page[0] = m_Page[1] = m_CompressBuffer = NULL;
    m_Error = m_Read->GetError();
    return false;
  }

  int32_t decompSize = LZ4_decompress_safe_continue(m_LZ4Decomp, (const char *)m_CompressBuffer,
                                                    (char *)m_Page[0], compSize, lz4BlockSize);

  if(decompSize < 0)
  {
    FreeAlignedBuffer(m_Page[0]);
    FreeAlignedBuffer(m_Page[1]);
    FreeAlignedBuffer(m_CompressBuffer);
    m_Page[0] = m_Page[1] = m_CompressBuffer = NULL;

    SET_ERROR_RESULT(m_Error, ResultCode::CompressionFailed,
                     "LZ4 decompression failed on block: %i", decompSize);

    return false;
  }

  m_PageOffset = 0;
  m_PageLength = decompSize;

  return success;
}
