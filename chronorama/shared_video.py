"""Resumable, bounded Shanghai-only 4K jobs for the shared 180-second clock."""
import argparse,hashlib,json,os,subprocess,urllib.error
from shared_timeline import OUT,ROOT,YEARS,manifest,scene
from seedance_common import request,ENDPOINT,BASE,MATTE,generation_lock
from generate import load_auth
import gengen

def save(path,data):
 path.write_text(json.dumps(data,indent=2))

def prepare():
 for y in YEARS:
  src=OUT/f'frames/day-{y}.png';dst=OUT/f'letterbox/day-{y}.png'
  if not src.exists():continue
  dst.parent.mkdir(exist_ok=True)
  if not dst.exists():subprocess.run(['ffmpeg','-v','error','-y','-i',str(src),'-vf','format=rgb24,pad=iw:ceil(iw*9/16):0:(oh-ih)/2:black',str(dst)],check=True)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--submit',action='store_true');ap.add_argument('--prepare',action='store_true');args=ap.parse_args()
 if args.prepare:prepare()
 key=load_auth('gengen')['key'];active=0;missing=[];summary=[];downloads=[]
 for job in manifest()['segments']:
  p=OUT/'jobs'/job['id'];p.mkdir(parents=True,exist_ok=True)
  task=p/'task.json';clip=p/'clip.mp4'
  if clip.exists():summary.append({'id':job['id'],'status':'downloaded'});continue
  if not task.exists():
   if (p/'submission-started.json').exists():summary.append({'id':job['id'],'status':'uncertain submission: reconcile before retry'});continue
   if all((OUT/f'letterbox/day-{y}.png').exists() for y in [job['from'],job['to']]):missing.append((job,p))
   continue
  result=request(ENDPOINT+'/'+json.loads(task.read_text())['id'],key);save(p/'status.json',result)
  status=result.get('status');summary.append({'id':job['id'],'status':status})
  if status in ('completed','succeeded'):
   outputs=result.get('outputs',{}).get('videos',[])
   if not outputs:raise RuntimeError('Completed task without output')
   url=outputs[0] if isinstance(outputs[0],str) else outputs[0]['url']
   downloads.append((job['id'],url,clip))
  elif status not in ('failed','cancelled','expired'):active+=1
 blocked=any(x['status'] in ('failed','cancelled','expired') or str(x['status']).startswith('uncertain') for x in summary)
 if args.submit and not blocked:
  for j,p in missing[:max(0,3-active)]:
   urls=[];hashes={}
   for y in [j['from'],j['to']]:
    src=OUT/f'letterbox/day-{y}.png';blob=src.read_bytes();digest=hashlib.sha256(blob).hexdigest();hashes[str(y)]=digest
    cache=OUT/'uploads';cache.mkdir(exist_ok=True);c=cache/f'{digest}.json'
    if c.exists():url=json.loads(c.read_text())['url']
    else:url=gengen.upload(blob,key,f'shanghai-day-{y}.png','image/png');save(c,{'url':url})
    urls.append(url)
   prompt=MATTE+BASE+f"Shanghai daytime only. Transition from {j['from']} to {j['to']}. Initial state: {scene(j['from'])} Final state: {scene(j['to'])} Follow these endpoint states. Reveal only appropriate intermediate construction. Completed structures never move or resize. No giant tower followed by shrinking. Match supplied first/last frames exactly. Keep neutral photographic tone, sky and water horizon stable. No captions. Slow motion gently at both endpoints for adjoining clips."
   body={'model':'dreamina-seedance-2-0-260128','mode':'image_first_last_frame','prompt':prompt,'assets':dict(zip(('firstFrameImage','lastFrameImage'),urls)),'controls':{'duration':4,'resolution':'4k','ratio':'adaptive','generateAudio':False,'watermark':False}}
   save(p/'request.json',body);save(p/'input-hashes.json',hashes);save(p/'submission-started.json',{'state':'Do not automatically retry an ambiguous submission'})
   try:result=request(ENDPOINT,key,body)
   except urllib.error.HTTPError as e:
    save(p/'submission-error.json',{'status':e.code,'detail':e.read().decode()});raise SystemExit(f'Submission rejected: HTTP{e.code}; details saved locally')
   save(p/'task.json',result);summary.append({'id':j['id'],'status':result.get('status'),'taskId':result.get('id')})
 save(OUT/'progress.json',summary)
 from shared_download import fetch
 for ident,url,clip in downloads:
  fetch(url,clip)
  next(x for x in summary if x['id']==ident)['status']='downloaded'
  save(OUT/'progress.json',summary)
 print(json.dumps({'downloaded':sum(x['status']=='downloaded' for x in summary),'total':45,'jobs':summary},indent=2),flush=True)

if __name__=='__main__':
 with generation_lock(OUT/'submission.lock'):main()
