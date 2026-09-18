"""Process-tree signalling and streamed subprocess execution."""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from typing import List


def terminate_process_tree(process, force: bool = False) -> None:
    """Signals the process (and its process group) with SIGTERM or SIGKILL.

    The child is started with start_new_session=True, so its PID is also its
    process-group id. Signaling the group ensures grandchildren spawned by the
    agent CLI are stopped too, not just the immediate child.
    """
    if not process or not hasattr(process, "pid") or not isinstance(process.pid, int) or process.pid <= 0:
        return
    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        pgid = os.getpgid(process.pid)
        if pgid == os.getpgrp() or pgid <= 0:
            if force:
                process.kill()
            else:
                process.terminate()
            return
        os.killpg(pgid, sig)
    except Exception:
        try:
            if force:
                process.kill()
            else:
                process.terminate()
        except (ProcessLookupError, AttributeError):
            pass


async def wait_or_cancel(process) -> int:
    """Waits for a subprocess, terminating its process tree if the task is cancelled."""
    try:
        return await process.wait()
    except asyncio.CancelledError:
        terminate_process_tree(process)
        try:
            await asyncio.wait_for(process.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            terminate_process_tree(process, force=True)
            try:
                await process.wait()
            except ProcessLookupError:
                pass
        except ProcessLookupError:
            pass
        raise


async def communicate_or_cancel(process) -> tuple[bytes, bytes]:
    """Runs process.communicate(), terminating the process tree on cancellation."""
    communicate_task = asyncio.create_task(process.communicate())
    try:
        return await communicate_task
    except asyncio.CancelledError:
        terminate_process_tree(process)
        try:
            await asyncio.wait_for(process.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            terminate_process_tree(process, force=True)
            try:
                await process.wait()
            except ProcessLookupError:
                pass
        except ProcessLookupError:
            pass
        communicate_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await communicate_task
        raise


async def run_command_and_stream(command: List[str], cwd: str = "/workspace") -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
        # Run the child in its own process group so that on cancellation we can
        # signal the whole tree (agent CLIs frequently spawn their own children).
        start_new_session=True,
    )

    stdout_chunks = []
    stderr_chunks = []

    async def read_stream(stream, chunks, prefix):
        while True:
            line = await stream.readline()
            if not line:
                break
            decoded = line.decode('utf-8', errors='replace')
            chunks.append(decoded)
            print(f"[{prefix}] {decoded.rstrip()}", flush=True)

    try:
        await asyncio.gather(
            read_stream(process.stdout, stdout_chunks, "STDOUT"),
            read_stream(process.stderr, stderr_chunks, "STDERR")
        )
        returncode = await process.wait()
    except asyncio.CancelledError:
        terminate_process_tree(process)
        try:
            await asyncio.wait_for(process.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            terminate_process_tree(process, force=True)
            try:
                await process.wait()
            except ProcessLookupError:
                pass
        except ProcessLookupError:
            pass
        raise

    return returncode, "".join(stdout_chunks), "".join(stderr_chunks)
