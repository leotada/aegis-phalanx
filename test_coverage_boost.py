"""Additional tests to reach >=99% coverage across agents, scripts, and orchestrator."""

import asyncio
import os
import runpy
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.base import AgentCLI
from scripts import render_compose_overlay


def test_agent_cli_cannot_be_instantiated():
    with pytest.raises(TypeError):
        AgentCLI()


def test_render_compose_overlay_main_writes_file(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_TOOL", "agy")
    output = tmp_path / "compose.tool.yml"
    monkeypatch.setattr(render_compose_overlay, "OUTPUT", output)

    render_compose_overlay.main()

    content = output.read_text(encoding="utf-8")
    assert "AGENT_TOOL=agy" in content
    assert "~/.config/aegis-phalanx" in content


def test_normalize_repo_url_shorthand_strips_git_suffix():
    from telegram_listener import normalize_repo_url

    assert normalize_repo_url("owner/repo.git") == "https://github.com/owner/repo.git"


def test_save_session_handles_write_error(monkeypatch, tmp_path):
    from telegram_listener import save_session

    session_file = tmp_path / "bad" / "session.json"
    with patch("builtins.open", side_effect=OSError("disk full")):
        save_session("https://github.com/o/r.git", "d", "step", {}, "feature/x", str(session_file))


def test_load_session_handles_read_error(tmp_path):
    from telegram_listener import load_session

    session_file = tmp_path / "session.json"
    session_file.write_text("{not-json", encoding="utf-8")
    assert load_session(str(session_file)) is None


def test_clear_session_handles_errors(tmp_path):
    from telegram_listener import clear_session, save_session

    session_file = tmp_path / "session.json"
    save_session("https://github.com/o/r.git", "d", "s", {}, "b", str(session_file))

    with patch("builtins.open", side_effect=OSError("fail")):
        clear_session(str(session_file))

    with patch("os.remove", side_effect=OSError("fail")):
        clear_session(str(tmp_path / "missing.json"))


def test_delete_session_handles_error(tmp_path):
    from telegram_listener import delete_session, save_session

    session_file = tmp_path / "session.json"
    save_session("https://github.com/o/r.git", "d", "s", {}, "b", str(session_file))

    with patch("os.remove", side_effect=OSError("fail")):
        delete_session(str(session_file))


@pytest.mark.anyio
async def test_classify_intent_handles_registry_failure():
    from telegram_listener import classify_intent

    with patch("telegram_listener.AgentRegistry.get_agent", side_effect=RuntimeError("boom")):
        assert await classify_intent("please resume") == "RESUME"


class _StreamReader:
    def __init__(self, lines: list[bytes]):
        self._lines = list(lines)

    async def readline(self):
        if self._lines:
            return self._lines.pop(0)
        return b""


@pytest.mark.anyio
async def test_run_command_and_stream_collects_output():
    from telegram_listener import run_command_and_stream

    mock_process = AsyncMock()
    mock_process.stdout = _StreamReader([b"stdout-line\n", b""])
    mock_process.stderr = _StreamReader([b"stderr-line\n", b""])
    mock_process.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        code, out, err = await run_command_and_stream(["echo", "hi"], cwd="/tmp")

    assert code == 0
    assert "stdout-line" in out
    assert "stderr-line" in err


@pytest.mark.anyio
async def test_run_command_and_stream_terminates_on_cancel():
    from telegram_listener import run_command_and_stream

    mock_process = AsyncMock()
    mock_process.pid = 4242
    mock_process.stdout = _StreamReader([])
    mock_process.stderr = _StreamReader([])
    mock_process.terminate = MagicMock()
    mock_process.kill = MagicMock()

    async def slow_wait():
        await asyncio.sleep(0.05)
        return 0

    mock_process.wait = AsyncMock(side_effect=slow_wait)

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        task = asyncio.create_task(run_command_and_stream(["sleep", "10"]))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    mock_process.terminate.assert_called_once()


class _BlockingStreamReader:
    async def readline(self):
        await asyncio.sleep(3600)
        return b""


@pytest.mark.anyio
async def test_run_command_and_stream_process_lookup_error_on_terminate():
    from telegram_listener import run_command_and_stream

    mock_process = MagicMock()
    mock_process.pid = 4242
    mock_process.stdout = _BlockingStreamReader()
    mock_process.stderr = _BlockingStreamReader()
    mock_process.terminate = MagicMock(side_effect=ProcessLookupError)
    mock_process.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        task = asyncio.create_task(run_command_and_stream(["sleep", "10"]))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.anyio
async def test_run_command_and_stream_kill_after_terminate_timeout():
    from telegram_listener import run_command_and_stream

    mock_process = MagicMock()
    mock_process.pid = 4242
    mock_process.stdout = _BlockingStreamReader()
    mock_process.stderr = _BlockingStreamReader()
    mock_process.terminate = MagicMock()
    mock_process.kill = MagicMock()

    waits = 0

    async def wait_side_effect():
        nonlocal waits
        waits += 1
        if waits == 1:
            raise asyncio.TimeoutError
        return 0

    mock_process.wait = AsyncMock(side_effect=wait_side_effect)

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        task = asyncio.create_task(run_command_and_stream(["sleep", "10"]))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    mock_process.kill.assert_called_once()


def test_get_git_changes_formats_status():
    from telegram_listener import get_git_changes

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=" M file1.py\n?? file2.py\n" + "\n".join(f" M f{i}.py" for i in range(6)),
        )
        result = get_git_changes()
    assert "file1.py" in result
    assert "more files" in result


def test_get_git_changes_handles_errors():
    from telegram_listener import get_git_changes

    with patch("subprocess.run", side_effect=OSError("git missing")):
        assert get_git_changes() == ""


def test_get_pytest_summary_patterns():
    from telegram_listener import get_pytest_summary

    assert "2 passed" in get_pytest_summary("===== 2 passed in 1.23s =====")
    assert "1 failed" in get_pytest_summary("1 passed, 1 failed in 0.5s")
    assert get_pytest_summary("no pytest here") == ""


