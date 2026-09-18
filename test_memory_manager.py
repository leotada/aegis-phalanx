import json
import os
import tarfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agents.memory_manager as mm
from agents.config import env_flag
from agents.memory_manager import (
    AIMemoryManager,
    DisabledMemoryManager,
    MEMORY_PREAMBLE,
    PROGRESS_PAGE_PATH,
    clip_text,
    env_float,
    env_int,
    format_search_hits,
    get_memory_manager,
    is_ai_memory_available,
    is_ai_memory_enabled,
    is_ai_memory_requested,
    memory_status_label,
    project_slug,
    reset_memory_manager_cache,
)


@pytest.fixture(autouse=True)
def _reset_memory_globals():
    reset_memory_manager_cache()
    mm._MISSING_BINARY_WARNED = False
    yield
    reset_memory_manager_cache()
    mm._MISSING_BINARY_WARNED = False


def test_env_flag_and_numeric_helpers(monkeypatch):
    monkeypatch.delenv("TEST_FLAG", raising=False)
    assert env_flag("TEST_FLAG") is False
    assert env_flag("TEST_FLAG", default=True) is True

    monkeypatch.setenv("TEST_FLAG", "YES")
    assert env_flag("TEST_FLAG") is True
    monkeypatch.setenv("TEST_FLAG", "off")
    assert env_flag("TEST_FLAG") is False

    monkeypatch.delenv("N", raising=False)
    assert env_int("N", 4) == 4
    assert env_float("N", 1.5) == 1.5
    monkeypatch.setenv("N", "nope")
    assert env_int("N", 4) == 4
    assert env_float("N", 1.5) == 1.5
    monkeypatch.setenv("N", "0")
    assert env_int("N", 4) == 4
    assert env_float("N", 1.5) == 1.5
    monkeypatch.setenv("N", "-2")
    assert env_int("N", 4) == 4
    monkeypatch.setenv("N", "8")
    assert env_int("N", 4) == 8
    monkeypatch.setenv("N", "2.5")
    assert env_float("N", 1.5) == 2.5


def test_clip_text_and_project_slug():
    assert clip_text("abc", 10) == "abc"
    assert clip_text("abcdef", 0) == "abcdef"
    assert clip_text("abcdefghij", 8, ellipsis="..").endswith("..")
    assert project_slug(None) == "project"
    assert project_slug("") == "project"
    assert project_slug("https://github.com/Acme/Api.git") == "acme-api"
    assert project_slug("git@github.com:Acme/Api.git") == "acme-api"
    assert project_slug("just-name") == "just-name"
    assert project_slug("///") == "project"
    assert project_slug("owner/repo with spaces") == "owner-repo-with-spaces"


def test_format_search_hits_variants():
    assert format_search_hits("") == ""
    assert format_search_hits("not-json") == "not-json"
    assert format_search_hits('{"path": "x"}') == '{"path": "x"}'
    payload = [
        {"path": "notes/a.md", "title": "A", "snippet": "hello"},
        {"title": "Only title"},
        {"path": "notes/b.md"},
        "ignored",
        {},
    ]
    rendered = format_search_hits(json.dumps(payload))
    assert "notes/a.md — A: hello" in rendered
    assert "Only title" in rendered
    assert "- notes/b.md" in rendered


def test_memory_enablement(monkeypatch):
    monkeypatch.delenv("AI_MEMORY_ENABLED", raising=False)
    assert is_ai_memory_requested() is False
    assert memory_status_label() == "off"
    assert isinstance(get_memory_manager(), DisabledMemoryManager)

    monkeypatch.setenv("AI_MEMORY_ENABLED", "true")
    with patch("agents.memory.settings.shutil.which", return_value=None):
        assert is_ai_memory_available() is False
        assert is_ai_memory_enabled() is False
        assert memory_status_label() == "requested (binary missing)"
        assert isinstance(get_memory_manager(), DisabledMemoryManager)
        assert isinstance(get_memory_manager(), DisabledMemoryManager)

    with patch("agents.memory.settings.shutil.which", return_value="/usr/bin/ai-memory"):
        assert is_ai_memory_enabled() is True
        assert memory_status_label() == "on"
        first = get_memory_manager()
        second = get_memory_manager()
        assert isinstance(first, AIMemoryManager)
        assert first is second


