"""schema_version migrations. Register (kind, from_version) -> step function."""
from __future__ import annotations

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Callable, Dict, Tuple

from .cards import CardError
from .library import sha256_file

CURRENT: Dict[str, str] = {"scene": "2", "character": "1", "request": "1", "sidecar": "1"}
MAX_STEPS = 20
MIGRATIONS: Dict[Tuple[str, str], Callable[[dict], dict]] = {}


def _scene_1_to_2(doc: dict) -> dict:
    # v4 semantics changed (shy characters, play modes), so the user must confirm again.
    doc.pop("style_preset", None)
    doc.update(schema_version="2", style="realistic", aspect="2:3", play_mode="classic_presence")
    for member in doc.get("characters") or []:
        member.setdefault("character_presence", "cropped")
    doc["status"] = "unverified"
    revisions = doc.setdefault("revisions", [])
    last = revisions[-1].get("n", len(revisions)) if revisions else 0
    revisions.append({"n": last + 1, "fields_changed": ["schema_version", "play_mode", "style",
                                                         "aspect", "character_presence"],
                      "status": "unverified"})
    return doc


MIGRATIONS[("scene", "1")] = _scene_1_to_2


def migrate(doc: dict, kind: str) -> dict:
    version = doc.get("schema_version")
    if version is None:
        raise CardError("missing_schema_version", "文档缺少 schema_version")
    target = CURRENT.get(kind, "1")
    for _ in range(MAX_STEPS):
        if version == target:
            return doc
        step = MIGRATIONS.get((kind, version))
        if step is None:
            raise CardError("unsupported_schema_version", f"不支持的 {kind} schema_version：{version}")
        doc = step(copy.deepcopy(doc))
        version = doc.get("schema_version")
    raise CardError("unsupported_schema_version", f"{kind} 迁移步数超过 {MAX_STEPS}")


BACKUP_SUFFIX = '.pre-relative-paths-'


def _old_root(value, relative: Path):
    """Only recognise the exact registered layout, never a basename-only match."""
    if not isinstance(value, str):
        return None
    path = Path(value)
    if (path.is_absolute() and '..' not in path.parts
            and path.parts[-len(relative.parts):] == relative.parts):
        return path.parents[len(relative.parts) - 1]
    return None


def ledger_paths(ws: Path, doc: dict) -> dict:
    result = copy.deepcopy(doc)
    value = result.get('chain_image')
    if value:
        relative = Path('outputs/sets') / doc['set_id'] / 'chain.png'
        if Path(value).is_absolute():
            if _old_root(value, relative) is None:
                raise CardError('chain_tampered', '首图登记路径不符合固定套图位置')
            result['chain_image'] = relative.as_posix()
    return result


def legacy_roots(ws: Path) -> set:
    """Recover old roots only from fixed-location files whose copied bytes still match.

    Migration backups preserve this evidence after the live records become relative.
    No request, sidecar, digest or acceptance record is rewritten.
    """
    ws = Path(ws).resolve()
    roots = set()
    ledgers = list((ws / 'outputs/sets').glob('*/set.json'))
    ledgers += list((ws / 'outputs/sets').glob(f'*/set.json{BACKUP_SUFFIX}*.bak'))
    consents = [ws / 'consent.json', *ws.glob(f'consent.json{BACKUP_SUFFIX}*.bak')]
    for path in ledgers + consents:
        if not path.resolve().is_relative_to(ws):
            continue
        try:
            doc = json.loads(path.read_text(encoding='utf-8'))
            if path in ledgers:
                if doc.get('set_id') != path.parent.name:
                    continue
                anchors = [(doc.get('chain_image'), Path('outputs/sets') / path.parent.name / 'chain.png',
                            doc.get('chain_sha256'))]
            else:
                anchors = [(p.get('archived_path'), Path('input/originals') / Path(p.get('archived_path', '')).name,
                            p.get('sha256')) for p in doc.get('photos', []) if isinstance(p, dict)]
            for value, relative, digest in anchors:
                root = _old_root(value, relative)
                local = (ws / relative).resolve()
                if root and local.is_relative_to(ws) and local.is_file() and sha256_file(local) == digest:
                    roots.add(root)
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return roots


