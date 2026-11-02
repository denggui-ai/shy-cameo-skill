"""User-visible routing and audit regressions; synthetic data only, no image service."""
import json
import os
import struct
import zlib
from pathlib import Path
import pytest
from coshoot import audit, backend_exec, frame, photo
from coshoot.cards import CardError
from test_compiler import setup, build
from test_audit import call_line

MODES = ['classic_presence','opera_costume','original_text','archetype','genre_scene','location_checkin']

@pytest.mark.parametrize('mode', MODES)
@pytest.mark.parametrize('identity', ['traveler','fitting','in_story'])
@pytest.mark.parametrize('visual', [
    {'subject':'photographic','environment':'photographic'},
    {'subject':'photographic','environment':'animation_2d'},
    {'subject':'animation_3d','environment':'animation_3d'},
])
def test_confirmed_clothing_and_visual_choices_survive_every_route(mode, identity, visual):
    s,c=setup()
    s.update(play_mode=mode,visual=visual,cinematography='门外侧光照亮交接物，背景保留空间层次')
    if mode in ['opera_costume','location_checkin']:s['characters']=[]
    s['user']={'mode':identity,'role':'京剧花旦' if mode=='opera_costume' else '学徒',
               'position':'left','action':'看手中的信件','outfit':'青绿色绣银鹤长袍',
               'hairstyle':'低发髻','makeup':'桃红眼妆'}
    prompt=build(scene=s,chars=c)['prompt']
    for value in [s['user']['outfit'],'低发髻','桃红眼妆',s['cinematography']]:assert value in prompt
    if visual['subject']=='photographic':
        assert '不把主角动画化' in prompt
        assert '把主角用日式动画画风重绘' not in prompt
    else:
        assert '三维动画造型与渲染风格重绘' in prompt
    if visual['environment']=='animation_2d':assert '环境采用二维动画' in prompt


def test_ip_name_no_longer_selects_hidden_rendering_branch():
    s,c=setup();s['visual']={'subject':'photographic','environment':'animation_2d'}
    prompts=[]
    for ip in ['naruto','totoro','xiyou','original-test']:
        s['ip']=ip;prompts.append(build(scene=s,chars=c)['prompt'])
    assert len(set(prompts))==1


def test_position_and_expression_are_transmitted_without_face():
    s,c=setup();member=s['characters'][0]
    member.update(position='left',expression='惊喜地缩回手')
    result=build(scene=s,chars=c)['prompt']
    assert '局部或影子位于画面左侧' in result and '惊喜地缩回手' in result and '角色绝不露脸' in result


def test_full_body_and_environment_wide_are_real_choices():
    s,c=setup()
    for framing in ['full_body','wide']:
        s['framing']=framing
        prompt=build(scene=s,chars=c)['prompt']
        assert '不出现小腿和脚' not in prompt
        assert '角色绝不露脸' in prompt


def test_scene_reference_drop_is_visible(capsys):
    s,c=setup()
    req=build(scene=s,chars=c,scene_ref=Path('/synthetic/place.png'),chain_ref=Path('/synthetic/chain.png'),max_refs=3)
    assert '/synthetic/place.png' not in req['referenced_image_paths']
    assert '未采用场景图：/synthetic/place.png' in capsys.readouterr().err


def test_automatic_audit_scopes_by_read_events_not_prompt_matching(tmp_path):
    a,b=tmp_path/'a/request.json',tmp_path/'b/request.json'
    req={'prompt':'A','referenced_image_paths':[]}
    def read_line(path):
        return json.dumps({'type':'response_item','payload':{'type':'function_call','name':'exec_command','arguments':json.dumps({'cmd':f'cat {path}'})}})
    lines=[read_line(a),call_line('image_gen({prompt: "A", referenced_image_paths: []})'),
           read_line(b),call_line('image_gen({prompt: "B", referenced_image_paths: []})')]
    log=tmp_path/'log.jsonl';log.write_text('\n'.join(lines))
    assert audit.audit_files([log],req,a,[],scope_to_request=True).status=='pass'
    # No read anchors: uncertainty, not an accusation against a legitimate second shot.
    log.write_text('\n'.join([lines[1],lines[3]]))
    assert audit.audit_files([log],req,a,[],scope_to_request=True).status=='unverifiable'
    # Rogue call inside A's window must not be filtered out.
    log.write_text('\n'.join(lines[:2]+[lines[3]]+lines[2:]))
    assert audit.audit_files([log],req,a,[],scope_to_request=True).status=='tampered'


def test_duplicate_identical_calls_not_single_call_pass():
    line=call_line('image_gen({prompt: "A", referenced_image_paths: []})')
    assert audit.audit_lines([line,line],{'prompt':'A','referenced_image_paths':[]},Path('/a/request.json'),[]).status=='tampered'


