import subprocess
from pathlib import Path

import pytest
from types import SimpleNamespace

from coshoot.backend_exec import build_command, find_image, run_exec
from coshoot.preflight import parse_version, preflight


def runner(version="codex-cli 0.161.0", login_rc=0):
    def run(cmd, **kw):
        if cmd[1] == "--version":
            return SimpleNamespace(stdout=version, returncode=0)
        return SimpleNamespace(stdout="", returncode=login_rc)
    return run


def codes(findings):
    return {f.code for f in findings}


def test_parse_version():
    assert parse_version("codex-cli 0.161.0") == (0, 161, 0)
    assert parse_version("unknown") is None


def test_preflight_all_good_creates_workspace(tmp_path):
    found = preflight(tmp_path, run=runner(), which=lambda name: "/bin/codex")
    assert not [f for f in found if f.level == "block"]
    assert (tmp_path / "input").is_dir() and (tmp_path / "cache" / "library").is_dir()


def test_preflight_missing_codex_blocks(tmp_path):
    assert "codex_missing" in codes(preflight(tmp_path, run=runner(), which=lambda name: None))


def test_preflight_old_and_logged_out(tmp_path):
    found = preflight(tmp_path, run=runner("codex-cli 0.150.0", login_rc=1), which=lambda name: "/bin/codex")
    assert {"codex_too_old", "codex_not_logged_in"} <= codes(found)


def test_five_unconfirmed_drafts_need_no_generation_login(tmp_path, monkeypatch):
    """Structural preparation only; this does not claim a fresh model session was run."""
    from coshoot import backend_exec, compiler, names, sets
    from coshoot.cards import require_valid
    from test_sets import make_card

    def forbidden(*args, **kwargs):
        pytest.fail('draft preparation attempted compilation or image submission')
    monkeypatch.setattr(backend_exec, 'run_exec', forbidden)
    monkeypatch.setattr(compiler, 'write_request', forbidden)
    card = make_card()
    card['status'] = 'unverified'
    for shot in card['shots']:
        shot['status'] = 'unverified'
        require_valid(shot, 'scene')
        assert not names.scan(str(shot), names.load_names())
    sets.require_set_shape(card)
    assert len(card['shots']) == 5 and not list(tmp_path.iterdir())
    # Login is a generation preflight concern and supplies an actionable instruction.
    findings = preflight(tmp_path, run=runner(login_rc=1), which=lambda name: '/fake/codex')
    login = next(f for f in findings if f.code == 'codex_not_logged_in')
    assert login.level == 'block' and 'codex login' in login.message
    assert not list(tmp_path.rglob('request.json')) and not list(tmp_path.rglob('generation-count'))


def test_preflight_old_python(tmp_path):
    found = preflight(tmp_path, run=runner(), which=lambda name: "/bin/codex", python_version=(3, 8))
    assert "python_too_old" in codes(found)


def fake_run_factory(behavior, calls, codex_home):
    def fake_run(cmd, stdout, stderr, timeout, text):
        calls.append(cmd)
        last = Path(cmd[cmd.index("-o") + 1])
        if behavior == "timeout":
            raise subprocess.TimeoutExpired(cmd, timeout)
        if behavior == "refuse":
            last.write_text("REFUSED: policy", encoding="utf-8")
        if behavior == "ok":
            img = codex_home / "generated_images" / "t1" / "exec-1.png"
            img.parent.mkdir(parents=True, exist_ok=True)
            img.write_bytes(b"png")
            last.write_text(str(img), encoding="utf-8")
        if behavior == "noimage":
            last.write_text("done", encoding="utf-8")
        stdout.write('{"type":"thread.started"}\n')
    return fake_run


def run_case(tmp_path, behavior):
    calls = []
    home = tmp_path / "codex-home"
    request = tmp_path / "ws" / "outputs" / "r1" / "request.json"
    result = run_exec(request, request.parent, tmp_path / "ws",
                      run=fake_run_factory(behavior, calls, home), codex_home=home)
    return result, calls