@pytest.mark.anyio
async def test_disabled_middleware_is_noop():
    manager = DisabledMemoryManager()
    await manager.begin_run(cwd="/tmp", project="p", demand="d", git_branch="b")
    assert await manager.enrich_prompt("PROMPT", demand="d", step_name="s") == "PROMPT"
    await manager.after_step(step_name="s", status="success")
    await manager.end_run(status="success")
    assert manager.enabled is False


def _manager(tmp_path: Path, **kwargs) -> AIMemoryManager:
    return AIMemoryManager(
        binary="ai-memory",
        data_dir=str(tmp_path / "data"),
        server_url="http://127.0.0.1:49374",
        workspace="aegis-phalanx",
        context_chars=200,
        cli_timeout=0.2,
        serve_poll_attempts=kwargs.pop("serve_poll_attempts", 2),
        serve_poll_interval=kwargs.pop("serve_poll_interval", 0),
        **kwargs,
    )


@pytest.mark.anyio
async def test_run_cli_timeout(tmp_path):
    manager = _manager(tmp_path)
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(side_effect=TimeoutError("timed out"))
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        code, _, err = await manager._run_cli(["status"])
        assert code == 1


def test_manager_reads_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AI_MEMORY_DATA_DIR", str(tmp_path / "mem"))
    monkeypatch.setenv("AI_MEMORY_SERVER_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("AI_MEMORY_WORKSPACE", "ws")
    monkeypatch.setenv("AI_MEMORY_CONTEXT_CHARS", "12")
    monkeypatch.setenv("AI_MEMORY_CLI_TIMEOUT", "3")
    monkeypatch.setenv("AI_MEMORY_SERVE_POLL_ATTEMPTS", "3")
    monkeypatch.setenv("AI_MEMORY_SERVE_POLL_INTERVAL", "0.1")
    manager = AIMemoryManager(binary="ai-memory")
    assert manager.data_dir.endswith("mem")
    assert manager.server_url.endswith(":9")
    assert manager.workspace == "ws"
    assert manager.context_chars == 12
    assert manager.cli_timeout == 3
    assert manager.serve_poll_attempts == 3
    assert manager.serve_poll_interval == 0.1


@pytest.mark.anyio
async def test_run_cli_success_and_failure(tmp_path):
    manager = _manager(tmp_path)
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'{"ok":true}', b""))
    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        code, out, err = await manager._run_cli(["status", "--json"], stdin="{}")
        assert code == 0
        assert "ok" in out
        assert err == ""
        assert mock_exec.call_args.kwargs["stdin"] is not None

    with patch("asyncio.create_subprocess_exec", side_effect=RuntimeError("boom")):
        code, out, err = await manager._run_cli(["status"])
        assert code == 1
        assert "boom" in err


