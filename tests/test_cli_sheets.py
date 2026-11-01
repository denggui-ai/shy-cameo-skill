import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "skills" / "shy-cameo" / "scripts" / "cli.py"
FIX = Path(__file__).parent / "fixtures" / "cards"
FAKE = Path(__file__).parent / "fakes" / "fake_codex"


def cli(*args, env=None):
    proc = subprocess.run([sys.executable, str(CLI), *map(str, args)],
                          capture_output=True, text=True, env=env)
    assert proc.stdout, proc.stderr
    return proc.returncode, json.loads(proc.stdout)


def draft_card(ws):
    """Temp wukong in the workspace with no sheets attached yet."""
    card = json.loads((FIX / "wukong.json").read_text(encoding="utf-8"))
    card["status"] = "temp_draft"
    for variant in card["variants"]:
        variant["lookalike_check"] = {"status": "pending"}
        variant.pop("sheets")
    path = ws / "characters" / "xiyou-wukong" / "card.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    return path


def set_status(card_path, status):
    data = json.loads(card_path.read_text(encoding="utf-8"))
    data["status"] = status
    card_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def attach(card, variant, sheet, image, ws):
    return cli("attach-sheet", "--character", card, "--variant", variant, "--sheet", sheet,
               "--image", image, "--workspace", ws)


def test_sheet_flow_needs_no_consent(tmp_path, png_factory):
    ws = tmp_path / "ws"
    card = draft_card(ws)
    env = dict(os.environ, CODEX_HOME=str(tmp_path / "codex-home"), FAKE_CODEX_MODE="ok")
    src = tmp_path / "qujing-head.png"
    src.write_bytes(png_factory(16, 16))
    code, out = attach(card, "qujing", "head", src, ws)
    assert code == 0 and out["sheet"]["url"] == "characters/xiyou-wukong/qujing-head.png", out
    code, out = cli("compile-sheet", "--character", card, "--variant", "mhw", "--sheet", "head",
                    "--ref-variant", "qujing", "--workspace", ws)
    assert code == 0 and out["kind"] == "sheet" and len(out["referenced_image_paths"]) == 1, out
    request = Path(out["request_path"])
    assert not (ws / "consent.json").exists()
    code, gen = cli("generate-exec", "--request", request, "--workspace", ws,
                    "--authorized-count", "1", "--codex", FAKE, env=env)
    assert code == 0 and gen["status"] == "generated", gen
    code, audit = cli("verify", "--request", request, "--codex-home", tmp_path / "codex-home")
    assert audit["status"] == "pass", audit
    code, att = attach(card, "mhw", "head", gen["image_path"], ws)
    assert code == 0 and att["card_status"] == "temp_draft" and att["c2pa_present"] is True, att
    head = json.loads(card.read_text(encoding="utf-8"))["variants"][0]["sheets"]["head"]
    assert head["sha256"] == hashlib.sha256(Path(gen["image_path"]).read_bytes()).hexdigest()
    code, out = cli("compile-sheet", "--character", card, "--variant", "mhw", "--sheet", "body",
                    "--workspace", ws)
    assert code == 0 and out["referenced_image_paths"] == [str((ws / head["url"]).resolve())], out


def test_attach_resets_confirmation_and_guards_inputs(tmp_path, png_factory):
    ws = tmp_path / "ws"
    card = draft_card(ws)
    src = tmp_path / "a.png"
    src.write_bytes(png_factory(8, 8))
    set_status(card, "temp_confirmed")
    code, out = attach(card, "qujing", "head", src, ws)
    assert code == 0 and json.loads(card.read_text(encoding="utf-8"))["status"] == "temp_draft"
    set_status(card, "gold")
    code, out = attach(card, "qujing", "head", src, ws)
    assert code == 2 and out["status"] == "sheet_not_temp"
    set_status(card, "temp_draft")
    jpg = tmp_path / "a.jpg"
    jpg.write_bytes(b"not-a-png")
    code, out = attach(card, "qujing", "head", jpg, ws)
    assert code == 2 and out["status"] == "bad_image"


