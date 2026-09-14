"""Run the authorized finite45-clip pilot, never other locations or lighting modes."""
import subprocess,time,json,sys
from pathlib import Path
from shared_timeline import OUT,ROOT,YEARS
from seedance_common import generation_lock

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 missing=[y for y in YEARS if not (OUT/f'frames/day-{y}.png').exists()]
 if missing:raise SystemExit(f'Missing reviewed input images for years: {missing}. No jobs submitted.')
 if not (OUT/'timeline.json').exists():raise SystemExit('Run shared_timeline.py before starting the pipeline.')
 for cycle in range(240):
  result=subprocess.run([sys.executable,str(ROOT/'shared_video.py'),'--prepare','--submit'],capture_output=True,text=True)
  if result.returncode:
   (OUT/'pipeline-error.log').write_text(result.stdout+'\n'+result.stderr)
   print('Pipeline stopped; diagnostic saved in pipeline-error.log',flush=True);raise SystemExit(result.returncode)
  progress=json.loads((OUT/'progress.json').read_text())
  completed=sum(x['status']=='downloaded' for x in progress)
  failed=[x for x in progress if x['status'] in ('failed','cancelled','expired') or str(x['status']).startswith('uncertain')]
  print(f'{completed}/45 clips downloaded;{len(failed)} failed or uncertain',flush=True)
  subprocess.run([sys.executable,str(ROOT/'prepare_shared_preview.py'),'--videos'],check=True)
  if failed:
   print('Stopped expansion for review of failed/uncertain job; no automatic regeneration',flush=True);raise SystemExit(2)
  if completed==45:
   print('All45 clips downloaded and preview assembled',flush=True);break
  time.sleep(30)
 else:raise SystemExit('Bounded worker ended; resume after reviewing progress')

if __name__=='__main__':
 with generation_lock(OUT/'pipeline.lock'):main()