def test_command_passes_path_not_prompt():
    cmd = build_command("codex", Path("/ws/r/request.json"), Path("/ws"), Path("/ws/r/last.txt"))
    assert cmd[:3] == ["codex", "exec", "--json"]
    assert "/ws/r/request.json" in cmd[-1]


def test_exec_generated(tmp_path):
    result, calls = run_case(tmp_path, "ok")
    assert result.status == "generated" and result.image_path.endswith("exec-1.png") and len(calls) == 1


def test_exec_timeout_is_not_retried(tmp_path):
    result, calls = run_case(tmp_path, "timeout")
    assert result.status == "failed_timeout" and len(calls) == 1


def test_exec_refusal_is_reported(tmp_path):
    result, calls = run_case(tmp_path, "refuse")
    assert result.status == "blocked_platform_input" and len(calls) == 1 and "REFUSED" in result.message


def test_exec_no_image(tmp_path):
    result, _ = run_case(tmp_path, "noimage")
    assert result.status == "failed_no_image"


def test_find_image_does_not_claim_another_session_image(tmp_path):
    home = tmp_path / "codex-home"
    unrelated = home / "generated_images" / "another-session" / "image.png"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_bytes(b"unrelated image")
    assert find_image("done", home, since=0) is None


def test_exec_without_output_path_does_not_deliver_another_session(tmp_path):
    home = tmp_path / "codex-home"
    request = tmp_path / "ws" / "outputs" / "this-run" / "request.json"
    calls = []

    def run(cmd, stdout, stderr, timeout, text):
        calls.append(cmd)
        unrelated = home / "generated_images" / "other-run" / "image.png"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_bytes(b"another session generated this")
        Path(cmd[cmd.index("-o") + 1]).write_text("done", encoding="utf-8")
        stdout.write("{}\n")

    result = run_exec(request, request.parent, tmp_path / "ws", run=run, codex_home=home)
    assert result.status == "failed_no_image"
    assert result.image_path is None
    assert len(calls) == 1


def test_preflight_codex_timeout_blocks(tmp_path):
    def run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 30)
    found = preflight(tmp_path, run=run, which=lambda name: "/bin/codex")
    hit = [f for f in found if f.code == "codex_unusable"]
    assert len(hit) == 1 and hit[0].level == "block" and "TimeoutExpired" in hit[0].message
    assert not codes(found) & {"codex_too_old", "codex_not_logged_in"}


def test_preflight_codex_oserror_blocks(tmp_path):
    def run(cmd, **kw):
        raise OSError("exec format error")
    assert "codex_unusable" in codes(preflight(tmp_path, run=run, which=lambda name: "/bin/codex"))


def test_preflight_login_status_timeout_blocks(tmp_path):
    def run(cmd, **kw):
        if cmd[1] == "--version":
            return SimpleNamespace(stdout="codex-cli 0.161.0", returncode=0)
        raise subprocess.TimeoutExpired(cmd, 30)
    assert "codex_unusable" in codes(preflight(tmp_path, run=run, which=lambda name: "/bin/codex"))


def test_exec_ignores_stale_last_message(tmp_path):
    request = tmp_path / "ws" / "outputs" / "r1" / "request.json"
    request.parent.mkdir(parents=True)
    (request.parent / "last-message.txt").write_text("REFUSED: old", encoding="utf-8")

    def fake_run(cmd, stdout, stderr, timeout, text):
        stdout.write("{}\n")
    result = run_exec(request, request.parent, tmp_path / "ws", run=fake_run, codex_home=tmp_path / "home")
    assert result.status == "failed_no_image"


