import json
from pathlib import Path

import pytest

from test_cli import FIX, cli, consent, temp_wukong
from test_sets import vary_poses
from coshoot import sets


def set_workspace(tmp_path, png_factory):
    ws = tmp_path / "ws"
    (ws / "input").mkdir(parents=True)
    photo = ws / "input" / "me.png"
    photo.write_bytes(png_factory(600, 600))
    card_path = temp_wukong(ws)
    assert consent(ws, photo)[0] == 0
    scene = json.loads((FIX / "scene-shuiliandong.json").read_text(encoding="utf-8"))
    shots = [json.loads(json.dumps(dict(scene, id=f"hgs-{role}"))) for role in sets.ROLES]
    shots[sets.ROLES.index("shy")]["characters"][0].update(character_presence="cover", cover_level="face")
    vary_poses(shots)
    set_card = ws / "cards" / "set-hgs1.json"
    set_card.parent.mkdir(parents=True)
    set_card.write_text(json.dumps({"schema_version": "1", "set_id": "hgs1", "status": "user_confirmed",
                                    "shots": shots}, ensure_ascii=False), encoding="utf-8")
    return ws, photo, card_path, set_card


def test_compile_shot_and_record_native_path(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    base = ["--set-card", set_card, "--character", card, "--photo", photo, "--workspace", ws]
    code, out = cli("compile-shot", "--index", "2", *base)
    assert code == 2 and out["status"] == "chain_not_ready"
    code, out = cli("compile-shot", "--index", "1", *base)
    assert code == 0 and out["role"] == "cover", out
    gen = tmp_path / "gen.png"
    gen.write_bytes(png_factory())
    code, ledger = cli("set-record", "--set-card", set_card, "--workspace", ws, "--index", "1",
                       "--status", "generated", "--image", gen)
    assert code == 0 and ledger["chain_image"].endswith("outputs/sets/hgs1/chain.png")
    code, out = cli("compile-shot", "--index", "2", *base)
    assert code == 0 and out["referenced_image_paths"][-1] == ledger["chain_image"]
    req = json.loads(Path(out["request_path"]).read_text(encoding="utf-8"))
    assert req["set"] == {"set_id": "hgs1", "index": 2, "role": "wide"}


def test_native_first_refused_cancels_rest(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    base = ["--set-card", set_card, "--character", card, "--photo", photo, "--workspace", ws]
    assert cli("compile-shot", "--index", "1", *base)[0] == 0
    cli("set-record", "--set-card", set_card, "--workspace", ws, "--index", "1", "--status", "rejected")
    code, status = cli("set-status", "--set-card", set_card, "--workspace", ws)
    assert [i["status"] for i in status["items"]] == ["rejected"] + ["cancelled"] * 4
    code, out = cli("compile-shot", "--index", "3", *base)
    assert code == 2 and out["status"] == "set_cancelled"


def test_native_path_compiles_and_records_all_five_shots(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    base = ["--set-card", set_card, "--character", card, "--photo", photo, "--workspace", ws]
    generated = tmp_path / "generated.png"
    generated.write_bytes(png_factory())
    for index, role in enumerate(sets.ROLES, start=1):
        code, request = cli("compile-shot", "--index", index, *base)
        assert code == 0 and request["role"] == role, request
        code, ledger = cli("set-record", "--set-card", set_card, "--workspace", ws,
                           "--index", index, "--status", "generated", "--image", generated)
        assert code == 0 and ledger["items"][index - 1]["status"] == "generated", ledger
    assert len(ledger["items"]) == 5


from test_cli import FAKE, fake_env  # noqa: E402


def gen_args(set_card, card, photo, ws, count="5"):
    return ["generate-set", "--set-card", set_card, "--character", card, "--photo", photo,
            "--workspace", ws, "--authorized-count", count, "--codex", FAKE]


def test_generate_set_needs_five_credits(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    code, out = cli(*gen_args(set_card, card, photo, ws, "4"), env=fake_env(tmp_path, "ok"))
    assert code == 2 and out["status"] == "blocked_quota"
    assert not (ws / "outputs" / "sets" / "hgs1" / "set.json").exists()


def test_generate_set_happy_path_chains_image_one(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    code, out = cli(*gen_args(set_card, card, photo, ws), env=fake_env(tmp_path, "ok"))
    assert code == 0 and out["status"] == "set_generated" and out["quota_used"] == 5, out
    chain = str((ws / "outputs" / "sets" / "hgs1" / "chain.png").resolve())
    for r in out["results"][1:]:
        req = json.loads(Path(r["request_path"]).read_text(encoding="utf-8"))
        assert req["referenced_image_paths"][-1] == chain
    shy = json.loads(Path(out["results"][3]["request_path"]).read_text(encoding="utf-8"))
    assert shy["set"]["role"] == "shy" and "身体藏在本张写明的遮挡物" in shy["prompt"]
    code, again = cli(*gen_args(set_card, card, photo, ws), env=fake_env(tmp_path, "ok"))
    assert code == 2 and again["status"] == "set_already_started"
    # D34: without face models the likeness check degrades and never stops the set.
    assert out["results"][0]["likeness"]["status"] == "unavailable"
    assert all("likeness" not in r for r in out["results"][1:])


def _run_in_process(monkeypatch, capsys, tmp_path, argv):
    import cli as cli_module
    for key, value in fake_env(tmp_path, "ok").items():
        monkeypatch.setenv(key, value)
    code = cli_module.main([str(a) for a in argv])
    return code, json.loads(capsys.readouterr().out)


def test_generate_set_low_likeness_pauses_after_cover_then_resumes(tmp_path, png_factory, monkeypatch, capsys):
    # D34: a drifted cover face must not become the reference for shots 2-5 before the user compares it.
    import cli as cli_module
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    calls = []

    def low(photos, image, workspace):
        calls.append(image)
        return {"status": "low", "score": 0.7, "threshold": 0.83, "message": "low"}

    monkeypatch.setattr(cli_module.likeness, "score", low)
    code, out = _run_in_process(monkeypatch, capsys, tmp_path, gen_args(set_card, card, photo, ws))
    assert code == 2 and out["status"] == "set_paused_likeness" and out["quota_used"] == 1, out
    assert [r["status"] for r in out["results"]] == ["generated"] + ["pending"] * 4
    assert len(calls) == 1
    ledger = json.loads(_ledger_path(ws).read_text(encoding="utf-8"))
    assert [i["status"] for i in ledger["items"]] == ["generated"] + ["pending"] * 4
    code, out = _run_in_process(monkeypatch, capsys, tmp_path,
                                [*gen_args(set_card, card, photo, ws, "4"), "--resume"])
    assert code == 0 and out["status"] == "set_generated" and out["quota_used"] == 4, out
    assert len(calls) == 1  # the user already compared the cover; resume does not re-check it


def test_resume_after_hand_recorded_cover_still_compares_face(tmp_path, png_factory, monkeypatch, capsys):
    # codex-review 06eb9c9: unknown cover -> set-record generated -> --resume skipped the comparison.
    import cli as cli_module
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    calls = []
    monkeypatch.setattr(cli_module.likeness, "score", lambda photos, image, workspace: calls.append(image) or
                        {"status": "low", "score": 0.7, "threshold": 0.83, "message": "low"})
    for key, value in fake_env(tmp_path, "timeout").items():
        monkeypatch.setenv(key, value)
    assert cli_module.main([str(a) for a in gen_args(set_card, card, photo, ws)] + ["--timeout", "1"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "set_paused_unknown"
    gen = tmp_path / "gen.png"
    gen.write_bytes(png_factory())
    assert cli("set-record", "--set-card", set_card, "--workspace", ws, "--index", "1",
               "--status", "generated", "--image", gen)[0] == 0
    resume = [*gen_args(set_card, card, photo, ws, "4"), "--resume"]
    code, out = _run_in_process(monkeypatch, capsys, tmp_path, resume)
    assert code == 2 and out["status"] == "set_paused_likeness" and out["quota_used"] == 0, out
    assert len(calls) == 1 and _items(ws) == ["generated"] + ["pending"] * 4
    code, out = _run_in_process(monkeypatch, capsys, tmp_path, resume)
    assert code == 0 and out["status"] == "set_generated" and out["quota_used"] == 4, out
    assert len(calls) == 1


def test_generate_set_skips_likeness_for_faceless_cover(tmp_path, png_factory, monkeypatch, capsys):
    import cli as cli_module
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    doc = json.loads(set_card.read_text(encoding="utf-8"))
    doc["shots"][0]["user"].update(action="背对镜头走向宫门", presence="back")
    set_card.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cli_module.likeness, "score", lambda *a: pytest.fail("faceless cover was scored"))
    code, out = _run_in_process(monkeypatch, capsys, tmp_path, gen_args(set_card, card, photo, ws))
    assert code == 0 and out["status"] == "set_generated", out


def test_generate_set_first_refused_cancels_rest(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    code, out = cli(*gen_args(set_card, card, photo, ws), env=fake_env(tmp_path, "refuse"))
    assert code == 2 and out["status"] == "set_partial" and out["quota_used"] == 1
    assert [r["status"] for r in out["results"]] == [
        "blocked_platform_input", "cancelled", "cancelled", "cancelled", "cancelled"]
    run_dirs = [p for p in (ws / "outputs").iterdir() if p.name != "sets"]
    assert len(run_dirs) == 1  # later images were never compiled or submitted


def test_generate_set_chain_registration_error_keeps_honest_result(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    # A directory named chain.png makes the byte copy fail after image 1 was generated.
    (ws / "outputs" / "sets" / "hgs1" / "chain.png").mkdir(parents=True)
    code, out = cli(*gen_args(set_card, card, photo, ws), env=fake_env(tmp_path, "ok"))
    assert code == 2 and out["status"] == "set_partial" and out["quota_used"] == 1, out
    assert out["results"][0]["status"] not in ("generated", "cancelled")
    assert [r["status"] for r in out["results"][1:]] == ["cancelled"] * 4
    ledger = json.loads((ws / "outputs" / "sets" / "hgs1" / "set.json").read_text(encoding="utf-8"))
    assert [i["status"] for i in ledger["items"]] == ["failed"] + ["cancelled"] * 4


def _ledger_path(ws):
    return ws / "outputs" / "sets" / "hgs1" / "set.json"


def _registered_set(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    base = ["--set-card", set_card, "--character", card, "--photo", photo, "--workspace", ws]
    assert cli("compile-shot", "--index", "1", *base)[0] == 0
    gen = tmp_path / "gen.png"
    gen.write_bytes(png_factory())
    code, ledger = cli("set-record", "--set-card", set_card, "--workspace", ws, "--index", "1",
                       "--status", "generated", "--image", gen)
    assert code == 0 and ledger["chain_sha256"]
    return ws, photo, card, set_card, base


def test_tampered_ledger_chain_path_is_rejected(tmp_path, png_factory):
    ws, photo, card, set_card, base = _registered_set(tmp_path, png_factory)
    outside = tmp_path / "unconsented.png"
    outside.write_bytes(png_factory(300, 300))
    ledger = json.loads(_ledger_path(ws).read_text(encoding="utf-8"))
    ledger["chain_image"] = str(outside)
    _ledger_path(ws).write_text(json.dumps(ledger), encoding="utf-8")
    code, out = cli("compile-shot", "--index", "2", *base)
    assert code == 2 and out["status"] == "chain_tampered", out
    for req in (ws / "outputs").glob("*/request.json"):
        assert str(outside) not in req.read_text(encoding="utf-8")


def test_replaced_chain_bytes_are_rejected(tmp_path, png_factory):
    ws, photo, card, set_card, base = _registered_set(tmp_path, png_factory)
    (ws / "outputs" / "sets" / "hgs1" / "chain.png").write_bytes(png_factory(300, 300))
    code, out = cli("compile-shot", "--index", "2", *base)
    assert code == 2 and out["status"] == "chain_tampered", out


def test_ledger_set_id_mismatch_is_rejected(tmp_path, png_factory):
    ws, photo, card, set_card, base = _registered_set(tmp_path, png_factory)
    ledger = json.loads(_ledger_path(ws).read_text(encoding="utf-8"))
    ledger["set_id"] = "other"
    _ledger_path(ws).write_text(json.dumps(ledger), encoding="utf-8")
    code, out = cli("set-status", "--set-card", set_card, "--workspace", ws)
    assert code == 2 and out["status"] == "ledger_mismatch", out


def _run_dirs(ws):
    return sorted(p.name for p in (ws / "outputs").iterdir() if p.name != "sets")


def test_lost_ledger_with_chain_blocks_compile_shot_and_generate_set(tmp_path, png_factory):
    ws, photo, card, set_card, base = _registered_set(tmp_path, png_factory)
    _ledger_path(ws).unlink()
    before = _run_dirs(ws)
    for index in ("1", "2"):
        code, out = cli("compile-shot", "--index", index, *base)
        assert code == 2 and out["status"] == "ledger_missing", out
    code, out = cli(*gen_args(set_card, card, photo, ws), env=fake_env(tmp_path, "ok"))
    assert code == 2 and out["status"] == "ledger_missing", out
    # No new run, no recreated pending ledger, history left in place.
    assert _run_dirs(ws) == before
    assert not _ledger_path(ws).exists()
    assert (ws / "outputs" / "sets" / "hgs1" / "chain.png").is_file()


def test_lost_ledger_with_only_a_claimed_request_blocks_restart(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    base = ["--set-card", set_card, "--character", card, "--photo", photo, "--workspace", ws]
    assert cli("compile-shot", "--index", "1", *base)[0] == 0
    _ledger_path(ws).unlink()
    before = _run_dirs(ws)
    code, out = cli("compile-shot", "--index", "1", *base)
    assert code == 2 and out["status"] == "ledger_missing", out
    code, out = cli("set-status", "--set-card", set_card, "--workspace", ws)
    assert code == 2 and out["status"] == "ledger_missing", out
    assert _run_dirs(ws) == before


def test_sheet_request_cannot_reference_set_chain(tmp_path, png_factory):
    from test_cli_sheets import draft_card
    ws = tmp_path / "ws"
    card = draft_card(ws)
    code, out = cli("compile-sheet", "--character", card, "--variant", "mhw", "--sheet", "head",
                    "--workspace", ws)
    assert code == 0, out
    request = Path(out["request_path"])
    chain = ws / "outputs" / "sets" / "hgs1" / "chain.png"
    chain.parent.mkdir(parents=True)
    chain.write_bytes(png_factory(8, 8))
    data = json.loads(request.read_text(encoding="utf-8"))
    data["referenced_image_paths"] = [str(chain)]
    request.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    code, out = cli("generate-exec", "--request", request, "--workspace", ws,
                    "--authorized-count", "1", "--codex", FAKE)
    assert code == 2 and out["status"] == "bad_sheet_ref", out


def test_generate_exec_blocks_unconsented_file_under_sets(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    base = ["--set-card", set_card, "--character", card, "--photo", photo, "--workspace", ws]
    code, out = cli("compile-shot", "--index", "1", *base)
    assert code == 0, out
    request = Path(out["request_path"])
    other = ws / "outputs" / "sets" / "hgs1" / "other.png"
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_bytes(png_factory(300, 300))
    data = json.loads(request.read_text(encoding="utf-8"))
    data["referenced_image_paths"].append(str(other))
    request.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    code, out = cli("generate-exec", "--request", request, "--workspace", ws,
                    "--authorized-count", "1", "--codex", FAKE, env=fake_env(tmp_path, "ok"))
    assert code == 2 and out["status"] == "blocked_consent", out


def test_set_record_missing_image_is_card_error(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    base = ["--set-card", set_card, "--character", card, "--photo", photo, "--workspace", ws]
    assert cli("compile-shot", "--index", "1", *base)[0] == 0
    code, out = cli("set-record", "--set-card", set_card, "--workspace", ws, "--index", "1",
                    "--status", "generated", "--image", tmp_path / "nope.png")
    assert code == 2 and out["status"] == "missing_image", out


def test_generate_set_actor_name_in_first_prompt_spends_nothing(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    data = json.loads(set_card.read_text(encoding="utf-8"))
    data["shots"][0]["setting"] = "木" * 800 + "六小龄童"
    set_card.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    code, out = cli(*gen_args(set_card, card, photo, ws), env=fake_env(tmp_path, "ok"))
    assert code == 2 and out["status"] == "blocked_name", out
    assert not (ws / "outputs").exists() or list((ws / "outputs").iterdir()) == []


def _break_shot(set_card, index, **member):
    data = json.loads(set_card.read_text(encoding="utf-8"))
    shot = data["shots"][index - 1]
    if member:
        shot["characters"][0].update(member)
    else:
        shot["setting"] = "木" * 800 + "六小龄童"
    set_card.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_generate_set_bad_later_shot_spends_nothing(tmp_path, png_factory):
    # A forbidden name in image 3 must block before image 1 is claimed or submitted.
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    _break_shot(set_card, 3)
    code, out = cli(*gen_args(set_card, card, photo, ws), env=fake_env(tmp_path, "ok"))
    assert code == 2 and out["status"] == "blocked_name", out
    assert not (ws / "outputs").exists() or list((ws / "outputs").iterdir()) == []
    # Once fixed, the same set can still start: nothing was claimed.
    data = json.loads(set_card.read_text(encoding="utf-8"))
    data["shots"][2]["setting"] = data["shots"][0]["setting"]
    set_card.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    code, out = cli(*gen_args(set_card, card, photo, ws), env=fake_env(tmp_path, "ok"))
    assert code == 0 and out["status"] == "set_generated", out


def test_set_card_cover_without_level_is_caught_before_any_claim(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    data = json.loads(set_card.read_text(encoding="utf-8"))
    del data["shots"][3]["characters"][0]["cover_level"]  # the shy shot
    set_card.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    code, out = cli(*gen_args(set_card, card, photo, ws), env=fake_env(tmp_path, "ok"))
    assert code == 2 and out["status"] == "cover_level_required", out
    assert not _ledger_path(ws).exists()


def test_compile_shot_one_prechecks_whole_set(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    _break_shot(set_card, 4)
    base = ["--set-card", set_card, "--character", card, "--photo", photo, "--workspace", ws]
    code, out = cli("compile-shot", "--index", "1", *base)
    assert code == 2 and out["status"] == "blocked_name", out
    assert not _ledger_path(ws).exists()


def test_set_record_still_works_after_presence_retired(tmp_path, png_factory):
    # An old set already claimed image 1; retiring side_profile later must not strand that claim.
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    base = ["--set-card", set_card, "--character", card, "--photo", photo, "--workspace", ws]
    assert cli("compile-shot", "--index", "1", *base)[0] == 0
    _break_shot(set_card, 2, character_presence="side_profile")
    code, ledger = cli("set-record", "--set-card", set_card, "--workspace", ws, "--index", "1",
                       "--status", "rejected")
    assert code == 0 and ledger["items"][0]["status"] == "rejected", ledger
    code, status = cli("set-status", "--set-card", set_card, "--workspace", ws)
    assert code == 0, status
    code, out = cli("compile-shot", "--index", "2", *base)
    assert code == 2 and out["status"] == "presence_retired", out


def test_compile_later_shot_prechecks_the_rest(tmp_path, png_factory):
    # Card edited after image 1: compiling image 3 must not claim it while image 4 can no longer compile.
    ws, photo, card, set_card, base = _registered_set(tmp_path, png_factory)
    _break_shot(set_card, 4)
    code, out = cli("compile-shot", "--index", "3", *base)
    assert code == 2 and out["status"] == "blocked_name", out
    ledger = json.loads(_ledger_path(ws).read_text(encoding="utf-8"))
    assert ledger["items"][2]["status"] == "pending"


def test_long_set_prompts_compile_and_generate_with_fake_backend(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    data = json.loads(set_card.read_text(encoding="utf-8"))
    for shot in data["shots"]:
        shot["setting"] = "木" * 800 + "完整场景尾部" + shot['setting']
    set_card.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    code, out = cli(*gen_args(set_card, card, photo, ws), env=fake_env(tmp_path, "ok"))
    assert code == 0 and out["status"] == "set_generated" and out["quota_used"] == 5, out
    for result in out["results"]:
        request = json.loads(Path(result["request_path"]).read_text(encoding="utf-8"))
        assert "木" * 800 + "完整场景尾部" in request["prompt"]


def test_long_native_shot_compiles_without_spending_generation_quota(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    data = json.loads(set_card.read_text(encoding="utf-8"))
    data["shots"][3]["setting"] = "木" * 800 + "完整场景尾部"
    set_card.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    base = ["--set-card", set_card, "--character", card, "--photo", photo, "--workspace", ws]
    code, out = cli("compile-shot", "--index", "1", *base)
    assert code == 0 and out["status"] == "compiled", out
    assert not (Path(out["request_path"]).parent / "generation-count").exists()


def test_old_four_shot_card_gets_hint_on_bookkeeping_too(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    data = json.loads(set_card.read_text(encoding="utf-8"))
    del data["shots"][3]
    set_card.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    code, out = cli("set-status", "--set-card", set_card, "--workspace", ws)
    assert code == 2 and out["status"] == "set_size_changed", out
    code, out = cli(*gen_args(set_card, card, photo, ws), env=fake_env(tmp_path, "ok"))
    assert code == 2 and out["status"] == "set_size_changed", out


def test_docs_authorize_a_full_set(skill_root):
    # Stage-4 audit: SKILL.md still said --authorized-count 4, which blocks a five-shot set.
    import re
    lines = [l for l in (skill_root / "SKILL.md").read_text(encoding="utf-8").splitlines() if "generate-set" in l]
    counts = {int(n) for l in lines for n in re.findall(r"--authorized-count (\d+)", l)}
    assert counts == {sets.SET_SIZE}, counts


def _items(ws):
    return [i["status"] for i in json.loads(_ledger_path(ws).read_text(encoding="utf-8"))["items"]]


def test_generate_set_pauses_on_unknown_later_result(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    code, out = cli(*gen_args(set_card, card, photo, ws), env=fake_env(tmp_path, "crash_after_2"))
    assert code == 2 and out["status"] == "set_paused_unknown" and out["quota_used"] == 3, out
    assert [r["status"] for r in out["results"]] == [
        "generated", "generated", "failed_no_image", "pending", "pending"]
    assert _items(ws) == ["generated", "generated", "claimed", "pending", "pending"]


def test_generate_set_pauses_on_unknown_first_result_without_cancelling(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    code, out = cli(*gen_args(set_card, card, photo, ws) + ["--timeout", "1"],
                    env=fake_env(tmp_path, "timeout"))
    assert code == 2 and out["status"] == "set_paused_unknown" and out["quota_used"] == 1, out
    assert _items(ws) == ["claimed", "pending", "pending", "pending", "pending"]


def test_resume_after_checking_unknown_runs_only_pending(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    cli(*gen_args(set_card, card, photo, ws), env=fake_env(tmp_path, "crash_after_2"))
    code, out = cli(*gen_args(set_card, card, photo, ws, "2") + ["--resume"], env=fake_env(tmp_path, "ok"))
    assert code == 2 and out["status"] == "set_has_unknown", out
    code, _ = cli("set-record", "--set-card", set_card, "--workspace", ws, "--index", "3", "--status", "failed")
    assert code == 0
    code, out = cli(*gen_args(set_card, card, photo, ws, "1") + ["--resume"], env=fake_env(tmp_path, "ok"))
    assert code == 2 and out["status"] == "blocked_quota" and "2" in out["message"]
    code, out = cli(*gen_args(set_card, card, photo, ws, "2") + ["--resume"], env=fake_env(tmp_path, "ok"))
    assert out["quota_used"] == 2 and [r["index"] for r in out["results"]] == [4, 5], out
    assert _items(ws) == ["generated", "generated", "failed", "generated", "generated"]
    code, out = cli(*gen_args(set_card, card, photo, ws, "5") + ["--resume"], env=fake_env(tmp_path, "ok"))
    assert code == 2 and out["status"] == "nothing_to_resume"


def test_consent_follows_photo_bytes_on_resume(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    cli(*gen_args(set_card, card, photo, ws), env=fake_env(tmp_path, "crash_after_2"))
    cli("set-record", "--set-card", set_card, "--workspace", ws, "--index", "3", "--status", "failed")
    photo.write_bytes(png_factory(640, 640))  # same path, different bytes
    code, out = cli(*gen_args(set_card, card, photo, ws, "2") + ["--resume"], env=fake_env(tmp_path, "ok"))
    assert code == 2 and out["status"] == "blocked_consent", out


def test_generate_set_reports_progress_per_shot_on_stderr(tmp_path, png_factory):
    import subprocess
    import sys
    from test_cli import CLI
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    proc = subprocess.run([sys.executable, str(CLI), *map(str, gen_args(set_card, card, photo, ws))],
                          capture_output=True, text=True, env=fake_env(tmp_path, "ok"))
    events = [json.loads(l) for l in proc.stderr.splitlines() if l.startswith('{"event"')]
    assert [(e["index"], e["done"], e["of"]) for e in events] == [(i, i, 5) for i in range(1, 6)]
    assert json.loads(proc.stdout)["status"] == "set_generated"


def _two_set_project(ws, set_card):
    second = json.loads(set_card.read_text(encoding="utf-8"))
    second["set_id"] = "hgs2"
    second_path = set_card.parent / "set-hgs2.json"
    second_path.write_text(json.dumps(second, ensure_ascii=False), encoding="utf-8")
    (ws / "project.json").write_text(json.dumps({
        "schema_version": "1", "project_id": "me-and-wukong", "title": "我和悟空",
        "character": {"name": "孙悟空", "version": "测试"},
        "series": [{"series_id": "s", "title": "两套", "brief": "测试",
                    "sets": [{"set_id": "hgs1", "card": "cards/set-hgs1.json"},
                             {"set_id": "hgs2", "card": "cards/set-hgs2.json"}]}],
        "selection": ["hgs1", "hgs2"]}, ensure_ascii=False), encoding="utf-8")
    return second_path


def test_second_set_waits_for_user_continue(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    second = _two_set_project(ws, set_card)
    code, out = cli("project-continue", "--workspace", ws, "--set-id", "hgs2")
    assert code == 2 and out["status"] == "previous_set_unfinished", out
    code, out = cli(*gen_args(set_card, card, photo, ws), env=fake_env(tmp_path, "ok"))
    assert out["status"] == "set_generated", out
    code, out = cli(*gen_args(second, card, photo, ws), env=fake_env(tmp_path, "ok"))
    assert code == 2 and out["status"] == "blocked_await_continue"
    assert not (ws / "outputs" / "sets" / "hgs2").exists()
    code, out = cli("compile-shot", "--index", "1", "--set-card", second, "--character", card,
                    "--photo", photo, "--workspace", ws)
    assert code == 2 and out["status"] == "blocked_await_continue"
    code, out = cli("project-continue", "--workspace", ws, "--set-id", "hgs2")
    assert code == 0 and out["continued"] == ["hgs2"], out
    code, out = cli(*gen_args(second, card, photo, ws), env=fake_env(tmp_path, "ok"))
    assert out["status"] == "set_generated", out
    code, out = cli("project-continue", "--workspace", ws, "--set-id", "nope")
    assert code == 2


def test_single_set_without_project_needs_no_continue(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    code, out = cli(*gen_args(set_card, card, photo, ws), env=fake_env(tmp_path, "ok"))
    assert out["status"] == "set_generated", out


def test_continue_gate_covers_custom_project_file_name(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    second = _two_set_project(ws, set_card)
    (ws / "project.json").rename(ws / "wukong-project.json")
    assert cli(*gen_args(set_card, card, photo, ws), env=fake_env(tmp_path, "ok"))[1]["status"] == "set_generated"
    code, out = cli(*gen_args(second, card, photo, ws), env=fake_env(tmp_path, "ok"))
    assert code == 2 and out["status"] == "blocked_await_continue", out
    code, out = cli("compile-shot", "--index", "1", "--set-card", second, "--character", card,
                    "--photo", photo, "--workspace", ws)
    assert code == 2 and out["status"] == "blocked_await_continue", out
    code, out = cli("project-continue", "--workspace", ws, "--set-id", "hgs2", "--project", "wukong-project.json")
    assert code == 0, out
    assert cli(*gen_args(second, card, photo, ws), env=fake_env(tmp_path, "ok"))[1]["status"] == "set_generated"


def test_project_index_must_be_json_outside_outputs(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    _two_set_project(ws, set_card)
    body = (ws / "project.json").read_text(encoding="utf-8")
    (ws / "project.json").unlink()
    (ws / "outputs").mkdir(exist_ok=True)
    for name in ("wukong-project", "outputs/wukong-project.json"):
        (ws / name).write_text(body, encoding="utf-8")
        for cmd in (["project-status", "--workspace", ws, "--project", name],
                    ["project-continue", "--workspace", ws, "--set-id", "hgs2", "--project", name]):
            code, out = cli(*cmd)
            assert code == 2 and out["status"] == "invalid_project", (name, out)


def test_continue_gate_sees_upper_case_json_index(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    second = _two_set_project(ws, set_card)
    assert cli(*gen_args(set_card, card, photo, ws), env=fake_env(tmp_path, "ok"))[1]["status"] == "set_generated"
    (ws / "project.json").rename(ws / "project.JSON")
    code, out = cli(*gen_args(second, card, photo, ws), env=fake_env(tmp_path, "ok"))
    assert code == 2 and out["status"] == "blocked_await_continue", out


def _with_mood(ws, set_card, png_factory, register=True, where="input/mood.png"):
    mood = ws / where
    mood.parent.mkdir(parents=True, exist_ok=True)
    mood.write_bytes(png_factory(500, 400))
    if register:
        assert consent(ws, mood)[0] == 0
    card = json.loads(set_card.read_text(encoding="utf-8"))
    card["mood_ref"] = str(mood.resolve())
    set_card.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    return mood


def test_mood_ref_needs_consent_and_claims_nothing(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    _with_mood(ws, set_card, png_factory, register=False)
    base = ["--set-card", set_card, "--character", card, "--photo", photo, "--workspace", ws]
    code, out = cli("compile-shot", "--index", "1", *base)
    assert code == 2 and out["status"] == "blocked_consent", out
    code, ledger = cli("set-status", "--set-card", set_card, "--workspace", ws)
    assert ledger["items"][0]["status"] == "pending"


def test_mood_ref_rides_every_shot_and_is_pinned(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    mood = _with_mood(ws, set_card, png_factory)
    base = ["--set-card", set_card, "--character", card, "--photo", photo, "--workspace", ws]
    code, out = cli("compile-shot", "--index", "1", *base)
    assert code == 0 and str(mood.resolve()) in out["referenced_image_paths"], out
    gen = tmp_path / "gen.png"
    gen.write_bytes(png_factory())
    assert cli("set-record", "--set-card", set_card, "--workspace", ws, "--index", "1",
               "--status", "generated", "--image", gen)[0] == 0
    code, out = cli("compile-shot", "--index", "3", *base)
    assert code == 0 and str(mood.resolve()) in out["referenced_image_paths"], out
    _with_mood(ws, set_card, lambda *a: png_factory(300, 300), where="input/other.png")
    code, out = cli("compile-shot", "--index", "2", *base)
    assert code == 2 and out["status"] == "mood_ref_changed", out
    code, ledger = cli("set-status", "--set-card", set_card, "--workspace", ws)
    assert ledger["items"][1]["status"] == "pending"


def test_mood_ref_path_rules(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    base = ["--set-card", set_card, "--character", card, "--photo", photo, "--workspace", ws]
    _with_mood(ws, set_card, png_factory, where="characters/x/mood.png")
    code, out = cli("compile-shot", "--index", "1", *base)
    assert code == 2 and out["status"] == "mood_ref_bad_location", out
    _with_mood(ws, set_card, png_factory, where="outputs/sets/other/chain.png")
    code, out = cli("compile-shot", "--index", "1", *base)
    assert code == 2 and out["status"] == "mood_ref_bad_location", out
    data = json.loads(set_card.read_text(encoding="utf-8"))
    data["mood_ref"] = "input/mood.png"
    set_card.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    code, out = cli("compile-shot", "--index", "1", *base)
    assert code == 2 and out["status"] == "mood_ref_not_absolute", out
    data["mood_ref"] = str(ws / "input" / "gone.png")
    set_card.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    code, out = cli("compile-shot", "--index", "1", *base)
    assert code == 2 and out["status"] == "missing_mood_ref", out


def test_reshoot_with_chain_set_keeps_mood(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    mood = _with_mood(ws, set_card, png_factory)
    base = ["--set-card", set_card, "--character", card, "--photo", photo, "--workspace", ws]
    assert cli("compile-shot", "--index", "1", *base)[0] == 0
    gen = tmp_path / "gen.png"
    gen.write_bytes(png_factory())
    assert cli("set-record", "--set-card", set_card, "--workspace", ws, "--index", "1",
               "--status", "generated", "--image", gen)[0] == 0
    scene = ws / "cards" / "reshoot.json"
    scene.write_text(json.dumps(json.loads(set_card.read_text())["shots"][2]), encoding="utf-8")
    code, out = cli("compile", "--scene", scene, "--character", card, "--photo", photo,
                    "--workspace", ws, "--chain-set", set_card)
    assert code == 0 and str(mood.resolve()) in out["referenced_image_paths"], out


def test_symlinked_sheet_root_cannot_lift_mood_consent(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    mood = _with_mood(ws, set_card, png_factory, where="mood-input/mood.png")
    base = ["--set-card", set_card, "--character", card, "--photo", photo, "--workspace", ws]
    code, out = cli("compile-shot", "--index", "1", *base)
    assert code == 0, out
    assert cli("consent", "--workspace", ws, "--subject", "--adult", "--self-or-consented",
               "--photo", photo, "--reset")[0] == 0
    lib = ws / "cache" / "library"
    if lib.exists():
        lib.rename(ws / "cache" / "library-old")
    lib.parent.mkdir(parents=True, exist_ok=True)
    lib.symlink_to(mood.parent, target_is_directory=True)
    code, gen = cli("generate-exec", "--request", out["request_path"], "--workspace", ws,
                    "--authorized-count", "1", "--codex", FAKE, env=fake_env(tmp_path, "ok"))
    assert code == 2 and gen["status"] == "blocked_consent", gen


def _with_pet(ws, set_card, png_factory, register=True, where="input/cat.png", shots=(1, 3)):
    pet = ws / where
    pet.parent.mkdir(parents=True, exist_ok=True)
    pet.write_bytes(png_factory(400, 500))
    if register:
        assert consent(ws, pet)[0] == 0
    card = json.loads(set_card.read_text(encoding="utf-8"))
    card["pet"] = {"ref": str(pet.resolve()), "kind": "猫"}
    for i in shots:
        card["shots"][i - 1]["pet"] = "蹲在主角脚边"
    set_card.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    return pet


def _record_cover(tmp_path, ws, set_card, png_factory):
    gen = tmp_path / "gen.png"
    gen.write_bytes(png_factory())
    assert cli("set-record", "--set-card", set_card, "--workspace", ws, "--index", "1",
               "--status", "generated", "--image", gen)[0] == 0


def test_pet_needs_consent_and_path_rules(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    base = ["--set-card", set_card, "--character", card, "--photo", photo, "--workspace", ws]
    _with_pet(ws, set_card, png_factory, register=False)
    code, out = cli("compile-shot", "--index", "1", *base)
    assert code == 2 and out["status"] == "blocked_consent", out
    code, ledger = cli("set-status", "--set-card", set_card, "--workspace", ws)
    assert ledger["items"][0]["status"] == "pending"
    _with_pet(ws, set_card, png_factory, where="characters/x/cat.png")
    code, out = cli("compile-shot", "--index", "1", *base)
    assert code == 2 and out["status"] == "pet_ref_bad_location", out
    data = json.loads(set_card.read_text(encoding="utf-8"))
    data["pet"]["ref"] = "input/cat.png"
    set_card.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    code, out = cli("compile-shot", "--index", "1", *base)
    assert code == 2 and out["status"] == "pet_ref_not_absolute", out
    data["pet"]["ref"] = str(ws / "input" / "gone.png")
    set_card.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    code, out = cli("compile-shot", "--index", "1", *base)
    assert code == 2 and out["status"] == "missing_pet_ref", out


def test_pet_rides_only_its_shots_and_is_pinned(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    pet = str(_with_pet(ws, set_card, png_factory).resolve())
    base = ["--set-card", set_card, "--character", card, "--photo", photo, "--workspace", ws]
    code, out = cli("compile-shot", "--index", "1", *base)
    assert code == 0 and pet in out["referenced_image_paths"], out
    _record_cover(tmp_path, ws, set_card, png_factory)
    code, out = cli("compile-shot", "--index", "3", *base)
    assert code == 0 and pet in out["referenced_image_paths"], out
    code, out = cli("compile-shot", "--index", "4", *base)
    assert code == 0 and pet not in out["referenced_image_paths"], out
    _with_pet(ws, set_card, lambda *a: png_factory(300, 300), where="input/other.png")
    code, out = cli("compile-shot", "--index", "2", *base)
    assert code == 2 and out["status"] == "pet_ref_changed", out
    code, ledger = cli("set-status", "--set-card", set_card, "--workspace", ws)
    assert ledger["items"][1]["status"] == "pending"


def test_pet_added_mid_set_is_refused(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    base = ["--set-card", set_card, "--character", card, "--photo", photo, "--workspace", ws]
    assert cli("compile-shot", "--index", "1", *base)[0] == 0
    _record_cover(tmp_path, ws, set_card, png_factory)
    _with_pet(ws, set_card, png_factory)
    code, out = cli("compile-shot", "--index", "2", *base)
    assert code == 2 and out["status"] == "pet_ref_changed", out


def test_precheck_catches_pet_shot_without_set_pet(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    data = json.loads(set_card.read_text(encoding="utf-8"))
    data["shots"][2]["pet"] = "蹲在主角脚边"
    set_card.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    code, out = cli("compile-shot", "--index", "1", "--set-card", set_card, "--character", card,
                    "--photo", photo, "--workspace", ws)
    assert code == 2 and out["status"] == "pet_without_ref", out
    code, ledger = cli("set-status", "--set-card", set_card, "--workspace", ws)
    assert ledger["items"][0]["status"] == "pending"


def test_reshoot_with_chain_set_keeps_pet(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    pet = str(_with_pet(ws, set_card, png_factory).resolve())
    base = ["--set-card", set_card, "--character", card, "--photo", photo, "--workspace", ws]
    assert cli("compile-shot", "--index", "1", *base)[0] == 0
    _record_cover(tmp_path, ws, set_card, png_factory)
    scene = ws / "cards" / "reshoot.json"
    scene.write_text(json.dumps(json.loads(set_card.read_text())["shots"][2]), encoding="utf-8")
    code, out = cli("compile", "--scene", scene, "--character", card, "--photo", photo,
                    "--workspace", ws, "--chain-set", set_card)
    assert code == 0 and pet in out["referenced_image_paths"], out


def test_pet_look_rides_into_prompt_and_is_capped(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    _with_pet(ws, set_card, png_factory)
    data = json.loads(set_card.read_text(encoding="utf-8"))
    base = ["--set-card", set_card, "--character", card, "--photo", photo, "--workspace", ws]
    data["pet"]["look"] = "长" * 61
    set_card.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    code, out = cli("compile-shot", "--index", "1", *base)
    assert code == 2 and "look" in json.dumps(out, ensure_ascii=False), out
    data["pet"]["look"] = "英短金渐层，圆脸大眼"
    set_card.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    code, out = cli("compile-shot", "--index", "1", *base)
    assert code == 0, out
    assert "它是英短金渐层，圆脸大眼" in json.loads(Path(out["request_path"]).read_text(encoding="utf-8"))["prompt"]


def _daily_set(ws, set_card, png_factory, skip=None):
    _with_pet(ws, set_card, png_factory, shots=[i for i in range(1, 6) if i != skip])
    data = json.loads(set_card.read_text(encoding="utf-8"))
    for shot in data["shots"]:
        shot.update(play_mode="pet_daily", characters=[])
    set_card.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_pet_daily_precheck_needs_pet_on_every_shot(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    _daily_set(ws, set_card, png_factory, skip=4)
    code, out = cli("compile-shot", "--index", "1", "--set-card", set_card, "--photo", photo, "--workspace", ws)
    assert code == 2 and out["status"] == "pet_daily_every_shot", out
    code, ledger = cli("set-status", "--set-card", set_card, "--workspace", ws)
    assert ledger["items"][0]["status"] == "pending"


def test_pet_daily_single_compile_needs_chain_set(tmp_path, png_factory):
    ws, photo, card, set_card = set_workspace(tmp_path, png_factory)
    _daily_set(ws, set_card, png_factory)
    scene = ws / "cards" / "single.json"
    scene.write_text(json.dumps(json.loads(set_card.read_text())["shots"][0]), encoding="utf-8")
    code, out = cli("compile", "--scene", scene, "--photo", photo, "--workspace", ws)
    assert code == 2 and out["status"] == "pet_daily_needs_pet", out