def test_invalid_png_pixels_block_without_face_detector(tmp_path):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    p=tmp_path/'broken.png';p.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',600,800,8,2,0,0,0))+chunk(b'IDAT',b'not a zlib stream')+chunk(b'IEND',b''))
    assert photo.check_photo(p,detector=None).to_dict()['level']=='block'
    assert frame.check_frame(p,'waist_up',detector=None)['level']=='block'


@pytest.mark.parametrize('returncode,old',[(7,False),(0,True)])
def test_relay_error_or_stale_output_is_not_success(tmp_path,png_factory,returncode,old):
    image=tmp_path/'image.png'
    def fake(cmd,**kw):
        image.write_bytes(png_factory())
        if old:os.utime(image,(1,1))
        Path(cmd[cmd.index('-o')+1]).write_text(str(image))
        return returncode
    result=backend_exec.run_exec(tmp_path/'request.json',tmp_path/'run',tmp_path,run=fake)
    assert result.status=='failed_no_image'


def test_reshoot_can_keep_validated_set_reference(tmp_path,png_factory):
    from test_cli_sets import set_workspace
    from test_cli import cli
    ws,p,char,card=set_workspace(tmp_path,png_factory)
    base=['--set-card',card,'--character',char,'--photo',p,'--workspace',ws]
    assert cli('compile-shot','--index',1,*base)[0]==0
    img=tmp_path/'first.png';img.write_bytes(png_factory())
    assert cli('set-record','--set-card',card,'--workspace',ws,'--index',1,'--status','generated','--image',img)[0]==0
    scene=ws/'cards/reshoot.json';scene.write_text(json.dumps(json.loads(card.read_text())['shots'][2]))
    args=['--scene',scene,'--character',char,'--photo',p,'--workspace',ws,'--chain-set',card]
    code,result=cli('compile',*args)
    assert code==0,result
    chain=ws/'outputs/sets/hgs1/chain.png'
    assert str(chain.resolve()) in result['referenced_image_paths']
    chain.write_bytes(b'changed')
    code,result=cli('compile',*args)
    assert code==2 and result['status']=='chain_tampered'


def test_fake_read_and_dynamic_calls_do_not_make_false_audit_claims(tmp_path):
    a=Path('/ws/a/request.json')
    read=json.dumps({'payload':{'type':'function_call','name':'exec_command','arguments':json.dumps({'cmd':f'cat {a}'})}})
    good=call_line('image_gen({prompt: "A", referenced_image_paths: []})')
    echo=json.dumps({'payload':{'type':'function_call','name':'exec_command','arguments':json.dumps({'cmd':'echo "cat /ws/b/request.json"'})}})
    rogue=call_line('image_gen({prompt: "ROGUE", referenced_image_paths: []})')
    log=tmp_path/'events';log.write_text('\n'.join([read,good,echo,rogue]))
    req={'prompt':'A','referenced_image_paths':[]}
    assert audit.audit_files([log],req,a,[],scope_to_request=True).status=='tampered'
    dynamic=call_line('image_gen({prompt: r.prompt, referenced_image_paths: r.referenced_image_paths})')
    assert audit.audit_lines([dynamic,dynamic],req,a,[]).status=='unverifiable'


def test_wide_does_not_warn_against_full_body(tmp_path,png_factory):
    p=tmp_path/'wide.png';p.write_bytes(png_factory(600,800))
    class Detector:
        def faces(self,path):return [(0,0,30,30)]
    r=frame.check_frame(p,'wide',detector=Detector())
    assert not any(f['code']=='framing_drift' for f in r['findings'])


def test_indexed_png_requires_palette(tmp_path):
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    p=tmp_path/'palette.png'
    p.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,3,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00\x00'))+chunk(b'IEND',b''))
    assert frame.check_frame(p,'waist_up',detector=None)['level']=='block'


def test_tool_output_example_cannot_create_audit_boundary(tmp_path):
    a=Path('/ws/a/request.json')
    read=json.dumps({'payload':{'type':'function_call','name':'exec_command','arguments':json.dumps({'cmd':f'cat {a}'})}})
    good=call_line('image_gen({prompt: "A", referenced_image_paths: []})')
    example=json.dumps({'payload':{'type':'function_call_output','output':json.dumps({'code':'await tools.exec_command({cmd: "cat /ws/b/request.json"})'})}})
    rogue=call_line('image_gen({prompt: "ROGUE", referenced_image_paths: []})')
    log=tmp_path/'events';log.write_text('\n'.join([read,good,example,rogue]))
    assert audit.audit_files([log],{'prompt':'A','referenced_image_paths':[]},a,[],scope_to_request=True).status=='tampered'
