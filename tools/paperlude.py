#!/usr/bin/env python3
"""Safe entry for the pinned two-second giraffe case. Read docs/TOOLS.md."""
from pathlib import Path
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
from fractions import Fraction
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import uuid

TOOL = Path(__file__).resolve().parent
WORKFLOW = TOOL.parent
DEFAULT_CONFIG = WORKFLOW / 'config/giraffe.json'
SAMPLE_ID = 'giraffe-20260713-0121-v2'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def require(test, message):
    if not test:
        raise ValueError(message)


def resolve(config, key):
    value = Path(config[key]).expanduser()
    return value.resolve() if value.is_absolute() else (WORKFLOW/value).resolve()


def probe(path):
    raw = subprocess.check_output(['ffprobe', '-v', 'error', '-count_frames',
        '-show_streams', '-show_format', '-of', 'json', str(path)], text=True)
    data = json.loads(raw)
    videos = [s for s in data['streams'] if s['codec_type']=='video']
    require(len(videos)==1, f'需要单路视频：{path}')
    s = videos[0]
    return {'width':int(s['width']), 'height':int(s['height']),
        'fps':s['avg_frame_rate'], 'frames':int(s.get('nb_read_frames', s.get('nb_frames', 0))),
        'duration':float(data['format']['duration']),
        'audio_streams':sum(s['codec_type']=='audio' for s in data['streams']),
        'pix_fmt':s.get('pix_fmt')}


def check_media(actual, expected, name):
    for key in ('width','height','frames','audio_streams'):
        require(actual[key]==expected[key], f'{name} {key} 不匹配：{actual[key]} != {expected[key]}')
    require(Fraction(actual['fps'])==Fraction(expected['fps']), f'{name}帧率不匹配')
    require(abs(actual['duration']-expected['duration'])<0.001, f'{name}时长不匹配')


def dependency_check(config):
    for cmd in ('ffmpeg','ffprobe'):
        require(shutil.which(cmd), f'未找到 {cmd}')
    runtime = resolve(config,'runtime')
    python = runtime/'.venv/bin/python'
    require(python.is_file(), f'运行环境不存在：{python}')
    # The read-only commands must not create __pycache__ in the archive.
    code = ('import cv2,numpy,PIL,torch,sam2,json; '
            'print(json.dumps({"opencv":cv2.__version__,"numpy":numpy.__version__,'
            '"pillow":PIL.__version__,"torch":torch.__version__,'
            '"sam2":sam2.__file__,"mps_available":torch.backends.mps.is_available()}))')
    env = os.environ.copy(); env['PYTHONDONTWRITEBYTECODE']='1'
    values = json.loads(subprocess.check_output([str(python),'-B','-c',code], env=env,text=True))
    require((runtime/'models/sam2.1_hiera_small.pt').is_file(), 'SAM2模型缺失')
    require((runtime/'vendor/sam2/sam2').is_dir(), 'SAM2源码缺失')
    return python, values


def image_check(python, root, count):
    code = r'''from pathlib import Path
from PIL import Image
import numpy as np
import json,sys
root=Path(sys.argv[1]); count=int(sys.argv[2]); nonempty=0
for folder,suffix in [('raw_crop','.jpg'),('masks','.png')]:
    files=sorted((root/folder).glob('*'+suffix))
    assert [p.name for p in files]==[f'{i:05d}{suffix}' for i in range(count)], f'{folder} frame numbering/count'
    for p in files:
        with Image.open(p) as im:
            assert im.size==(600,1200), f'{p} size {im.size}'
            im.load()
            if folder=='masks':
                a=np.asarray(im.convert('L'))
                assert set(np.unique(a)).issubset({0,255}), f'{p} not binary'
                assert np.any(a), f'{p} empty mask'
                nonempty+=1
print(json.dumps({'crop_frames':count,'mask_frames':nonempty,'size':[600,1200]}))
'''
    return json.loads(subprocess.check_output([str(python),'-B','-c',code,str(root),str(count)],text=True))


def baseline_check(config):
    require(config.get('sample_id')==SAMPLE_ID, '此入口只支持已验证长颈鹿样例')
    # The retained engine has fixed render geometry and tracking prompts.
    require(config['roi']==[1050,600,600,1200], '当前核心只支持已验证ROI；新素材需另建适配版本')
    expected = config['media']
    require((expected['width'],expected['height'],expected['frames'],expected['fps'])==(3840,2160,123,'60000/1001'),
            '当前核心只支持4K、123帧、60000/1001样例')
    python,deps=dependency_check(config)
    source=resolve(config,'source')
    require(source.is_file(), f'案例原片缺失：{source}')
    fp=read(WORKFLOW/config['fingerprints'])
    require(sha(resolve(config,'runtime')/'models/sam2.1_hiera_small.pt')==fp['archive_files']['models/sam2.1_hiera_small.pt'],'运行环境模型权重与已验证样例不符')
    require(sha(source)==fp['source_sha256'], '原片内容变化，禁止套用旧缓存')
    check_media(probe(source), expected, '原片')
    archive=resolve(config,'archive')
    # Pin all crop frames, masks, initial prompt, texture, model and engine code.
    for rel,digest in fp['archive_files'].items():
        path=(resolve(config,'runtime')/rel) if rel.startswith('models/') else archive/rel
        require(path.is_file() and sha(path)==digest, f'历史缓存/资产内容变化或缺失：{rel}')
    for rel,digest in fp['engine_files'].items():
        path=TOOL/'core'/rel
        require(path.is_file() and sha(path)==digest, f'核心代码与输入指纹不匹配：{rel}')
    images=image_check(python,archive,expected['frames'])
    return {'sample_id':SAMPLE_ID,'source_sha256':fp['source_sha256'],
        'source':str(source),'archive':str(archive),'runtime':str(resolve(config,'runtime')),
        'media':expected,'dependencies':deps,'image_checks':images,
        'scope':'只验证文件绑定、数据结构和依赖；不证明分割、修复或美术质量'}, python, fp