def _fake_launcher(tmp_path):
    # codex is a node launcher around a native binary. The grandchild here ignores SIGTERM,
    # like a binary that outlives its launcher, and appends a heartbeat every 0.1 s (bounded to 60 s).
    heartbeat = tmp_path / "heartbeat"
    script = tmp_path / "fake-launcher.sh"
    # The launcher leads its own group, so its pid is the pgid a failing test must clean up.
    script.write_text(
        f"#!/bin/sh\necho $$ > '{tmp_path / 'launcher.pid'}'\n"
        "sh -c 'trap \"\" TERM; i=0; while [ $i -lt 600 ]; do echo . >> \"$0\"; i=$((i+1)); sleep 0.1; done' "
        f"'{heartbeat}' &\nwait\n")
    return script, heartbeat


def _wait_for(predicate, seconds):
    import time
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _kill_leftover_group(tmp_path):
    import os
    import signal
    try:
        os.killpg(int((tmp_path / "launcher.pid").read_text()), signal.SIGKILL)
    except (OSError, ValueError):
        pass


def _assert_group_gone(heartbeat):
    # No heartbeat growth for 1 s means the whole group is gone; `ps` is denied in sandboxes.
    import time
    time.sleep(0.3)
    size = heartbeat.stat().st_size
    time.sleep(1.0)
    assert heartbeat.stat().st_size == size, "grandchild still running"


def test_timeout_kills_the_whole_process_group(tmp_path):
    # Runs 84/89 delivered images after the timeout, run 94 kept running: only the launcher died.
    from coshoot.backend_exec import DEFAULT_TIMEOUT, run_in_group
    script, heartbeat = _fake_launcher(tmp_path)
    try:
        with open(tmp_path / "log", "w") as fh:
            with pytest.raises(subprocess.TimeoutExpired):
                run_in_group(["/bin/sh", str(script)], stdout=fh, stderr=subprocess.STDOUT, timeout=3, text=True)
        assert heartbeat.exists(), "grandchild never started"
        _assert_group_gone(heartbeat)
    finally:
        _kill_leftover_group(tmp_path)
    assert DEFAULT_TIMEOUT >= 1800  # images took ~16 min on 2026-10-12


# Each case is the list of signals sent to the caller; repeats land during the cleanup.
@pytest.mark.parametrize("sigs", [["SIGINT"], ["SIGTERM"], ["SIGHUP"], ["SIGTERM", "SIGTERM"], ["SIGTERM", "SIGHUP"],
                                  ["SIGINT", "SIGINT"]])
