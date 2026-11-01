"""Claude Code backend: relay request.json to Codex's built-in image tool via `codex exec`.

Exactly one attempt per call; no retries on any failure.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, List, Optional

# Images took ~16 min on 2026-10-12 (runs 84/89 finished after a 900 s timeout).
DEFAULT_TIMEOUT = 1800
GRACE_SECONDS = 5
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
RELAY_BRIEF = (
    "You are a relay for a local skill. Read the JSON file at {request_path}. "
    "Call the built-in image generation tool exactly once, passing the file's \"prompt\" field verbatim "
    "as the prompt and its \"referenced_image_paths\" field verbatim as the reference images. "
    "Do not rewrite, translate, shorten or extend the prompt. Do not retry. "
    "If the tool refuses, reply with REFUSED: followed by the refusal text. "
    "Otherwise reply with only the absolute path of the generated image."
)


@dataclass
class ExecResult:
    status: str  # generated | failed_timeout | failed_no_image | blocked_platform_input
    image_path: Optional[str]
    log_path: str
    message: str

    def to_dict(self) -> dict:
        return asdict(self)


def run_in_group(cmd: List[str], stdout, stderr, timeout: int, text: bool = True) -> int:
    """Run cmd in its own process group; on timeout, Ctrl-C or SIGTERM/SIGHUP kill the whole
    group, then re-raise.

    `codex` is a launcher around a native binary: killing only the launcher left the binary
    generating (and spending credits) after the timeout. The new session also hides the
    terminal's Ctrl-C from codex, so this process must forward every way it can end.
    Signals are only handled on the main thread (the CLI's case).
    """
    proc = None
    saved = {}
    fired = []  # set by the first signal, or by a timeout: later signals are no-ops
    try:
        # Blocked while spawning and swapping handlers: a signal arriving after fork but before
        # `proc` is set would otherwise skip the cleanup. It is delivered on unblock, inside `try`.
        with _forwarded_blocked():
            _install(dict.fromkeys(FORWARDED_SIGNALS, _raise_once(fired)), saved)
            # stdin is closed: codex exec reads a non-TTY stdin to EOF, and an inherited socket never ends.
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, text=text,
                                    start_new_session=True, preexec_fn=_unblock_forwarded)
        return proc.wait(timeout=timeout)
    except BaseException:
        fired.append(None)
        if proc is not None:
            _kill_group(proc)
        raise
    finally:
        with _forwarded_blocked():
            for sig, old in saved.items():
                signal.signal(sig, old)


FORWARDED_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


class _Terminated(SystemExit):
    pass


def _raise_once(fired: list):
    """Raise on the first signal only: later ones must not cut the group cleanup short."""
    def handler(signum, frame):
        if not fired:
            fired.append(signum)
            raise _Terminated(128 + signum)
    return handler


@contextmanager
def _forwarded_blocked():
    old = signal.pthread_sigmask(signal.SIG_BLOCK, FORWARDED_SIGNALS)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, old)


def _unblock_forwarded() -> None:
    # The child inherits the blocked mask from the fork; codex must still die on SIGTERM.
    signal.pthread_sigmask(signal.SIG_UNBLOCK, FORWARDED_SIGNALS)


def _install(handlers: dict, saved: dict) -> None:
    try:
        for sig, handler in handlers.items():
            saved[sig] = signal.signal(sig, handler)
    except ValueError:  # not the main thread: signals cannot be handled here
        pass


def _kill_group(proc: subprocess.Popen) -> None:
    # SIGTERM first, then SIGKILL the group regardless: the launcher may exit while a
    # grandchild that ignores SIGTERM keeps running.
    _signal_group(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    time.sleep(0.2)
    _signal_group(proc.pid, signal.SIGKILL)
    try:
        proc.wait(timeout=GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass


def _signal_group(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def build_command(codex: str, request_path: Path, workspace: Path, last_message: Path) -> List[str]:
    return [codex, "exec", "--json", "--skip-git-repo-check", "-C", str(workspace),
            "-o", str(last_message), RELAY_BRIEF.format(request_path=request_path)]


def _default_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))


def find_image(message: str, codex_home: Path, since: float) -> Optional[Path]:
    """Read the relay's explicit path; legacy home/time arguments remain for compatibility."""
    lines = [line.strip() for line in message.strip().splitlines() if line.strip()]
    if lines:
        candidate = Path(lines[-1])
        if candidate.suffix.lower() in IMAGE_SUFFIXES and candidate.is_file() and candidate.is_absolute() and candidate.stat().st_mtime >= since:
            return candidate
    # A recent file in the global directory may belong to a different session.
    # Without this run's explicit output path, fail closed instead of guessing.
    return None


def run_exec(request_path: Path, run_dir: Path, workspace: Path, codex: str = "codex",
             timeout: int = DEFAULT_TIMEOUT, run: Callable = run_in_group,
             codex_home: Optional[Path] = None) -> ExecResult:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    log = run_dir / "exec.jsonl"
    last = run_dir / "last-message.txt"
    last.unlink(missing_ok=True)  # never read a previous attempt's message
    start = time.time()
    cmd = build_command(codex, request_path, workspace, last)
    with open(log, "w", encoding="utf-8") as fh:
        try:
            outcome = run(cmd, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout, text=True)
        except subprocess.TimeoutExpired:
            return ExecResult("failed_timeout", None, str(log), "生成超时：额度很可能已扣除，不会自动重试")
    message = last.read_text(encoding="utf-8") if last.is_file() else ""
    if message.strip().startswith("REFUSED:"):
        return ExecResult("blocked_platform_input", None, str(log), message.strip())
    returncode = outcome if isinstance(outcome, int) else getattr(outcome, "returncode", 0)
    if returncode:
        return ExecResult("failed_no_image", None, str(log), f"生成进程退出码 {returncode}，结果待核实，不自动重试；末次消息保留在 {last}")
    image = find_image(message, codex_home or _default_codex_home(), start)
    if image is None:
        return ExecResult("failed_no_image", None, str(log), "没有拿到生成的图片：额度可能已扣除，不会自动重试")
    return ExecResult("generated", str(image), str(log), "已生成")