def test_get_pr_url_success_and_failure():
    from telegram_listener import get_pr_url

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="https://github.com/o/r/pull/1\n")
        assert get_pr_url() == "https://github.com/o/r/pull/1"

    with patch("subprocess.run", side_effect=OSError("gh missing")):
        assert get_pr_url() == ""


def test_strip_ansi():
    from telegram_listener import _strip_ansi

    assert _strip_ansi("\x1b[31mred\x1b[0m") == "red"


def test_fetch_agy_quota_output_mocked_pty(monkeypatch, tmp_path):
    from telegram_listener import fetch_agy_quota_output

    monkeypatch.setattr("telegram_listener.AGY_SCRATCH_DIR", str(tmp_path / "scratch"))

    master_fd = 10
    slave_fd = 11
    chunks = [
        b"trust this folder\n",
        b"Antigravity CLI\n>\n",
        b"GEMINI MODELS\nFive Hour Limit\n] 10.00%\n10% remaining\n",
    ]

    class FakeProc:
        def poll(self):
            return None

        def terminate(self):
            return None

        def wait(self, timeout=None):
            return 0

        def kill(self):
            return None

    read_calls = {"n": 0}

    def fake_read(fd, size):
        idx = read_calls["n"]
        read_calls["n"] += 1
        if idx < len(chunks):
            return chunks[idx]
        return b"\n"

    monkeypatch.setattr("pty.openpty", lambda: (master_fd, slave_fd))
    monkeypatch.setattr("fcntl.ioctl", lambda *args, **kwargs: None)
    monkeypatch.setattr("os.close", lambda fd: None)
    monkeypatch.setattr("os.write", lambda fd, data: len(data))
    monkeypatch.setattr("os.read", fake_read)
    monkeypatch.setattr("select.select", lambda r, w, x, t: ([master_fd], [], []))
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: FakeProc())
    monkeypatch.setattr("time.time", lambda: 1)
    monkeypatch.setattr("time.sleep", lambda *args, **kwargs: None)

    output = fetch_agy_quota_output(timeout=5)
    assert "GEMINI MODELS" in output or "Five Hour Limit" in output


def test_fetch_agy_quota_output_exits_when_process_ends(monkeypatch, tmp_path):
    from telegram_listener import fetch_agy_quota_output

    monkeypatch.setattr("telegram_listener.AGY_SCRATCH_DIR", str(tmp_path / "scratch"))

    class ExitedProc:
        def poll(self):
            return 0

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr("pty.openpty", lambda: (10, 11))
    monkeypatch.setattr("fcntl.ioctl", lambda *args, **kwargs: None)
    monkeypatch.setattr("os.close", lambda fd: None)
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: ExitedProc())
    monkeypatch.setattr("select.select", lambda *r: ([], [], []))
    monkeypatch.setattr("time.time", iter([0, 1]).__next__)

    assert fetch_agy_quota_output(timeout=5) == ""


def test_fetch_agy_quota_output_read_oserror(monkeypatch, tmp_path):
    from telegram_listener import fetch_agy_quota_output

    monkeypatch.setattr("telegram_listener.AGY_SCRATCH_DIR", str(tmp_path / "scratch"))

    class FakeProc:
        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr("pty.openpty", lambda: (10, 11))
    monkeypatch.setattr("fcntl.ioctl", lambda *args, **kwargs: None)
    monkeypatch.setattr("os.close", lambda fd: None)
    monkeypatch.setattr("os.read", lambda fd, size: (_ for _ in ()).throw(OSError("read fail")))
    monkeypatch.setattr("select.select", lambda *r: ([10], [], []))
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: FakeProc())
    monkeypatch.setattr("time.time", iter([0, 1]).__next__)

    assert fetch_agy_quota_output(timeout=5) == ""


def test_fetch_agy_quota_output_select_not_ready(monkeypatch, tmp_path):
    from telegram_listener import fetch_agy_quota_output

    monkeypatch.setattr("telegram_listener.AGY_SCRATCH_DIR", str(tmp_path / "scratch"))
    read_calls = [0]

    def fake_read(fd, size):
        read_calls[0] += 1
        return b"line\n"

    select_calls = [0]

    def fake_select(*args):
        select_calls[0] += 1
        if select_calls[0] == 1:
            return ([], [], [])
        return ([10], [], [])

    poll_calls = [0]

    class FakeProc:
        def poll(self):
            poll_calls[0] += 1
            return 0 if poll_calls[0] > 4 else None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr("pty.openpty", lambda: (10, 11))
    monkeypatch.setattr("fcntl.ioctl", lambda *args, **kwargs: None)
    monkeypatch.setattr("os.close", lambda fd: None)
    monkeypatch.setattr("os.read", fake_read)
    monkeypatch.setattr("select.select", fake_select)
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: FakeProc())
    monkeypatch.setattr("time.time", lambda: 1)

    output = fetch_agy_quota_output(timeout=5)
    assert "line" in output


def test_fetch_agy_quota_output_empty_chunk_breaks(monkeypatch, tmp_path):
    from telegram_listener import fetch_agy_quota_output

    monkeypatch.setattr("telegram_listener.AGY_SCRATCH_DIR", str(tmp_path / "scratch"))
    read_calls = [0]

    def fake_read(fd, size):
        read_calls[0] += 1
        if read_calls[0] == 1:
            return b""
        return b"after\n"

    class FakeProc:
        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr("pty.openpty", lambda: (10, 11))
    monkeypatch.setattr("fcntl.ioctl", lambda *args, **kwargs: None)
    monkeypatch.setattr("os.close", lambda fd: None)
    monkeypatch.setattr("os.read", fake_read)
    monkeypatch.setattr("select.select", lambda *args: ([10], [], []))
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: FakeProc())
    monkeypatch.setattr("time.time", lambda: 1)

    output = fetch_agy_quota_output(timeout=5)
    assert output == ""


