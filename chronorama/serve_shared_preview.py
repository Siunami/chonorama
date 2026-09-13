"""Serve only this pilot's public assets, with byte ranges for video seeking."""
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import re
from shared_timeline import OUT
BASE=(OUT/'preview').resolve()
class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*a,**kw):super().__init__(*a,directory=str(BASE),**kw)
 def list_directory(self,path):self.send_error(403);return None
 def send_head(self):
  self.remaining=None
  p=Path(self.translate_path(self.path)).resolve()
  if not p.is_relative_to(BASE):self.send_error(403);return None
  if p.is_file() and p.suffix=='.mp4' and self.headers.get('Range'):
   size=p.stat().st_size;m=re.fullmatch(r'bytes=(\d*)-(\d*)',self.headers['Range'])
   if not m or not any(m.groups()):self.send_error(416);return None
   if m[1]:start=int(m[1]);end=min(int(m[2]),size-1) if m[2] else size-1
   else:start=max(0,size-int(m[2]));end=size-1
   if start>=size or start>end:self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.end_headers();return None
   f=p.open('rb');f.seek(start);self.remaining=end-start+1
   self.send_response(206);self.send_header('Content-Type','video/mp4');self.send_header('Accept-Ranges','bytes');self.send_header('Content-Range',f'bytes {start}-{end}/{size}');self.send_header('Content-Length',str(self.remaining));self.end_headers();return f
  return super().send_head()
 def copyfile(self,source,output):
  if self.remaining is None:return super().copyfile(source,output)
  try:
   while self.remaining>0:
    b=source.read(min(1024*1024,self.remaining))
    if not b:break
    output.write(b);self.remaining-=len(b)
  except (BrokenPipeError,ConnectionResetError):pass
if __name__=='__main__':
 print('Shanghai preview: http://127.0.0.1:8749/',flush=True)
 ThreadingHTTPServer(('127.0.0.1',8749),Handler).serve_forever()
