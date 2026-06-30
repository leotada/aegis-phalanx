#!/usr/bin/env python3
"""Install the agent CLI selected by AGENT_TOOL (used during image build)."""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

INSTALL_DIR = Path(__file__).resolve().parent
TOOL_SPECS_PATH = INSTALL_DIR / "tool_specs.py"

if not TOOL_SPECS_PATH.exists():
    TOOL_SPECS_PATH = INSTALL_DIR.parent / "agents" / "tool_specs.py"

spec = importlib.util.spec_from_file_location("tool_specs", TOOL_SPECS_PATH)
tool_specs = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(tool_specs)


def main() -> None:
    tool = tool_specs.validate_tool(os.environ.get("AGENT_TOOL", "agy"))
    install_spec = tool_specs.get_tool_spec(tool)
    print(f"Installing agent tool: {tool}", flush=True)

    for command in install_spec.install_commands:
        print(f"  $ {command}", flush=True)
        subprocess.run(command, shell=True, check=True)


if __name__ == "__main__":
    main()
