"""Environment preflight: block before any quota is spent."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .detect import default_detector
from .findings import Finding

MIN_CODEX = (0, 161, 0)
WORKSPACE_DIRS = ("input", "cache/library", "characters", "cards", "outputs")


def parse_version(text: str) -> Optional[Tuple[int, int, int]]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    if match is None:
        return None
    major, minor, patch = (int(x) for x in match.groups())
    return (major, minor, patch)


def preflight(workspace: Path, run: Callable = subprocess.run, which: Callable = shutil.which,
              python_version: Tuple[int, int] = tuple(sys.version_info[:2])) -> List[Finding]:
    out: List[Finding] = []
    if tuple(python_version) < (3, 9):
        out.append(Finding("block", "python_too_old", "需要 Python 3.9 或更高版本"))
    codex = which("codex")
    if codex is None:
        out.append(Finding("block", "codex_missing", "未找到 Codex CLI：请先安装（npm install -g @openai/codex）并登录"))
    else:
        try:
            version = run([codex, "--version"], capture_output=True, text=True, timeout=30)
            login = run([codex, "login", "status"], capture_output=True, text=True, timeout=30)
        except Exception as exc:
            out.append(Finding("block", "codex_unusable",
                               f"Codex CLI 无法正常运行（{type(exc).__name__}）：请重新安装或检查"))
        else:
            parsed = parse_version(version.stdout)
            if parsed is None or parsed < MIN_CODEX:
                out.append(Finding("block", "codex_too_old",
                                   f"Codex CLI 需要 ≥ {'.'.join(map(str, MIN_CODEX))}，当前：{(version.stdout or '').strip() or '未知'}"))
            if login.returncode != 0:
                out.append(Finding("block", "codex_not_logged_in", "Codex 未登录：请先运行 codex login"))
    try:
        for name in WORKSPACE_DIRS:
            (Path(workspace) / name).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        out.append(Finding("block", "workspace_not_writable", f"工作区不可写：{exc}"))
    if default_detector() is None:
        out.append(Finding("info", "opencv_missing", "未安装可用的 opencv 4.x：照片体检与构图检查将改为人工确认"))
    return out
