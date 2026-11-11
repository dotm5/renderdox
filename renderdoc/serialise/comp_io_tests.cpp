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

#include "lz4io.h"
#include "serialiser.h"
#include "zstdio.h"

#if ENABLED(ENABLE_UNIT_TESTS)

#include "catch/catch.hpp"

TEST_CASE("Test LZ4 compression/decompression", "[streamio][lz4]")
{
  StreamWriter buf(StreamWriter::DefaultScratchSize);

  byte *randomData = new byte[1024 * 1024];

  for(int i = 0; i < 1024 * 1024; i++)
    randomData[i] = rand() & 0xff;

  // write the data
  {
    StreamWriter writer(new LZ4Compressor(&buf, Ownership::Nothing), Ownership::Stream);

    byte *fixedData = new byte[1024 * 1024];
    byte *regularData = new byte[1024 * 1024];

    memset(fixedData, 0x7c, 1024 * 1024);

    for(int i = 0; i < 1024 * 1024; i++)
      regularData[i] = i & 0xff;

    writer.Write(fixedData, 1024 * 1024);
    writer.Write(randomData, 1024 * 1024);
    writer.Write(regularData, 1024 * 1024);
    writer.Write(fixedData, 1024 * 1024);

    // check that the compression got good wins out of the above data. The random data will be
    // pretty much untouched but the rest should compress massively.
    CHECK(buf.GetOffset() < 1024 * 1024 + 30 * 1024);
    CHECK(writer.GetOffset() == 4 * 1024 * 1024);

    CHECK_FALSE(writer.IsErrored());

    writer.Finish();

    CHECK_FALSE(writer.IsErrored());

    delete[] fixedData;
    delete[] regularData;
  }

  // we now only have the compressed data, decompress it
  {
    StreamReader reader(
        new LZ4Decompressor(new StreamReader(buf.GetData(), buf.GetOffset()), Ownership::Stream),
        4 * 1024 * 1024, Ownership::Stream);
    // recreate this for easy memcmp'ing
    byte *fixedData = new byte[1024 * 1024];
    byte *regularData = new byte[1024 * 1024];

    memset(fixedData, 0x7c, 1024 * 1024);

    for(int i = 0; i < 1024 * 1024; i++)
      regularData[i] = i & 0xff;

    byte *readData = new byte[1024 * 1024];

    reader.Read(readData, 1024 * 1024);
    CHECK_FALSE(memcmp(readData, fixedData, 1024 * 1024));

    reader.Read(readData, 1024 * 1024);
    CHECK_FALSE(memcmp(readData, randomData, 1024 * 1024));

    reader.Read(readData, 1024 * 1024);
    CHECK_FALSE(memcmp(readData, regularData, 1024 * 1024));

    reader.Read(readData, 1024 * 1024);
    CHECK_FALSE(memcmp(readData, fixedData, 1024 * 1024));

    CHECK_FALSE(reader.IsErrored());
    CHECK(reader.AtEnd());

    delete[] readData;
    delete[] fixedData;
    delete[] regularData;
  }

  delete[] randomData;
};

TEST_CASE("Parallel LZ4 retains stream order and dictionary history", "[streamio][lz4]")
{
  const size_t block = 1024 * 1024;
  bytebuf input;
  input.resize(8 * block + 37);
  uint32_t state = 1;
  for(size_t i = 0; i < block; i++)
  {
    state = 1664525U * state + 1013904223U;
    input[i] = byte(state >> 24);
  }

  // The beginning of each block can match bytes at the end of its predecessor.
  for(size_t i = block; i < input.size(); i++)
    input[i] = input[i - 32768];

  for(uint32_t workers : {2U, 3U, 4U})
  {
    StreamWriter buffer(StreamWriter::DefaultScratchSize);
    LZ4Compressor *compressor = new LZ4Compressor(&buffer, Ownership::Nothing);
    compressor->ConfigureParallelCompression(workers);
    StreamWriter writer(compressor, Ownership::Stream);
    for(size_t offset = 0; offset < input.size();)
    {
      const size_t count = RDCMIN(size_t(129013), input.size() - offset);
      REQUIRE(writer.Write(input.data() + offset, count));
      offset += count;
    }
    REQUIRE(writer.Finish());

    StreamReader reader(
        new LZ4Decompressor(new StreamReader(buffer.GetData(), buffer.GetOffset()), Ownership::Stream),
        input.size(), Ownership::Stream);
    bytebuf decoded;
    decoded.resize(input.size());
    REQUIRE(reader.Read(decoded.data(), decoded.size()));
    CHECK(reader.AtEnd());
    CHECK(memcmp(decoded.data(), input.data(), input.size()) == 0);
  }
}

TEST_CASE("Test ZSTD compression/decompression", "[streamio][zstd]")
{
  StreamWriter buf(StreamWriter::DefaultScratchSize);

  byte *randomData = new byte[1024 * 1024];

  for(int i = 0; i < 1024 * 1024; i++)
    randomData[i] = rand() & 0xff;

  // write the data
  {
    StreamWriter writer(new ZSTDCompressor(&buf, Ownership::Nothing), Ownership::Stream);

    byte *fixedData = new byte[1024 * 1024];
    byte *regularData = new byte[1024 * 1024];

    memset(fixedData, 0x7c, 1024 * 1024);

    for(int i = 0; i < 1024 * 1024; i++)
      regularData[i] = i & 0xff;

    writer.Write(fixedData, 1024 * 1024);
    writer.Write(randomData, 1024 * 1024);
    writer.Write(regularData, 1024 * 1024);
    writer.Write(fixedData, 1024 * 1024);

    // check that the compression got good wins out of the above data. The random data will be
    // pretty much untouched but the rest should compress massively.
    CHECK(buf.GetOffset() < 1024 * 1024 + 4 * 1024);
    CHECK(writer.GetOffset() == 4 * 1024 * 1024);

    CHECK_FALSE(writer.IsErrored());

    writer.Finish();

    CHECK_FALSE(writer.IsErrored());

    delete[] fixedData;
    delete[] regularData;
  }

  // we now only have the compressed data, decompress it
  {
    StreamReader reader(
        new ZSTDDecompressor(new StreamReader(buf.GetData(), buf.GetOffset()), Ownership::Stream),
        4 * 1024 * 1024, Ownership::Stream);
    // recreate this for easy memcmp'ing
    byte *fixedData = new byte[1024 * 1024];
    byte *regularData = new byte[1024 * 1024];

    memset(fixedData, 0x7c, 1024 * 1024);

    for(int i = 0; i < 1024 * 1024; i++)
      regularData[i] = i & 0xff;

    byte *readData = new byte[1024 * 1024];

    reader.Read(readData, 1024 * 1024);
    CHECK_FALSE(memcmp(readData, fixedData, 1024 * 1024));

    reader.Read(readData, 1024 * 1024);
    CHECK_FALSE(memcmp(readData, randomData, 1024 * 1024));

    reader.Read(readData, 1024 * 1024);
    CHECK_FALSE(memcmp(readData, regularData, 1024 * 1024));

    reader.Read(readData, 1024 * 1024);
    CHECK_FALSE(memcmp(readData, fixedData, 1024 * 1024));

    CHECK_FALSE(reader.IsErrored());
    CHECK(reader.AtEnd());

    delete[] readData;
    delete[] fixedData;
    delete[] regularData;
  }

  delete[] randomData;
};

#endif    // ENABLED(ENABLE_UNIT_TESTS)
