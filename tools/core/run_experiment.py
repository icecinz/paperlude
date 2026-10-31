"""Reproducible single-target held-photograph video experiment.

Run track first, inspect qa/tracking_contact.jpg, then compose.
Source media is read only. All derived files live beside this script.
"""
from pathlib import Path
import argparse
import json
import os
import subprocess
import time

os.environ.setdefault('PYTORCH_ENABLE_MPS_FALLBACK', '1')
ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'source.mov'  # The entrypoint binds the archived demo source.
FPS = 60000 / 1001
ROI = (1050, 600, 600, 1200)


def dump(path, value):
    import numpy as np
    def default(x):
        if isinstance(x, np.ndarray): return x.tolist()
        if isinstance(x, np.generic): return x.item()
        raise TypeError(type(x).__name__)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=default), encoding='utf-8')


def contact(images, labels, path, cols=6, cell=(240, 480)):
    from PIL import Image, ImageDraw
    import cv2
    w, h = cell
    rows = (len(images) + cols - 1) // cols
    canvas = Image.new('RGB', (cols*w, rows*(h+28)), '#222222')
    draw = ImageDraw.Draw(canvas)
    for i, (im, label) in enumerate(zip(images, labels)):
        view = Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB))
        view.thumbnail((w,h))
        x, y = i%cols*w, i//cols*(h+28)
        canvas.paste(view, (x+(w-view.width)//2,y))
        draw.text((x+5,y+h+5), str(label), fill='white')
    canvas.save(path, quality=94)


def track():
    import cv2
    import numpy as np
    import torch
    from sam2.build_sam import build_sam2_video_predictor
    start = time.perf_counter()
    device = 'mps' if torch.backends.mps.is_available() else 'cpu'
    print(f'Tracking on {device}', flush=True)
    predictor = build_sam2_video_predictor(
        'configs/sam2.1/sam2.1_hiera_s.yaml',
        str(ROOT/'models/sam2.1_hiera_small.pt'), device=device,
        apply_postprocessing=False)
    with torch.inference_mode():
        state = predictor.init_state(str(ROOT/'raw_crop'), offload_video_to_cpu=True,
                                     offload_state_to_cpu=True)
        init = cv2.imread(str(ROOT/'setup_first_mask.png'), cv2.IMREAD_GRAYSCALE)
        if init is not None:
            predictor.add_new_mask(state, frame_idx=0, obj_id=1, mask=init>127)
        else:
            predictor.add_new_points_or_box(state, frame_idx=0, obj_id=1,
                points=np.array([[200,335],[205,660],[191,930]],np.float32),
                labels=np.array([1,1,1],np.int32),
                box=np.array([115,275,325,1035],np.float32))
        stats=[]
        for idx, ids, logits in predictor.propagate_in_video(state):
            prob = torch.sigmoid(logits[0,0]).cpu().numpy()
            binary = (prob>.5).astype(np.uint8)*255
            nc,cc,cs,_=cv2.connectedComponentsWithStats((binary>0).astype(np.uint8))
            if nc>2:
                main=int(np.argmax(cs[1:,cv2.CC_STAT_AREA]))+1
                binary=np.where(cc==main,255,0).astype(np.uint8)
            cv2.imwrite(str(ROOT/'masks'/f'{idx:05d}.png'), binary)
            ys,xs=np.where(binary>0)
            stats.append({'frame':idx,'pixels':len(xs),'box':[int(xs.min()),int(ys.min()),int(xs.max()),int(ys.max())] if len(xs) else None})
            if idx%10==0: print(f'frame {idx}: {len(xs)} px',flush=True)
    dump(ROOT/'tracking.json',{'model':'sam2.1_hiera_small','device':device,
        'seconds':time.perf_counter()-start,'roi':ROI,'frames':stats})
    views=[];labels=[]
    for i in np.linspace(0,len(stats)-1,12,dtype=int):
        im=cv2.imread(str(ROOT/'raw_crop'/f'{i:05d}.jpg'))
        m=cv2.imread(str(ROOT/'masks'/f'{i:05d}.png'),0)>127
        im[m]=(im[m]*.45+np.array([30,220,250])*.55).astype(np.uint8)
        views.append(im);labels.append(f'{i/FPS:.3f}s / f{i}')
    contact(views,labels,ROOT/'qa/tracking_contact.jpg')
    print('Tracking complete',flush=True)


def compose():
    import cv2
    import numpy as np
    from background_tools import estimate_camera, clean_background
    from paper_logic import plan_segments, make_paper
    files=sorted((ROOT/'raw_crop').glob('*.jpg'))
    frames=[cv2.imread(str(p)) for p in files]
    masks=[cv2.imread(str(ROOT/'masks'/f'{i:05d}.png'),0)>127 for i in range(len(frames))]
    if any(m.shape!=frames[0].shape[:2] for m in masks): raise ValueError('mask shape')
    print('Estimating camera motion',flush=True)
    ground_camera=estimate_camera(frames,masks)
    np.save(ROOT/'camera_ground.npy',ground_camera)
    # Ground-plane apparent rotation is not camera roll. An upright cutout
    # follows its ground contact but should not lean with the receding grass.
    yy,xx=np.where(masks[0]); bottom=yy>np.percentile(yy,98)
    anchor=np.array([float(np.median(xx[bottom])),float(np.median(yy[bottom])),1.0])
    camera=[]
    for g in ground_camera:
        q=g@anchor;q=q/q[2]
        scale=float(np.hypot(g[0,0],g[1,0]))
        camera.append(np.array([[scale,0,q[0]-scale*anchor[0]],[0,scale,q[1]-scale*anchor[1]],[0,0,1]]))
    camera=np.array(camera)
    np.save(ROOT/'camera.npy',camera)
    dump(ROOT/'camera_report.json',getattr(estimate_camera,'last_diagnostics',{}))
    print('Planning held poses',flush=True)
    segments=plan_segments(frames,masks,camera,FPS)
    dump(ROOT/'segments.json',segments)
    print('Segments: '+str([(s['start'],s['end'],s['key']) for s in segments]),flush=True)
    print('Restoring local background',flush=True)
    clean, info=clean_background(frames,masks,ground_camera)
    small_info={}
    for key,val in info.items():
        if isinstance(val,np.ndarray):
            if val.ndim==2:
                cv2.imwrite(str(ROOT/'qa'/f'background_{key}.png'),val.astype(np.uint8)*255 if val.dtype==bool else val)
            else: np.save(ROOT/'qa'/f'background_{key}.npy',val)
        else: small_info[key]=val
    dump(ROOT/'background_report.json',small_info)
    texture=cv2.imread(str(ROOT/'assets/paper_texture_ai.png'))
    paper=[];opacities=[]
    for j,s in enumerate(segments):
        p,opaque=make_paper(frames[s['key']],masks[s['key']],seed=29,texture=texture)
        cv2.imwrite(str(ROOT/'assets'/f'paper_{j:02d}.png'),p)
        paper.append(p);opacities.append(opaque)
    samples=[];sample_labels=[]
    output_frames=[]
    diagnostics=[]
    leak_metrics=[]
    for i, (im,m) in enumerate(zip(frames,masks)):
        j=next(j for j,s in enumerate(segments) if s['start']<=i<s['end'])
        s=segments[j]; k=s['key']
        warp=camera[i] @ np.linalg.inv(camera[k])
        # Resample premultiplied color to prevent dark transparent-edge halos.
        rgba=paper[j].astype(np.float32)/255
        rgba[:,:,:3]*=rgba[:,:,3,None]
        p=cv2.warpPerspective(rgba,warp,(im.shape[1],im.shape[0]),flags=cv2.INTER_LINEAR)
        opacity=p[:,:,3]
        # Only exposed original-object pixels need background. Use a generous
        # cleanup band to remove antialiased hairs and boundary remnants.
        remove=cv2.dilate(m.astype(np.uint8),cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(13,13))).astype(bool)
        feather=cv2.GaussianBlur(remove.astype(np.float32),(0,0),1.2)
        base=im.astype(np.float32)*(1-feather[:,:,None])+clean[i].astype(np.float32)*feather[:,:,None]
        out=np.clip(base*(1-opacity[:,:,None])+p[:,:,:3]*255,0,255).astype(np.uint8)
        raw_leak=m & (opacity<.98)
        # Background repair is deliberately applied over all visible old-object
        # pixels. Report mask coverage separately from visual quality.
        uncovered=raw_leak & (feather<.98)
        leak_metrics.append({'frame':i,'raw_outside_paper':int(raw_leak.sum()),'unrepaired_mask_pixels':int(uncovered.sum())})
        diag=out.copy();diag[raw_leak]=(diag[raw_leak]*.45+np.array([15,25,250])*.55).astype(np.uint8)
        output_frames.append(out)
        diagnostics.append(diag)
        if i in {s['start'] for s in segments} or i==len(frames)-1:
            samples.append(np.hstack([im,out,diag]));sample_labels.append(f'f{i} / {i/FPS:.3f}s / pose {j+1}')
    dump(ROOT/'coverage.json',{'frames':leak_metrics,'max_unrepaired_mask_pixels':max(v['unrepaired_mask_pixels'] for v in leak_metrics)})
    contact(samples,sample_labels,ROOT/'qa/segment_comparison.jpg',cols=3,cell=(600,400))
    print('Rendering original-size output',flush=True)
    render_full(frames,output_frames)
    render_crops(frames,output_frames,diagnostics)
    print('Composition complete',flush=True)


def render_full(original_crops,crops):
    import hashlib
    import numpy as np
    source=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-i',str(SOURCE),'-f','rawvideo','-pix_fmt','bgr24','-'],stdout=subprocess.PIPE)
    dest=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s','3840x2160','-r','60000/1001','-i','-', '-an','-c:v','libx264','-preset','medium','-crf','17','-pix_fmt','yuv420p','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-movflags','+faststart',str(ROOT/'长颈鹿_纸片替换_v2_4K.mp4')],stdin=subprocess.PIPE)
    x,y,w,h=ROI
    outside_equal=[]
    def outside_hash(frame):
        z=hashlib.sha256()
        for part in [frame[:y],frame[y+h:],frame[y:y+h,:x],frame[y:y+h,x+w:]]:
            z.update(part.tobytes())
        return z.digest()
    for original_crop,crop in zip(original_crops,crops):
        data=source.stdout.read(3840*2160*3)
        if len(data)!=3840*2160*3: raise RuntimeError('source ended early')
        frame=np.frombuffer(data,np.uint8).reshape(2160,3840,3).copy()
        before=outside_hash(frame)
        # Only paste the effect's local region, preserving source pixels outside it.
        # Apply only the effect delta. JPEG proxies are used for analysis, so
        # pasting a whole proxy crop would subtly re-encode unrelated grass.
        delta=crop.astype(np.int16)-original_crop.astype(np.int16)
        region=frame[y:y+h,x:x+w]
        frame[y:y+h,x:x+w]=np.clip(region.astype(np.int16)+delta,0,255).astype(np.uint8)
        outside_equal.append(before==outside_hash(frame))
        dest.stdin.write(frame.tobytes())
    dest.stdin.close();source.stdout.close()
    if source.wait()!=0 or dest.wait()!=0:raise RuntimeError('render failed')
    dump(ROOT/'pixel_preservation.json',{'method':'apply local effect delta to source-decoded frames before encoding','frames':len(crops),'outside_roi_sha256_equal_all_frames':all(outside_equal),'source_modified':False,'roi':ROI,'note':'Lossy delivery encoding can change pixels after decoding; equality is checked before encoding.'})


def render_crops(original,output,diagnostics):
    import cv2
    import numpy as np
    def encode(name, imgs, width, height):
        p=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s',f'{width}x{height}','-r','60000/1001','-i','-','-an','-c:v','libx264','-crf','17','-preset','fast','-pix_fmt','yuv420p','-movflags','+faststart',str(ROOT/name)],stdin=subprocess.PIPE)
        for im in imgs:p.stdin.write(im.tobytes())
        p.stdin.close()
        if p.wait()!=0:raise RuntimeError('crop encode')
    pairs=[cv2.resize(np.hstack([a,b]),(960,960),interpolation=cv2.INTER_AREA) for a,b in zip(original,output)]
    encode('局部原片与效果对比.mp4',pairs,960,960)
    encode('露边修复位置检查.mp4',diagnostics,600,1200)
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-stream_loop','3','-i',str(ROOT/'局部原片与效果对比.mp4'),'-c','copy','-movflags','+faststart',str(ROOT/'局部对比_循环四次.mp4')],check=True)
    cv2.imwrite(str(ROOT/'效果预览.jpg'),pairs[len(pairs)//2])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['track','compose']);a=p.parse_args()
    {'track':track,'compose':compose}[a.stage]()
