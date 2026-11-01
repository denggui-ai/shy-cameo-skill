"""Offline compilation only: fixtures are authored drafts, not real user approvals.

Breaks caught: unsupported IP/age/style bans returning, shy-face/identity protections
lost, or changed reference/request semantics.
No image provider, backend, actual photo, or user workspace is used here.
"""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from coshoot.cards import CardError, require_valid
from coshoot.compiler import ADAPTATION_TEXT, CAST_CLOSE_TEXT
from test_compiler import build, setup

FIX = Path(__file__).parent / 'fixtures' / 'animation'
IPS = ('original-fox-inn', 'original-paper-crane', 'original-umbrella-spirit')


def candidates(ip, index=0, confirmed=True):
    scene = json.loads((FIX / f'set-{ip}.json').read_text())['shots'][index]
    character = json.loads((FIX / f'character-{ip}.json').read_text())
    # Synthetic confirmed copies are for the compiler unit test only; fixture drafts stay unverified.
    if confirmed:
        scene['status'] = 'user_confirmed'
        character['status'] = 'temp_confirmed'
    return scene, {f"{character['ip']}/{character['id']}": character}


@pytest.mark.parametrize('ip', IPS)
@pytest.mark.parametrize('index', range(5))
def test_three_themes_compile_without_contradictory_animation_ban(ip, index):
    scene, chars = candidates(ip, index)
    scene["visual"] = {"subject":"photographic", "environment":"animation_3d" if ip == "original-fox-inn" else "animation_2d"}
    chain = Path('/synthetic/cover.png') if index else None
    request = build(scene=scene, chars=chars, photos=(Path('/synthetic/adult.png'),),
                    chain_ref=chain, set_info={'set_id': ip, 'index': index + 1,
                                              'role': ('cover', 'wide', 'interaction', 'shy', 'ending')[index]})
    prompt = request['prompt']
    assert '不复刻动画或游戏的角色设计' not in prompt
    assert '动画' in prompt and '真人' in prompt
    assert '不把主角动画化' in prompt
    assert CAST_CLOSE_TEXT in prompt
    assert request['referenced_image_paths'] == (['/synthetic/adult.png'] + ([str(chain)] if chain else []))
    assert request['max_refs'] == 5
    assert request['set']['index'] == index + 1
    payload = json.dumps({'prompt': prompt, 'referenced_image_paths': request['referenced_image_paths']},
                         ensure_ascii=False, sort_keys=True)
    assert request['sha256'] == hashlib.sha256(payload.encode('utf-8')).hexdigest()
    require_valid(request, 'request')


@pytest.mark.parametrize('ip', IPS)
def test_unconfirmed_animation_drafts_are_not_made_generation_ready(ip):
    scene, chars = candidates(ip, confirmed=False)
    with pytest.raises(CardError) as exc:
        build(scene=scene, chars=chars)
    assert exc.value.code == 'scene_not_confirmed'
    scene['status'] = 'user_confirmed'
    with pytest.raises(CardError) as exc:
        build(scene=scene, chars=chars)
    assert exc.value.code == 'character_not_confirmed'


@pytest.mark.parametrize('mutation', ('other-character', 'other-variant', 'extra-character',
                                     'original_text', 'archetype', 'fitting'))
def test_character_era_or_costume_is_not_an_ip_permission_gate(mutation):
    scene, chars = candidates('original-paper-crane')
    if mutation == 'other-character':
        character = copy.deepcopy(next(iter(chars.values())))
        character['id'] = 'paper-crane-senior'
        character['name'] = '纸鸢师兄'
        chars['original-paper-crane/paper-crane-senior'] = character
        scene['characters'][0]['character_id'] = 'original-paper-crane/paper-crane-senior'
    elif mutation == 'other-variant':
        scene['characters'][0]['variant_id'] = 'later-years'
        next(iter(chars.values()))['variants'][0]['variant_id'] = 'later-years'
    elif mutation == 'extra-character':
        scene['characters'].append(copy.deepcopy(scene['characters'][0]))
    elif mutation in ('original_text', 'archetype'):
        scene['play_mode'] = mutation
    elif mutation == 'fitting':
        scene['user'].update(mode='fitting', role='纸鸢', costume='月白短打')
        scene['user'].pop('outfit', None)
    result = build(scene=scene, chars=chars)
    require_valid(result, 'request')
    assert '限定成年' not in result['prompt']
    assert CAST_CLOSE_TEXT in result['prompt']