def test_fetch_agy_quota_output_gemini_break(monkeypatch, tmp_path):
    from telegram_listener import fetch_agy_quota_output

    monkeypatch.setattr("telegram_listener.AGY_SCRATCH_DIR", str(tmp_path / "scratch"))
    chunk = (
        b"Antigravity CLI\n>\n"
        b"GEMINI MODELS\n"
        b"Five Hour Limit: 100%\n"
    )

    class FakeProc:
        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr("pty.openpty", lambda: (10, 11))
    monkeypatch.setattr("fcntl.ioctl", lambda *args, **kwargs: None)
    monkeypatch.setattr("os.close", lambda fd: None)
    monkeypatch.setattr("os.read", lambda fd, size: chunk)
    monkeypatch.setattr("select.select", lambda *args: ([10], [], []))
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: FakeProc())
    monkeypatch.setattr("time.time", lambda: 1)
    monkeypatch.setattr("time.sleep", lambda *args, **kwargs: None)
    monkeypatch.setattr("os.write", lambda fd, data: len(data))

    output = fetch_agy_quota_output(timeout=5)
    assert "GEMINI MODELS" in output
    assert "Five Hour Limit" in output


def test_fetch_agy_quota_output_usage_timeout(monkeypatch, tmp_path):
    from telegram_listener import fetch_agy_quota_output

    monkeypatch.setattr("telegram_listener.AGY_SCRATCH_DIR", str(tmp_path / "scratch"))
    clock = iter([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 60])

    chunks = [
        b"trust this folder\n",
        b"Antigravity CLI\n>\n",
        b"partial output without quota table\n",
    ]
    idx = {"n": 0}

    def fake_read(fd, size):
        if idx["n"] < len(chunks):
            data = chunks[idx["n"]]
            idx["n"] += 1
            return data
        return b"more\n"

    class FakeProc:
        def poll(self):
            return None

        def terminate(self):
            pass

        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    monkeypatch.setattr("pty.openpty", lambda: (10, 11))
    monkeypatch.setattr("fcntl.ioctl", lambda *args, **kwargs: None)
    monkeypatch.setattr("os.close", lambda fd: None)
    monkeypatch.setattr("os.write", lambda fd, data: len(data))
    monkeypatch.setattr("os.read", fake_read)
    monkeypatch.setattr("select.select", lambda *r: ([10], [], []))
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: FakeProc())
    monkeypatch.setattr("time.time", lambda: next(clock))
    monkeypatch.setattr("time.sleep", lambda *args, **kwargs: None)

    output = fetch_agy_quota_output(timeout=60)
    assert isinstance(output, str)


def test_format_model_quota_section_empty():
    from telegram_listener import format_model_quota_section

    assert format_model_quota_section({}) == ""


def test_get_model_quota_summary_success_and_error():
    import telegram_listener

    with patch("telegram_listener.DEFAULT_AGENT_TOOL", "agy"), \
         patch("telegram_listener.fetch_agy_quota_output", return_value="GEMINI MODELS\nFive Hour Limit\n] 50.00%\n50% remaining\n"), \
         patch("telegram_listener.parse_model_quota", return_value={"GEMINI MODELS": {"five_hour": {"usage": 50.0, "remaining": 50.0}}}):
        assert "Model Quota Usage" in telegram_listener.get_model_quota_summary()

    with patch("telegram_listener.DEFAULT_AGENT_TOOL", "agy"), \
         patch("telegram_listener.fetch_agy_quota_output", side_effect=RuntimeError("pty fail")):
        assert telegram_listener.get_model_quota_summary() == ""


def test_parse_model_quota_refresh_only_line():
    from telegram_listener import parse_model_quota

    text = """
GEMINI MODELS
Five Hour Limit
] 25.00%
25% remaining · Refreshes in 2h
Refreshes in 2h
"""
    quota = parse_model_quota(text)
    assert quota["GEMINI MODELS"]["five_hour"]["refresh"] == "2h"


def _mock_update():
    mock_update = AsyncMock()
    mock_update.effective_chat.id = 12345
    mock_update.message = AsyncMock()
    mock_update.message.reply_text = AsyncMock()
    return mock_update


@pytest.mark.anyio
async def test_run_pipeline_resume_without_session():
    import telegram_listener

    mock_update = _mock_update()
    with patch("telegram_listener.load_session", return_value=None):
        await telegram_listener.run_pipeline(mock_update, MagicMock(), "u", "d", is_resume=True)
    assert "No previous session" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.anyio
async def test_run_pipeline_resume_all_steps_complete():
    import telegram_listener

    mock_update = _mock_update()
    session = {
        "repo_url": "git@github.com:o/r.git",
        "demand": "d",
        "git_branch": "feature/d",
        "steps_status": {step["step_name"]: "success" for step in telegram_listener.resolve_pipeline_config()},
    }
    with patch("telegram_listener.load_session", return_value=session):
        await telegram_listener.run_pipeline(mock_update, MagicMock(), "u", "d", is_resume=True)
    assert "already completed successfully" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.anyio
async def test_run_pipeline_missing_github_token_for_https(monkeypatch):
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    mock_update = _mock_update()
    with patch("telegram_listener.resolve_clone_url", return_value=(None, None, "Neither GITHUB_TOKEN nor valid SSH keys were found.")):
        await telegram_listener.run_pipeline(
            mock_update, MagicMock(), "https://github.com/o/r.git", "demand", is_resume=False
        )
    assert "GITHUB_TOKEN" in mock_update.message.reply_text.call_args_list[-1][0][0]


@pytest.mark.anyio
async def test_run_pipeline_clone_failure(monkeypatch):
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    mock_update = _mock_update()
    mock_process = AsyncMock()
    mock_process.returncode = 1
    mock_process.communicate.return_value = (b"", b"clone failed")

    with patch("asyncio.create_subprocess_exec", return_value=mock_process), \
         patch("os.path.exists", return_value=False):
        await telegram_listener.run_pipeline(
            mock_update, MagicMock(), "git@github.com:o/r.git", "demand", is_resume=False
        )
    assert "Failed to clone" in mock_update.message.reply_text.call_args_list[-1][0][0]


