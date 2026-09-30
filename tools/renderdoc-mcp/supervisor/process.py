import asyncio
import json
import os
import secrets
import uuid
from pathlib import Path

from contracts import ToolError


class Worker:
    def __init__(self, package_root, source_root, interpreter, output, mode, on_event=None):
        self.package_root, self.source_root = Path(package_root), Path(source_root)
        self.interpreter, self.output, self.mode = Path(interpreter), Path(output), mode
        self.identifier = "worker-" + uuid.uuid4().hex
        self.on_event, self.process, self.reader_task = on_event, None, None
        self.lock, self.pending, self.tasks = asyncio.Lock(), {}, set()
        self.closing = False

    async def start(self):
        loop = asyncio.get_running_loop()
        connected = loop.create_future()
        token = secrets.token_hex(32)
        async def accept(reader, writer):
            try:
                hello = json.loads(await reader.readline())
                if hello.get("token") != token or connected.done():
                    writer.close()
                    return
                connected.set_result((reader, writer, hello["hello"]))
            except Exception as exc:
                writer.close()
                if not connected.done():
                    connected.set_exception(exc)
        server = await asyncio.start_server(accept, "127.0.0.1", 0, limit=128 * 1024 * 1024)
        self.listener = server
        directory = self.output / "workers" / self.identifier
        directory.mkdir(parents=True, exist_ok=True)
        self.log = open(directory / "native.log", "wb")
        try:
            command = [str(self.interpreter), str(self.source_root / "worker" / "entry.py"),
                       "--package-root", str(self.package_root), "--mode", self.mode,
                       "--port", str(server.sockets[0].getsockname()[1]), "--token", token,
                       "--artifacts", str(directory / "artifacts")]
            self.process = await asyncio.create_subprocess_exec(*command, cwd=str(self.package_root),
                stdin=asyncio.subprocess.DEVNULL, stdout=self.log, stderr=self.log,
                creationflags=0x08000000 if os.name == "nt" else 0)
            self.reader, self.writer, self.hello = await asyncio.wait_for(connected, 45)
            self.reader_task = asyncio.create_task(self.read_messages())
            return self
        except BaseException:
            if self.process and self.process.returncode is None:
                self.process.kill()
                await self.process.wait()
            self.log.close()
            raise
        finally:
            server.close()
            # On modern asyncio, wait_closed also waits for accepted clients.
            # The authenticated IPC client lives until Worker.close.

    async def read_messages(self):
        try:
            while True:
                line = await self.reader.readline()
                if not line:
                    raise ToolError("worker_exited", "Native worker ended; inspect its native.log")
                message = json.loads(line)
                if "event" in message:
                    if self.on_event:
                        self.on_event(message["event"])
                else:
                    future = self.pending.pop(message["id"], None)
                    if future and not future.done():
                        if "error" in message:
                            error = message["error"]
                            future.set_exception(ToolError(error["code"], error["message"], error.get("traceback")))
                        else:
                            future.set_result(message["result"])
        except (Exception, asyncio.CancelledError) as exc:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(exc if isinstance(exc, Exception) else ToolError("worker_closed", "Worker closed"))
            self.pending.clear()

    async def invoke(self, operation, arguments):
        # Lock belongs to the actual operation task, so cancelling a client
        # await never unlocks a still-running native transaction.
        async with self.lock:
            if self.process is None or self.process.returncode is not None:
                raise ToolError("worker_exited", self.identifier)
            request_id = uuid.uuid4().hex
            future = asyncio.get_running_loop().create_future()
            self.pending[request_id] = future
            try:
                self.writer.write((json.dumps({"id": request_id, "operation": operation, "arguments": arguments}) + "\n").encode())
                await self.writer.drain()
                return await future
            finally:
                self.pending.pop(request_id, None)

    async def call(self, operation, arguments=None):
        if self.closing:
            raise ToolError("worker_closing", self.identifier)
        task = asyncio.create_task(self.invoke(operation, arguments or {}))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        # Retrieve detached errors as well as keeping serial ownership intact.
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        return await asyncio.shield(task)

    async def close(self):
        if self.closing:
            return
        self.closing = True
        if self.process:
            if self.process.returncode is None:
                try:
                    await self.invoke("shutdown", {})
                    await self.process.wait()
                except Exception:
                    if self.process.returncode is None:
                        self.process.kill()
                        await self.process.wait()
            if hasattr(self, "writer"):
                self.writer.close()
            if self.reader_task:
                self.reader_task.cancel()
                await asyncio.gather(self.reader_task, return_exceptions=True)
            await self.listener.wait_closed()
            self.log.close()
