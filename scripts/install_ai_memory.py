#!/usr/bin/env python3
"""Install the optional ai-memory CLI from a GitHub release tarball."""

from __future__ import annotations

import os
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

DEFAULT_VERSION = "v2.3.1"
RELEASE_BASE = "https://github.com/akitaonrails/ai-memory/releases/download"
ARCHIVE_BY_MACHINE = {
    "x86_64": "ai-memory-linux-x86_64.tar.gz",
    "amd64": "ai-memory-linux-x86_64.tar.gz",
    "aarch64": "ai-memory-linux-aarch64.tar.gz",
    "arm64": "ai-memory-linux-aarch64.tar.gz",
}


def archive_name(machine: str | None = None) -> str:
    resolved = (machine or platform.machine() or "").strip().lower()
    archive = ARCHIVE_BY_MACHINE.get(resolved)
    if not archive:
        raise SystemExit(f"Unsupported architecture for ai-memory: {resolved or 'unknown'}")
    return archive


def _safe_member_path(name: str) -> Path | None:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts:
        return None
    if path.name != "ai-memory":
        return None
    return path


def install(version: str | None = None, dest: str | None = None, machine: str | None = None) -> Path:
    version = version or os.environ.get("AI_MEMORY_VERSION", DEFAULT_VERSION)
    dest_path = Path(dest or os.environ.get("AI_MEMORY_DEST", "/usr/local/bin/ai-memory"))
    archive = archive_name(machine)
    url = f"{RELEASE_BASE}/{version}/{archive}"
    print(f"Downloading ai-memory {version} ({archive})", flush=True)

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        archive_path = tmp_dir / archive
        urllib.request.urlretrieve(url, archive_path)
        extract_dir = tmp_dir / "extract"
        extract_dir.mkdir()
        found: Path | None = None
        with tarfile.open(archive_path, "r:gz") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                safe = _safe_member_path(member.name)
                if safe is None:
                    continue
                tar.extract(member, extract_dir)
                found = extract_dir / safe
                break
        if found is None or not found.is_file():
            raise SystemExit(f"ai-memory binary not found inside {archive}")
        shutil.copy2(found, dest_path)
        dest_path.chmod(dest_path.stat().st_mode | 0o111)
    print(f"Installed ai-memory to {dest_path}", flush=True)
    return dest_path


def main() -> None:
    try:
        install()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Failed to install ai-memory: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
