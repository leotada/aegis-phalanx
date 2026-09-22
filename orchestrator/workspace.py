"""Git clone, identity, and branch checkout for pipeline workspaces."""

from __future__ import annotations

import asyncio
import os

from orchestrator.paths import PROJECT_DIR


class GitWorkspace:
    """The on-disk clone where a pipeline or review runs git commands."""

    def __init__(self, project_dir: str = PROJECT_DIR):
        self.project_dir = project_dir

    async def remove(self, path: str, *, start_new_session: bool = False, wait_fn=None) -> None:
        kwargs = {}
        if start_new_session:
            kwargs["start_new_session"] = True
        proc = await asyncio.create_subprocess_exec("rm", "-rf", path, **kwargs)
        if wait_fn is not None:
            await wait_fn(proc)
        else:
            await proc.wait()

    async def clone(
        self,
        repo_url: str,
        dest: str | None = None,
        *,
        start_new_session: bool = False,
        communicate_fn=None,
    ) -> tuple[int, bytes, bytes]:
        dest = self.project_dir if dest is None else dest
        kwargs: dict = {
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
        }
        if start_new_session:
            kwargs["start_new_session"] = True
        proc = await asyncio.create_subprocess_exec("git", "clone", repo_url, dest, **kwargs)
        if communicate_fn is not None:
            stdout, stderr = await communicate_fn(proc)
        else:
            stdout, stderr = await proc.communicate()
        return proc.returncode, stdout, stderr

    async def configure_identity(self, project_dir: str | None = None) -> None:
        project_dir = self.project_dir if project_dir is None else project_dir
        for key, val in [("user.name", "Aegis Agent"), ("user.email", "agent@aegis-phalanx.local")]:
            proc = await asyncio.create_subprocess_exec("git", "config", key, val, cwd=project_dir)
            await proc.wait()

    async def local_branch_exists(self, git_branch: str, project_dir: str | None = None) -> bool:
        project_dir = self.project_dir if project_dir is None else project_dir
        proc = await asyncio.create_subprocess_exec(
            "git", "show-ref", "--verify", f"refs/heads/{git_branch}",
            cwd=project_dir,
        )
        await proc.wait()
        return proc.returncode == 0

    async def checkout(self, git_branch: str, project_dir: str | None = None) -> int:
        project_dir = self.project_dir if project_dir is None else project_dir
        proc = await asyncio.create_subprocess_exec("git", "checkout", git_branch, cwd=project_dir)
        await proc.wait()
        return proc.returncode

    async def checkout_origin(self, git_branch: str, project_dir: str | None = None) -> int:
        project_dir = self.project_dir if project_dir is None else project_dir
        proc = await asyncio.create_subprocess_exec(
            "git", "checkout", "-b", git_branch, f"origin/{git_branch}",
            cwd=project_dir,
        )
        await proc.wait()
        return proc.returncode

    async def create_branch(self, git_branch: str, project_dir: str | None = None) -> int:
        project_dir = self.project_dir if project_dir is None else project_dir
        proc = await asyncio.create_subprocess_exec("git", "checkout", "-b", git_branch, cwd=project_dir)
        await proc.wait()
        return proc.returncode

    def read_abort_reason(self, project_dir: str | None = None) -> str | None:
        project_dir = self.project_dir if project_dir is None else project_dir
        abort_file_path = os.path.join(project_dir, "architect_abort.txt")
        if not os.path.exists(abort_file_path):
            return None
        try:
            with open(abort_file_path, "r", encoding="utf-8", errors="replace") as f:
                abort_reason = f.read().strip()
        except Exception:
            abort_reason = "Architectural review rejected the plan."
        try:
            os.remove(abort_file_path)
        except Exception:
            pass
        return abort_reason


git_workspace = GitWorkspace()