@pytest.mark.anyio
async def test_run_pipeline_removes_existing_project_dir(monkeypatch):
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    mock_update = _mock_update()

    async def subprocess_side_effect(*args, **kwargs):
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.wait = AsyncMock(return_value=0)
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=subprocess_side_effect) as mock_exec, \
         patch("os.path.exists", return_value=True), \
         patch.object(telegram_listener, "run_command_and_stream", return_value=(0, "", "")), \
         patch.object(telegram_listener, "get_pr_url", return_value="https://github.com/o/r/pull/1"):
        await telegram_listener.run_pipeline(
            mock_update, MagicMock(), "git@github.com:o/r.git", "demand", is_resume=False
        )

    assert any(call.args[0] == "rm" for call in mock_exec.call_args_list)


@pytest.mark.anyio
async def test_run_pipeline_resume_branch_from_origin(monkeypatch):
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    mock_update = _mock_update()
    session = {
        "repo_url": "git@github.com:o/r.git",
        "demand": "d",
        "git_branch": "feature/d",
        "steps_status": {"Architect (Planning - PLAN)": "success"},
    }

    async def subprocess_side_effect(*args, **kwargs):
        proc = AsyncMock()
        if args[:3] == ("git", "show-ref", "--verify"):
            proc.returncode = 1
        elif args[:4] == ("git", "checkout", "-b", "feature/d") and len(args) > 4 and args[4].startswith("origin/"):
            proc.returncode = 1
        else:
            proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.wait = AsyncMock(return_value=proc.returncode)
        return proc

    with patch("telegram_listener.load_session", return_value=session), \
         patch("asyncio.create_subprocess_exec", side_effect=subprocess_side_effect), \
         patch("os.path.exists", return_value=True), \
         patch.object(telegram_listener, "run_command_and_stream", return_value=(0, "===== 1 passed =====", "")), \
         patch.object(telegram_listener, "get_git_changes", return_value="• `a.py` (M)"), \
         patch.object(telegram_listener, "get_pytest_summary", return_value="1 passed"), \
         patch.object(telegram_listener, "get_pr_url", return_value="https://github.com/o/r/pull/9"):
        await telegram_listener.run_pipeline(mock_update, MagicMock(), "u", "d", is_resume=True)

    replies = [call.args[0] for call in mock_update.message.reply_text.call_args_list]
    assert any("lost because the container was rebuilt" in msg for msg in replies)


@pytest.mark.anyio
async def test_run_pipeline_initialization_error(monkeypatch):
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    mock_update = _mock_update()

    with patch("asyncio.create_subprocess_exec", side_effect=RuntimeError("spawn failed")), \
         patch("os.path.exists", return_value=False):
        await telegram_listener.run_pipeline(
            mock_update, MagicMock(), "git@github.com:o/r.git", "demand", is_resume=False
        )
    assert "Initialization error" in mock_update.message.reply_text.call_args_list[-1][0][0]


@pytest.mark.anyio
async def test_run_pipeline_step_failure_reports_stderr_stdout(monkeypatch):
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    mock_update = _mock_update()
    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate = AsyncMock(return_value=(b"", b""))
    mock_process.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_process), \
         patch("os.path.exists", return_value=False), \
         patch.object(telegram_listener, "run_command_and_stream", return_value=(1, "out", "err")):
        await telegram_listener.run_pipeline(
            mock_update, MagicMock(), "git@github.com:o/r.git", "demand", is_resume=False
        )

    final = mock_update.message.reply_text.call_args_list[-1][0][0]
    assert "Failure in step" in final
    assert "Stderr" in final
    assert "Stdout" in final


@pytest.mark.anyio
async def test_run_pipeline_step_exception(monkeypatch):
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    mock_update = _mock_update()
    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate = AsyncMock(return_value=(b"", b""))
    mock_process.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_process), \
         patch("os.path.exists", return_value=False), \
         patch("telegram_listener.AgentRegistry.get_agent", side_effect=RuntimeError("adapter fail")):
        await telegram_listener.run_pipeline(
            mock_update, MagicMock(), "git@github.com:o/r.git", "demand", is_resume=False
        )
    assert "System error" in mock_update.message.reply_text.call_args_list[-1][0][0]


@pytest.mark.anyio
async def test_run_pipeline_pr_create_failure(monkeypatch):
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    mock_update = _mock_update()

    async def subprocess_side_effect(*args, **kwargs):
        proc = AsyncMock()
        if args[:3] == ("gh", "pr", "create"):
            proc.returncode = 1
            proc.communicate = AsyncMock(return_value=(b"", b"pr create failed"))
        else:
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.wait = AsyncMock(return_value=proc.returncode)
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=subprocess_side_effect), \
         patch("os.path.exists", return_value=False), \
         patch.object(telegram_listener, "run_command_and_stream", return_value=(0, "", "")), \
         patch.object(telegram_listener, "get_pr_url", return_value=""):
        await telegram_listener.run_pipeline(
            mock_update, MagicMock(), "git@github.com:o/r.git", "demand", is_resume=False
        )

    replies = [call.args[0] for call in mock_update.message.reply_text.call_args_list]
    assert any("Failed to create PR" in msg for msg in replies)


@pytest.mark.anyio
async def test_run_pipeline_cancel_during_init():
    import telegram_listener

    mock_update = _mock_update()

    with patch("telegram_listener.clear_session", side_effect=asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await telegram_listener.run_pipeline(
                mock_update, MagicMock(), "git@github.com:o/r.git", "demand", is_resume=False
            )
    assert "stopped during initialization" in mock_update.message.reply_text.call_args[0][0]


@pytest.mark.anyio
async def test_run_pipeline_success_summary_with_pr_in_step(monkeypatch):
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    mock_update = _mock_update()
    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate = AsyncMock(return_value=(b"", b""))
    mock_process.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_process), \
         patch("os.path.exists", return_value=False), \
         patch.object(telegram_listener, "run_command_and_stream", return_value=(0, "plain output", "")), \
         patch.object(telegram_listener, "get_git_changes", return_value=""), \
         patch.object(telegram_listener, "get_pytest_summary", return_value=""), \
         patch.object(telegram_listener, "get_pr_url", return_value="https://github.com/o/r/pull/2"):
        await telegram_listener.run_pipeline(
            mock_update, MagicMock(), "git@github.com:o/r.git", "demand", is_resume=False
        )

    replies = [call.args[0] for call in mock_update.message.reply_text.call_args_list]
    assert any("PR Created" in msg for msg in replies)
    assert any("Pipeline completed successfully" in msg for msg in replies)