@pytest.mark.anyio
async def test_ensure_ready_paths(tmp_path, monkeypatch):
    manager = _manager(tmp_path)

    with patch("agents.memory.settings.shutil.which", return_value=None):
        assert await manager.ensure_ready() is False

    manager._ready = True
    assert await manager.ensure_ready() is True
    manager._ready = False

    dead = MagicMock()
    dead.returncode = 1
    manager._serve_proc = dead
    with patch("agents.memory.settings.shutil.which", return_value="/bin/ai-memory"), \
         patch.object(manager, "_run_cli", new=AsyncMock(return_value=(1, "", "init failed"))), \
         patch.object(manager, "_status_ok", new=AsyncMock(side_effect=[True])):
        assert await manager.ensure_ready() is True
        assert manager._serve_proc is None

    manager._ready = False
    with patch("agents.memory.settings.shutil.which", return_value="/bin/ai-memory"), \
         patch("os.makedirs", side_effect=OSError("denied")):
        assert await manager.ensure_ready() is False

    manager = _manager(tmp_path)
    with patch("agents.memory.settings.shutil.which", return_value="/bin/ai-memory"), \
         patch.object(manager, "_run_cli", new=AsyncMock(return_value=(0, "", ""))), \
         patch.object(manager, "_status_ok", new=AsyncMock(side_effect=[False, False, True])), \
         patch.object(manager, "_start_serve", new=AsyncMock()) as start:
        assert await manager.ensure_ready() is True
        start.assert_awaited()

    manager = _manager(tmp_path, serve_poll_attempts=1)
    with patch("agents.memory.settings.shutil.which", return_value="/bin/ai-memory"), \
         patch.object(manager, "_run_cli", new=AsyncMock(return_value=(0, "", ""))), \
         patch.object(manager, "_status_ok", new=AsyncMock(return_value=False)), \
         patch.object(manager, "_start_serve", new=AsyncMock(side_effect=RuntimeError("no serve"))):
        assert await manager.ensure_ready() is False

    manager = _manager(tmp_path, serve_poll_attempts=1)
    with patch("agents.memory.settings.shutil.which", return_value="/bin/ai-memory"), \
         patch.object(manager, "_run_cli", new=AsyncMock(return_value=(0, "", ""))), \
         patch.object(manager, "_status_ok", new=AsyncMock(return_value=False)), \
         patch.object(manager, "_start_serve", new=AsyncMock()):
        assert await manager.ensure_ready() is False


@pytest.mark.anyio
async def test_start_serve_reuses_running_process(tmp_path):
    manager = _manager(tmp_path)
    running = MagicMock()
    running.returncode = None
    manager._serve_proc = running
    await manager._start_serve()
    assert manager._serve_proc is running

    manager._serve_proc = None
    spawned = AsyncMock()
    spawned.returncode = None
    with patch("asyncio.create_subprocess_exec", return_value=spawned) as mock_exec:
        await manager._start_serve()
        assert manager._serve_proc is spawned
        args = mock_exec.call_args.args
        assert "serve" in args
        assert "--bind" in args
        assert manager._bind_address() == "127.0.0.1:49374"


@pytest.mark.anyio
async def test_begin_enrich_after_end_flow(tmp_path):
    manager = _manager(tmp_path)
    hits = json.dumps([{"path": "notes/x.md", "title": "X", "snippet": "red tests"}])

    async def fake_cli(args, **kwargs):
        if args[:1] == ["read-page"]:
            return 0, "# previous snapshot", ""
        if args[:1] == ["search"]:
            return 0, hits, ""
        if args[:1] == ["write-page"]:
            return 0, "ok", ""
        return 0, "", ""

    with patch.object(manager, "ensure_ready", new=AsyncMock(return_value=True)), \
         patch.object(manager, "_run_cli", side_effect=fake_cli) as run_cli:
        await manager.begin_run(
            cwd=str(tmp_path),
            project="owner/repo",
            demand='Add "login"',
            git_branch="feature/login",
            is_resume=False,
        )
        enriched = await manager.enrich_prompt("WRITE TESTS", demand="login", step_name="RED")
        assert MEMORY_PREAMBLE in enriched
        assert "previous snapshot" in enriched
        assert "Related memory" in enriched
        assert "WRITE TESTS" in enriched
        await manager.after_step(step_name="RED", status="success", git_changes="• a.py", stdout="ok")
        await manager.end_run(status="success")
        assert manager._begun is False
        write_calls = [call.args[0] for call in run_cli.await_args_list if call.args[0][:1] == ["write-page"]]
        assert any(PROGRESS_PAGE_PATH in cmd for cmd in write_calls)

    manager._begun = False
    with patch.object(manager, "ensure_ready", new=AsyncMock(return_value=False)):
        await manager.begin_run(cwd="c", project="p", demand="d", git_branch="b")
        assert manager._begun is False
        assert await manager.enrich_prompt("P", demand="d", step_name="s") == "P"
        await manager.after_step(step_name="s", status="failed")
        await manager.end_run(status="failed")


