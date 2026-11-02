import hashlib
import json
import os
import subprocess
import sys

import pytest
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "skills" / "shy-cameo" / "scripts" / "cli.py"
FIX = Path(__file__).parent / "fixtures" / "cards"
FAKE = Path(__file__).parent / "fakes" / "fake_codex"


def cli(*args, env=None):
    proc = subprocess.run([sys.executable, str(CLI), *map(str, args)],
                          capture_output=True, text=True, env=env)
    assert proc.stdout, proc.stderr
    return proc.returncode, json.loads(proc.stdout)


def temp_wukong(ws):
    """Workspace-local temp character so no network fetch is needed."""
    card = json.loads((FIX / "wukong.json").read_text(encoding="utf-8"))
    card["status"] = "temp_confirmed"
    for variant in card["variants"]:
        for kind in ("head", "body"):
            rel = f"characters/xiyou-wukong/{variant['variant_id']}-{kind}.png"
            data = f"{variant['variant_id']}-{kind}".encode()
            (ws / rel).parent.mkdir(parents=True, exist_ok=True)
            (ws / rel).write_bytes(data)
            variant["sheets"][kind] = {"url": rel, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    path = ws / "characters" / "xiyou-wukong" / "card.json"
    path.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    return path


def compiled(tmp_path, png_factory):
    ws = tmp_path / "ws"
    (ws / "input").mkdir(parents=True)
    photo = ws / "input" / "me.png"
    photo.write_bytes(png_factory(600, 600))
    card = temp_wukong(ws)
    assert consent(ws, photo)[0] == 0
    code, out = cli("compile", "--scene", FIX / "scene-shuiliandong.json", "--character", card,
                    "--photo", photo, "--workspace", ws)
    assert code == 0, out
    return ws, Path(out["request_path"])


def consent(ws, *photos):
    args = ["consent", "--workspace", ws, "--subject", "--adult", "--self-or-consented"]
    for p in photos:
        args += ["--photo", p]
    return cli(*args)


def fake_env(tmp_path, mode):
    return dict(os.environ, CODEX_HOME=str(tmp_path / "codex-home"), FAKE_CODEX_MODE=mode)


def test_compile_writes_request(tmp_path, png_factory):
    _, request = compiled(tmp_path, png_factory)
    assert len(json.loads(request.read_text(encoding="utf-8"))["referenced_image_paths"]) == 3


def test_compile_length_notice_keeps_stdout_json_and_spends_nothing(tmp_path, png_factory):
    ws, _ = compiled(tmp_path, png_factory)
    scene = json.loads((FIX / "scene-shuiliandong.json").read_text(encoding="utf-8"))
    scene["setting"] = "木" * 800 + "完整场景尾部"
    scene_path = ws / "cards" / "long.json"
    scene_path.parent.mkdir(parents=True)
    scene_path.write_text(json.dumps(scene, ensure_ascii=False), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(CLI), "compile", "--scene", str(scene_path),
                           "--character", str(ws / "characters/xiyou-wukong/card.json"),
                           "--photo", str(ws / "input/me.png"), "--workspace", str(ws)],
                          capture_output=True, text=True)
    output = json.loads(proc.stdout)
    assert proc.returncode == 0 and output["status"] == "compiled", output
    assert "建议" in proc.stderr and "760" in proc.stderr
    request_path = Path(output["request_path"])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert scene["setting"] in request["prompt"]
    assert not (request_path.parent / "generation-count").exists()


def test_scan_names_blocked_exit_code():
    code, out = cli("scan-names", "--text", "想和星爷合影")
    assert code == 2 and out["status"] == "blocked_name" and out["blocked"] == ["星爷"]


