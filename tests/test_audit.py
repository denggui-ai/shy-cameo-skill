import json
from pathlib import Path

import pytest

from coshoot.audit import audit_files, audit_lines, find_rollouts
from coshoot.names import NameEntry

NAMES = [NameEntry("六小龄童")]
REQ_PATH = Path("/ws/outputs/r1/request.json")
REQ = {"prompt": "电影剧照质感。\n场景：水帘洞。", "referenced_image_paths": []}


def call_line(code):
    # Synthetic record shaped like a Codex 0.161.0 rollout function call.
    return json.dumps({"type": "response_item", "payload": {
        "type": "function_call", "name": "exec", "arguments": json.dumps({"code": code})}})


def test_pass_when_call_loads_request_file():
    code = (f"const r = JSON.parse(await read('{REQ_PATH}')); "
            "await tools.image_gen__imagegen({prompt: r.prompt, referenced_image_paths: r.referenced_image_paths})")
    assert audit_lines([call_line(code)], REQ, REQ_PATH, NAMES).status == "unverifiable"


def test_unverifiable_without_any_call():
    lines = [json.dumps({"type": "session_meta", "payload": {"instructions": "You can use the image_gen tool."}})]
    assert audit_lines(lines, REQ, REQ_PATH, NAMES).status == "unverifiable"


def test_unverifiable_when_call_not_linked():
    code = 'await tools.image_gen__imagegen({prompt: load("spoon_prompt")})'
    assert audit_lines([call_line(code)], REQ, REQ_PATH, NAMES).status == "unverifiable"


def test_tampered_on_inline_prompt_mismatch():
    code = 'await tools.image_gen__imagegen({prompt: "a totally different prompt"})'
    assert audit_lines([call_line(code)], REQ, REQ_PATH, NAMES).status == "tampered"


def test_inline_exact_prompt_passes():
    code = 'await tools.image_gen__imagegen({prompt: "电影剧照质感。\\n场景：水帘洞。", referenced_image_paths: []})'
    assert audit_lines([call_line(code)], REQ, REQ_PATH, NAMES).status == "pass"


def test_revised_prompt_with_actor_name_is_tampered():
    lines = [json.dumps({"type": "event", "payload": {
        "kind": "image_gen.generation", "revisedPrompt": "六小龄童 as the monkey king"}})]
    assert audit_lines(lines, REQ, REQ_PATH, NAMES).status == "tampered"


def test_malformed_lines_are_skipped():
    code = f"x = read('{REQ_PATH}'); image_gen({{prompt: x.prompt}})"
    assert audit_lines(["not json", call_line(code)], REQ, REQ_PATH, NAMES).status == "unverifiable"


def test_find_rollouts_filters_by_request_path(tmp_path):
    day = tmp_path / "sessions" / "2026" / "10" / "10"
    day.mkdir(parents=True)
    hit = day / "rollout-a.jsonl"
    hit.write_text(str(REQ_PATH))
    (day / "rollout-b.jsonl").write_text("other")
    assert find_rollouts(tmp_path, REQ_PATH, newer_than=0) == [hit]
    assert audit_files([], REQ, REQ_PATH, NAMES).status == "unverifiable"


def test_probe_user_message_mentioning_call_is_not_a_call():
    line = json.dumps({"type": "message", "payload": {
        "role": "user", "content": f"Read {REQ_PATH} then call image_gen( ..."}})
    assert audit_lines([line], REQ, REQ_PATH, NAMES).status == "unverifiable"


def test_probe_rogue_second_call_is_not_masked_by_linked_call():
    good = f"read('{REQ_PATH}'); image_gen({{prompt: r.prompt}})"
    rogue = 'image_gen({prompt: "evil"})'
    assert audit_lines([call_line(good), call_line(rogue)], REQ, REQ_PATH, NAMES).status == "tampered"


def test_probe_documentation_text_is_not_tampered():
    line = json.dumps({"type": "session_meta", "payload": {
        "instructions": "tools.image_gen__imagegen({prompt: 'a cat'})"}})
    assert audit_lines([line], REQ, REQ_PATH, NAMES).status == "unverifiable"


def test_probe_inline_prompt_with_extra_text_is_tampered():
    code = 'image_gen({prompt: "六小龄童 电影剧照质感。\\n场景：水帘洞。", referenced_image_paths: []})'
    assert audit_lines([call_line(code)], REQ, REQ_PATH, NAMES).status == "tampered"
    code = 'image_gen({prompt: "电影剧照质感。\\n场景：水帘洞。 extra"})'
    assert audit_lines([call_line(code)], REQ, REQ_PATH, NAMES).status == "tampered"


def test_fake_codex_item_completed_shape_passes():
    code = (f"const r = JSON.parse(await read('{REQ_PATH}')); "
            "await tools.image_gen__imagegen({prompt: r.prompt, referenced_image_paths: r.referenced_image_paths})")
    line = json.dumps({"type": "item.completed", "item": {
        "type": "function_call", "arguments": json.dumps({"code": code})}})
    assert audit_lines([line], REQ, REQ_PATH, NAMES).status == "unverifiable"


def read_line(*paths):
    return json.dumps({'payload': {'type': 'function_call', 'name': 'exec_command',
                                  'arguments': json.dumps({'cmd': 'cat ' + ' '.join(map(str, paths))})}})


@pytest.mark.parametrize('legacy_scope_flag', [True, False])
def test_explicit_log_and_discovery_require_the_same_unique_window(tmp_path, legacy_scope_flag):
    good = call_line('image_gen({prompt: "电影剧照质感。\\n场景：水帘洞。", referenced_image_paths: []})')
    log = tmp_path / 'rollout.jsonl'
    log.write_text(good)
    def check():
        return audit_files([log], REQ, REQ_PATH, NAMES, scope_to_request=legacy_scope_flag)
    assert check().status == 'unverifiable'
    log.write_text(read_line(REQ_PATH) + '\n' + good)
    assert check().status == 'pass'
    log.write_text(read_line(REQ_PATH) + '\n' + good + '\n' + read_line(REQ_PATH))
    assert check().status == 'unverifiable'
    log.write_text(read_line(REQ_PATH, '/ws/outputs/r2/request.json') + '\n' + good)
    assert check().status == 'unverifiable'
    log.write_text(read_line(REQ_PATH) + '\n' + good + '\n' + '{truncated')
    assert check().status == 'unverifiable'


def test_multiple_sessions_and_unreadable_logs_are_unverifiable(tmp_path):
    paths = [tmp_path / 'a.jsonl', tmp_path / 'b.jsonl']
    for path in paths:
        path.write_text(read_line(REQ_PATH))
    result = audit_files(paths, REQ, REQ_PATH, NAMES)
    assert result.status == 'unverifiable' and '多个会话' in result.reason
    result = audit_files([tmp_path / 'missing'], REQ, REQ_PATH, NAMES)
    assert result.status == 'unverifiable' and '无法审计' in result.reason