@pytest.mark.anyio
async def test_handlers_ignore_unauthorized_chat():
    import telegram_listener

    mock_update = _mock_update()
    mock_update.effective_chat.id = 99999
    mock_context = MagicMock()

    with patch("telegram_listener.ALLOWED_CHAT_ID", "12345"):
        await telegram_listener.handle_continue(mock_update, mock_context)
        await telegram_listener.handle_status(mock_update, mock_context)
        await telegram_listener.handle_stop(mock_update, mock_context)
        await telegram_listener.handle_clear(mock_update, mock_context)
        await telegram_listener.handle_demand(mock_update, mock_context)

    mock_update.message.reply_text.assert_not_called()


@pytest.mark.anyio
async def test_handle_demand_resume_and_status_and_new():
    import telegram_listener

    mock_update = _mock_update()
    mock_context = MagicMock()

    with patch("telegram_listener.ALLOWED_CHAT_ID", "12345"), \
         patch("telegram_listener.classify_intent", return_value="RESUME"), \
         patch("telegram_listener.run_pipeline", new_callable=AsyncMock) as mock_run:
        await telegram_listener.handle_demand(mock_update, mock_context)
        mock_run.assert_awaited_once()
        assert mock_run.call_args.kwargs["is_resume"] is True

    with patch("telegram_listener.ALLOWED_CHAT_ID", "12345"), \
         patch("telegram_listener.classify_intent", return_value="QUERY_STATUS"), \
         patch("telegram_listener.send_status", new_callable=AsyncMock) as mock_status:
        await telegram_listener.handle_demand(mock_update, mock_context)
        mock_status.assert_awaited_once()

    with patch("telegram_listener.ALLOWED_CHAT_ID", "12345"), \
         patch("telegram_listener.classify_intent", return_value="NEW_DEMAND"), \
         patch("telegram_listener.parse_demand", return_value=(None, "demand")), \
         patch("telegram_listener.run_pipeline", new_callable=AsyncMock):
        await telegram_listener.handle_demand(mock_update, mock_context)
        assert "No repository specified" in mock_update.message.reply_text.call_args[0][0]

    with patch("telegram_listener.ALLOWED_CHAT_ID", "12345"), \
         patch("telegram_listener.classify_intent", return_value="NEW_DEMAND"), \
         patch("telegram_listener.parse_demand", return_value=("git@github.com:o/r.git", "demand")), \
         patch("telegram_listener.run_pipeline", new_callable=AsyncMock) as mock_run:
        await telegram_listener.handle_demand(mock_update, mock_context)
        mock_run.assert_awaited()


@pytest.mark.anyio
async def test_handle_clear_deletes_session():
    import telegram_listener

    mock_update = _mock_update()
    with patch("telegram_listener.ALLOWED_CHAT_ID", "12345"), \
         patch("telegram_listener.delete_session") as mock_delete:
        await telegram_listener.handle_clear(mock_update, MagicMock())
    mock_delete.assert_called_once()


@pytest.mark.anyio
async def test_send_status_quota_only_paths():
    import telegram_listener

    mock_update = _mock_update()

    with patch("telegram_listener.load_session", return_value={"repo_url": "https://github.com/o/r.git"}), \
         patch("telegram_listener.get_model_quota_summary", return_value="📉 quota"):
        await telegram_listener.send_status(mock_update)

    with patch("telegram_listener.load_session", return_value={"steps_status": {}}), \
         patch("telegram_listener.get_model_quota_summary", return_value="📉 quota"):
        await telegram_listener.send_status(mock_update)

    with patch("telegram_listener.load_session", return_value={"steps_status": {}}), \
         patch("telegram_listener.get_model_quota_summary", return_value=""):
        await telegram_listener.send_status(mock_update)

    assert mock_update.message.reply_text.await_count == 3


@pytest.mark.anyio
async def test_start_ignores_unauthorized_chat():
    import telegram_listener

    mock_update = _mock_update()
    mock_update.effective_chat.id = 99999
    with patch("telegram_listener.ALLOWED_CHAT_ID", "12345"):
        await telegram_listener.start(mock_update, MagicMock())
    mock_update.message.reply_text.assert_not_called()


@pytest.mark.anyio
async def test_start_authorized_chat():
    import telegram_listener

    mock_update = _mock_update()
    with patch("telegram_listener.ALLOWED_CHAT_ID", "12345"):
        await telegram_listener.start(mock_update, MagicMock())
    mock_update.message.reply_text.assert_called_once()


def test_build_application_missing_token():
    from telegram_listener import build_application

    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
            build_application()


def test_get_model_quota_summary_empty_parse_result():
    import telegram_listener

    with patch("telegram_listener.DEFAULT_AGENT_TOOL", "agy"), \
         patch("telegram_listener.fetch_agy_quota_output", return_value="no quota"), \
         patch("telegram_listener.parse_model_quota", return_value={}):
        assert telegram_listener.get_model_quota_summary() == ""


