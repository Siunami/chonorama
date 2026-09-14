"""Verify actual recorded job inputs and finished video metadata."""
import hashlib,json
from shared_timeline import OUT,manifest
from prepare_shared_preview import probe
errors=[];checked=0;links=0;prior=None
for j in manifest()['segments']:
 p=OUT/'jobs'/j['id'];h=p/'input-hashes.json'
 if not h.exists():continue
 hashes=json.loads(h.read_text());checked+=1
 for y in [j['from'],j['to']]:
  actual=hashlib.sha256((OUT/f'letterbox/day-{y}.png').read_bytes()).hexdigest()
  if hashes[str(y)]!=actual:errors.append(f'{j["id"]}: input hash mismatch {y}')
 if prior and str(j['from']) in prior:
  links+=1
  if prior[str(j['from'])]!=hashes[str(j['from'])]:errors.append(f'{j["id"]}: adjacent input differs')
 prior=hashes
 req=json.loads((p/'request.json').read_text())
 if req['controls']['duration']!=4 or req['controls']['resolution']!='4k' or req['model']!='dreamina-seedance-2-0-260128':errors.append(f'{j["id"]}: request differs from pilot specification')
report={'jobs_checked':checked,'shared_boundaries_checked':links,'errors':errors}
film=OUT/'preview/timelapse.mp4'
if film.exists():
 m=probe(film);report['export']=m
 if (m['width'],m['height'],m['r_frame_rate'],int(m['nb_frames']))!=(3840,1920,'24/1',4321):errors.append('Final export metadata mismatch')
 if abs(float(m['duration'])-4321/24)>.001:errors.append('Final export timing mismatch')
(OUT/'input-audit.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if errors:raise SystemExit(1)