def test_generate_requires_quota_then_consent(tmp_path, png_factory):
    ws, request = compiled(tmp_path, png_factory)
    code, out = cli("generate-exec", "--request", request, "--workspace", ws,
                    "--authorized-count", "0", "--codex", FAKE)
    assert code == 2 and out["status"] == "blocked_quota"
    (ws / "consent.json").unlink()
    code, out = cli("generate-exec", "--request", request, "--workspace", ws,
                    "--authorized-count", "1", "--codex", FAKE)
    assert code == 2 and out["status"] == "blocked_consent"
    assert not (request.parent / "generation-count").exists()


def test_full_exec_flow_with_fake_codex(tmp_path, png_factory):
    ws, request = compiled(tmp_path, png_factory)
    assert consent(ws, ws / "input" / "me.png")[0] == 0
    env = fake_env(tmp_path, "ok")
    code, out = cli("generate-exec", "--request", request, "--workspace", ws,
                    "--authorized-count", "1", "--codex", FAKE, env=env)
    assert code == 0 and out["status"] == "generated", out
    code, again = cli("generate-exec", "--request", request, "--workspace", ws,
                      "--authorized-count", "1", "--codex", FAKE, env=env)
    assert code == 2 and again["status"] == "blocked_quota"
    # S1 (2026-10-11): `codex exec --json` stdout carries no image event, so it cannot verify.
    code, stdout_audit = cli("verify", "--request", request, "--log", request.parent / "exec.jsonl")
    assert stdout_audit["status"] == "unverifiable", stdout_audit
    # The session rollout does: verify without --log finds it by request path.
    code, audit = cli("verify", "--request", request, "--codex-home", tmp_path / "codex-home")
    assert audit["status"] == "pass", audit
    assert cli("frame-check", out["image_path"], "--framing", "waist_up", "--out", request.parent / "frame.json")[0] == 0
    code, side = cli("deliver", "--image", out["image_path"], "--request", request,
                     "--workspace", ws, "--audit", request.parent / "audit.json", "--frame", request.parent / "frame.json")
    assert code == 0 and side["audit"]["status"] == "pass" and side["c2pa_present"] is True


def test_timeout_consumes_quota_and_does_not_retry(tmp_path, png_factory):
    ws, request = compiled(tmp_path, png_factory)
    consent(ws, ws / "input" / "me.png")
    code, out = cli("generate-exec", "--request", request, "--workspace", ws, "--authorized-count", "1",
                    "--codex", FAKE, "--timeout", "1", env=fake_env(tmp_path, "timeout"))
    assert code == 2 and out["status"] == "failed_timeout"
    assert (request.parent / "generation-count").read_text() == "1"


def test_asset_info_for_temp_sheet(tmp_path):
    ws = tmp_path / "ws"
    sheet = ws / "characters" / "xiyou-bajie" / "base-head.png"
    sheet.parent.mkdir(parents=True)
    sheet.write_bytes(b"sheet")
    code, out = cli("asset-info", sheet, "--workspace", ws)
    assert code == 0 and out == {"url": "characters/xiyou-bajie/base-head.png",
                                 "sha256": hashlib.sha256(b"sheet").hexdigest(), "bytes": 5}
    code, out = cli("asset-info", tmp_path / "elsewhere.png", "--workspace", ws)
    assert code == 2 and out["status"] == "asset_outside_workspace"


def test_validate_shipped_library():
    code, out = cli("validate-library")
    assert code == 0 and out["ok"] is True


def test_migrate_missing_path_emits_json_error(tmp_path):
    code, out = cli("migrate", "--kind", "scene", tmp_path / "nope.json")
    assert code == 1 and out["status"] == "error" and out["error"] == "FileNotFoundError"


def _compile_args(ws, photo, card):
    return ["compile", "--scene", FIX / "scene-shuiliandong.json", "--character", card,
            "--photo", photo, "--workspace", ws]


def test_compile_requires_consent(tmp_path, png_factory):
    ws = tmp_path / "ws"
    (ws / "input").mkdir(parents=True)
    photo = ws / "input" / "me.png"
    photo.write_bytes(png_factory(600, 600))
    card = temp_wukong(ws)
    code, out = cli(*_compile_args(ws, photo, card))
    assert code == 2 and out["status"] == "blocked_consent"
    assert not (ws / "outputs").exists()


