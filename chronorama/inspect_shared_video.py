"""Create review sheets from completed clips without altering generated media."""
import json,subprocess,io
from PIL import Image,ImageDraw
from shared_timeline import OUT,manifest
qa=OUT/'qa-cfr';qa.mkdir(exist_ok=True)
for segment in manifest()['segments']:
 folder=OUT/'jobs'/segment['id'];src=folder/'panorama-cfr.mp4';dst=qa/(segment['id']+'.jpg')
 if not src.exists() or dst.exists():continue
 sheet=Image.new('RGB',(1440,4*260),'#111318');d=ImageDraw.Draw(sheet)
 for i,t in enumerate([0,1,2,3.95]):
  data=subprocess.check_output(['ffmpeg','-v','error','-ss',str(t),'-i',str(src),'-frames:v','1','-f','image2pipe','-vcodec','png','-'])
  im=Image.open(io.BytesIO(data)).convert('RGB')
  # Compare whole panorama, Pudong and the wrap seam at the same time.
  whole=im.copy();whole.thumbnail((480,240));sheet.paste(whole,(0,i*260+20))
  pudong=im.crop((int(im.width*.33),int(im.height*.2),int(im.width*.67),int(im.height*.65)));pudong.thumbnail((480,240));sheet.paste(pudong,(480,i*260+20))
  seam=Image.new('RGB',(int(im.width*.16),im.height));w=int(im.width*.08);seam.paste(im.crop((im.width-w,0,im.width,im.height)),(0,0));seam.paste(im.crop((0,0,w,im.height)),(w,0));seam.thumbnail((480,240));sheet.paste(seam,(960,i*260+20))
  d.text((5,i*260+3),f"{segment['from']} to {segment['to']}  {t}s | panorama / Pudong / wrap seam",fill='white')
 sheet.save(dst,quality=90)
 print(dst.name,flush=True)