def test_render_compose_overlay_main_block(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_TOOL", "cursor")
    output = tmp_path / "compose.tool.yml"
    script_path = Path(render_compose_overlay.__file__)
    source = script_path.read_text(encoding="utf-8").replace(
        "OUTPUT = ROOT / \"compose.tool.yml\"",
        f'OUTPUT = Path(r"{output}")',
    )
    namespace = {
        "__name__": "__main__",
        "__file__": str(script_path),
        "os": os,
        "sys": sys,
        "Path": Path,
    }
    exec(compile(source, str(script_path), "exec"), namespace)
    assert output.exists()


@pytest.mark.anyio
async def test_run_pipeline_pr_create_exception(monkeypatch):
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    mock_update = _mock_update()

    async def subprocess_side_effect(*args, **kwargs):
        if args[:3] == ("gh", "pr", "create"):
            raise RuntimeError("gh unavailable")
        proc = AsyncMock()
        proc.returncode = 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.wait = AsyncMock(return_value=0)
        return proc

    with patch("asyncio.create_subprocess_exec", side_effect=subprocess_side_effect), \
         patch("os.path.exists", return_value=False), \
         patch.object(telegram_listener, "run_command_and_stream", return_value=(0, "", "")), \
         patch.object(telegram_listener, "get_pr_url", return_value=""):
        await telegram_listener.run_pipeline(
            mock_update, MagicMock(), "git@github.com:o/r.git", "demand", is_resume=False
        )

    replies = [call.args[0] for call in mock_update.message.reply_text.call_args_list]
    assert any("Error creating PR" in msg for msg in replies)


@pytest.mark.anyio
async def test_run_pipeline_resume_local_branch_checkout(monkeypatch):
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    mock_update = _mock_update()
    session = {
        "repo_url": "git@github.com:o/r.git",
        "demand": "d",
        "git_branch": "feature/d",
        "steps_status": {"Architect (Planning - PLAN)": "success"},
    }
    calls = []

    async def subprocess_side_effect(*args, **kwargs):
        calls.append(args)
        proc = AsyncMock()
        proc.returncode = 0 if args[:3] == ("git", "show-ref", "--verify") else 0
        proc.communicate = AsyncMock(return_value=(b"", b""))
        proc.wait = AsyncMock(return_value=0)
        return proc

    with patch("telegram_listener.load_session", return_value=session), \
         patch("asyncio.create_subprocess_exec", side_effect=subprocess_side_effect), \
         patch("os.path.exists", return_value=True), \
         patch.object(telegram_listener, "run_command_and_stream", return_value=(0, "", "")), \
         patch.object(telegram_listener, "get_pr_url", return_value="https://github.com/o/r/pull/1"):
        await telegram_listener.run_pipeline(mock_update, MagicMock(), "u", "d", is_resume=True)

    assert ("git", "checkout", "feature/d") in calls


@pytest.mark.anyio
async def test_run_pipeline_output_tail_fallback(monkeypatch):
    import telegram_listener

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    mock_update = _mock_update()
    mock_process = AsyncMock()
    mock_process.returncode = 0
    mock_process.communicate = AsyncMock(return_value=(b"", b""))
    mock_process.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_process), \
         patch("os.path.exists", return_value=False), \
         patch.object(telegram_listener, "run_command_and_stream", return_value=(0, "line1\n**bold**\n", "")), \
         patch.object(telegram_listener, "get_git_changes", return_value=""), \
         patch.object(telegram_listener, "get_pytest_summary", return_value=""), \
         patch.object(telegram_listener, "get_pr_url", return_value=""):
        await telegram_listener.run_pipeline(
            mock_update, MagicMock(), "git@github.com:o/r.git", "demand", is_resume=False
        )

    replies = [call.args[0] for call in mock_update.message.reply_text.call_args_list]
    assert any("Output Tail" in msg for msg in replies)


@pytest.mark.anyio
async def test_handle_continue_and_status_authorized():
    import telegram_listener

    mock_update = _mock_update()
    with patch("telegram_listener.ALLOWED_CHAT_ID", "12345"), \
         patch("telegram_listener.run_pipeline", new_callable=AsyncMock) as mock_run, \
         patch("telegram_listener.send_status", new_callable=AsyncMock) as mock_status:
        await telegram_listener.handle_continue(mock_update, MagicMock())
        await telegram_listener.handle_status(mock_update, MagicMock())
    mock_run.assert_awaited_once()
    mock_status.assert_awaited_once()


@pytest.mark.anyio
async def test_send_status_incomplete_session_without_repo_url():
    import telegram_listener

    mock_update = _mock_update()
    with patch("telegram_listener.load_session", return_value={"steps_status": {}}), \
         patch("telegram_listener.get_model_quota_summary", return_value=""):
        await telegram_listener.send_status(mock_update)
    assert "No active session" in mock_update.message.reply_text.call_args[0][0]


def test_fetch_agy_quota_output_handles_proc_errors(monkeypatch, tmp_path):
    from telegram_listener import fetch_agy_quota_output

    monkeypatch.setattr("telegram_listener.AGY_SCRATCH_DIR", str(tmp_path / "scratch"))

    class BrokenProc:
        def poll(self):
            return None

        def terminate(self):
            raise RuntimeError("terminate failed")

        def wait(self, timeout=None):
            raise RuntimeError("wait failed")

        def kill(self):
            raise RuntimeError("kill failed")

    monkeypatch.setattr("pty.openpty", lambda: (10, 11))
    monkeypatch.setattr("fcntl.ioctl", lambda *args, **kwargs: None)
    monkeypatch.setattr("os.close", lambda fd: None)
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: BrokenProc())
    monkeypatch.setattr("select.select", lambda *r: ([], [], []))
    monkeypatch.setattr("time.time", iter([0, 100]).__next__)

    assert fetch_agy_quota_output(timeout=1) == ""


def test_main_entrypoint_exits_without_tokens(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(
            str(Path(__file__).resolve().parent / "telegram_listener.py"),
            run_name="__main__",
        )
    assert exc.value.code == 1


def test_render_compose_overlay_load_env_nonexistent(tmp_path):
    from scripts import render_compose_overlay
    render_compose_overlay.load_env_file(tmp_path / "nonexistent.env")


@pytest.mark.anyio
async def test_gh_auth_token_coverage(monkeypatch):
    from telegram_listener import _gh_auth_token
    import shutil

    # Case 1: gh not in path
    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    assert await _gh_auth_token() is None

    # Case 2: gh in path, subprocess raises
    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/gh")
    with patch("asyncio.create_subprocess_exec", side_effect=Exception("boom")):
        assert await _gh_auth_token() is None

    # Case 3: gh returns non-zero code
    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        assert await _gh_auth_token() is None

    # Case 4: gh returns token
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"gho_test123\n", b""))
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        assert await _gh_auth_token() == "gho_test123"