def local_path(ws: Path, value: str) -> Path:
    """Resolve a workspace reference, accepting a provable legacy workspace prefix."""
    ws = Path(ws).resolve()
    path = Path(value)
    if '..' in path.parts:
        raise CardError('project_reference_outside_workspace', '工作区引用不能包含上级目录')
    if path.is_absolute() and path.resolve().is_relative_to(ws):
        return path.resolve()
    if path.is_absolute() and not path.is_relative_to(ws):
        candidates = {ws / path.relative_to(root) for root in legacy_roots(ws) if path.is_relative_to(root)}
        if len(candidates) != 1:
            raise CardError('project_reference_outside_workspace', '无法唯一关联旧工作区路径；请核对项目引用')
        path = candidates.pop()
    path = (ws / path).resolve()
    if not path.is_relative_to(ws):
        raise CardError('project_reference_outside_workspace', '项目引用必须位于当前私有工作区内')
    return path


def workspace_document(ws: Path, doc: dict, kind: str) -> dict:
    """Normalise only known mutable location fields, in memory for read operations."""
    if kind == 'ledger':
        return ledger_paths(ws, doc)
    result = copy.deepcopy(doc)
    def relative(value):
        return local_path(ws, value).relative_to(Path(ws).resolve()).as_posix()
    if kind == 'project':
        for key in ('photo_refs',):
            if key in result:
                result[key] = [relative(v) for v in result[key]]
        if 'cards' in result['character']:
            result['character']['cards'] = [relative(v) for v in result['character']['cards']]
        for series in result['series']:
            for entry in series['sets']:
                entry['card'] = relative(entry['card'])
                for shot in entry.get('shots', []):
                    for candidate in shot['candidates']:
                        candidate['scene_card'] = relative(candidate['scene_card'])
    elif kind == 'set':
        def local_reference(value):
            path = Path(value)
            if not path.is_absolute():
                return value  # Execution validates relative paths before using them.
            # Explicit external uploads remain external, as before. Only proven
            # workspace paths are stored relative; history and scene content stay intact.
            if path.is_absolute() and not path.resolve().is_relative_to(Path(ws).resolve()):
                if not any(path.is_relative_to(root) for root in legacy_roots(ws)):
                    return value
            return relative(value)
        if result.get('mood_ref'):
            result['mood_ref'] = local_reference(result['mood_ref'])
        if result.get('pet'):
            result['pet']['ref'] = local_reference(result['pet']['ref'])
    elif kind == 'consent':
        for photo in result.get('photos', []):
            if photo.get('archived_path'):
                photo['archived_path'] = relative(photo['archived_path'])
            # The source path is provenance and may legitimately live outside WS.
    return result


def write_workspace_document(path: Path, doc: dict, kind: str, ws: Path) -> None:
    """Write the migrated form atomically, backing up exact old bytes once per content."""
    path = Path(path)
    if not path.resolve().is_relative_to(Path(ws).resolve()):
        raise CardError('project_reference_outside_workspace', '记录文件必须位于当前私有工作区内')
    result = workspace_document(ws, doc, kind)
    raw = path.read_bytes() if path.is_file() else None
    if raw is not None:
        old = json.loads(raw)
        if workspace_document(ws, old, kind) != old:
            backup = path.with_name(path.name + BACKUP_SUFFIX + sha256_file(path) + '.bak')
            # O_EXCL refuses symlinks and never overwrites an earlier backup.
            try:
                fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                if backup.is_symlink() or backup.read_bytes() != raw:
                    raise CardError('migration_backup_mismatch', '迁移备份不一致，已停止写入')
            else:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(raw)
    content = json.dumps(result, ensure_ascii=False, indent=2).encode('utf-8')
    if raw == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.migrate-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