def test_sheet_request_cannot_carry_user_photo(tmp_path, png_factory):
    ws = tmp_path / "ws"
    card = draft_card(ws)
    code, out = cli("compile-sheet", "--character", card, "--variant", "mhw", "--sheet", "head",
                    "--workspace", ws)
    assert code == 0, out
    request = Path(out["request_path"])
    photo = ws / "input" / "me.png"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(png_factory(8, 8))
    data = json.loads(request.read_text(encoding="utf-8"))
    data["referenced_image_paths"] = [str(photo)]
    request.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    code, out = cli("generate-exec", "--request", request, "--workspace", ws,
                    "--authorized-count", "1", "--codex", FAKE)
    assert code == 2 and out["status"] == "bad_sheet_ref", out
    assert not (request.parent / "generation-count").exists()


def test_compile_sheet_refuses_gold_card(tmp_path):
    ws = tmp_path / "ws"
    card = draft_card(ws)
    set_status(card, "gold")
    code, out = cli("compile-sheet", "--character", card, "--variant", "mhw", "--sheet", "head",
                    "--workspace", ws)
    assert code == 2 and out["status"] == "sheet_not_temp"


def test_sheet_request_rejects_relative_ref(tmp_path, png_factory):
    ws = tmp_path / "ws"
    card = draft_card(ws)
    code, out = cli("compile-sheet", "--character", card, "--variant", "mhw", "--sheet", "head",
                    "--workspace", ws)
    request = Path(out["request_path"])
    for rel in ("characters/xiyou-wukong/qujing-head.png", "input/me.png"):
        data = json.loads(request.read_text(encoding="utf-8"))
        data["referenced_image_paths"] = [rel]
        request.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        code, out = cli("generate-exec", "--request", request, "--workspace", ws,
                        "--authorized-count", "1", "--codex", FAKE)
        assert code == 2 and out["status"] == "bad_sheet_ref", out
        assert not (request.parent / "generation-count").exists()


def test_attach_rejects_fake_png_and_resets_lookalike(tmp_path, png_factory):
    ws = tmp_path / "ws"
    card = draft_card(ws)
    fake = tmp_path / "fake.png"
    fake.write_bytes(b"not-a-png")
    code, out = attach(card, "qujing", "head", fake, ws)
    assert code == 2 and out["status"] == "bad_image"
    assert not (ws / "characters/xiyou-wukong/qujing-head.png").exists()
    data = json.loads(card.read_text(encoding="utf-8"))
    data["variants"][1]["lookalike_check"] = {"status": "passed", "date": "2026-10-10", "reviewer": "x"}
    card.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    good = tmp_path / "good.png"
    good.write_bytes(png_factory(8, 8))
    code, out = attach(card, "qujing", "head", good, ws)
    assert code == 0, out
    assert json.loads(card.read_text(encoding="utf-8"))["variants"][1]["lookalike_check"] == {"status": "pending"}
    assert not list(ws.rglob("*.part"))


BASE = "https://github.com/denggui-ai/classic-coshoot/releases/download/library-v1"


def test_promote_card_cli_writes_gold_card(tmp_path):
    ws = tmp_path / "ws"
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
    out_path = tmp_path / "gold" / "card.json"
    code, out = cli("promote-card", "--character", path, "--release-base", BASE, "--workspace", ws,
                    "--stage", tmp_path / "stage", "--out", out_path)
    assert code == 0 and len(out["uploads"]) == 4, out
    gold = json.loads(out_path.read_text(encoding="utf-8"))
    assert gold["status"] == "gold"
    assert gold["variants"][1]["sheets"]["body"]["url"] == BASE + "/xiyou-wukong-qujing-body.png"


def test_promote_card_blocks_actor_name_in_card_text(tmp_path):
    ws = tmp_path / "ws"
    card = json.loads((FIX / "wukong.json").read_text(encoding="utf-8"))
    card["status"] = "temp_confirmed"
    card["variants"][0]["lookalike_check"] = {"status": "passed", "reviewer": "六小龄童"}
    path = ws / "characters" / "xiyou-wukong" / "card.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")
    stage = tmp_path / "stage"
    code, out = cli("promote-card", "--character", path, "--release-base", BASE, "--workspace", ws,
                    "--stage", stage, "--out", tmp_path / "gold" / "card.json")
    assert code == 2 and out["status"] == "blocked_name", out
    assert not stage.exists()
