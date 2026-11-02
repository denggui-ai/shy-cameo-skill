"""Best-effort post-hoc audit of an image generation call against request.json.

Only the supported literal call form can be compared exactly. Unknown JS data
flow remains unverifiable; logs are never executed.
"""
from __future__ import annotations

import json
import re
import shlex
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Sequence, Tuple

from .names import NameEntry, scan

CALL_RE = re.compile(r"image_?gen\w*\s*\(")
CALL_KEYS = ("arguments", "input", "code", "command")
REVISED_KEYS = ("revisedPrompt", "revised_prompt")


@dataclass
class AuditResult:
    status: str  # pass | unverifiable | tampered
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


def _strings(obj, key: str = "") -> Iterator[Tuple[str, str]]:
    """Yield (key, string) pairs, descending into JSON-encoded strings."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v, key)
    elif isinstance(obj, str):
        stripped = obj.strip()
        if stripped[:1] in ("{", "["):
            try:
                yield from _strings(json.loads(stripped), key)
                return
            except ValueError:
                pass
        yield key, obj


def audit_lines(lines: Iterable[str], request: dict, request_path: Path,
                names: Sequence[NameEntry]) -> AuditResult:
    """Judge every generation call on its own: tampered > unverifiable > pass."""
    expected = request["prompt"]
    calls = 0
    unlinked = 0
    for raw in lines:
        try:
            record = json.loads(raw)
        except ValueError:
            unlinked += 1
            continue
        for key, text in _strings(record):
            if key in REVISED_KEYS:
                hits = scan(text, names)
                if hits:
                    return AuditResult("tampered", "改写后的提示词含真实演员姓名：" + hits[0].matched)
                continue
            if key not in CALL_KEYS or not CALL_RE.search(text):
                continue
            # Template interpolation can execute nested calls; do not infer its data flow.
            if '`' in text and '${' in text:
                unlinked += 1
            for match in _code_calls(text):
                calls += 1
                args = _literal_arguments(text[match.end():])
                if args is None:
                    unlinked += 1
                    continue
                if not isinstance(args.get('prompt'), str):
                    unlinked += 1
                    continue
                if scan(args['prompt'], names) or args['prompt'] != expected:
                    return AuditResult('tampered', '生图提示词与请求不一致或包含真实演员姓名')
                if 'referenced_image_paths' not in args or 'referenced_image_paths' not in request:
                    unlinked += 1
                elif args['referenced_image_paths'] != request['referenced_image_paths']:
                    return AuditResult('tampered', '生图参考路径与请求不一致')
    if calls == 0:
        return AuditResult("unverifiable", "无法审计：日志中未找到生图调用")
    if unlinked:
        return AuditResult("unverifiable", "无法审计：有生图调用无法关联到本次 request.json")
    if calls > 1:
        return AuditResult("tampered", "同一请求窗口发现多次可核对生图调用；不能视为一次已核验调用")
    return AuditResult("pass", "日志中的每次调用均含与请求一致的完整提示词和参考路径")


def _literal_arguments(text: str):
    """Only decode the known literal-object form; never evaluate JS or infer data flow."""
    tail = text.lstrip()
    if not tail.startswith('{'):
        return None
    tail = tail[1:].lstrip()
    args = {}
    decoder = json.JSONDecoder()
    try:
        while not tail.startswith('}'):
            key = re.match(r'(\w+)\s*:\s*', tail)
            if not key or key.group(1) in args:
                return None
            tail = tail[key.end():]
            value, end = decoder.raw_decode(tail)
            args[key.group(1)] = value
            tail = tail[end:].lstrip()
            if tail.startswith(','):
                tail = tail[1:].lstrip()
            elif not tail.startswith('}'):
                return None
        return args if re.match(r'}\s*\)', tail) else None
    except ValueError:
        return None


def _code_calls(text: str):
    """Ignore quoted examples/comments instead of treating them as executed calls."""
    pos = 0
    while pos < len(text):
        if text.startswith('//', pos):
            end = text.find('\n', pos + 2)
            pos = len(text) if end < 0 else end + 1
        elif text.startswith('/*', pos):
            end = text.find('*/', pos + 2)
            pos = len(text) if end < 0 else end + 2
        elif text[pos] in ('"', "'", '`'):
            quote = text[pos]; pos += 1
            while pos < len(text):
                if text[pos] == '\\':
                    pos += 2
                elif text[pos] == quote:
                    pos += 1
                    break
                else:
                    pos += 1
        else:
            match = CALL_RE.match(text, pos)
            if match:
                yield match
                pos = match.end()
            else:
                pos += 1


def find_rollouts(codex_home: Path, request_path: Path, newer_than: float) -> List[Path]:
    found: List[Path] = []
    for path in (Path(codex_home) / "sessions").glob("**/rollout-*.jsonl"):
        try:
            if path.stat().st_mtime < newer_than:
                continue
            if str(request_path) in path.read_text(encoding="utf-8", errors="replace"):
                found.append(path)
        except OSError:
            continue
    return sorted(found, key=lambda p: p.stat().st_mtime)


def audit_files(paths: Sequence[Path], request: dict, request_path: Path,
                names: Sequence[NameEntry], scope_to_request: bool = True) -> AuditResult:
    paths = list(dict.fromkeys(Path(p).resolve() for p in paths))
    if len(paths) > 1:
        return AuditResult("unverifiable", "无法审计：匹配到多个会话文件，不能唯一确定本次窗口")
    if not paths:
        return AuditResult("unverifiable", "无法审计：找不到可用的会话日志（Codex 可能已改用新的存储）")
    lines: List[str] = []
    for path in paths:
        try:
            lines.extend(Path(path).read_text(encoding="utf-8").splitlines())
        except (OSError, UnicodeError):
            return AuditResult("unverifiable", "无法审计：会话文件缺失、不可读或编码损坏")
    # Legacy keyword remains accepted; explicit logs cannot bypass request scoping.
    # Never select by matching prompts: only an explicit request-file read may
    # delimit the complete window. Ambiguous batches remain unverifiable.
    boundaries = []
    for index, raw in enumerate(lines):
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        reads = set()
        # A direct exec_command cmd is an action; an arbitrary string that
        # mentions cat/read is not. Unknown JS dataflow never creates bounds.
        payload = record.get("payload", record) if isinstance(record, dict) else {}
        if not isinstance(payload, dict):
            continue
        if payload.get("type") == "function_call" and payload.get("name", "").split(".")[-1] == "exec_command":
            args = payload.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            if isinstance(args, dict):
                reads.update(_cat_reads(args.get("cmd", "")))
        nested_args = payload.get("arguments", payload.get("input", "")) if payload.get("type") in ("function_call", "custom_tool_call") and payload.get("name", "").split(".")[-1] in ("exec", "js") else ""
        for key, text in _strings({"arguments": nested_args}):
            if key not in CALL_KEYS:
                continue
            # Support only a single literal tool invocation, not comments,
            # compound assignments, concatenation, echo, compound commands or examples.
            match = re.fullmatch(r"\s*(?:(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*)?(?:await\s+)?tools\.exec_command\s*\((.*)\)\s*;?\s*", text, re.S)
            if match:
                args = _literal_arguments(match.group(1) + ")")
                if args:
                    reads.update(_cat_reads(args.get("cmd", "")))
        if reads:
            boundaries.append((index, reads))
    target = [(i, refs) for i, refs in boundaries if str(request_path) in refs]
    if len(target) != 1 or len(target[0][1]) != 1:
        return AuditResult("unverifiable", "无法审计：无法唯一确定本请求的完整读取窗口；不将其他分镜判为篡改")
    start = target[0][0]
    end = next((i for i, _ in boundaries if i > start), len(lines))
    lines = lines[start:end]
    return audit_lines(lines, request, request_path, names)


def _cat_reads(command):
    if not isinstance(command, str) or any(c in command for c in ("\n", ";", "|", "&", "<", ">", "$", "`")):
        return set()
    try:
        parts = shlex.split(command)
    except ValueError:
        return set()
    if len(parts) >= 2 and parts[0] in ("cat", "/bin/cat"):
        return {str(Path(p)) for p in parts[1:] if Path(p).is_absolute() and Path(p).name == "request.json"}
    return set()
