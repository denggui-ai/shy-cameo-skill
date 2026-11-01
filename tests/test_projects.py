"""Multi-series read-only recovery using real compiler/ledger/delivery code, no image service."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from coshoot import label, projects, sets
from coshoot.cards import CardError
from coshoot.library import sha256_file
from test_compiler import build, setup
from test_sets import make_card

CLI = Path(__file__).resolve().parents[1] / 'skills/shy-cameo/scripts/cli.py'


def save(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False))


@pytest.fixture
def project(tmp_path, png_factory):
    (tmp_path / 'input').mkdir()
    (tmp_path / 'input/me.png').write_bytes(png_factory())
    doc = {'schema_version': '1', 'project_id': 'po', 'title': '我和阿宝',
           'character': {'name': '阿宝', 'version': '三维动画'}, 'photo_refs': ['input/me.png'],
           'preferences': {'subject': 'photographic'}, 'series': [], 'selection': ['studio', 'training', 'daily']}
    cards = {}
    for sid in doc['selection']:
        card = make_card()
        card['set_id'] = sid
        for index, shot in enumerate(card['shots'], 1):
            shot['id'] = f'{sid}-{index}'
        cards[sid] = card
        save(tmp_path / f'cards/{sid}.json', card)
        doc['series'].append({'series_id': sid, 'title': sid, 'brief': f'{sid}的独立体验',
                              'sets': [{'set_id': sid, 'card': f'cards/{sid}.json'}]})
    save(tmp_path / 'project.json', doc)
    return tmp_path, doc, cards


def record(ws, card, index, png_factory, outcome='generated', accepted=False, retake=False):
    n = len(list((ws / 'outputs').glob('2026*'))) + 1
    run_id = f'20261017-120000-{n:06x}'
    scene = copy.deepcopy(card['shots'][index - 1])
    if retake:
        scene['id'] += '-retake'
    _, chars = setup()
    for char in chars.values():
        for variant in char['variants']:
            variant.pop('sheets', None)
    info = None if retake else {'set_id': card['set_id'], 'index': index, 'role': sets.ROLES[index - 1]}
    request = build(scene=scene, chars=chars, photos=[ws / 'input/me.png'], run_id=run_id, set_info=info)
    root = ws / 'outputs' / run_id
    if not retake:
        # Same order as the CLI: the ledger is read before this run's request exists.
        ledger = sets.load_ledger(ws, card)
    save(root / 'request.json', request)
    if not retake:
        sets.claim(ledger, index, run_id)
    if outcome == 'generated':
        image = ws / f'{run_id}.png'
        image.write_bytes(png_factory())
        if not retake:
            sets.record(ws, ledger, index, outcome, str(image))
        audit = {'status': 'unverified', 'reason': 'synthetic test', 'run_id': run_id, 'request_sha256': request['sha256']}
        frame = {'level': 'pass', 'image_sha256': sha256_file(image)}
        consent = {'subject_confirmed': True, 'adult_confirmed': True, 'self_or_consented': True, 'at': 'test'}
        sidecar = label.deliver(image, root, request, consent, audit, frame)
        if accepted:
            sidecar.update(verdict='accepted', self_check={'likeness': True, 'character': True, 'no_face_mix': True, 'at': 'test'})
            save(root / 'sidecar.json', sidecar)
    elif outcome != 'claimed':
        sets.record(ws, ledger, index, outcome)
    if not retake:
        sets.save_ledger(ws, card, ledger)
    else:
        save(ws / f'cards/{run_id}.json', scene)
    return run_id


def test_three_sets_fifteen_images_and_frozen_all(project):
    ws, doc, _ = project
    doc['series'].append({'series_id': 'new', 'title': '新提案', 'brief': '下次再拍', 'sets': []})
    save(ws / 'project.json', doc)
    result = projects.status(ws)
    assert result['selection']['planned_images'] == 15
    assert result['selection']['generation'] == {'pending': 15}
    assert result['selection']['set_ids'] == ['studio', 'training', 'daily']
    assert not result['selection']['complete']
    assert not (ws / 'outputs').exists()
    doc['selection'] = ['daily']
    save(ws / 'project.json', doc)
    assert projects.status(ws)['selection']['planned_images'] == 5


def test_finished_then_failed_then_unsubmitted_survives_new_process(project, png_factory):
    ws, doc, cards = project
    for index in range(1, 6):
        record(ws, cards['studio'], index, png_factory)
    record(ws, cards['training'], 1, png_factory, outcome='failed')
    before = {str(p): sha256_file(p) for p in ws.rglob('*') if p.is_file()}
    proc = subprocess.run([sys.executable, '-B', str(CLI), 'project-status', '--workspace', str(ws)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = json.loads(proc.stdout)
    assert result['selection']['generation'] == {'generated': 5, 'failed': 1, 'cancelled': 4, 'pending': 5}
    assert result['selection']['delivered'] == 5 and result['selection']['accepted'] == 0
    assert result['selection']['pause_before_next_set']
    assert result['selection']['unsubmitted'] == [{'set_id': 'daily', 'indices': [1, 2, 3, 4, 5]}]
    assert not result['selection']['complete']
    assert before == {str(p): sha256_file(p) for p in ws.rglob('*') if p.is_file()}
    # Explicit continuation changes the current scope, not the failed historical ledger.
    doc['selection'] = ['daily']
    save(ws / 'project.json', doc)
    assert not projects.status(ws)['selection']['pause_before_next_set']


def test_retake_selection_preserves_original_and_other_sets(project, png_factory):
    ws, doc, cards = project
    for index in range(1, 6):
        record(ws, cards['training'], index, png_factory, accepted=True)
    old = projects.status(ws)['series'][1]['sets'][0]['shots'][2]['selected_run_id']
    new = record(ws, cards['training'], 3, png_factory, retake=True)
    entry = doc['series'][1]['sets'][0]
    entry['shots'] = [{'index': 3, 'candidates': [{'run_id': new, 'scene_card': f'cards/{new}.json'}]}]
    save(ws / 'project.json', doc)
    report = projects.status(ws)['series'][1]['sets'][0]
    assert report['complete'] and report['shots'][2]['selected_run_id'] == old
    entry['shots'][0]['selected_run_id'] = new
    save(ws / 'project.json', doc)
    result = projects.status(ws)
    report = result['series'][1]['sets'][0]
    assert report['accepted'] == 4 and not report['complete']
    assert {v['run_id'] for v in report['shots'][2]['versions']} == {old, new}
    assert result['series'][0]['sets'][0]['generation'] == {'pending': 5}
    assert json.loads((ws / f'outputs/{old}/sidecar.json').read_text())['verdict'] == 'accepted'


@pytest.mark.parametrize('fault', ['card_missing', 'ledger_corrupt', 'chain_missing', 'image_changed', 'request_changed', 'false_acceptance', 'tampered_acceptance', 'unlinked_selected'])
def test_unknown_or_changed_results_never_complete(project, png_factory, fault):
    ws, doc, cards = project
    run = record(ws, cards['studio'], 1, png_factory, accepted=True)
    root = ws / 'outputs' / run
    if fault == 'card_missing':
        (ws / 'cards/studio.json').unlink()
    elif fault == 'ledger_corrupt':
        save(ws / 'outputs/sets/studio/set.json', {'set_id': 'other'})
    elif fault == 'chain_missing':
        (ws / 'outputs/sets/studio/chain.png').unlink()
    elif fault == 'image_changed':
        (root / 'image.png').write_bytes(b'changed')
    elif fault == 'request_changed':
        request = json.loads((root / 'request.json').read_text())
        request['prompt'] += 'changed'
        save(root / 'request.json', request)
    elif fault == 'false_acceptance':
        sidecar = json.loads((root / 'sidecar.json').read_text())
        del sidecar['self_check']
        save(root / 'sidecar.json', sidecar)
    elif fault == 'tampered_acceptance':
        sidecar = json.loads((root / 'sidecar.json').read_text())
        sidecar['audit']['status'] = 'tampered'
        save(root / 'sidecar.json', sidecar)
    else:
        doc['series'][0]['sets'][0]['shots'] = [{'index': 1, 'candidates': [], 'selected_run_id': '20261017-120000-ffffff'}]
        save(ws / 'project.json', doc)
    result = projects.status(ws)
    assert result['issues'] and result['selection']['pause_before_next_set']
    assert not result['selection']['complete']


def test_claimed_is_unknown_submission_not_safe_to_resume(project, png_factory):
    ws, _, cards = project
    record(ws, cards['studio'], 1, png_factory, outcome='claimed')
    result = projects.status(ws)
    assert result['selection']['generation']['claimed'] == 1
    assert result['selection']['pause_before_next_set']
    assert 1 not in result['selection']['unsubmitted'][0]['indices']


@pytest.mark.parametrize('fault', ['duplicate_set', 'unknown_selection', 'duplicate_series'])
def test_ambiguous_index_rejected(project, fault):
    ws, doc, _ = project
    if fault == 'duplicate_set':
        doc['series'][1]['sets'] = doc['series'][0]['sets']
    elif fault == 'unknown_selection':
        doc['selection'] = ['unregistered']
    else:
        doc['series'][1]['series_id'] = doc['series'][0]['series_id']
    save(ws / 'project.json', doc)
    with pytest.raises(CardError):
        projects.status(ws)


def test_reference_cannot_escape_workspace_via_symlink(project, tmp_path_factory):
    ws, doc, _ = project
    outside = tmp_path_factory.mktemp('outside') / 'private.json'
    outside.write_text('private')
    (ws / 'cards/escape.json').symlink_to(outside)
    doc['series'][0]['sets'][0]['card'] = 'cards/escape.json'
    save(ws / 'project.json', doc)
    result = projects.status(ws)
    assert 'project_reference_outside_workspace' in result['issues'][0]


def test_old_standalone_set_needs_no_project(project, png_factory):
    ws, _, cards = project
    (ws / 'project.json').unlink()
    record(ws, cards['studio'], 1, png_factory)
    assert sets.load_ledger(ws, cards['studio'])['items'][0]['status'] == 'generated'


def test_other_sets_request_cannot_be_attached_as_retake(project, png_factory):
    ws, doc, cards = project
    other = record(ws, cards['daily'], 1, png_factory)
    save(ws / 'cards/other-scene.json', cards['daily']['shots'][0])
    doc['series'][0]['sets'][0]['shots'] = [{'index': 1, 'candidates': [{'run_id': other, 'scene_card': 'cards/other-scene.json'}], 'selected_run_id': other}]
    save(ws / 'project.json', doc)
    result = projects.status(ws)
    assert any('project_run_mismatch' in issue for issue in result['issues'])
    assert result['series'][0]['sets'][0]['delivered'] == 0


def test_missing_ledger_with_existing_set_directory_is_unknown(project):
    ws, _, _ = project
    (ws / 'outputs/sets/studio').mkdir(parents=True)
    result = projects.status(ws)
    assert result['series'][0]['sets'][0]['generation'] == {'unknown': 5}
    assert result['selection']['pause_before_next_set']


def test_unlinked_generated_run_is_reported_not_replaced_by_latest_file(project, png_factory):
    ws, _, cards = project
    run = record(ws, cards['studio'], 1, png_factory)
    record(ws, cards['daily'], 1, png_factory)
    (ws / f'outputs/{run}/request.json').unlink()
    result = projects.status(ws)
    assert result['series'][0]['sets'][0]['delivered'] == 0
    assert result['series'][1]['sets'][0]['generation'] == {'pending': 5}
    assert result['issues']


def test_unselected_missing_history_stays_unknown_without_blocking_new_series(project):
    ws, doc, _ = project
    (ws / 'cards/studio.json').unlink()
    doc['selection'] = ['daily']
    save(ws / 'project.json', doc)
    result = projects.status(ws)
    assert result['issues'] and result['status'] == 'project_needs_review'
    assert not result['selection']['pause_before_next_set']
    assert result['selection']['generation'] == {'pending': 5}


def test_invalid_historical_candidate_does_not_claim_legitimate_run(project, png_factory):
    ws, doc, cards = project
    run = record(ws, cards['daily'], 1, png_factory, accepted=True)
    save(ws / 'cards/stale-scene.json', cards['studio']['shots'][0])
    doc['series'][0]['sets'][0]['shots'] = [{'index': 1, 'candidates': [
        {'run_id': run, 'scene_card': 'cards/stale-scene.json'}]}]
    doc['selection'] = ['daily']
    save(ws / 'project.json', doc)
    result = projects.status(ws)
    assert result['issues']  # Invalid history remains visible.
    assert result['selection']['delivered'] == result['selection']['accepted'] == 1
    assert not result['selection']['pause_before_next_set']


def test_interrupted_retake_is_visible_after_new_process(project, png_factory):
    ws, doc, cards = project
    for index in range(1, 6):
        record(ws, cards['studio'], index, png_factory, accepted=True)
    original = projects.status(ws)['series'][0]['sets'][0]['shots'][2]['selected_run_id']
    run = record(ws, cards['studio'], 3, png_factory, outcome='claimed', retake=True)
    doc['series'][0]['sets'][0]['shots'] = [{'index': 3, 'candidates': [
        {'run_id': run, 'scene_card': f'cards/{run}.json'}]}]
    save(ws / 'project.json', doc)
    proc = subprocess.run([sys.executable, '-B', str(CLI), 'project-status', '--workspace', str(ws)], capture_output=True, text=True)
    result = json.loads(proc.stdout)
    assert result['selection']['pause_before_next_set']
    assert result['selection']['review_set_ids'] == ['studio']
    shot = result['series'][0]['sets'][0]['shots'][2]
    assert shot['selected_run_id'] == original and shot['verdict'] == 'accepted'
    assert next(v for v in shot['versions'] if v['run_id'] == run)['verdict'] == 'unknown'
    assert run in ' '.join(result['issues'])