@pytest.mark.anyio
async def test_enrich_and_lifecycle_guards(tmp_path):
    manager = _manager(tmp_path)
    manager._begun = True
    manager._demand = "d"

    with patch.object(manager, "ensure_ready", new=AsyncMock(return_value=True)), \
         patch.object(manager, "_read_progress", new=AsyncMock(return_value="")), \
         patch.object(manager, "_search_demand", new=AsyncMock(return_value="")):
        assert await manager.enrich_prompt("P", demand="", step_name="s") == "P"

    with patch.object(manager, "ensure_ready", new=AsyncMock(return_value=True)), \
         patch.object(manager, "_read_progress", new=AsyncMock(side_effect=RuntimeError("x"))):
        assert await manager.enrich_prompt("P", demand="d", step_name="s") == "P"

    with patch.object(manager, "ensure_ready", new=AsyncMock(side_effect=RuntimeError("x"))):
        await manager.begin_run(cwd="c", project="p", demand="d", git_branch="b")
        manager._begun = True
        await manager.after_step(step_name="s", status="ok")
        await manager.end_run(status="ok")

    manager._begun = False
    await manager.after_step(step_name="s", status="ok")
    await manager.end_run(status="ok")

    manager._begun = True
    with patch.object(manager, "ensure_ready", new=AsyncMock(return_value=True)), \
         patch.object(manager, "_write_progress", new=AsyncMock()) as write:
        await manager.after_step(step_name="s", status="ok", git_changes="f", stdout="o")
        await manager.end_run(status="success")
        assert write.await_count == 2
        assert manager._begun is False

    manager._begun = True
    with patch.object(manager, "ensure_ready", new=AsyncMock(return_value=False)):
        await manager.after_step(step_name="s", status="ok")
        await manager.end_run(status="ok")


@pytest.mark.anyio
async def test_search_and_write_helpers(tmp_path):
    manager = _manager(tmp_path)
    manager._project = "acme-api"
    manager._demand = "login"
    manager._git_branch = "feature/login"

    with patch.object(manager, "_run_cli", new=AsyncMock(return_value=(1, "", "nope"))):
        assert await manager._read_progress() == ""
        assert await manager._search_demand("login") == ""
        await manager._write_progress("RED", "success", "", "")

    with patch.object(manager, "_run_cli", new=AsyncMock(return_value=(0, "[]", ""))):
        assert await manager._search_demand("   ") == ""
        assert await manager._search_demand("login") == ""

    with patch.object(manager, "ensure_ready", new=AsyncMock(return_value=True)), \
         patch.object(manager, "_write_progress", new=AsyncMock()) as write:
        await manager.begin_run(
            cwd=str(tmp_path),
            project="acme/api",
            demand="resume me",
            git_branch="feature/x",
            is_resume=True,
        )
        write.assert_not_awaited()
        assert manager._project == "acme-api"


@pytest.mark.anyio
async def test_status_ok_and_https_bind(tmp_path):
    manager = _manager(tmp_path)
    manager.server_url = "https://example.internal:9/"
    assert manager._bind_address() == "example.internal:9"
    with patch.object(manager, "_run_cli", new=AsyncMock(return_value=(0, "{}", ""))):
        assert await manager._status_ok() is True
    with patch.object(manager, "_run_cli", new=AsyncMock(return_value=(2, "", "down"))):
        assert await manager._status_ok() is False


