"""Bounded, resumable byte-range downloads for signed video outputs."""
import concurrent.futures,json,re,subprocess
from pathlib import Path

def fetch(url,dest):
 dest=Path(dest);parts=dest.parent/'download-parts';parts.mkdir(exist_ok=True)
 def transfer(start,end,output,headers):
  return subprocess.run(['curl','--fail','--location','--silent','--show-error','--connect-timeout','20','--max-time','120','--range',f'{start}-{end}','--dump-header',str(headers),'--output',str(output),'--config','-'],input='url = '+json.dumps(url)+'\n',text=True,capture_output=True,timeout=135)
 probe=parts/'probe';headers=parts/'probe.headers';r=transfer(0,0,probe,headers)
 matches=re.findall(r'content-range:\s*bytes\s+(\d+)-(\d+)/(\d+)',headers.read_text().lower())
 if r.returncode or not matches or matches[-1][:2]!=('0','0'):raise RuntimeError('Provider range probe failed; saved task can be resumed')
 total=int(matches[-1][2]);size=512*1024
 def chunk(start):
  end=min(total,start+size)-1;part=parts/f'{start}.bin'
  for attempt in range(5):
   have=part.stat().st_size if part.exists() else 0
   if have==end-start+1:return part
   if have>end-start+1:raise RuntimeError('Unexpected saved chunk size')
   incoming=parts/f'{start}.incoming';head=parts/f'{start}.headers';transfer(start+have,end,incoming,head)
   ranges=re.findall(r'content-range:\s*bytes\s+(\d+)-(\d+)/(\d+)',head.read_text().lower())
   if not ranges or tuple(map(int,ranges[-1]))!=(start+have,end,total):continue
   data=incoming.read_bytes() if incoming.exists() else b''
   if len(data)>end-start+1-have:raise RuntimeError('Unexpected range body size')
   with part.open('ab') as f:f.write(data)
   if part.stat().st_size==end-start+1:return part
  raise RuntimeError('Video chunk transfer remained slow; partial data retained for resume')
 with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:ordered=list(pool.map(chunk,range(0,total,size)))
 temp=dest.with_suffix('.assembling')
 with temp.open('wb') as f:
  for p in ordered:f.write(p.read_bytes())
 if temp.stat().st_size!=total:raise RuntimeError('Downloaded size mismatch')
 check=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height','-of','json',str(temp)],capture_output=True,text=True)
 if check.returncode or not json.loads(check.stdout).get('streams'):raise RuntimeError('Downloaded video failed validation')
 temp.replace(dest)