def check_segments(root, count):
    segments=read(root/'segments.json')
    cursor=0
    for s in segments:
        a,b,k=s['start'],s['end'],s['key']
        require(all(type(v) is int for v in (a,b,k)), '分段帧号须为整数')
        require(a==cursor and a<=k<b<=count, '分段不连续、越界或关键帧不在区间内')
        cursor=b
    require(cursor==count and len(segments)>0, '分段未覆盖全部帧')
    return {'count':len(segments),'continuous':True,
            'keys':[s['key'] for s in segments]}


def verify_run(config,root,python,fp):
    archive=resolve(config,'archive')
    root=root.resolve()
    if root!=archive:
        binding=read(root/'运行绑定.json')
        require(binding['sample_id']==SAMPLE_ID and binding['source_sha256']==fp['source_sha256'], '运行目录与本样例原片未绑定')
        for rel,digest in binding['crop_sha256'].items():
            require(sha(root/'raw_crop'/rel)==digest==fp['archive_files']['raw_crop/'+rel],'运行目录裁剪帧被更改')
        require(len(binding.get('mask_sha256',{}))==123,'运行目录缺少完整蒙版内容指纹')
        for rel,digest in binding['mask_sha256'].items():
            require(sha(root/'masks'/rel)==digest,'运行目录蒙版被更改')
        for rel,digest in binding['core_sha256'].items():
            require(sha(root/rel)==digest,'运行目录核心代码被更改')
    images=image_check(python,root,config['media']['frames'])
    report={'directory':str(root),'image_checks':images,
        'visual_acceptance':'未由此命令判定。零未处理蒙版像素不证明蒙版准确、背景修复自然或无残影。'}
    if not (root/'segments.json').is_file():
        require(root!=archive,'历史基线分段缺失')
        report['stage']='tracking only'
        return report
    report['segments']=check_segments(root,config['media']['frames'])
    outputs={
        '长颈鹿_纸片替换_v2_4K.mp4':(3840,2160,123,2.05205),
        '局部原片与效果对比.mp4':(960,960,123,2.05205),
        '局部对比_循环四次.mp4':(960,960,492,8.2082),
        '露边修复位置检查.mp4':(600,1200,123,2.05205)}
    result={}
    for name,(w,h,n,d) in outputs.items():
        path=root/name; require(path.is_file(),f'输出缺失：{path}')
        actual=probe(path)
        check_media(actual,{'width':w,'height':h,'frames':n,'fps':'60000/1001','duration':d,'audio_streams':0},name)
        subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(path),'-f','null','-'],check=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        result[name]=actual
    coverage=read(root/'coverage.json')
    cf=coverage['frames']
    require([x['frame'] for x in cf]==list(range(123)), '覆盖报告帧号缺失')
    require(all(x['raw_outside_paper']>=0 and x['unrepaired_mask_pixels']>=0 for x in cf),'覆盖报告计数非法')
    report['outputs']=result
    report['coverage_diagnostics']={
        'max_unrepaired_mask_pixels':max(x['unrepaired_mask_pixels'] for x in cf),
        'max_raw_outside_paper':max(x['raw_outside_paper'] for x in cf),
        'interpretation':'相对既有蒙版的合成区域记录；不判断背景修复像素是否正确。'}
    preservation=read(root/'pixel_preservation.json')
    require(preservation['frames']==123 and preservation['roi']==config['roi'],'像素保留报告不匹配')
    require(preservation['outside_roi_sha256_equal_all_frames'] is True,'编码前ROI外像素记录未通过')
    report['pixel_preservation_note']='读取已有编码前检查报告；该命令未从有损输出反推逐像素一致。'
    return report