@pytest.mark.anyio
async def test_ssh_github_available_coverage(monkeypatch):
    from telegram_listener import _ssh_github_available
    import shutil

    # Case 1: ssh not in path
    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    assert await _ssh_github_available() is False

    # Case 2: ssh in path, subprocess raises
    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/ssh")
    with patch("asyncio.create_subprocess_exec", side_effect=Exception("boom")):
        assert await _ssh_github_available() is False

    # Case 3: ssh unauthenticated
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b"Permission denied (publickey)."))
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        assert await _ssh_github_available() is False

    # Case 4: ssh authenticated
    mock_proc.communicate = AsyncMock(return_value=(b"Hi user! You've successfully authenticated.", b""))
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        assert await _ssh_github_available() is True


@pytest.mark.anyio
async def test_resolve_clone_url_edge_cases():
    from telegram_listener import resolve_clone_url

    # Empty repo_url
    url, method, err = await resolve_clone_url("", None)
    assert url == ""
    assert method == "as-is"

    # Non-GitHub HTTPS
    url, method, err = await resolve_clone_url("https://gitlab.com/owner/repo.git", None)
    assert url == "https://gitlab.com/owner/repo.git"
    assert method == "as-is"


def test_terminate_process_tree_force_pgid_equal_pgrp(monkeypatch):
    from telegram_listener import _terminate_process_tree

    mock_proc = MagicMock()
    mock_proc.pid = 9999
    mock_proc.kill = MagicMock()
    mock_proc.terminate = MagicMock()

    monkeypatch.setattr(os, "getpgid", lambda pid: os.getpgrp())
    _terminate_process_tree(mock_proc, force=True)
    mock_proc.kill.assert_called_once()

    _terminate_process_tree(mock_proc, force=False)
    mock_proc.terminate.assert_called_once()


@pytest.mark.anyio
async def test_wait_or_cancel_process_lookup_error_on_second_wait():
    from telegram_listener import _wait_or_cancel

    mock_proc = MagicMock()
    mock_proc.pid = 8888
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()

    waits = 0
    async def wait_side_effect():
        nonlocal waits
        waits += 1
        if waits == 1:
            raise asyncio.CancelledError
        elif waits == 2:
            raise asyncio.TimeoutError
        raise ProcessLookupError

    mock_proc.wait = AsyncMock(side_effect=wait_side_effect)

    with pytest.raises(asyncio.CancelledError):
        await _wait_or_cancel(mock_proc)


@pytest.mark.anyio
async def test_communicate_or_cancel_error_branches():
    from telegram_listener import _communicate_or_cancel

    mock_proc = MagicMock()
    mock_proc.pid = 8888
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()

    waits = 0
    async def wait_side_effect():
        nonlocal waits
        waits += 1
        if waits == 1:
            raise asyncio.TimeoutError
        raise ProcessLookupError

    mock_proc.wait = AsyncMock(side_effect=wait_side_effect)

    async def communicate_cancelled():
        raise asyncio.CancelledError

    mock_proc.communicate = AsyncMock(side_effect=communicate_cancelled)

    with pytest.raises(asyncio.CancelledError):
        await _communicate_or_cancel(mock_proc)


def test_get_git_changes_more_than_five_files():
    from telegram_listener import get_git_changes
    import subprocess

    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "M file1.py\nM file2.py\nM file3.py\nM file4.py\nM file5.py\nM file6.py\nM file7.py\n"

    with patch("subprocess.run", return_value=mock_res):
        changes = get_git_changes()
        assert "and 2 more files" in changes


@pytest.mark.anyio
async def test_fetch_pr_context_nonzero_exits():
    from telegram_listener import fetch_pr_context

    proc_view = AsyncMock()
    proc_view.returncode = 1
    proc_view.communicate = AsyncMock(return_value=(b"", b"Could not resolve PR"))

    proc_diff = AsyncMock()
    proc_diff.returncode = 1
    proc_diff.communicate = AsyncMock(return_value=(b"", b"Diff failed"))

    def subprocess_side_effect(*args, **kwargs):
        if "view" in args:
            return proc_view
        return proc_diff

    with patch("asyncio.create_subprocess_exec", side_effect=subprocess_side_effect):
        ctx = await fetch_pr_context("o/r", 123, "/tmp")
        assert "Could not fetch PR metadata" in ctx
        assert "Could not fetch PR diff" in ctx


def test_render_markdown_messages_large_splitting():
    from telegram_listener import render_markdown_messages

    # Large code block splitting
    huge_code = "```python\n" + ("x = 1\n" * 1000) + "```"
    chunks = render_markdown_messages(huge_code, max_len=500)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 500

    # Large text block splitting
    huge_text = ("This is a very long line of explanatory text without breaks.\n" * 100)
    text_chunks = render_markdown_messages(huge_text, max_len=500)
    assert len(text_chunks) > 1
    for chunk in text_chunks:
        assert len(chunk) <= 500


@pytest.mark.anyio
async def test_handle_demand_active_pipeline_rejections():
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener

    mock_update = AsyncMock()
    mock_update.effective_chat.id = 12345
    mock_update.message = AsyncMock()
    mock_update.message.text = "continue"
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    mock_task = MagicMock()
    mock_task.done.return_value = False
    telegram_listener.ACTIVE_TASKS["12345"] = mock_task

    # Resume intent with active pipeline
    with patch("telegram_listener.ALLOWED_CHAT_ID", "12345"), \
         patch("telegram_listener.classify_intent", new_callable=AsyncMock, return_value="RESUME"):
        await telegram_listener.handle_demand(mock_update, mock_context)
        assert "/stop" in mock_update.message.reply_text.call_args[0][0]

    telegram_listener.ACTIVE_TASKS.clear()