def test_install_ai_memory_archive_and_extract(tmp_path, monkeypatch):
    from scripts import install_ai_memory

    assert install_ai_memory.archive_name("x86_64") == "ai-memory-linux-x86_64.tar.gz"
    assert install_ai_memory.archive_name("aarch64") == "ai-memory-linux-aarch64.tar.gz"
    with pytest.raises(SystemExit):
        install_ai_memory.archive_name("ppc64")

    archive = tmp_path / "ai-memory-linux-x86_64.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        empty_dir = tmp_path / "empty_dir"
        empty_dir.mkdir()
        tar.add(empty_dir, arcname="extra-dir")
        evil = tmp_path / "evil"
        evil.write_text("nope", encoding="utf-8")
        tar.add(evil, arcname="../evil")
        nested = tmp_path / "ai-memory"
        nested.write_text("#!/bin/sh\n", encoding="utf-8")
        tar.add(nested, arcname="bin/ai-memory")

    dest = tmp_path / "out" / "ai-memory"

    def fake_retrieve(url, filename):
        Path(filename).write_bytes(archive.read_bytes())

    monkeypatch.setattr(install_ai_memory.urllib.request, "urlretrieve", fake_retrieve)
    installed = install_ai_memory.install(version="v2.3.1", dest=str(dest), machine="x86_64")
    assert installed == dest
    assert dest.is_file()
    assert os.access(dest, os.X_OK)


def test_install_ai_memory_missing_binary(tmp_path, monkeypatch):
    from scripts import install_ai_memory

    archive = tmp_path / "ai-memory-linux-x86_64.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        other = tmp_path / "README"
        other.write_text("hi", encoding="utf-8")
        tar.add(other, arcname="README")

    def fake_retrieve(url, filename):
        Path(filename).write_bytes(archive.read_bytes())

    monkeypatch.setattr(install_ai_memory.urllib.request, "urlretrieve", fake_retrieve)
    with pytest.raises(SystemExit, match="binary not found"):
        install_ai_memory.install(dest=str(tmp_path / "bin" / "ai-memory"), machine="x86_64")


def test_safe_member_path_rejects_absolute_and_unknown_names():
    from scripts import install_ai_memory

    assert install_ai_memory._safe_member_path("/ai-memory") is None
    assert install_ai_memory._safe_member_path("notes/README") is None
    assert install_ai_memory._safe_member_path("bin/ai-memory").name == "ai-memory"


def test_ai_memory_binary_fallback(monkeypatch):
    monkeypatch.setenv("AI_MEMORY_BINARY", "  ")
    assert mm.ai_memory_binary() == "ai-memory"
    monkeypatch.setenv("AI_MEMORY_BINARY", "custom-memory")
    assert mm.ai_memory_binary() == "custom-memory"


def test_install_ai_memory_main(monkeypatch):
    from scripts import install_ai_memory

    monkeypatch.setattr(install_ai_memory, "install", MagicMock(return_value=Path("/usr/local/bin/ai-memory")))
    install_ai_memory.main()
    install_ai_memory.install.assert_called_once()

    monkeypatch.setattr(install_ai_memory, "install", MagicMock(side_effect=RuntimeError("net")))
    with pytest.raises(SystemExit) as exc:
        install_ai_memory.main()
    assert exc.value.code == 1

    monkeypatch.setattr(install_ai_memory, "install", MagicMock(side_effect=SystemExit(2)))
    with pytest.raises(SystemExit) as exc:
        install_ai_memory.main()
    assert exc.value.code == 2


def test_install_ai_memory_as_main(monkeypatch, tmp_path):
    import runpy
    from scripts import install_ai_memory

    dest = tmp_path / "installed" / "ai-memory"
    archive = tmp_path / "ai-memory-linux-x86_64.tar.gz"
    binary = tmp_path / "ai-memory"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(binary, arcname="ai-memory")

    def fake_retrieve(url, filename):
        Path(filename).write_bytes(archive.read_bytes())

    monkeypatch.setenv("AI_MEMORY_DEST", str(dest))
    monkeypatch.setenv("AI_MEMORY_VERSION", "v2.3.1")
    monkeypatch.setattr(install_ai_memory.urllib.request, "urlretrieve", fake_retrieve)
    monkeypatch.setattr(install_ai_memory.platform, "machine", lambda: "x86_64")
    # run_path loads a separate module object; patch urllib globally for it.
    monkeypatch.setattr("urllib.request.urlretrieve", fake_retrieve)
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    script = Path(__file__).resolve().parent / "scripts" / "install_ai_memory.py"
    runpy.run_path(str(script), run_name="__main__")
    assert dest.is_file()
