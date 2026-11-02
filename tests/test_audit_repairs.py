"""Regression cases from the independent 2026-10-14 audit; local data only."""
import fcntl
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import cli as cli_module
from coshoot import audit, compiler, frame, sets
from coshoot.cards import CardError
from test_cli import cli, compiled, FAKE, fake_env
from test_cli_sets import set_workspace
from test_sets import make_card


def call(code):
    return json.dumps({'input': code})


@pytest.mark.parametrize('expression', [
    '"ok" + "六小龄童"', 'r.prompt', '`ok${other}`',
])
def test_unknown_expression_never_passes(expression):
    result = audit.audit_lines([call('image_gen({prompt: '+expression+', referenced_image_paths: []})')],
                               {'prompt': 'ok', 'referenced_image_paths': []}, Path('/request.json'), [])
    assert result.status == 'unverifiable'


def test_all_calls_and_reference_paths_are_checked():
    req = {'prompt': 'ok', 'referenced_image_paths': ['/a']}
    good = 'image_gen({prompt: "ok", referenced_image_paths: ["/a"]});'
    bad = 'image_gen({prompt: "ok", referenced_image_paths: ["/b"]})'
    assert audit.audit_lines([call(good+bad)], req, Path('/request.json'), []).status == 'tampered'
    assert audit.audit_lines([call(good+'image_gen({prompt: other.prompt})')], req, Path('/request.json'), []).status == 'unverifiable'
    nested = 'const t = `${image_gen({prompt: "other", referenced_image_paths: []})}`'
    assert audit.audit_lines([call(good+nested)], req, Path('/request.json'), []).status == 'unverifiable'


def test_escaped_prompt_decodes_exactly():
    prompt = '有 "引号"、反斜线 \\ 和\n换行'
    code = 'image_gen({prompt: '+json.dumps(prompt)+', referenced_image_paths: []})'
    assert audit.audit_lines([call(code)], {'prompt': prompt, 'referenced_image_paths': []}, Path('/r'), []).status == 'pass'


def test_space_plan_and_explicit_same_setting_exception():
    card = make_card()
    for shot in card['shots']:
        shot['setting'] = '同一面黄墙'
    sets.validate_set_card(card)
    card['same_setting_confirmed'] = True
    sets.validate_set_card(card)
    # Two places may be reused; five distinct backgrounds are not required.
    card.pop('same_setting_confirmed')
    card['shots'][1]['setting'] = '故事布景大空间'
    sets.validate_set_card(card)


def test_genre_with_cast_requires_shy_cover():
    card = make_card(play_mode='genre_scene')
    card['shots'][3]['characters'][0]['character_presence'] = 'peek'
    card['shots'][3]['characters'][0].pop('cover_level')
    sets.validate_set_card(card)
    for s in card['shots']:
        s['characters'] = []
    sets.validate_set_card(card)


def test_missing_frame_image_blocks(tmp_path):
    assert frame.check_frame(tmp_path/'missing.png', 'waist_up', detector=None)['level'] == 'block'


def test_reference_bytes_checked_before_count(tmp_path, png_factory):
    ws, request_path = compiled(tmp_path, png_factory)
    request = json.loads(request_path.read_text())
    sheet = Path(request['referenced_image_paths'][1])
    sheet.write_bytes(b'changed-sheet')
    code, result = cli('generate-exec', '--request', request_path, '--workspace', ws,
                       '--authorized-count', 1, '--codex', FAKE, env=fake_env(tmp_path, 'ok'))
    assert code == 2 and result['status'] == 'reference_changed'
    assert not (request_path.parent/'generation-count').exists()


def test_workspace_overlap_is_rejected(tmp_path, png_factory):
    ws, photo, char, card = set_workspace(tmp_path, png_factory)
    with (ws/'.shy-cameo.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        code, result = cli('compile-shot', '--index', 1, '--workspace', ws,
                           '--set-card', card, '--character', char, '--photo', photo)
    assert code == 2 and result['status'] == 'workspace_busy'
    assert not (ws/'outputs').exists()


