"""Build an isolated preview; crop mattes only, never stretch the scene."""
import argparse,json,shutil,subprocess,html
from pathlib import Path
from PIL import Image,ImageDraw
from shared_timeline import OUT,ROOT,manifest,YEARS

def run(*args):subprocess.run(args,check=True)
def probe(path):return json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height,r_frame_rate,nb_frames,duration','-of','json',str(path)]))['streams'][0]

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--videos',action='store_true');args=ap.parse_args();preview=OUT/'preview';(preview/'frames').mkdir(parents=True,exist_ok=True)
 shutil.copy2(ROOT/'shared-viewer.html',preview/'index.html');shutil.copy2(OUT/'timeline.json',preview/'timeline.json')
 (preview/'render-progress.json').write_text(json.dumps({'ready':len(list((OUT/'jobs').glob('*/panorama-cfr.mp4'))),'total':45,'complete':(preview/'timelapse.mp4').exists()}))
 cards=[];sheet=Image.new('RGB',(1200,180*((len(YEARS)+2)//3)),'#101318');draw=ImageDraw.Draw(sheet)
 for i,y in enumerate(YEARS):
  src=OUT/f'frames/day-{y}.png'
  if not src.exists():continue
  public=preview/'frames'/src.name
  if not public.exists() or public.stat().st_mtime<src.stat().st_mtime:shutil.copy2(src,public)
  cards.append(f'<article><h2>{y}</h2><a href="frames/{src.name}"><img loading="lazy" src="frames/{src.name}" alt="Shanghai in {y}"></a></article>')
  im=Image.open(src).convert('RGB');im.thumbnail((390,155));x=(i%3)*400;top=(i//3)*180;sheet.paste(im,(x,top+22));draw.text((x+5,top+4),str(y),fill='white')
 sheet.save(OUT/'keyframes-contact.jpg',quality=90)
 (preview/'frames.html').write_text('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Shanghai reference images</title><style>body{background:#101318;color:#eee;font:15px system-ui;padding:24px}a{color:#e8c17a}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}img{width:100%}h2{font-size:16px}</style><a href="index.html">← Panorama</a><h1>Shanghai · 46 shared dates</h1><p id="render-status">Preparing the daytime film…</p><p>Daytime reference images. Illustrative reconstructions; compare horizon, landmark scale and appearance between dates.</p><main>'+''.join(cards)+'</main><script>async function progress(){try{const p=await fetch("render-progress.json",{cache:"no-store"}).then(r=>r.json());document.getElementById("render-status").textContent=p.complete?"The complete three-minute film is ready. Open Panorama above.":p.ready+" of 45 video chapters are ready. The full film is still rendering."}catch(e){}}progress();setInterval(progress,30000);</script>')
 if not args.videos:return
 clips=[];metadata=[]
 for i,j in enumerate(manifest()['segments']):
  folder=OUT/'jobs'/j['id'];raw=folder/'clip.mp4';dst=folder/'panorama-cfr.mp4'
  if not raw.exists():continue
  m=probe(raw);metadata.append({'id':j['id'],**m})
  if (m['width'],m['height'],m['r_frame_rate'])!=(3840,2160,'24/1'):raise RuntimeError(f'Unexpected dimensions/fps for {j["id"]}: {m}')
  frames=97 if i==44 else 96
  if int(m['nb_frames'])<frames:raise RuntimeError('Video is shorter than requested')
  if not dst.exists():
   temp=folder/'panorama-cfr-working.mp4'
   run('ffmpeg','-v','error','-y','-i',str(raw),'-vf',f'crop=3840:1920:0:120,trim=end_frame={frames},setpts=N/(24*TB)','-r','24','-fps_mode','cfr','-c:v','libx264','-preset','veryfast','-crf','20','-g','6','-keyint_min','6','-sc_threshold','0','-pix_fmt','yuv420p','-an','-movflags','+faststart',str(temp));temp.replace(dst)
   print(j['id'],'prepared',flush=True)
  encoded=probe(dst)
  if int(encoded['nb_frames'])!=frames or abs(float(encoded['duration'])-frames/24)>.00001:raise RuntimeError(f'Unexpected output timing: {encoded}')
  clips.append(dst)
 (OUT/'video-metadata.json').write_text(json.dumps(metadata,indent=2))
 if len(clips)==45:
  listing=OUT/'concat.txt';listing.write_text(''.join("file '"+str(p)+"'\n" for p in clips))
  dst=preview/'timelapse.mp4'
  if not dst.exists():
   tmp=preview/'timelapse-working.mp4';run('ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',str(listing),'-c','copy','-movflags','+faststart',str(tmp));tmp.replace(dst)
  (preview/'render-progress.json').write_text(json.dumps({'ready':45,'total':45,'complete':True}));report=probe(dst);(OUT/'export-metadata.json').write_text(json.dumps(report,indent=2));print('Joined',report,flush=True)
 else:print(f'{len(clips)}/45 clips ready; full timeline not assembled',flush=True)

if __name__=='__main__':main()
