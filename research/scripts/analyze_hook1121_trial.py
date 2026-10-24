"""Offline analysis of the bounded Hook trial; never opens the game process."""
import argparse,json,math
from pathlib import Path
import numpy as np

def main():
    ap=argparse.ArgumentParser();ap.add_argument('run',type=Path);ap.add_argument('--video',type=Path)
    args=ap.parse_args();r=json.loads((args.run/'report.json').read_text())
    es=[json.loads(x) for x in (args.run/'events.jsonl').read_text().splitlines()]
    us=[e for e in es if e['kind']==1];ds=[e for e in es if e['kind']==2]
    stats={'update_events':len(us),'draw_events':len(ds),'threads':sorted(set(e['thread']for e in es)),
           'draw_stage_counts':{s:sum(e['stage']==s for e in ds)for s in range(5)}}
    preceding=None;differences=[];pairs=[]
    for e in es:
        if e['kind']==1:preceding=e
        elif preceding:
            differences.append(math.dist(e['position'],preceding['position']))
            pairs.append((preceding,e))
    stats['max_update_to_draw_position_difference']=max(differences)
    stats['draws_with_matching_update_counter']=sum(u['updates']==d['updates']for u,d in pairs)
    stats['max_update_dt']=max(e['dt']for e in us)
    for k in ('projection','width','step','angles','fov','direction'):
        v=np.array([e[k]for e in ds]);stats[k]={'min':v.min(axis=0).tolist(),'max':v.max(axis=0).tolist(),'maximum_range':float(np.ptp(v,axis=0).max())}
    a=np.array(r['config']['a']);b=np.array(r['config']['b'])
    def expected(t):
        f,to=(b,a)if t<11 else(a,b);t=t if t<11 else t-11
        u=np.clip(t/8,0,1);p=f+(to-f)*u;p[2]+=2*math.sin(math.pi*u);return p
    moving=[e for e in us if e['stage']]
    errs=[float(np.linalg.norm(np.array(e['position'])-expected(e['elapsed'])))for e in moving]
    stats['path_error_using_after_apply_log_time']={'max':max(errs),'p99':float(np.percentile(errs,99)),'note':'Includes native call and logging delay; not an independently measured setter timestamp.'}
    stats['first_a_hold_elapsed']=next(e['elapsed']for e in us if e['stage']==2)
    stats['first_b_hold_elapsed']=next(e['elapsed']for e in us if e['stage']==4)
    stats['a_hold_max_position_error']=max(math.dist(e['position'],a)for e in ds if e['stage']==2)
    stats['b_hold_max_position_error']=max(math.dist(e['position'],b)for e in ds if e['stage']==4)
    stats['final_position_error']=math.dist(r['final_camera']['camera']['position'],b)
    stats['replay_time_unchanged']=r['reference']['replay']==r['final_camera']['replay']
    stats['hooks_detached']=r['hooks_detached'];stats['dlls_remain_resident']=True
    # Matrix changes are reported as data, not labelled visual artifacts.
    for k in ('shadow_projection','shadow_vp'):
        v=np.array([e[k]for e in ds]);delta=np.abs(np.diff(v,axis=0))
        stats[k]={'max_component_range_per_cascade':np.ptp(v,axis=0).max(axis=1).tolist(),
                  'max_adjacent_component_delta_per_cascade':delta.max(axis=(0,2)).tolist()}
    if args.video:
        import av
        from PIL import Image,ImageDraw
        v=av.open(str(args.video));s=v.streams.video[0]
        stats['video']={'path':str(args.video.resolve()),'duration_seconds':float(s.duration*s.time_base),'width':s.width,'height':s.height,'fps':float(s.average_rate)}
        times=[28,30,32,34,36,38,40,42,44,46,48,50]
        sheet=Image.new('RGB',(4*480,3*294),(20,20,20));draw=ImageDraw.Draw(sheet)
        for i,t in enumerate(times):
            v.seek(int(t/s.time_base),stream=s,backward=True)
            frame=next(f for f in v.decode(s)if float(f.pts*s.time_base)>=t)
            im=frame.to_image();im.thumbnail((480,270));x=i%4*480;y=i//4*294
            sheet.paste(im,(x,y+24));draw.text((x+6,y+5),f'{float(frame.pts*s.time_base):.3f} s',fill='white')
        sheet.save(args.run/'video-contact-sheet.jpg',quality=92)
        sheet=Image.new('RGB',(3*720,4*454),(25,25,25));draw=ImageDraw.Draw(sheet)
        for i in range(12):
            t=46.8+.1*i;v.seek(int(t/s.time_base),stream=s,backward=True)
            frame=next(f for f in v.decode(s)if float(f.pts*s.time_base)>=t)
            im=frame.to_image().crop((1200,650,1920,1080));x=i%3*720;y=i//3*454
            sheet.paste(im,(x,y+24));draw.text((x+8,y+5),f'{float(frame.pts*s.time_base):.3f} s',fill='white')
        sheet.save(args.run/'tree-shadow-100ms-sequence.jpg',quality=94)
        v.close()
    (args.run/'analysis.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(stats,ensure_ascii=False))
if __name__=='__main__':main()