def test_set_rechecks_photo_after_first_submission(tmp_path, png_factory, monkeypatch):
    ws, photo, char, card = set_workspace(tmp_path, png_factory)
    generated = tmp_path/'generated.png'
    generated.write_bytes(png_factory())
    calls = []
    def fake(*args, **kwargs):
        calls.append(1)
        photo.write_bytes(png_factory(601, 600))
        return SimpleNamespace(status='generated', image_path=str(generated), message='fake')
    monkeypatch.setattr(cli_module.backend_exec, 'run_exec', fake)
    messages = []
    monkeypatch.setattr(cli_module, 'emit', lambda result, code=0: messages.append(result) or code)
    args = SimpleNamespace(workspace=str(ws), set_card=str(card), character=[str(char)],
                           photo=[str(photo)], authorized_count=5, codex='never-called', timeout=1)
    assert cli_module.cmd_generate_set(args) == 2
    assert len(calls) == 1 and messages[-1]['quota_used'] == 1


def test_verify_rejects_stale_request_hash(tmp_path, png_factory):
    _, p = compiled(tmp_path, png_factory)
    req = json.loads(p.read_text()); req['prompt'] += 'changed'
    p.write_text(json.dumps(req))
    log = tmp_path/'log.jsonl'; log.write_text(call('image_gen({prompt: '+json.dumps(req['prompt'])+'})'))
    code, result = cli('verify', '--request', p, '--log', log)
    assert code == 2 and result['status'] == 'request_tampered'


def test_delivery_evidence_and_final_bytes_are_bound(tmp_path, png_factory):
    ws, p = compiled(tmp_path, png_factory)
    image = tmp_path/'g.png'; image.write_bytes(png_factory())
    wrong = tmp_path/'wrong-audit.json'; wrong.write_text(json.dumps({'status':'pass','reason':'other run'}))
    assert cli('deliver','--request',p,'--workspace',ws,'--image',image,'--audit',wrong)[1]['status'] == 'qa_mismatch'
    assert cli('deliver','--request',p,'--workspace',ws,'--image',image)[1]['status'] == 'qa_incomplete'
    assert not (p.parent/'sidecar.json').exists()
    log = tmp_path/'empty.jsonl'; log.write_text('')
    assert cli('verify','--request',p,'--log',log)[0] == 0
    assert cli('frame-check',image,'--framing','waist_up','--out',p.parent/'frame.json')[0] == 0
    assert cli('deliver','--request',p,'--workspace',ws,'--image',image,'--audit',p.parent/'audit.json','--frame',p.parent/'frame.json')[0] == 0
    verdict = ['record-verdict','--run-dir',p.parent,'--likeness','yes','--character','yes','--no-face-mix','yes']
    assert cli(*verdict)[1]['verdict'] == 'accepted'
    (p.parent/'image.png').write_bytes(png_factory(10, 12))
    assert cli(*verdict)[1]['status'] == 'delivery_changed'


def test_header_only_png_is_not_a_frame(tmp_path):
    import struct
    image = tmp_path / "header.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sII", 13, b"IHDR", 600, 800))
    assert frame.check_frame(image, "waist_up", detector=None)["level"] == "block"


def test_relative_workspace_delivers_absolute_request_to_relay(tmp_path, png_factory, monkeypatch):
    ws, photo, char, card = set_workspace(tmp_path, png_factory)
    image = tmp_path/'g.png'; image.write_bytes(png_factory())
    calls = []
    def fake(request, run_dir, workspace, **kwargs):
        assert request.is_absolute() and request.is_file() and workspace == ws
        calls.append(request)
        return SimpleNamespace(status='generated', image_path=str(image), message='local fake')
    monkeypatch.setattr(cli_module.backend_exec,'run_exec',fake)
    monkeypatch.setattr(cli_module,'emit',lambda result, code=0: code)
    monkeypatch.chdir(tmp_path)
    args = SimpleNamespace(workspace='ws',set_card=str(card),character=[str(char)],photo=[str(photo)],
                           authorized_count=5,codex='never-called',timeout=1)
    assert cli_module.cmd_generate_set(args) == 0
    assert len(calls) == 5