def test_compile_invalid_character_without_ip(tmp_path, png_factory):
    ws = tmp_path / "ws"
    (ws / "input").mkdir(parents=True)
    photo = ws / "input" / "me.png"
    photo.write_bytes(png_factory(600, 600))
    card = temp_wukong(ws)
    data = json.loads(card.read_text(encoding="utf-8"))
    del data["ip"]
    card.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    consent(ws, photo)
    code, out = cli(*_compile_args(ws, photo, card))
    assert code == 2 and out["status"] == "invalid_character"


def test_compile_missing_photo(tmp_path, png_factory):
    ws = tmp_path / "ws"
    (ws / "input").mkdir(parents=True)
    ok = ws / "input" / "ok.png"
    ok.write_bytes(png_factory(600, 600))
    card = temp_wukong(ws)
    consent(ws, ok)
    code, out = cli(*_compile_args(ws, ws / "input" / "nope.png", card))
    assert code == 2 and out["status"] == "no_user_photo"
    assert not (ws / "outputs").exists()


def test_generate_exec_missing_codex_binary(tmp_path, png_factory):
    ws, request = compiled(tmp_path, png_factory)
    code, out = cli("generate-exec", "--request", request, "--workspace", ws,
                    "--authorized-count", "1", "--codex", tmp_path / "no-such-codex")
    assert code == 1 and out["status"] == "error" and out["error"] == "OSError"
    assert "额度可能已扣" in out["message"]
    assert (request.parent / "generation-count").read_text() == "1"


def test_consent_binds_photo_bytes(tmp_path, png_factory):
    ws = tmp_path / "ws"
    (ws / "input").mkdir(parents=True)
    me = ws / "input" / "me.png"
    me.write_bytes(png_factory(600, 600))
    other = ws / "input" / "other.png"
    other.write_bytes(png_factory(500, 500))
    card = temp_wukong(ws)
    code, out = consent(ws, me)
    assert code == 0 and out["photos"][0]["sha256"] == hashlib.sha256(me.read_bytes()).hexdigest()
    code, out = cli(*_compile_args(ws, other, card))
    assert code == 2 and out["status"] == "blocked_consent" and "other.png" in out["message"]
    me.write_bytes(png_factory(601, 600))  # same path, different bytes
    code, out = cli(*_compile_args(ws, me, card))
    assert code == 2 and out["status"] == "blocked_consent"


def test_consent_requires_existing_photo(tmp_path):
    ws = tmp_path / "ws"
    code, out = consent(ws, ws / "input" / "nope.png")
    assert code == 2 and out["status"] == "no_user_photo"
    assert not (ws / "consent.json").exists()


def test_record_verdict_after_self_check(tmp_path, png_factory):
    ws, request = compiled(tmp_path, png_factory)
    code, out = cli("generate-exec", "--request", request, "--workspace", ws, "--authorized-count", "1",
                    "--codex", FAKE, env=fake_env(tmp_path, "ok"))
    assert code == 0, out
    assert cli('verify', '--request', request, '--codex-home', tmp_path / 'codex-home')[0] == 0
    assert cli('frame-check', out['image_path'], '--framing', 'waist_up', '--out', request.parent / 'frame.json')[0] == 0
    code, side = cli("deliver", "--image", out["image_path"], "--request", request, "--workspace", ws,
                     '--audit', request.parent / 'audit.json', '--frame', request.parent / 'frame.json')
    assert code == 0 and side["verdict"] == "pending"
    run_dir = request.parent
    code, rec = cli("record-verdict", "--run-dir", run_dir, "--likeness", "yes", "--character", "yes",
                    "--no-face-mix", "no")
    assert code == 0 and rec["verdict"] == "rejected"
    code, rec = cli("record-verdict", "--run-dir", run_dir, "--likeness", "yes", "--character", "yes",
                    "--no-face-mix", "yes")
    saved = json.loads((run_dir / "sidecar.json").read_text(encoding="utf-8"))
    assert code == 0 and saved["verdict"] == "accepted" and saved["self_check"]["no_face_mix"] is True


