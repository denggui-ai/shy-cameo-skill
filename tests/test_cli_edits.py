"""Local-edit compilation only: these tests never invoke a generation backend."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from coshoot import compiler
from coshoot.cards import CardError

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "skills/shy-cameo/scripts/cli.py"
SCENE = ROOT / "tests/fixtures/cards/scene-shuiliandong.json"


def invoke(*args):
    proc = subprocess.run([sys.executable, "-B", str(CLI), *map(str, args)],
                          capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout) if proc.stdout else {"stderr": proc.stderr}


def prepare(tmp_path, png_factory, consent=True):
    ws = tmp_path / "ws"
    ws.mkdir()
    image = ws / "base.png"
    image.write_bytes(png_factory(30, 40))
    scene = json.loads(SCENE.read_text())
    scene["revisions"] = [{"n": 2, "fields_changed": ["user.outfit"], "status": "user_confirmed"}]
    scene_path = ws / "scene.json"
    scene_path.write_text(json.dumps(scene, ensure_ascii=False))
    if consent:
        code, out = invoke("consent", "--workspace", ws, "--subject", "--adult",
                           "--self-or-consented", "--photo", image)
        assert code == 0, out
    return ws, image, scene_path


def compile_edit(ws, image, scene, instruction="只把袖口改成暗酒红色，其他地方保持原样。"):
    return invoke("compile-edit", "--scene", scene, "--image", image,
                  "--instruction", instruction, "--workspace", ws)


def test_compile_edit_uses_the_base_and_preserves_scope_without_submission(tmp_path, png_factory):
    ws, image, scene = prepare(tmp_path, png_factory)
    before = {p: p.read_bytes() for p in ws.rglob("*") if p.is_file()}
    instruction = "只把袖口改成暗酒红色，其他地方保持原样。"
    code, out = compile_edit(ws, image, scene, instruction)
    assert code == 0, out
    request_path = Path(out["request_path"])
    request = json.loads(request_path.read_text())
    assert request["referenced_image_paths"] == [str(image.resolve())]
    assert request["card_ref"] == {"scene_id": "xiyou/" + json.loads(scene.read_text())["id"], "revision": 2}
    assert instruction in request["prompt"]
    # Local edits must not inherit the old storyboard's pose/framing or full retake instructions.
    source = json.loads(scene.read_text())
    assert source["setting"] not in request["prompt"]
    assert source["user"]["action"] not in request["prompt"]
    compiler.check_request_integrity(request)
    compiler.check_reference_hashes(request_path, request)
    manifest = json.loads((request_path.parent / "reference-hashes.json").read_text())
    assert manifest["references"] == {str(image.resolve()): hashlib.sha256(image.read_bytes()).hexdigest()}
    assert set(p.name for p in request_path.parent.iterdir()) == {"request.json", "reference-hashes.json"}
    assert all(p.read_bytes() == data for p, data in before.items())


@pytest.mark.parametrize("fault,status", [
    ("missing_image", "missing_edit_image"),
    ("no_consent", "blocked_consent"),
    ("changed_image", "blocked_consent"),
    ("unconfirmed_scene", "scene_not_confirmed"),
    ("empty_instruction", "empty_edit_instruction"),
    ("actor_name", "blocked_name"),
])
def test_compile_edit_rejects_invalid_inputs_before_writing_request(tmp_path, png_factory, fault, status):
    ws, image, scene = prepare(tmp_path, png_factory, consent=fault != "no_consent")
    instruction = "只改袖口颜色。"
    if fault == "missing_image":
        image.unlink()
    elif fault == "changed_image":
        image.write_bytes(png_factory(31, 40))
    elif fault == "unconfirmed_scene":
        data = json.loads(scene.read_text())
        data["status"] = "unverified"
        scene.write_text(json.dumps(data))
    elif fault == "empty_instruction":
        instruction = " \n "
    elif fault == "actor_name":
        instruction = "把脸改成六小龄童。"
    code, out = compile_edit(ws, image, scene, instruction)
    assert code == 2 and out.get("status") == status, out
    assert not (ws / "outputs").exists()


def test_edit_base_change_after_compile_uses_existing_reference_integrity_check(tmp_path, png_factory):
    ws, image, scene = prepare(tmp_path, png_factory)
    code, out = compile_edit(ws, image, scene)
    assert code == 0, out
    request_path = Path(out["request_path"])
    request = json.loads(request_path.read_text())
    image.write_bytes(png_factory(32, 40))
    with pytest.raises(CardError) as exc:
        compiler.check_reference_hashes(request_path, request)
    assert exc.value.code == "reference_changed"
    assert not (request_path.parent / "generation-count").exists()