@pytest.mark.parametrize('ip', ('one-piece', 'dragon-ball', 'original-superhero'))
def test_other_themes_are_not_categorically_banned(ip):
    scene, chars = candidates('original-fox-inn')
    scene['ip'] = ip
    result = build(scene=scene, chars=chars)
    assert '不复刻动画或游戏的角色设计' not in result['prompt']
    assert CAST_CLOSE_TEXT in result['prompt']


@pytest.mark.parametrize('ip', IPS)
def test_anime_style_is_a_user_choice_for_existing_characters(ip):
    scene, chars = candidates(ip)
    scene['style'] = 'anime'
    result = build(scene=scene, chars=chars)
    assert '日本电视动画的画面质感' in result['prompt']
    assert '把主角用日式动画画风重绘' in result['prompt']
    assert CAST_CLOSE_TEXT in result['prompt']


@pytest.mark.parametrize('ip', IPS)
def test_other_compiler_guards_still_apply(ip):
    scene, chars = candidates(ip)
    with pytest.raises(CardError) as exc:
        build(scene=scene, chars=chars, photos=())
    assert exc.value.code == 'no_user_photo'
    scene['characters'][0]['action'] = '六小龄童递来道具'
    with pytest.raises(CardError) as exc:
        build(scene=scene, chars=chars)
    assert exc.value.code == 'blocked_name'


@pytest.mark.parametrize('mode', ('classic_presence', 'original_text', 'archetype',
                                 'genre_scene', 'opera_costume', 'location_checkin'))
def test_existing_modes_keep_request_and_reference_contract(mode):
    scene, chars = setup()
    scene['play_mode'] = mode
    if mode in ('opera_costume', 'location_checkin'):
        scene['characters'] = []
    if mode == 'opera_costume':
        scene['user']['role'] = '京剧花旦'
    result = build(scene=scene, chars=chars, run_id='20261016-120000-abcdef')
    assert result['schema_version'] == '1'
    assert result['run_id'] == '20261016-120000-abcdef'
    assert result['card_ref']['scene_id'] == 'xiyou/shuiliandong'
    assert result['referenced_image_paths'][0] == '/in/me.jpg'
    assert result['max_refs'] == 5 and 'set' not in result
    require_valid(result, 'request')


@pytest.mark.parametrize('ip', IPS)
def test_animation_cli_compilation_keeps_first_failure_cancellation(ip, tmp_path, png_factory):
    """The real CLI compiles a synthetic fixture; no generate command is invoked."""
    from test_cli import cli
    from test_cli_sets import set_workspace

    ws, photo, card_path, set_path = set_workspace(tmp_path, png_factory)
    card = json.loads((FIX / f'character-{ip}.json').read_text())
    card['status'] = 'temp_confirmed'
    card_path.write_text(json.dumps(card, ensure_ascii=False))
    set_card = json.loads((FIX / f'set-{ip}.json').read_text())
    set_card['status'] = 'user_confirmed'
    for shot in set_card['shots']:
        shot['status'] = 'user_confirmed'
    set_path.write_text(json.dumps(set_card, ensure_ascii=False))
    base = ['--set-card', set_path, '--character', card_path, '--photo', photo, '--workspace', ws]
    code, compiled = cli('compile-shot', '--index', '1', *base)
    assert code == 0, compiled
    request = json.loads(Path(compiled['request_path']).read_text())
    assert '不复刻动画或游戏的角色设计' not in request['prompt']
    assert request['referenced_image_paths'] == [str(photo.resolve())]
    # A synthetic rejected result exercises cancellation without invoking any image service.
    code, _ = cli('set-record', '--set-card', set_path, '--workspace', ws,
                  '--index', '1', '--status', 'rejected')
    assert code == 0
    code, refused = cli('compile-shot', '--index', '2', *base)
    assert code == 2 and refused['status'] == 'set_cancelled'