def _delivered_with_audit(tmp_path, png_factory, status, reason):
    """Deliver one image whose bound audit record carries the given status."""
    ws, request = compiled(tmp_path, png_factory)
    code, out = cli("generate-exec", "--request", request, "--workspace", ws, "--authorized-count", "1",
                    "--codex", FAKE, env=fake_env(tmp_path, "ok"))
    assert code == 0, out
    assert cli('verify', '--request', request, '--codex-home', tmp_path / 'codex-home')[0] == 0
    audit_path = request.parent / 'audit.json'
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit.update(status=status, reason=reason)
    audit_path.write_text(json.dumps(audit, ensure_ascii=False), encoding="utf-8")
    assert cli('frame-check', out['image_path'], '--framing', 'waist_up', '--out', request.parent / 'frame.json')[0] == 0
    code, side = cli("deliver", "--image", out["image_path"], "--request", request, "--workspace", ws,
                     '--audit', audit_path, '--frame', request.parent / 'frame.json')
    assert code == 0 and side["audit"]["status"] == status
    return request.parent, audit_path


@pytest.mark.parametrize("status", ["unverifiable", "unverified"])
def test_declared_unverified_audit_can_still_be_accepted(tmp_path, png_factory, status):
    reason = "无法审计：日志中未找到生图调用"
    run_dir, audit_path = _delivered_with_audit(tmp_path, png_factory, status, reason)
    delivered = json.loads((run_dir / 'sidecar.json').read_text())
    assert delivered['verdict'] == 'pending' and delivered['audit']['reason'] == reason
    original_audit = audit_path.read_bytes()
    code, rec = cli("record-verdict", "--run-dir", run_dir, "--likeness", "yes", "--character", "yes",
                    "--no-face-mix", "yes")
    assert code == 0 and rec["verdict"] == "accepted"
    accepted = json.loads((run_dir / 'sidecar.json').read_text())
    assert accepted['audit'] == delivered['audit'] and audit_path.read_bytes() == original_audit


def test_goal_answer_is_recorded_and_no_rejects(tmp_path, png_factory):
    run_dir, _ = _delivered_with_audit(tmp_path, png_factory, "unverified", "日志中未找到生图调用")
    base = ["record-verdict", "--run-dir", run_dir, "--likeness", "yes", "--character", "yes", "--no-face-mix", "yes"]
    code, rec = cli(*base, "--goal", "no")
    assert code == 0 and rec["verdict"] == "rejected" and rec["self_check"]["goal_met"] is False
    code, rec = cli(*base, "--goal", "yes")
    assert code == 0 and rec["verdict"] == "accepted" and rec["self_check"]["goal_met"] is True


def test_tampered_audit_blocks_accepted_and_keeps_evidence(tmp_path, png_factory):
    run_dir, audit_path = _delivered_with_audit(tmp_path, png_factory, "tampered",
                                                "生图提示词与请求不一致或包含真实演员姓名")
    code, rec = cli("record-verdict", "--run-dir", run_dir, "--likeness", "yes", "--character", "yes",
                    "--no-face-mix", "yes")
    assert code == 2 and rec["status"] == "audit_tampered" and "tampered" in rec["message"]
    saved = json.loads((run_dir / "sidecar.json").read_text(encoding="utf-8"))
    assert saved["verdict"] == "pending" and saved["audit"]["status"] == "tampered"
    assert json.loads(audit_path.read_text(encoding="utf-8"))["status"] == "tampered"
    code, rec = cli("record-verdict", "--run-dir", run_dir, "--likeness", "no", "--character", "yes",
                    "--no-face-mix", "yes")
    assert code == 0 and rec["verdict"] == "rejected"