def test_interrupt_kills_the_whole_process_group(tmp_path, sigs):
    # start_new_session hides Ctrl-C from codex: if Python dies first, codex keeps spending credits.
    import signal
    import sys
    import time
    import coshoot
    script, heartbeat = _fake_launcher(tmp_path)
    scripts_dir = str(Path(coshoot.__file__).resolve().parents[1])
    parent = ("import signal, subprocess, sys; sys.path.insert(0, %r); "
              "signal.signal(signal.SIGINT, signal.default_int_handler); "
              "from coshoot.backend_exec import run_in_group; "
              "run_in_group(['/bin/sh', %r], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)"
              % (scripts_dir, str(script)))
    proc = subprocess.Popen([sys.executable, "-c", parent], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        assert _wait_for(heartbeat.exists, 20), "grandchild never started"
        for n, sig in enumerate(sigs):
            if n:
                time.sleep(0.05)
            proc.send_signal(getattr(signal, sig))
        proc.communicate(timeout=20)
        assert proc.returncode != 0
        _assert_group_gone(heartbeat)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        _kill_leftover_group(tmp_path)


def test_signal_while_spawning_still_kills_the_group(tmp_path):
    # Re-review round 2: a signal landing after fork but before Popen returned left proc unset,
    # so the cleanup was skipped. Two signals are sent from inside Popen to hit that window.
    import sys
    import coshoot
    script, heartbeat = _fake_launcher(tmp_path)
    scripts_dir = str(Path(coshoot.__file__).resolve().parents[1])
    parent = ("import os, signal, subprocess, sys; sys.path.insert(0, %r); "
              "real = subprocess.Popen\n"
              "class Late(real):\n"
              "    def __init__(self, *a, **k):\n"
              "        super().__init__(*a, **k)\n"
              "        os.kill(os.getpid(), signal.SIGTERM)\n"
              "        os.kill(os.getpid(), signal.SIGHUP)\n"
              "subprocess.Popen = Late\n"
              "from coshoot.backend_exec import run_in_group\n"
              "run_in_group(['/bin/sh', %r], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)"
              % (scripts_dir, str(script)))
    proc = subprocess.Popen([sys.executable, "-c", parent], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        proc.communicate(timeout=30)
        assert proc.returncode != 0
        # Killed before the grandchild started also counts as clean.
        if _wait_for(heartbeat.exists, 2):
            _assert_group_gone(heartbeat)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        _kill_leftover_group(tmp_path)


def test_signal_during_timeout_cleanup_still_kills_the_group(tmp_path):
    # Re-review round 4: Ctrl-C landing while the timeout cleanup runs skipped the SIGKILL.
    import sys
    import coshoot
    script, heartbeat = _fake_launcher(tmp_path)
    scripts_dir = str(Path(coshoot.__file__).resolve().parents[1])
    parent = ("import os, signal, subprocess, sys; sys.path.insert(0, %r)\n"
              "from coshoot import backend_exec\n"
              "real = backend_exec._signal_group\n"
              "def interrupted(pgid, sig):\n"
              "    real(pgid, sig)\n"
              "    if sig == signal.SIGTERM:\n"
              "        os.kill(os.getpid(), signal.SIGINT)\n"
              "backend_exec._signal_group = interrupted\n"
              "backend_exec.run_in_group(['/bin/sh', %r], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)"
              % (scripts_dir, str(script)))
    proc = subprocess.Popen([sys.executable, "-c", parent], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        proc.communicate(timeout=30)
        assert proc.returncode != 0
        assert heartbeat.exists(), "grandchild never started"
        _assert_group_gone(heartbeat)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        _kill_leftover_group(tmp_path)


def test_child_signal_mask_and_handlers_are_restored(tmp_path):
    import signal
    import sys
    from coshoot.backend_exec import run_in_group
    before = {s: signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    probe = "import signal; print(sorted(int(s) for s in signal.pthread_sigmask(signal.SIG_BLOCK, [])))"
    with open(tmp_path / "log", "w") as fh:
        assert run_in_group([sys.executable, "-c", probe], stdout=fh, stderr=subprocess.STDOUT, timeout=30) == 0
    blocked = set(eval((tmp_path / "log").read_text()))
    assert not blocked & {int(signal.SIGINT), int(signal.SIGTERM), int(signal.SIGHUP)}
    with open(tmp_path / "log", "w") as fh:
        with pytest.raises(subprocess.TimeoutExpired):
            run_in_group(["/bin/sh", "-c", "sleep 30"], stdout=fh, stderr=subprocess.STDOUT, timeout=1)
    assert {s: signal.getsignal(s) for s in before} == before
    assert not set(signal.pthread_sigmask(signal.SIG_BLOCK, [])) & set(before)


def test_codex_gets_closed_stdin(tmp_path):
    # codex exec reads stdin when it is not a TTY; an inherited never-closing socket made it
    # wait forever before starting (run 99 sat 27 min at "Reading additional input from stdin").
    import os
    from coshoot.backend_exec import run_in_group
    script = tmp_path / "reads-stdin.sh"
    script.write_text("#!/bin/sh\ncat > /dev/null\necho done\n")
    r, w = os.pipe()  # a stdin that never reaches EOF, like the harness socket
    saved = os.dup(0)
    os.dup2(r, 0)
    try:
        with open(tmp_path / "log", "w") as fh:
            assert run_in_group(["/bin/sh", str(script)], stdout=fh, stderr=subprocess.STDOUT, timeout=30) == 0
    finally:
        os.dup2(saved, 0)
        os.close(r); os.close(w); os.close(saved)
    assert (tmp_path / "log").read_text().strip() == "done"
