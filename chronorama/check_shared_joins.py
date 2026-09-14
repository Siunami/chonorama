"""Measure decoded neighboring boundary frames; no media alteration."""
import json,subprocess
import numpy as np
from PIL import Image,ImageDraw
from shared_timeline import OUT,manifest
qa=OUT/'qa-cfr';qa.mkdir(exist_ok=True)
def frame(path,index):
 raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-vf',f'select=eq(n\\,{index}),scale=960:480','-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'])
 return np.frombuffer(raw,dtype=np.uint8).reshape(480,960,3)
segments=manifest()['segments'];results=[]
for a,b in zip(segments,segments[1:]):
 pa=OUT/'jobs'/a['id']/'panorama-cfr.mp4';pb=OUT/'jobs'/b['id']/'panorama-cfr.mp4';cache=qa/f'join-{a["to"]}.json'
 if not pa.exists() or not pb.exists():continue
 if cache.exists():results.append(json.loads(cache.read_text()));continue
 last=frame(pa,95);first=frame(pb,0);before=frame(pa,94);after=frame(pb,1)
 def mae(x,y):return float(np.abs(x.astype(float)-y.astype(float)).mean())
 result={'year':a['to'],'boundary_mean_pixel_change':mae(last,first),'previous_frame_change':mae(before,last),'next_frame_change':mae(first,after),'note':'Difference metric is a review aid, not a geometry or perceptual pass/fail test.'}
 cache.write_text(json.dumps(result,indent=2));results.append(result)
 sheet=Image.new('RGB',(960,1000),'#111318');sheet.paste(Image.fromarray(last),(0,20));sheet.paste(Image.fromarray(first),(0,520));d=ImageDraw.Draw(sheet);d.text((5,3),f'{a["to"]}: previous clip final displayed frame',fill='white');d.text((5,503),'Following clip first frame',fill='white');sheet.save(qa/f'join-{a["to"]}.jpg',quality=90)
(qa/'joins.json').write_text(json.dumps(results,indent=2));print('Checked',len(results),'joins')