def test_record_verdict_without_sidecar(tmp_path):
    code, out = cli("record-verdict", "--run-dir", tmp_path, "--likeness", "yes", "--character", "yes",
                    "--no-face-mix", "yes")
    assert code == 1 and out["error"] == "FileNotFoundError"


def test_generate_exec_rejects_photo_swapped_after_compile(tmp_path, png_factory):
    ws, request = compiled(tmp_path, png_factory)
    (ws / "input" / "me.png").write_bytes(png_factory(777, 600))  # same path, different bytes
    code, out = cli("generate-exec", "--request", request, "--workspace", ws, "--authorized-count", "1",
                    "--codex", FAKE, env=fake_env(tmp_path, "ok"))
    assert code == 2 and out["status"] == "blocked_consent"
    assert not (request.parent / "generation-count").exists()


def test_consent_photos_null_is_blocked(tmp_path, png_factory):
    ws = tmp_path / "ws"
    (ws / "input").mkdir(parents=True)
    photo = ws / "input" / "me.png"
    photo.write_bytes(png_factory(600, 600))
    card = temp_wukong(ws)
    assert consent(ws, photo)[0] == 0
    data = json.loads((ws / "consent.json").read_text(encoding="utf-8"))
    data["photos"] = None
    (ws / "consent.json").write_text(json.dumps(data), encoding="utf-8")
    code, out = cli(*_compile_args(ws, photo, card))
    assert code == 2 and out["status"] == "blocked_consent"


def test_compile_blocks_unconsented_scene_ref(tmp_path, png_factory):
    ws = tmp_path / "ws"
    (ws / "input").mkdir(parents=True)
    me = ws / "input" / "me.png"
    me.write_bytes(png_factory(600, 600))
    scene = ws / "input" / "scene.png"
    scene.write_bytes(png_factory(640, 480))
    card = temp_wukong(ws)
    assert consent(ws, me)[0] == 0
    code, out = cli(*_compile_args(ws, me, card), "--scene-ref", scene)
    assert code == 2 and out["status"] == "blocked_consent"
    assert not (ws / "outputs").exists()
    code, out = cli(*_compile_args(ws, me, card), "--scene-ref", ws / "input" / "gone.png")
    assert code == 2 and out["status"] == "missing_scene_ref"


def test_consented_scene_ref_compiles_and_generates(tmp_path, png_factory):
    ws = tmp_path / "ws"
    (ws / "input").mkdir(parents=True)
    me = ws / "input" / "me.png"
    me.write_bytes(png_factory(600, 600))
    scene = ws / "input" / "scene.png"
    scene.write_bytes(png_factory(640, 480))
    card = temp_wukong(ws)
    assert consent(ws, me, scene)[0] == 0
    code, out = cli(*_compile_args(ws, me, card), "--scene-ref", scene)
    assert code == 0, out
    code, gen = cli("generate-exec", "--request", out["request_path"], "--workspace", ws,
                    "--authorized-count", "1", "--codex", FAKE, env=fake_env(tmp_path, "ok"))
    assert code == 0, gen


def _edit_request(request, **changes):
    data = json.loads(request.read_text(encoding="utf-8"))
    data.update(changes)
    request.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def _gen(ws, request, tmp_path):
    return cli("generate-exec", "--request", request, "--workspace", ws, "--authorized-count", "1",
               "--codex", FAKE, env=fake_env(tmp_path, "ok"))


def test_generate_rejects_prompt_edited_after_compile(tmp_path, png_factory):
    ws, request = compiled(tmp_path, png_factory)
    data = json.loads(request.read_text(encoding="utf-8"))
    _edit_request(request, prompt=data["prompt"] + " 加一句")
    code, out = _gen(ws, request, tmp_path)
    assert code == 2 and out["status"] == "request_tampered", out
    assert not (request.parent / "generation-count").exists()


