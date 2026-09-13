"""Shanghai daytime pilot on the common world clock; no other city jobs."""
from pathlib import Path
import json,shutil
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'output/shanghai-shared-day'
YEARS=list(range(1750,1851,25))+list(range(1860,1901,10))+list(range(1905,1991,5))+list(range(1992,2027,2))
assert len(YEARS)==46 and YEARS[-1]==2026

def scene(y):
 if y<1843:return 'Qing trading waterfront, timber shops, junks, earth quay and low rural Pudong. No colonial banks or modern towers.'
 if y<1900:return 'Treaty-port commercial waterfront; progressively denser period warehouses, junks and early steamships. Foreign concessions remain distinct. No1920s Customs House or HSBC building.'
 if y<1923:return 'Commercial stone quay, steam shipping, period warehouses and early banking frontage. No1923 HSBC building or1927 Customs House yet. '+('Late Qing civic details.' if y<1912 else 'Republican China, with foreign concessions still present; do not replace all foreign flags.')
 if y<1927:return '1923 HSBC building present; the later1927 Customs House clocktower is not complete yet. Banking-era Bund and industrial low-rise Pudong.'
 if y<1937:return 'Completed1920s banking Bund including Customs House; Republican city and distinct foreign settlements, steamships and early cars.'
 if y<1941:return 'Wartime Shanghai, foreign settlement still separate; restrained disruption, surviving Bund buildings, no wholesale destruction.'
 if y<1949:return 'Postwar1945 Republic of China; no PRC flags, standing Bund architecture, low industrial Pudong.'
 if y<1966:return 'PRC working port with modest period civic symbols, workwear, cargo boats and industrial low-rise Pudong. No modern landmark towers.'
 if y<1977:return 'Cultural Revolution-era working port, restrained period banners and workwear; retain standing buildings, no invented mass destruction.'
 if y<1990:return 'Late1970s/1980s working waterfront, modernization but still low-rise industrial Pudong and no Pearl Tower.'
 if y==1990:return 'Pudong redevelopment begins, cleared sites and low-rise industrial waterfront. No Pearl/JinMao/SWFC/ShanghaiTower.'
 if y==1992:return 'Pearl Tower lower structure under construction within final silhouette; no complete upper sphere/antenna. No JinMao/SWFC/ShanghaiTower.'
 if y<1999:return 'Completed Pearl Tower, fixed final size; JinMao construction only, no SWFC or ShanghaiTower.'
 if y<2007:return 'Completed Pearl and JinMao, same fixed dimensions; developing Lujiazui. No completed SWFC or ShanghaiTower.'
 if y==2008:return 'SWFC complete, ShanghaiTower site excavation only; Pearl and JinMao unchanged.'
 if y==2010:return 'ShanghaiTower foundations and low early core, not a full tower. All completed landmarks fixed.'
 if y==2012:return 'ShanghaiTower around400m, upper floors under construction and lower cladding. Never exceed final envelope. Other towers fixed.'
 if y==2014:return 'ShanghaiTower fullheight with unfinished crown/cladding and cranes. Match final footprint/height; other towers fixed.'
 return 'Completed modern skyline, Pearl/JinMao/SWFC/ShanghaiTower unchanged in silhouette and position; only modest era-appropriate activity and surrounding development.'

def manifest():
 return {'title':'Shanghai · Shared historical clock','lighting':'day','model':'dreamina-seedance-2-0-260128','resolution':'4k','seconds':180,'fps':24,'years':YEARS,'frames':[{'year':y,'file':f'frames/day-{y}.png','scene':scene(y),'time':i*4} for i,y in enumerate(YEARS)],'segments':[{'id':f'day-{a}-{b}','from':a,'to':b,'seconds':4,'start':i*4,'end':(i+1)*4} for i,(a,b) in enumerate(zip(YEARS,YEARS[1:]))]}

if __name__=='__main__':
 (OUT/'frames').mkdir(parents=True,exist_ok=True)
 # Reuse generated candidates only at their actual dates; never relabel another year.
 old=ROOT/'output/seedance-history-4k/frames'
 for y in YEARS:
  src=old/f'day-{y}.png';dst=OUT/'frames'/src.name
  if src.exists() and not dst.exists():
   shutil.copy2(src,dst)
   dst.with_suffix('.provenance.json').write_text(json.dumps({'reusedFrom':str(src),'year':y,'qa':'review candidate'},indent=2))
 (OUT/'timeline.json').write_text(json.dumps(manifest(),indent=2))
 print('46 dates;45 clips;180 seconds;missing:',[y for y in YEARS if not (OUT/f'frames/day-{y}.png').exists()])