@pytest.mark.anyio
async def test_handle_review_unauthorized():
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener

    mock_update = AsyncMock()
    mock_update.effective_chat.id = 99999
    mock_update.message = AsyncMock()
    mock_update.message.text = "/review owner/repo#123"

    with patch("telegram_listener.ALLOWED_CHAT_ID", "12345"), \
         patch("telegram_listener.run_pr_review", new_callable=AsyncMock) as mock_run:
        await telegram_listener.handle_review(mock_update, MagicMock())
        mock_run.assert_not_called()


def test_clear_session_write_error_with_repo(tmp_path):
    from telegram_listener import clear_session
    session_file = tmp_path / "session.json"
    with patch("telegram_listener.load_session", return_value={"repo_url": "https://github.com/o/r.git"}), \
         patch("builtins.open", side_effect=OSError("write error")):
        clear_session(str(session_file))


@pytest.mark.anyio
async def test_communicate_or_cancel_process_lookup_error_on_second_wait():
    from telegram_listener import _communicate_or_cancel
    mock_proc = MagicMock()
    mock_proc.pid = 7777
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()
    waits = 0
    async def wait_side_effect():
        nonlocal waits
        waits += 1
        if waits == 1:
            raise asyncio.TimeoutError
        raise ProcessLookupError
    mock_proc.wait = AsyncMock(side_effect=wait_side_effect)
    mock_proc.communicate = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await _communicate_or_cancel(mock_proc)


@pytest.mark.anyio
async def test_communicate_or_cancel_process_lookup_error_on_first_wait():
    from telegram_listener import _communicate_or_cancel
    mock_proc = MagicMock()
    mock_proc.pid = 7777
    mock_proc.terminate = MagicMock()
    mock_proc.wait = AsyncMock(side_effect=ProcessLookupError)
    mock_proc.communicate = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        await _communicate_or_cancel(mock_proc)


@pytest.mark.anyio
async def test_run_command_and_stream_process_lookup_error_on_second_wait():
    from telegram_listener import run_command_and_stream
    mock_proc = MagicMock()
    mock_proc.pid = 6666
    mock_proc.stdout = _BlockingStreamReader()
    mock_proc.stderr = _BlockingStreamReader()
    mock_proc.terminate = MagicMock()
    mock_proc.kill = MagicMock()
    waits = 0
    async def wait_side_effect():
        nonlocal waits
        waits += 1
        if waits == 1:
            raise asyncio.TimeoutError
        raise ProcessLookupError
    mock_proc.wait = AsyncMock(side_effect=wait_side_effect)
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        task = asyncio.create_task(run_command_and_stream(["sleep", "10"]))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.anyio
async def test_run_command_and_stream_process_lookup_error_on_first_wait():
    from telegram_listener import run_command_and_stream
    mock_proc = MagicMock()
    mock_proc.pid = 6666
    mock_proc.stdout = _BlockingStreamReader()
    mock_proc.stderr = _BlockingStreamReader()
    mock_proc.terminate = MagicMock()
    mock_proc.wait = AsyncMock(side_effect=ProcessLookupError)
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        task = asyncio.create_task(run_command_and_stream(["sleep", "10"]))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


def test_get_git_changes_exception():
    from telegram_listener import get_git_changes
    with patch("subprocess.run", side_effect=Exception("git error")):
        assert get_git_changes() == ""


@pytest.mark.anyio
async def test_run_pipeline_summary_with_changes_and_pytest(monkeypatch):
    import telegram_listener
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    mock_update = _mock_update()
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    mock_proc.wait = AsyncMock(return_value=0)

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
         patch("os.path.exists", return_value=False), \
         patch.object(telegram_listener, "run_command_and_stream", return_value=(0, "tests passed", "")), \
         patch.object(telegram_listener, "get_git_changes", return_value="• `main.py` (M)"), \
         patch.object(telegram_listener, "get_pytest_summary", return_value="5 passed"), \
         patch.object(telegram_listener, "get_pr_url", return_value="https://github.com/o/r/pull/10"):
        await telegram_listener.run_pipeline(mock_update, MagicMock(), "git@github.com:o/r.git", "demand", is_resume=False)

    replies = [call.args[0] for call in mock_update.message.reply_text.call_args_list]
    assert any("Files changed:" in msg for msg in replies)
    assert any("Tests status:" in msg for msg in replies)


def test_render_markdown_messages_line_budget_branches():
    from telegram_listener import render_markdown_messages
    long_code = "```\n" + ("A" * 60) + "\n" + ("B" * 60) + "\n```"
    chunks = render_markdown_messages(long_code, max_len=40)
    assert len(chunks) >= 2

    # Short preceding line followed by very long line
    long_text = "Short line 1\n" + ("X" * 100) + "\n" + ("Y" * 100)
    chunks_text = render_markdown_messages(long_text, max_len=40)
    assert len(chunks_text) >= 2

    # Multiple paragraphs forcing buffer flush in push
    res = render_markdown_messages("Para 1\n\nPara 2\n\nPara 3\n\nPara 4", max_len=18)
    assert len(res) >= 2


@pytest.mark.anyio
async def test_handle_demand_active_pipeline_rejection_new_demand():
    from unittest.mock import AsyncMock, MagicMock, patch
    import telegram_listener

    mock_update = AsyncMock()
    mock_update.effective_chat.id = 12345
    mock_update.message = AsyncMock()
    mock_update.message.text = "owner/repo: new demand"
    mock_update.message.reply_text = AsyncMock()
    mock_context = MagicMock()

    mock_task = MagicMock()
    mock_task.done.return_value = False
    telegram_listener.ACTIVE_TASKS["12345"] = mock_task

    with patch("telegram_listener.ALLOWED_CHAT_ID", "12345"), \
         patch("telegram_listener.classify_intent", new_callable=AsyncMock, return_value="NEW_DEMAND"):
        await telegram_listener.handle_demand(mock_update, mock_context)
        assert "/stop" in mock_update.message.reply_text.call_args[0][0]

    telegram_listener.ACTIVE_TASKS.clear()