def test_generate_rescans_names_after_resealed_edit(tmp_path, png_factory):
    sys.path.insert(0, str(CLI.parent))
    from coshoot import compiler
    ws, request = compiled(tmp_path, png_factory)
    data = json.loads(request.read_text(encoding="utf-8"))
    prompt = data["prompt"] + " 六小龄童"
    _edit_request(request, prompt=prompt,
                  sha256=compiler._body_sha256(prompt, data["referenced_image_paths"]))
    code, out = _gen(ws, request, tmp_path)
    assert code == 2 and out["status"] == "blocked_name", out
    assert not (request.parent / "generation-count").exists()


def test_generate_rejects_relative_coshoot_ref(tmp_path, png_factory):
    ws, request = compiled(tmp_path, png_factory)
    data = json.loads(request.read_text(encoding="utf-8"))
    refs = list(data["referenced_image_paths"])
    refs[0] = "input/me.png"
    _edit_request(request, referenced_image_paths=refs)
    code, out = _gen(ws, request, tmp_path)
    assert code == 2 and out["status"] == "bad_request_ref", out
    assert not (request.parent / "generation-count").exists()


def test_generate_rejects_request_missing_refs(tmp_path, png_factory):
    ws, request = compiled(tmp_path, png_factory)
    data = json.loads(request.read_text(encoding="utf-8"))
    del data["referenced_image_paths"]
    request.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    code, out = _gen(ws, request, tmp_path)
    assert code == 2 and out["status"] == "invalid_request", out
    assert not (request.parent / "generation-count").exists()


def _card_with_photo_as_sheet(ws, variant_id):
    """Temp card whose head sheet points at a user photo outside characters/ (hash is correct)."""
    card_path = temp_wukong(ws)
    photo = ws / "input" / "me.png"
    photo.parent.mkdir(parents=True, exist_ok=True)
    photo.write_bytes(b"user-photo")
    card = json.loads(card_path.read_text(encoding="utf-8"))
    for variant in card["variants"]:
        if variant["variant_id"] == variant_id:
            variant["sheets"]["head"] = {"url": "input/me.png", "bytes": 10,
                                         "sha256": hashlib.sha256(b"user-photo").hexdigest()}
    card_path.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    return card_path


def test_compile_refuses_sheet_outside_characters(tmp_path, png_factory):
    ws = tmp_path / "ws"
    card = _card_with_photo_as_sheet(ws, "mhw")
    photo = ws / "input" / "me.png"
    real = ws / "input" / "real.png"
    real.write_bytes(png_factory(600, 600))
    assert consent(ws, real)[0] == 0
    code, out = cli("compile", "--scene", FIX / "scene-shuiliandong.json", "--character", card,
                    "--photo", real, "--workspace", ws)
    assert code == 2 and out["status"] == "bad_sheet_ref", out
    assert not (ws / "outputs").exists()
    assert photo.is_file()


def test_compile_sheet_refuses_ref_variant_outside_characters(tmp_path):
    ws = tmp_path / "ws"
    card = _card_with_photo_as_sheet(ws, "qujing")
    code, out = cli("compile-sheet", "--character", card, "--variant", "mhw", "--sheet", "head",
                    "--ref-variant", "qujing", "--workspace", ws)
    assert code == 2 and out["status"] == "bad_sheet_ref", out
    assert not (ws / "outputs").exists()


