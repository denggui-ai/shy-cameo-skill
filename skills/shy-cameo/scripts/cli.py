#!/usr/bin/env python3
"""shy-cameo command line. Every subcommand prints exactly one JSON object.

Exit codes: 0 = ok, 2 = blocked or failed status (see the JSON "status" field).
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
from contextlib import ExitStack
from functools import wraps
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from coshoot import (audit, backend_exec, compiler, frame, label, library, likeness,  # noqa: E402
                     gallery, migrate, names, photo, png, preflight, projects, rules, sets)
from coshoot.cards import CardError, find_variant, load_json, require_valid  # noqa: E402
from coshoot.findings import worst, worst_level  # noqa: E402

EXIT_OK = 0
EXIT_BLOCKED = 2


def serialized(fn):
    """Reject overlapping mutations; OS releases the lock after a crash."""
    @wraps(fn)
    def wrapped(a):
        ws = Path(a.workspace).resolve()
        ws.mkdir(parents=True, exist_ok=True)
        with ExitStack() as stack:
            roots = {ws}
            if fn.__name__ == 'cmd_generate_exec':
                roots.add(Path(a.request).resolve().parent)
            for root in sorted(roots):
                root.mkdir(parents=True, exist_ok=True)
                lock = stack.enter_context((root / '.shy-cameo.lock').open('a'))
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise CardError('workspace_busy', '该工作区或请求已有操作进行中，请查账后再操作；不要重复提交')
            return fn(a)
    return wrapped


def emit(obj: dict, code: int = EXIT_OK) -> int:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    return code


def _codex_home(value):
    return Path(value) if value else Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))


def cmd_preflight(a):
    found = preflight.preflight(Path(a.workspace))
    level = worst(found)
    return emit({"level": level, "findings": [f.to_dict() for f in found]},
                EXIT_BLOCKED if level == "block" else EXIT_OK)


def cmd_fetch(a):
    paths = library.fetch_card_assets(load_json(a.card), Path(a.workspace) / "cache" / "library")
    return emit({"status": "fetched", "paths": [str(p) for p in paths]})


def cmd_photo_check(a):
    reports = [photo.check_photo(Path(p)).to_dict() for p in a.photos]
    level = worst_level([r["level"] for r in reports])
    return emit({"level": level, "reports": reports}, EXIT_BLOCKED if level == "block" else EXIT_OK)


def cmd_scan_names(a):
    result = names.classify(a.text, names.load_names())
    if result["blocked"]:
        return emit({"status": "blocked_name", **result}, EXIT_BLOCKED)
    return emit({"status": "ok", **result})


def cmd_consent(a):
    consent = {"subject_confirmed": a.subject, "adult_confirmed": a.adult,
               "self_or_consented": a.self_or_consented, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    label.check_consent(consent)
    out = Path(a.workspace) / "consent.json"
    # Append by default so registering a new photo never evicts an earlier one (POC U5).
    previous = [] if a.reset or not out.is_file() else (load_json(out).get("photos") or [])
    photos = [p for p in previous if isinstance(p, dict) and p.get("sha256")]
    seen = {p["sha256"] for p in photos}
    for p in a.photo:
        path = Path(p).resolve()
        if not path.is_file():
            raise CardError("no_user_photo", f"找不到照片：{p}")
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        size = png.image_size(path)
        suffix = ".png" if raw.startswith(b"\x89PNG\r\n\x1a\n") else ".jpg" if raw.startswith(b"\xff\xd8") else ".bin"
        root = out.parent.resolve()
        archive = root / "input" / "originals" / (sha + suffix)
        # A symlinked input/ or originals/ would copy the private photo out of the workspace.
        if not archive.parent.resolve().is_relative_to(root):
            raise CardError("photo_archive_outside_workspace", "私有原照副本目录指向工作区外，已停止，不复制照片")
        archive.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if archive.is_symlink() or library.sha256_file(archive) != sha:
                raise CardError("photo_archive_changed", "私有原照副本与摘要不符，请核对；不会覆盖已有副本")
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
        metadata = {"archived_path": str(archive), "byte_size": len(raw),
                    "dimensions": list(size) if size else None}
        if sha not in seen:
            photos.append({"path": str(path), "sha256": sha, **metadata})
            seen.add(sha)
        else:
            for record in photos:
                if record["sha256"] == sha:
                    record.update(metadata)
    consent["photos"] = photos
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(consent, ensure_ascii=False, indent=2), encoding="utf-8")
    return emit({"status": "consent_recorded", "path": str(out), **consent})


def _load_characters(paths) -> dict:
    characters = {}
    for card_path in paths or []:
        card = load_json(card_path)
        require_valid(card, "character")
        characters[f"{card['ip']}/{card['id']}"] = card
    return characters


def _consented_photos(ws: Path, photo_args) -> list:
    for p in photo_args:
        if not Path(p).is_file():
            raise CardError("no_user_photo", f"找不到照片：{p}")
    consent_path = ws / "consent.json"
    label.check_photo_consent(load_json(consent_path) if consent_path.is_file() else {},
                              [Path(p) for p in photo_args])
    return [Path(p).resolve() for p in photo_args]


def _set_context(a, check_shots: bool = True):
    """check_shots=False only for bookkeeping (set-record/set-status): a claim made before a rule
    changed (e.g. side_profile retired) must still be recordable."""
    ws = Path(a.workspace).resolve()
    card = load_json(a.set_card)
    if check_shots:
        sets.validate_set_card(card)
    else:
        sets.require_set_shape(card)
    return ws, card, sets.load_ledger(ws, card)


def _user_ref(ws: Path, raw: str, what: str, code: str) -> Path:
    """A set-wide user-supplied image: absolute, consented by bytes, never under sheet roots."""
    path = Path(raw)
    if not path.is_absolute():
        raise CardError(f"{code}_not_absolute", f"{what}要写完整路径：{raw}")
    if not path.is_file():
        raise CardError(f"missing_{code}", f"找不到{what}：{raw}")
    path = path.resolve()
    # generate-exec trusts sheet roots and set chain images under outputs/ without a consent check.
    for root in _sheet_roots(ws) + [(ws / "outputs").resolve()]:
        if path.is_relative_to(Path(root).resolve()):
            raise CardError(f"{code}_bad_location", f"{what}不能放在定妆表或生成结果目录里：{raw}")
    consent_path = ws / "consent.json"
    label.check_photo_consent(load_json(consent_path) if consent_path.is_file() else {}, [path])
    return path


def _mood_ref(ws: Path, card: dict) -> Optional[Path]:
    raw = card.get("mood_ref")
    return _user_ref(ws, raw, "氛围参考图", "mood_ref") if raw else None


def _pet(ws: Path, card: dict) -> Optional[dict]:
    pet = card.get("pet")
    if not pet:
        return None
    return {"ref": _user_ref(ws, pet["ref"], "宠物照", "pet_ref"), "kind": pet["kind"],
            **({"look": pet["look"]} if pet.get("look") else {})}


def _mood_sha(mood: Optional[Path]) -> Optional[str]:
    return library.sha256_file(mood) if mood is not None else None


def _pet_sha(pet: Optional[dict]) -> Optional[str]:
    return library.sha256_file(pet["ref"]) if pet is not None else None


def _compile_set_shot(ws: Path, card: dict, index: int, photos: list, characters: dict, chain):
    return compiler.compile_request(
        card["shots"][index - 1], characters, photos, _sheet_resolver(ws), names.load_names(),
        chain_ref=chain, set_info={"set_id": card["set_id"], "index": index, "role": sets.ROLES[index - 1]},
        chain_props=compiler.props_shown(card["shots"][0]), mood_ref=_mood_ref(ws, card), pet=_pet(ws, card))


def _precheck_set(ws: Path, card: dict, photos: list, characters: dict, start: int = 1) -> None:
    """Dry-compile shots start..last before shot `start` is claimed: a bad later shot must not strand
    a paid set (also when the card was edited after image 1).

    Nothing is written or claimed; later shots use the chain path image 1 is (or will be) copied to.
    """
    sets.check_episode_match(card["shots"], characters)
    chain = sets.set_dir(ws, card["set_id"]) / sets.CHAIN_NAME
    for index in range(start, sets.SET_SIZE + 1):
        _compile_set_shot(ws, card, index, photos, characters, chain if index > 1 else None)


def _compile_shot(ws: Path, card: dict, ledger: dict, index: int, photos: list, characters: dict):
    sets.require_claimable(ledger, index)
    chain = sets.chain_ref(ws, card, ledger) if index > 1 else None
    mood_sha = _mood_sha(_mood_ref(ws, card))
    pet_sha = _pet_sha(_pet(ws, card))
    if index == 1:
        ledger["mood_ref_sha256"] = mood_sha
        ledger["pet_ref_sha256"] = pet_sha
    else:
        sets.check_mood_ref(ledger, mood_sha)
        sets.check_pet_ref(ledger, pet_sha)
    request = _compile_set_shot(ws, card, index, photos, characters, chain)
    path = compiler.write_request(request, ws / "outputs" / request["run_id"])
    sets.claim(ledger, index, request["run_id"])
    sets.save_ledger(ws, card, ledger)
    return request, path


@serialized
def cmd_compile_shot(a):
    ws, card, ledger = _set_context(a)
    if a.index == 1:
        projects.require_continue(ws, card["set_id"])
    photos = _consented_photos(ws, a.photo)
    characters = _load_characters(a.character)
    sets.require_claimable(ledger, a.index)
    _precheck_set(ws, card, photos, characters, start=a.index)
    request, path = _compile_shot(ws, card, ledger, a.index, photos, characters)
    return emit({"status": "compiled", "request_path": str(path), "run_id": request["run_id"],
                 "set_id": card["set_id"], "index": a.index, "role": sets.ROLES[a.index - 1],
                 "referenced_image_paths": request["referenced_image_paths"]})


@serialized
def cmd_set_record(a):
    ws, card, ledger = _set_context(a, check_shots=False)
    sets.record(ws, ledger, a.index, a.status, a.image)
    sets.save_ledger(ws, card, ledger)
    return emit(ledger)


def cmd_set_status(a):
    _, _, ledger = _set_context(a, check_shots=False)
    return emit(ledger)


def cmd_project_status(a):
    result = projects.status(Path(a.workspace), a.project)
    return emit(result, EXIT_BLOCKED if result["issues"] else EXIT_OK)


def cmd_gallery(a):
    result = gallery.build(Path(a.workspace), a.project)
    return emit(result, EXIT_BLOCKED if result["issues"] else EXIT_OK)


# Timeouts and missing images may still have been generated and billed: check before going on.
UNKNOWN_RESULTS = {"failed_timeout", "failed_no_image"}


@serialized
def cmd_project_continue(a):
    doc = projects.mark_continue(Path(a.workspace), a.set_id, a.project)
    return emit({"status": "continue_recorded", "set_id": a.set_id, "continued": doc["continued"]})


def _check_cover_likeness(ws: Path, card: dict, ledger: dict, photos: list):
    """D34: score a generated face cover once and keep the result in the ledger.

    Image 1 becomes every later shot's reference, so a drifted face must not spread. A stored result
    means the user already saw the pause; resuming after it is their go-ahead. Returns None if skipped.
    """
    item = sets.item(ledger, 1)
    if ("cover_likeness" in ledger or item["status"] != "generated" or not ledger.get("chain_image")
            or card["shots"][0]["user"].get("presence", "face") != "face"):
        return None
    ledger["cover_likeness"] = likeness.score(photos, Path(ledger["chain_image"]), ws)
    return ledger["cover_likeness"]


def _likeness_paused(card: dict, quota_used: int, results: list) -> int:
    # Shots 2..5 stay pending: the user compares image 1 first, then --resume or retake the set.
    return emit({"status": "set_paused_likeness", "set_id": card["set_id"], "quota_used": quota_used,
                 "results": results,
                 "message": "首图机器比脸分偏低，已停在第 1 张：先给用户比脸；用户说像再用 --resume 拍后 4 张，"
                            "不像就改卡另起一套，不拿这张当后几张的参考"}, EXIT_BLOCKED)


@serialized
def cmd_generate_set(a):
    ws, card, ledger = _set_context(a)
    projects.require_continue(ws, card["set_id"])
    resume = getattr(a, "resume", False)
    todo = [it["index"] for it in ledger["items"] if it["status"] == "pending"]
    needed = len(todo) if resume else sets.SET_SIZE
    if a.authorized_count < needed:
        return emit({"status": "blocked_quota", "set_id": card["set_id"], "quota_used": 0, "results": [],
                     "message": f"本次要拍 {needed} 张，需要一次授权 {needed} 次生图额度"},
                    EXIT_BLOCKED)
    if resume:
        if any(it["status"] == "claimed" for it in ledger["items"]):
            raise CardError("set_has_unknown", "还有结果未核对的张，先核对并用 set-record 登记")
        if not todo:
            raise CardError("nothing_to_resume", "这套没有未提交的张")
    elif len(todo) != sets.SET_SIZE:
        raise CardError("set_already_started", "这套照片已经开始生成；核对后可用 --resume 只拍未提交的张，"
                        "单张重拍请走 compile + generate-exec 并重新授权")
    photos = _consented_photos(ws, a.photo)
    photo_hashes = [library.sha256_file(p) for p in photos]
    characters = _load_characters(a.character)
    _precheck_set(ws, card, photos, characters, start=todo[0])
    if resume and todo[0] > 1:
        # A cover recorded by hand (e.g. after an unknown result) has not been compared yet.
        checked = _check_cover_likeness(ws, card, ledger, photos)
        if checked is not None:
            sets.save_ledger(ws, card, ledger)
            if checked["status"] == "low":
                return _likeness_paused(card, 0, [{"index": 1, "status": "generated", "likeness": checked}]
                                        + [{"index": i, "status": "pending"} for i in todo])
    results = []
    submitted_count = 0
    paused = False
    likeness_low = False

    def progress(entry):
        # One line per shot so a host running this in the background can report progress.
        print(json.dumps({"event": "shot_done", "set_id": card["set_id"], "index": entry["index"],
                          "status": entry.get("status"), "done": len(results), "of": len(todo)},
                         ensure_ascii=False), file=sys.stderr, flush=True)

    for index in todo:
        if sets.item(ledger, index)["status"] == "cancelled":
            results.append({"index": index, "status": "cancelled"})
            progress(results[-1])
            continue
        entry = {"index": index}
        try:
            _consented_photos(ws, a.photo)
            if [library.sha256_file(p) for p in photos] != photo_hashes:
                raise CardError('blocked_consent', '本套确认的照片已变化，请停止并重新确认照片与分镜')
            request, path = _compile_shot(ws, card, ledger, index, photos, characters)
            compiler.check_reference_hashes(path, request)
            entry.update(run_id=request["run_id"], request_path=str(path))
            # Count before submitting: a timeout or refusal still consumes the credit.
            (path.parent / "generation-count").write_text("1")
            submitted_count += 1
            try:
                result = backend_exec.run_exec(path, path.parent, ws.resolve(), codex=a.codex, timeout=a.timeout)
                status, image, message = result.status, result.image_path, result.message
            except OSError as exc:
                status, image, message = "failed_no_image", None, f"{exc}；额度可能已扣，不会自动重试"
            entry.update(status=status, image_path=image, message=message)
            outcome = {"generated": "generated", "blocked_platform_input": "rejected"}.get(status)
            if outcome is None or status in UNKNOWN_RESULTS:
                # Keep the shot claimed for checking; submit nothing more in this run.
                entry["message"] = f"{message}；结果未知，已暂停：先核对，再用 set-record 登记"
                paused = True
            else:
                sets.record(ws, ledger, index, outcome, image)
                if index == 1:
                    entry["likeness"] = _check_cover_likeness(ws, card, ledger, photos)
                    likeness_low = (entry["likeness"] or {}).get("status") == "low"
        except (CardError, OSError) as exc:
            # Keep the honest result so far instead of aborting: credits may already be spent.
            entry.update(status=getattr(exc, "code", "failed_no_image"),
                         message=getattr(exc, "message", str(exc)))
            if sets.item(ledger, index)["status"] == "claimed":
                try:
                    sets.record(ws, ledger, index, "failed")
                except (CardError, OSError) as rec_exc:
                    entry["message"] = f"{entry.get('message', '')}；账本记录失败：{rec_exc}"
            if index == 1:
                # Image 1 has no usable result: later images must never be submitted.
                for other in ledger["items"][1:]:
                    if other["status"] == "pending":
                        other["status"] = "cancelled"
        try:
            sets.save_ledger(ws, card, ledger)
        except (CardError, OSError) as save_exc:
            entry["message"] = f"{entry.get('message', '')}；账本记录失败：{save_exc}"
        results.append(entry)
        progress(entry)
        if paused or likeness_low:
            results.extend({"index": i, "status": "pending"} for i in todo if i > index)
            break
    if paused:
        return emit({"status": "set_paused_unknown", "set_id": card["set_id"],
                     "quota_used": submitted_count, "results": results}, EXIT_BLOCKED)
    if likeness_low:
        return _likeness_paused(card, submitted_count, results)
    done = all(it["status"] == "generated" for it in ledger["items"])
    return emit({"status": "set_generated" if done else "set_partial", "set_id": card["set_id"],
                 "quota_used": submitted_count, "results": results}, EXIT_OK if done else EXIT_BLOCKED)


def cmd_compile(a):
    ws = Path(a.workspace)
    for p in a.photo:
        if not Path(p).is_file():
            raise CardError("no_user_photo", f"找不到照片：{p}")
    consent_path = ws / "consent.json"
    uploads = [Path(p) for p in a.photo]
    if a.scene_ref:
        if not Path(a.scene_ref).is_file():
            raise CardError("missing_scene_ref", f"找不到场景参考图：{a.scene_ref}")
        uploads.append(Path(a.scene_ref))
    label.check_photo_consent(load_json(consent_path) if consent_path.is_file() else {}, uploads)
    characters = _load_characters(a.character)

    resolver = _sheet_resolver(ws)
    chain = mood = pet = None
    if getattr(a, "chain_set", None):
        chain_card = load_json(a.chain_set)
        sets.require_set_shape(chain_card)
        chain_ledger = sets.load_ledger(ws, chain_card)
        chain = sets.chain_ref(ws, chain_card, chain_ledger)
        mood = _mood_ref(ws, chain_card)
        sets.check_mood_ref(chain_ledger, _mood_sha(mood))
        pet = _pet(ws, chain_card)
        sets.check_pet_ref(chain_ledger, _pet_sha(pet))
    request = compiler.compile_request(
        load_json(a.scene), characters, [Path(p).resolve() for p in a.photo], resolver,
        names.load_names(), scene_ref=Path(a.scene_ref).resolve() if a.scene_ref else None,
        max_refs=a.max_refs, chain_ref=chain, mood_ref=mood, pet=pet)
    path = compiler.write_request(request, ws / "outputs" / request["run_id"])
    return emit({"status": "compiled", "request_path": str(path), "run_id": request["run_id"],
                 "referenced_image_paths": request["referenced_image_paths"]})


@serialized
def cmd_compile_edit(a):
    ws = Path(a.workspace).resolve()
    image = Path(a.image).resolve()
    if not image.is_file():
        raise CardError("missing_edit_image", f"找不到局部编辑底图：{a.image}")
    consent_path = ws / "consent.json"
    label.check_photo_consent(load_json(consent_path) if consent_path.is_file() else {}, [image])
    request = compiler.compile_edit_request(load_json(a.scene), image, a.instruction, names.load_names())
    path = compiler.write_request(request, ws / "outputs" / request["run_id"])
    return emit({"status": "compiled", "request_path": str(path), "run_id": request["run_id"],
                 "referenced_image_paths": request["referenced_image_paths"]})


def _unlinked_root(ws: Path, *parts: str) -> Optional[Path]:
    """ws/<parts> resolved, or None when any component below the workspace is a symlink."""
    path = ws
    for part in parts:
        path = path / part
        if path.is_symlink():
            return None
    return path.resolve()


def _sheet_roots(ws: Path) -> list:
    """Workspace directories whose images are sheets, never user photos."""
    return [(ws / "characters").resolve(), (ws / "cache" / "library").resolve()]


def _is_chain_image(ws: Path, ref: str) -> bool:
    """True only for outputs/sets/<set_id>/chain.png, the byte copy of set image 1."""
    path = Path(ref).resolve()
    sets_root = (ws / "outputs" / "sets").resolve()
    return path.name == sets.CHAIN_NAME and path.parent.parent == sets_root


def _sheet_resolver(ws: Path):
    """Resolve card sheets; a local sheet must sit under characters/, never be a user photo."""
    local_root = (ws / "characters").resolve()

    def resolver(asset):
        path = library.resolve_sheet(asset, ws / "cache" / "library", ws)
        if not library.is_remote(asset["url"]) and local_root not in path.parents:
            raise CardError("bad_sheet_ref", f"定妆表必须放在工作区 characters/ 目录下：{asset['url']}")
        return path

    return resolver


def _check_sheet_request(request: dict, ws: Path) -> None:
    """A sheet request carries no user photo; its only reference must be a workspace sheet."""
    require_valid(request, "sheet_request")
    roots = _sheet_roots(ws)
    for ref in request["referenced_image_paths"]:
        # Codex resolves relative refs against the workspace, not this process cwd.
        if not Path(ref).is_absolute():
            raise CardError("bad_sheet_ref", f"定妆表请求的参考图必须是绝对路径：{ref}")
        path = Path(ref).resolve()
        if not any(root in path.parents for root in roots):
            raise CardError("bad_sheet_ref", f"定妆表请求只能参考工作区里的定妆表：{ref}")


@serialized
def cmd_generate_exec(a):
    ws = Path(a.workspace)
    request_path = Path(a.request).resolve()
    run_dir = request_path.parent
    if a.authorized_count < 1:
        return emit({"status": "blocked_quota", "message": "未获得生图授权"}, EXIT_BLOCKED)
    if (run_dir / "sidecar.json").exists():
        raise CardError("already_delivered", "这次生成已经交付过；再拍一张请重新编译")
    counter = run_dir / "generation-count"
    used = int(counter.read_text()) if counter.is_file() else 0
    if used >= a.authorized_count:
        return emit({"status": "blocked_quota",
                     "message": f"本次授权的 {a.authorized_count} 张已用完，请重新授权"}, EXIT_BLOCKED)
    request = load_json(request_path)
    is_sheet = request.get("kind") == "sheet"
    require_valid(request, "sheet_request" if is_sheet else "request")
    # Codex resolves relative refs against the workspace, not this process cwd.
    for ref in request["referenced_image_paths"]:
        if not Path(ref).is_absolute():
            if is_sheet:
                raise CardError("bad_sheet_ref", f"定妆表请求的参考图必须是绝对路径：{ref}")
            raise CardError("bad_request_ref", f"请求中的参考图必须是绝对路径：{ref}")
    if is_sheet:
        _check_sheet_request(request, ws)
    else:
        consent_path = ws / "consent.json"
        # Exempt only through real directories: a symlinked root swapped in after compile
        # would otherwise lift the consent recheck from a user-supplied image.
        roots = [r for r in (_unlinked_root(ws, "characters"), _unlinked_root(ws, "cache", "library")) if r]
        sets_ok = _unlinked_root(ws, "outputs", "sets") is not None
        photos = [Path(r) for r in request["referenced_image_paths"]
                  if not (any(root in Path(r).resolve().parents for root in roots)
                          or (sets_ok and _is_chain_image(ws, r)))]
        label.check_photo_consent(load_json(consent_path) if consent_path.is_file() else {}, photos)
    # Integrity and names are re-checked here because the request file is editable after compile.
    if compiler._body_sha256(request["prompt"], request["referenced_image_paths"]) != request["sha256"]:
        raise CardError("request_tampered", "request.json 在编译后被改动，请重新编译")
    compiler._check_names([request["prompt"]], names.load_names())
    compiler.check_reference_hashes(request_path, request)
    # Count before running: a timeout or failure still consumes quota.
    counter.write_text(str(used + 1))
    try:
        result = backend_exec.run_exec(request_path, run_dir, ws.resolve(), codex=a.codex, timeout=a.timeout)
    except OSError as exc:
        return emit({"status": "error", "error": "OSError",
                     "message": f"{exc}；额度可能已扣，不会自动重试"}, 1)
    return emit(result.to_dict(), EXIT_OK if result.status == "generated" else EXIT_BLOCKED)


def cmd_compile_sheet(a):
    ws = Path(a.workspace)

    request = compiler.compile_sheet_request(load_json(a.character), a.variant, a.sheet, _sheet_resolver(ws),
                                             names.load_names(), ref_variant=a.ref_variant)
    path = compiler.write_request(request, ws / "outputs" / request["run_id"])
    return emit({"status": "compiled", "kind": "sheet", "request_path": str(path),
                 "run_id": request["run_id"], "referenced_image_paths": request["referenced_image_paths"]})


def cmd_attach_sheet(a):
    ws = Path(a.workspace).resolve()
    card_path = Path(a.character)
    card = load_json(card_path)
    require_valid(card, "character")
    if card["status"] not in compiler.SHEET_STATUSES:
        raise CardError("sheet_not_temp", f"只有临时角色卡可以挂定妆表：{card['name']}")
    variant = find_variant(card, a.variant)
    image = Path(a.image)
    if image.suffix.lower() != ".png":
        raise CardError("bad_image", f"定妆表必须是 Codex 生成的 PNG 原图：{a.image}")
    try:
        with open(image, "rb") as fh:
            signature = fh.read(8)
    except OSError:
        signature = b""
    if signature != b"\x89PNG\r\n\x1a\n":
        raise CardError("bad_image", f"定妆表文件不是有效的 PNG：{a.image}")
    rel = f"characters/{card['ip']}-{card['id']}/{a.variant}-{a.sheet}.png"
    dest = ws / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Copy to a sibling first so a failed attach never clobbers an existing sheet.
    part = dest.with_suffix(".png.part")
    shutil.copyfile(image, part)
    sha = library.sha256_file(part)
    if sha != library.sha256_file(image):
        part.unlink()
        raise CardError("copy_mismatch", "定妆表复制后哈希不一致")
    os.replace(part, dest)
    variant.setdefault("sheets", {})[a.sheet] = {"url": rel, "sha256": sha, "bytes": dest.stat().st_size}
    variant["lookalike_check"] = {"status": "pending"}  # a new image voids the old lookalike check
    card["status"] = "temp_draft"  # a changed sheet always needs the user's confirmation again
    require_valid(card, "character")
    card_path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
    return emit({"status": "attached", "card_status": card["status"], "sheet": variant["sheets"][a.sheet],
                 "c2pa_present": png.has_c2pa(dest)})


def cmd_verify(a):
    request_path = Path(a.request).resolve()
    request = load_json(request_path)
    compiler.check_request_integrity(request)
    if a.log:
        paths = [Path(p) for p in a.log]
    else:
        paths = audit.find_rollouts(_codex_home(a.codex_home), request_path, request_path.stat().st_mtime)
    result = audit.audit_files(paths, request, request_path, names.load_names(), scope_to_request=not bool(a.log)).to_dict()
    result.update(run_id=request['run_id'], request_sha256=request['sha256'])
    (request_path.parent / "audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                                    encoding="utf-8")
    return emit(result)


def cmd_frame_check(a):
    result = frame.check_frame(Path(a.image), a.framing)
    if a.out:
        Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return emit(result, EXIT_BLOCKED if result['level'] == 'block' else EXIT_OK)


def cmd_likeness_check(a):
    # Advisory: never blocks; a low score means "show the user before using this face".
    return emit(likeness.score([Path(p) for p in a.photo], Path(a.image), Path(a.workspace)))


def cmd_deliver(a):
    request_path = Path(a.request).resolve()
    consent_path = Path(a.workspace) / "consent.json"
    request = load_json(request_path)
    compiler.check_request_integrity(request)
    audit_result = load_json(a.audit) if a.audit else {'status': 'unverified', 'reason': '未运行事后审计'}
    frame_result = load_json(a.frame) if a.frame else None
    if a.audit and (audit_result.get('run_id') != request['run_id'] or audit_result.get('request_sha256') != request['sha256']):
        raise CardError('qa_mismatch', '审计记录不属于本次请求，请重新 verify')
    if a.frame and frame_result.get('image_sha256') != library.sha256_file(Path(a.image)):
        raise CardError('qa_mismatch', '构图记录不属于这张图片，请重新 frame-check')
    if not a.audit or not a.frame or frame_result.get('level') == 'block':
        raise CardError('qa_incomplete', '交付前请完成本次 verify 和 frame-check，再带两份记录交付')
    sidecar = label.deliver(
        Path(a.image), request_path.parent, request,
        load_json(consent_path) if consent_path.is_file() else {},
        audit_result, frame_result, a.cli_version, badge=a.badge)
    return emit(sidecar)


def cmd_record_verdict(a):
    path = Path(a.run_dir) / "sidecar.json"
    sidecar = load_json(path)
    request = load_json(path.parent / 'request.json')
    compiler.check_request_integrity(request)
    images = [p for p in path.parent.glob('image.*') if p.suffix.lower() in ('.png', '.jpg', '.jpeg')]
    if (request['run_id'] != sidecar['run_id'] or request['sha256'] != sidecar['request_sha256']
            or len(images) != 1 or library.sha256_file(images[0]) != sidecar['original_sha256']):
        raise CardError('delivery_changed', '交付图片或请求已变化，不能沿用此前的验收记录')
    checks = {"likeness": a.likeness == "yes", "character": a.character == "yes",
              "no_face_mix": a.no_face_mix == "yes"}
    if getattr(a, "goal", None):
        checks["goal_met"] = a.goal == "yes"
    if all(checks.values()) and (sidecar['audit'].get('run_id') != request['run_id']
            or sidecar['audit'].get('request_sha256') != request['sha256']
            or not sidecar.get('frame_check')
            or sidecar['frame_check'].get('image_sha256') != sidecar['original_sha256']
            or sidecar['frame_check'].get('level') == 'block'):
        raise CardError('qa_incomplete', '接受前请完成属于本次请求和图片的 verify、frame-check 与交付')
    if all(checks.values()) and sidecar['audit'].get('status') == 'tampered':
        # The sidecar and audit.json stay untouched as evidence; unverified is still acceptable.
        raise CardError('audit_tampered', '本次调用审计为 tampered（' + str(sidecar['audit'].get('reason', '')) +
                        '），不能记为正式 accepted；问题记录已保留在 sidecar 与 audit.json。可记 rejected，或重新编译后按新请求生成')
    sidecar["self_check"] = {**checks, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    sidecar["verdict"] = "accepted" if all(checks.values()) else "rejected"
    require_valid(sidecar, "sidecar")
    path.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8")
    return emit({"status": "verdict_recorded", "verdict": sidecar["verdict"],
                 "self_check": sidecar["self_check"]})


def cmd_validate_library(a):
    lib = Path(a.library) if a.library else rules.DEFAULT_LIBRARY
    errors = rules.library_errors(lib, names.load_names())
    return emit({"ok": not errors, "errors": errors}, EXIT_BLOCKED if errors else EXIT_OK)


def cmd_migrate(a):
    return emit(migrate.migrate(load_json(a.card), a.kind))


def cmd_asset_info(a):
    root = Path(a.workspace).resolve()
    path = Path(a.file).resolve()
    if root not in path.parents:
        raise CardError("asset_outside_workspace", f"文件不在工作区内：{a.file}")
    return emit({"url": path.relative_to(root).as_posix(), "sha256": library.sha256_file(path),
                 "bytes": path.stat().st_size})


def cmd_promote_card(a):
    card = load_json(a.character)
    require_valid(card, "character")
    hits = names.scan(json.dumps(card, ensure_ascii=False), names.load_names())
    if hits:
        raise CardError("blocked_name", "角色卡中出现真实演员姓名：" + "、".join(sorted({h.matched for h in hits})))
    gold, uploads = library.promote_card(card, a.release_base, Path(a.workspace), Path(a.stage))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(gold, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return emit({"status": "promoted", "card_path": str(out), "uploads": uploads})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cli.py", description="shy-cameo engine")
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("preflight")
    s.add_argument("--workspace", required=True)
    s.set_defaults(func=cmd_preflight)

    s = sub.add_parser("fetch")
    s.add_argument("--card", required=True)
    s.add_argument("--workspace", required=True)
    s.set_defaults(func=cmd_fetch)

    s = sub.add_parser("photo-check")
    s.add_argument("photos", nargs="+")
    s.set_defaults(func=cmd_photo_check)

    s = sub.add_parser("scan-names")
    s.add_argument("--text", required=True)
    s.set_defaults(func=cmd_scan_names)

    s = sub.add_parser("consent")
    s.add_argument("--workspace", required=True)
    s.add_argument("--subject", action="store_true")
    s.add_argument("--adult", action="store_true")
    s.add_argument("--self-or-consented", action="store_true")
    s.add_argument("--photo", action="append", required=True)
    s.add_argument("--reset", action="store_true")
    s.set_defaults(func=cmd_consent)

    s = sub.add_parser("compile")
    s.add_argument("--scene", required=True)
    s.add_argument("--character", action="append")
    s.add_argument("--photo", action="append", required=True)
    s.add_argument("--scene-ref")
    s.add_argument("--chain-set", help="重拍时沿用该套图已登记并校验过的首图参考")
    s.add_argument("--workspace", required=True)
    s.add_argument("--max-refs", type=int, default=compiler.MAX_REFS)
    s.set_defaults(func=cmd_compile)

    s = sub.add_parser("compile-edit", help="从指定底图编译局部编辑请求；只写请求，不提交生图")
    s.add_argument("--scene", required=True)
    s.add_argument("--image", required=True, help="已获准使用的局部编辑底图")
    s.add_argument("--instruction", required=True, help="本次明确修改及保留项")
    s.add_argument("--workspace", required=True)
    s.set_defaults(func=cmd_compile_edit)

    s = sub.add_parser("compile-sheet")
    s.add_argument("--character", required=True)
    s.add_argument("--variant", required=True)
    s.add_argument("--sheet", required=True, choices=["head", "body"])
    s.add_argument("--ref-variant")
    s.add_argument("--workspace", required=True)
    s.set_defaults(func=cmd_compile_sheet)

    s = sub.add_parser("attach-sheet")
    s.add_argument("--character", required=True)
    s.add_argument("--variant", required=True)
    s.add_argument("--sheet", required=True, choices=["head", "body"])
    s.add_argument("--image", required=True)
    s.add_argument("--workspace", required=True)
    s.set_defaults(func=cmd_attach_sheet)

    s = sub.add_parser("generate-exec")
    s.add_argument("--request", required=True)
    s.add_argument("--workspace", required=True)
    s.add_argument("--authorized-count", type=int, required=True)
    s.add_argument("--codex", default="codex")
    s.add_argument("--timeout", type=int, default=backend_exec.DEFAULT_TIMEOUT)
    s.set_defaults(func=cmd_generate_exec)

    s = sub.add_parser("compile-shot")
    s.add_argument("--set-card", required=True)
    s.add_argument("--index", type=int, required=True, choices=range(1, len(sets.ROLES) + 1))
    s.add_argument("--character", action="append")
    s.add_argument("--photo", action="append", required=True)
    s.add_argument("--workspace", required=True)
    s.set_defaults(func=cmd_compile_shot)

    s = sub.add_parser("set-record")
    s.add_argument("--set-card", required=True)
    s.add_argument("--workspace", required=True)
    s.add_argument("--index", type=int, required=True, choices=range(1, len(sets.ROLES) + 1))
    s.add_argument("--status", required=True, choices=["generated", "rejected", "failed"])
    s.add_argument("--image")
    s.set_defaults(func=cmd_set_record)

    s = sub.add_parser("set-status")
    s.add_argument("--set-card", required=True)
    s.add_argument("--workspace", required=True)
    s.set_defaults(func=cmd_set_status)

    s = sub.add_parser("project-status", help="只读汇总角色项目；不提交、不恢复生图")
    s.add_argument("--workspace", required=True)
    s.add_argument("--project", default="project.json", help="相对工作区路径或工作区内绝对路径")
    s.set_defaults(func=cmd_project_status)

    s = sub.add_parser("project-continue", help="用户说“继续”后登记下一套可以开拍")
    s.add_argument("--workspace", required=True)
    s.add_argument("--set-id", required=True)
    s.add_argument("--project", default="project.json", help="相对工作区路径或工作区内绝对路径")
    s.set_defaults(func=cmd_project_continue)

    s = sub.add_parser("gallery", help="只读汇总项目，写本地作品页 WS/gallery.html；不生图")
    s.add_argument("--workspace", required=True)
    s.add_argument("--project", default="project.json", help="相对工作区路径或工作区内绝对路径")
    s.set_defaults(func=cmd_gallery)

    s = sub.add_parser("generate-set")
    s.add_argument("--set-card", required=True)
    s.add_argument("--character", action="append")
    s.add_argument("--photo", action="append", required=True)
    s.add_argument("--workspace", required=True)
    s.add_argument("--authorized-count", type=int, required=True)
    s.add_argument("--codex", default="codex")
    s.add_argument("--timeout", type=int, default=backend_exec.DEFAULT_TIMEOUT)
    s.add_argument("--resume", action="store_true", help="只拍账本中仍为 pending 的张")
    s.set_defaults(func=cmd_generate_set)

    s = sub.add_parser("verify")
    s.add_argument("--request", required=True)
    s.add_argument("--log", action="append")
    s.add_argument("--codex-home")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("frame-check")
    s.add_argument("image")
    s.add_argument("--framing", required=True, choices=list(compiler.FRAMING_TEXT))
    s.add_argument("--out")
    s.set_defaults(func=cmd_frame_check)

    s = sub.add_parser("likeness-check", help="露脸成图与本人照片机器比脸（仅供参考，像不像以用户为准）")
    s.add_argument("image")
    s.add_argument("--photo", action="append", required=True)
    s.add_argument("--workspace", required=True)
    s.set_defaults(func=cmd_likeness_check)

    s = sub.add_parser("deliver")
    s.add_argument("--image", required=True)
    s.add_argument("--request", required=True)
    s.add_argument("--workspace", required=True)
    s.add_argument("--audit")
    s.add_argument("--frame")
    s.add_argument("--cli-version")
    s.add_argument("--badge", action="store_true")
    s.set_defaults(func=cmd_deliver)

    s = sub.add_parser("record-verdict")
    s.add_argument("--run-dir", required=True)
    for flag in ("--likeness", "--character", "--no-face-mix"):
        s.add_argument(flag, required=True, choices=["yes", "no"])
    s.add_argument("--goal", choices=["yes", "no"], help="这张是否拍出了本套想要的感觉")
    s.set_defaults(func=cmd_record_verdict)

    s = sub.add_parser("validate-library")
    s.add_argument("--library")
    s.set_defaults(func=cmd_validate_library)

    s = sub.add_parser("migrate")
    s.add_argument("--kind", required=True, choices=["character", "scene", "request", "sidecar"])
    s.add_argument("card")
    s.set_defaults(func=cmd_migrate)

    s = sub.add_parser("asset-info")
    s.add_argument("file")
    s.add_argument("--workspace", required=True)
    s.set_defaults(func=cmd_asset_info)

    s = sub.add_parser("promote-card")
    s.add_argument("--character", required=True)
    s.add_argument("--release-base", required=True)
    s.add_argument("--workspace", required=True)
    s.add_argument("--stage", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(func=cmd_promote_card)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except CardError as exc:
        return emit({"status": exc.code, "message": exc.message}, EXIT_BLOCKED)
    except (FileNotFoundError, IsADirectoryError, ValueError, OSError, KeyError) as exc:
        return emit({"status": "error", "error": type(exc).__name__, "message": str(exc)}, 1)


if __name__ == "__main__":
    sys.exit(main())