def new_run(config,stage,fp,tracking_run=None):
    archive=resolve(config,'archive')
    output=resolve(config,'output_root')
    require(output==(WORKFLOW/'outputs').resolve(), '输出固定在工作流的产出目录，禁止写入历史目录')
    output.mkdir(parents=True,exist_ok=True)
    root=output/(datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S')+'-'+stage+'-'+uuid.uuid4().hex[:6])
    root.mkdir(exist_ok=False)
    for folder in ('raw_crop','masks','assets','qa'):
        (root/folder).mkdir()
    for path in sorted((archive/'raw_crop').glob('*.jpg')):
        shutil.copy2(path,root/'raw_crop'/path.name)
    mask_source=archive
    if tracking_run:
        mask_source=Path(tracking_run).resolve()
        require(mask_source.parent==output, '仅接受统一入口输出根目录下的追踪结果')
        binding=read(mask_source/'运行绑定.json')
        require(binding['sample_id']==SAMPLE_ID and binding['source_sha256']==fp['source_sha256'], '追踪结果绑定不匹配')
        for rel,digest in binding['crop_sha256'].items():
            require(sha(mask_source/'raw_crop'/rel)==digest,'追踪目录裁剪帧改变')
    if stage=='compose':
        for path in sorted((mask_source/'masks').glob('*.png')):
            shutil.copy2(path,root/'masks'/path.name)
    shutil.copy2(archive/'setup_first_mask.png',root/'setup_first_mask.png')
    shutil.copy2(archive/'assets/paper_texture_ai.png',root/'assets/paper_texture_ai.png')
    for path in (TOOL/'core').glob('*.py'):
        shutil.copy2(path,root/path.name)
    # Models are read by the engine. Avoid duplicating the 176 MB checkpoint.
    (root/'models').symlink_to(resolve(config,'runtime')/'models',target_is_directory=True)
    write(root/'运行绑定.json',{'sample_id':SAMPLE_ID,'stage':stage,
        'source_sha256':fp['source_sha256'],'source':str(resolve(config,'source')),
        'archive':str(archive),'roi':config['roi'],'media':config['media'],
        'mask_source':str(mask_source),
        'crop_sha256':{p.name:sha(p) for p in sorted((root/'raw_crop').glob('*.jpg'))},
        'core_sha256':{p.name:sha(p) for p in sorted(root.glob('*.py'))},
        'notes':'仅本样例；复制缓存，历史目录只读；运行结果需要人工目视验收。'})
    return root


def execute(config,stage,python,fp,tracking_run):
    if tracking_run:
        path=Path(tracking_run).resolve()
        require(path.parent==resolve(config,'output_root'),'追踪结果须在本工作流产出目录')
        require(read(path/'运行绑定.json')['stage']=='track','--tracking-run需要track命令生成的目录')
        verify_run(config,path,python,fp)
    root=new_run(config,stage,fp,tracking_run)
    print(f'新运行目录：{root}',flush=True)
    # Load copied core and override the source path before invoking its stage.
    code = r'''import importlib.util,sys
from pathlib import Path
root=Path(sys.argv[1]); source=Path(sys.argv[2]); stage=sys.argv[3]
sys.path.insert(0,str(root))
spec=importlib.util.spec_from_file_location('case_engine',root/'run_experiment.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module.ROOT=root;module.SOURCE=source
getattr(module,stage)()
'''
    env=os.environ.copy(); env['PYTORCH_ENABLE_MPS_FALLBACK']='1'; env['PYTHONDONTWRITEBYTECODE']='1'
    try:
        subprocess.run([str(python),'-B','-c',code,str(root),str(resolve(config,'source')),stage],
                       cwd=root,env=env,check=True)
        binding=read(root/'运行绑定.json')
        binding['mask_sha256']={p.name:sha(p) for p in sorted((root/'masks').glob('*.png'))}
        write(root/'运行绑定.json',binding)
        result=verify_run(config,root,python,fp)
        write(root/'本次验证.json',result)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except Exception as exc:
        write(root/'运行失败.json',{'error':str(exc),'stage':stage,'historical_baseline_modified':False})
        raise


def main():
    parser=argparse.ArgumentParser(description='长颈鹿已验证样例的安全入口；新素材须先适配')
    parser.add_argument('command',choices=['doctor','check','verify','track','compose'])
    parser.add_argument('--config',type=Path,default=DEFAULT_CONFIG)
    parser.add_argument('--run',type=Path,help='verify指定新运行目录，默认检查历史v2交付')
    parser.add_argument('--tracking-run',type=Path,help='compose使用统一入口新生成的追踪目录')
    args=parser.parse_args()
    require(args.command=='verify' or args.run is None,'--run只用于verify')
    require(args.command=='compose' or args.tracking_run is None,'--tracking-run只用于compose')
    config=read(args.config)
    if args.command=='doctor':
        python,values=dependency_check(config)
        print(json.dumps({'python':str(python),'dependencies':values},ensure_ascii=False,indent=2))
        return
    baseline,python,fp=baseline_check(config)
    if args.command=='check':
        print(json.dumps(baseline,ensure_ascii=False,indent=2))
    elif args.command=='verify':
        print(json.dumps(verify_run(config,args.run or resolve(config,'archive'),python,fp),ensure_ascii=False,indent=2))
    else:
        require(args.run is None,'track/compose自动新建目录，不接受--run覆盖')
        require(args.command=='compose' or args.tracking_run is None,'--tracking-run只用于compose')
        execute(config,args.command,python,fp,args.tracking_run)


if __name__=='__main__':
    try:
        main()
    except (ValueError,OSError,subprocess.SubprocessError,KeyError,AssertionError) as exc:
        print(f'停止：{exc}',file=sys.stderr)
        sys.exit(1)