def test_generate_refused_on_delivered_run(tmp_path, png_factory):
    ws, request = compiled(tmp_path, png_factory)
    env = fake_env(tmp_path, "ok")
    args = ["--request", request, "--workspace", ws, "--authorized-count", "2", "--codex", FAKE]
    code, out = cli("generate-exec", *args, env=env)
    assert code == 0, out
    assert cli("verify", "--request", request, "--log", request.parent / "exec.jsonl")[0] == 0
    assert cli("frame-check", out["image_path"], "--framing", "waist_up", "--out", request.parent / "frame.json")[0] == 0
    code, side = cli("deliver", "--image", out["image_path"], "--request", request, "--workspace", ws, "--audit", request.parent / "audit.json", "--frame", request.parent / "frame.json")
    assert code == 0, side
    code, again = cli("generate-exec", *args, env=env)
    assert code == 2 and again["status"] == "already_delivered", again
    assert (request.parent / "generation-count").read_text() == "1"


def test_consent_appends_and_reset_replaces(tmp_path, png_factory):
    ws = tmp_path / "ws"
    (ws / "input").mkdir(parents=True)
    a, b = ws / "input" / "a.png", ws / "input" / "b.png"
    a.write_bytes(png_factory(600, 600))
    b.write_bytes(png_factory(601, 600))
    assert consent(ws, a)[0] == 0
    code, out = consent(ws, b)
    assert code == 0 and len(out["photos"]) == 2
    code, out = consent(ws, a)  # same bytes again: no duplicate
    assert len(out["photos"]) == 2
    code, out = cli("consent", "--workspace", ws, "--subject", "--adult", "--self-or-consented",
                    "--photo", b, "--reset")
    assert [p["path"] for p in out["photos"]] == [str(b.resolve())]


def test_consent_preserves_private_original_after_source_deleted(tmp_path, png_factory):
    source = tmp_path / 'upload.png'
    raw = png_factory(600, 700)
    source.write_bytes(raw)
    ws = tmp_path / 'ws'
    code, out = consent(ws, source)
    assert code == 0, out
    record = out['photos'][0]
    archive = ws / record['archived_path']
    assert archive.parent == ws / 'input' / 'originals'
    assert record['dimensions'] == [600, 700]
    assert record['byte_size'] == len(raw)
    source.unlink()
    assert archive.read_bytes() == raw
    from coshoot.label import check_photo_consent
    check_photo_consent(out, [archive])


def test_consent_archive_refuses_symlinked_dir_outside_workspace(tmp_path, png_factory):
    source = tmp_path / 'upload.png'
    source.write_bytes(png_factory(600, 700))
    ws, outside = tmp_path / 'ws', tmp_path / 'shared'
    ws.mkdir()
    outside.mkdir()
    (ws / 'input').symlink_to(outside, target_is_directory=True)
    code, out = consent(ws, source)
    assert code == 2 and out['status'] == 'photo_archive_outside_workspace'
    assert list(outside.iterdir()) == []
    assert not (ws / 'consent.json').exists()


def test_consent_archive_conflict_does_not_overwrite_or_reconfirm(tmp_path, png_factory):
    source = tmp_path / 'upload.png'
    source.write_bytes(png_factory(600, 700))
    ws = tmp_path / 'ws'
    code, out = consent(ws, source)
    assert code == 0
    archive = ws / out['photos'][0]['archived_path']
    archive.write_bytes(b'corrupted')
    before = (ws / 'consent.json').read_bytes()
    code, out = consent(ws, source)
    assert code == 2 and out['status'] == 'photo_archive_changed'
    assert archive.read_bytes() == b'corrupted'
    assert (ws / 'consent.json').read_bytes() == before


def test_consent_backfills_legacy_record_without_duplicate(tmp_path, png_factory):
    source = tmp_path / 'upload.png'
    source.write_bytes(png_factory(600, 700))
    ws = tmp_path / 'ws'
    assert consent(ws, source)[0] == 0
    f = ws / 'consent.json'
    old = json.loads(f.read_text())
    old['photos'] = [{k: v for k, v in old['photos'][0].items() if k in ('path', 'sha256')}]
    f.write_text(json.dumps(old))
    code, out = consent(ws, source)
    assert code == 0 and len(out['photos']) == 1
    assert (ws / out['photos'][0]['archived_path']).read_bytes() == source.read_bytes()
