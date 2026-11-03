"""Read-only series index. Existing ledgers and delivery records remain authoritative.

No directory scan, generation, authorization or automatic recovery happens here; the only write is
mark_continue, which records the user's "continue" between sets.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from . import compiler, sets, migrate
from .cards import CardError, load_json, require_valid
from .library import sha256_file

RUN_ID = re.compile(r'^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$')
STATES = {'pending', 'claimed', 'generated', 'failed', 'rejected', 'cancelled'}


def local_path(ws: Path, value: str) -> Path:
    return migrate.local_path(ws, value)


def read(ws: Path, value: str, kind=None):
    data = load_json(local_path(ws, value))
    if kind:
        require_valid(data, kind)
    return data


def _unique(values, what):
    if len(values) != len(set(values)):
        raise CardError('invalid_project', f'{what}重复，无法唯一关联')


def _version(ws, run_id, scene, set_id, index, original):
    if not RUN_ID.fullmatch(run_id):
        raise CardError('project_run_mismatch', '非法运行编号')
    owner = (set_id, index)
    base = f'outputs/{run_id}'
    request = read(ws, f'{base}/request.json', 'request')
    expected_scene = f"{scene['ip']}/{scene['id']}"
    if (request['run_id'] != run_id or request['card_ref']['scene_id'] != expected_scene
            or request['card_ref']['revision'] != compiler.current_revision(scene)
            or request['sha256'] != compiler._body_sha256(request['prompt'], request['referenced_image_paths'])):
        raise CardError('project_run_mismatch', '运行请求与分镜或摘要不匹配')
    association = request.get('set')
    if original or association:
        if not association or (association['set_id'], association['index']) != owner:
            raise CardError('project_run_mismatch', '运行请求与套图镜头不匹配')
    result = {'run_id': run_id, 'delivered': False, 'verdict': 'pending', 'title': scene['title']}
    sidecar_path = local_path(ws, f'{base}/sidecar.json')
    if not sidecar_path.is_file():
        return result
    sidecar = read(ws, f'{base}/sidecar.json', 'sidecar')
    run_dir = local_path(ws, base)
    images = [local_path(ws, str(p)) for p in run_dir.glob('image.*') if p.is_file()]
    if (sidecar['run_id'] != run_id or sidecar['request_sha256'] != request['sha256']
            or len(images) != 1 or sha256_file(images[0]) != sidecar['original_sha256']):
        raise CardError('project_delivery_mismatch', '交付记录与请求或原图不匹配')
    if sidecar['verdict'] == 'accepted':
        checks, audit, frame = sidecar.get('self_check', {}), sidecar['audit'], sidecar.get('frame_check') or {}
        if (not all(checks.get(k) is True for k in ('likeness', 'character', 'no_face_mix'))
                or audit.get('run_id') != run_id or audit.get('request_sha256') != request['sha256']
                or frame.get('image_sha256') != sidecar['original_sha256'] or frame.get('level') == 'block'
                or audit.get('status') == 'tampered'):
            raise CardError('project_acceptance_mismatch', '已接受记录缺少匹配的自检或检查依据')
    result.update(delivered=True, verdict=sidecar['verdict'], image_path=str(images[0]),
                  audit=sidecar['audit']['status'])
    return result


def _ledger(ws, card):
    base = f"outputs/sets/{card['set_id']}"
    path = local_path(ws, f'{base}/{sets.LEDGER_NAME}')
    if not path.exists():
        if local_path(ws, base).exists():
            raise CardError('project_ledger_missing', '套图目录已存在但账本缺失，不能假定未提交')
        return sets.load_ledger(ws, card)  # constructs pending items in memory only
    ledger = sets.load_ledger(ws, card)
    items = ledger.get('items') if isinstance(ledger, dict) else None
    if ledger.get('set_id') != card['set_id'] or not isinstance(items, list) or len(items) != 5:
        raise CardError('ledger_mismatch', '套图账本不匹配')
    for index, item in enumerate(items, 1):
        if (not isinstance(item, dict) or item.get('index') != index
                or item.get('role') != sets.ROLES[index - 1] or item.get('status') not in STATES):
            raise CardError('ledger_mismatch', '账本镜头顺序或状态异常')
        if item['status'] in ('claimed', 'generated', 'failed', 'rejected'):
            if not isinstance(item.get('run_id'), str) or not RUN_ID.fullmatch(item['run_id']):
                raise CardError('ledger_mismatch', '已提交记录缺少有效运行编号')
        elif item.get('run_id') is not None:
            raise CardError('ledger_mismatch', '未提交记录不应持有运行编号')
    if items[0]['status'] == 'generated':
        local_path(ws, ledger.get('chain_image') or '')
        local_path(ws, f'{base}/{sets.CHAIN_NAME}')
        sets.chain_ref(ws, card, ledger)
    elif any(it['status'] != 'cancelled' for it in items[1:]) and items[0]['status'] in ('failed', 'rejected'):
        raise CardError('ledger_mismatch', '首张失败后余下镜头应取消')
    elif any(it['status'] not in ('pending', 'cancelled') for it in items[1:]):
        raise CardError('ledger_mismatch', '缺少成功首图却存在后续提交')
    return ledger


def _set_status(ws, entry, owners):
    result = {'set_id': entry['set_id'], 'card': entry['card'], 'shots': [], 'issues': []}
    card = read(ws, entry['card'], 'set')
    if card['set_id'] != entry['set_id']:
        raise CardError('project_set_mismatch', '索引套图编号与卡片不一致')
    for scene in card['shots']:
        require_valid(scene, 'scene')
    # Allows unconfirmed preparation; execution still uses the stricter existing validator.
    for scene in card['shots'][1:]:
        if any(scene[k] != card['shots'][0][k] for k in ('ip', 'play_mode', 'style', 'aspect')):
            raise CardError('set_inconsistent', '套图中的主题、玩法、画风或比例不一致')
    ledger = _ledger(ws, card)
    overrides = {s['index']: s for s in entry.get('shots', [])}
    _unique([s['index'] for s in entry.get('shots', [])], '选版镜头')
    for index, item in enumerate(ledger['items'], 1):
        override = overrides.get(index, {})
        base_run = item.get('run_id')
        versions = []
        candidates = override.get('candidates', [])
        _unique([c['run_id'] for c in candidates], '候选版本')
        if base_run and any(c['run_id'] == base_run for c in candidates):
            raise CardError('invalid_project', '原版由账本自动关联，不重复登记为重拍')
        sources = [(base_run, card['shots'][index - 1], True)] if base_run else []
        for candidate in candidates:
            sources.append((candidate['run_id'], candidate['scene_card'], False))
        for run_id, scene, original in sources:
            try:
                if not original:
                    scene = read(ws, scene, 'scene')
                    if scene['ip'] != card['shots'][index - 1]['ip']:
                        raise CardError('project_run_mismatch', '重拍的主题与原套图不同')
                version = _version(ws, run_id, scene, card['set_id'], index, original)
                if original and item['status'] != 'generated' and version['delivered']:
                    raise CardError('ledger_mismatch', '账本未成功但存在交付结果，请先核对')
                if not original and not version['delivered']:
                    raise CardError('project_retake_unresolved', '重拍尚无交付记录，先核对调用结果，不得自动重试')
                owner = (card['set_id'], index)
                if run_id in owners and owners[run_id] != owner:
                    raise CardError('project_run_mismatch', '同一结果不能归属于两张不同照片')
                # An invalid historical reference must not reserve a valid run.
                owners[run_id] = owner
                versions.append(version)
            except (CardError, OSError, ValueError, KeyError, TypeError) as exc:
                versions.append({'run_id': run_id, 'delivered': False, 'verdict': 'unknown', 'issue': str(exc)})
                result['issues'].append(f'第{index}张 {run_id}: {exc}')
        selected = override.get('selected_run_id', base_run if item['status'] == 'generated' else None)
        chosen = next((v for v in versions if v['run_id'] == selected), None)
        if selected and chosen is None:
            result['issues'].append(f'第{index}张选用版本未关联：{selected}')
        result['shots'].append({'index': index, 'generation': item['status'], 'versions': versions,
                                **({'story_index': sets.story_index(card, index)} if 'story_order' in card else {}),
                                'selected_run_id': selected, 'delivered': bool(chosen and chosen['delivered']),
                                'verdict': chosen['verdict'] if chosen else 'pending'})
    counts = Counter(s['generation'] for s in result['shots'])
    result.update(generation=dict(counts), delivered=sum(s['delivered'] for s in result['shots']),
                  accepted=sum(s['delivered'] and s['verdict'] == 'accepted' for s in result['shots']),
                  unsubmitted=[s['index'] for s in result['shots'] if s['generation'] == 'pending'])
    result['complete'] = result['accepted'] == 5 and not result['issues']
    return result


def project_index(ws: Path, value: str) -> str:
    """Project indexes live outside outputs/ and end in .json, so the continue gate can find every one."""
    path = local_path(ws, value)
    if path.suffix.lower() != '.json' or 'outputs' in (part.lower() for part in path.relative_to(ws).parts):
        raise CardError('invalid_project', '项目索引须是工作区内 outputs/ 以外的 .json 文件')
    return value


def status(workspace: Path, project='project.json') -> dict:
    ws = workspace.resolve()
    doc = read(ws, project_index(ws, project), 'project')
    _unique([s['series_id'] for s in doc['series']], '系列编号')
    entries = [entry for series in doc['series'] for entry in series['sets']]
    _unique([e['set_id'] for e in entries], '套图编号')
    if set(doc['selection']) - {e['set_id'] for e in entries}:
        raise CardError('invalid_project', '本次选择包含未登记的套图')
    issues, owners, series_results, lookup = [], {}, [], {}
    for ref in doc.get('photo_refs', []) + doc['character'].get('cards', []):
        if not local_path(ws, ref).is_file():
            issues.append(f'素材引用缺失：{ref}')
    material_issues = list(issues)
    for series in doc['series']:
        group = {k: series[k] for k in ('series_id', 'title', 'brief')}
        group['sets'] = []
        for entry in series['sets']:
            try:
                report = _set_status(ws, entry, owners)
            except (CardError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
                report = {'set_id': entry['set_id'], 'issues': [str(exc)], 'generation': {'unknown': 5},
                          'shots': [], 'delivered': 0, 'accepted': 0, 'complete': False, 'unsubmitted': []}
            issues.extend(f"{entry['set_id']}: {issue}" for issue in report['issues'])
            lookup[entry['set_id']] = report
            group['sets'].append(report)
        series_results.append(group)
    selected = [lookup[sid] for sid in doc['selection']]
    counts = Counter()
    for report in selected:
        counts.update(report['generation'])
    pauses = []
    for report in selected:
        if report['issues'] or any(report['generation'].get(s, 0) for s in ('claimed', 'unknown', 'failed', 'rejected', 'cancelled')):
            pauses.append(report['set_id'])
    return {'status': 'project_needs_review' if issues else 'project_status', 'project_id': doc['project_id'],
            'title': doc['title'], 'series': series_results, 'issues': issues,
            'selection': {'set_ids': doc['selection'], 'planned_images': len(selected) * 5,
                          'generation': dict(counts), 'delivered': sum(r['delivered'] for r in selected),
                          'accepted': sum(r['accepted'] for r in selected),
                          'complete': bool(selected) and all(r['complete'] for r in selected),
                          'pause_before_next_set': bool(pauses or material_issues), 'review_set_ids': pauses,
                          'unsubmitted': [{'set_id': r['set_id'], 'indices': r['unsubmitted']}
                                          for r in selected if r['unsubmitted']]},
            'execution': 'read_only_not_authorization'}


def _project_indexes(ws: Path):
    """Every project index in the workspace, whatever its file name (outputs/ holds only run records)."""
    # Case-insensitive on purpose: macOS volumes treat project.JSON and project.json as one file.
    for path in sorted(ws.rglob('*')):
        parts = [part.lower() for part in path.relative_to(ws).parts]
        if path.suffix.lower() != '.json' or 'outputs' in parts or not path.is_file():
            continue
        try:
            doc = load_json(path)
        except (CardError, OSError, ValueError):
            continue
        if isinstance(doc, dict) and 'selection' in doc and 'series' in doc:
            yield path, doc


def require_continue(ws: Path, set_id: str) -> None:
    """D12: in a multi-set selection, every set after the first starts only after the user said continue."""
    ws = Path(ws).resolve()
    for path, doc in _project_indexes(ws):
        selection = doc['selection'] if isinstance(doc['selection'], list) else []
        if set_id not in selection or selection.index(set_id) == 0 or set_id in doc.get('continued', []):
            continue
        previous = selection[selection.index(set_id) - 1]
        raise CardError('blocked_await_continue',
                        f'上一套 {previous} 拍完要先给用户看；用户说“继续”后用 project-continue 登记，再拍 {set_id}'
                        f'（项目索引 {path.relative_to(ws)}）')


def mark_continue(ws: Path, set_id: str, project='project.json') -> dict:
    ws = Path(ws).resolve()
    doc = read(ws, project_index(ws, project), 'project')
    selection = doc['selection']
    if set_id not in selection:
        raise CardError('invalid_project', f'{set_id} 不在本次选择里')
    if selection.index(set_id) > 0:
        # "Continue" only means something after the previous set has finished generating.
        previous = selection[selection.index(set_id) - 1]
        ledger = sets.set_dir(ws, previous) / sets.LEDGER_NAME
        items = load_json(ledger)['items'] if ledger.is_file() else []
        if not items or any(it['status'] in ('pending', 'claimed') for it in items):
            raise CardError('previous_set_unfinished', f'上一套 {previous} 还没拍完或有结果未核对，不能登记继续')
    continued = doc.setdefault('continued', [])
    if set_id not in continued:
        continued.append(set_id)
    require_valid(doc, 'project')
    migrate.write_workspace_document(local_path(ws, project), doc, 'project', ws)
    return doc
