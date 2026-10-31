#!/usr/bin/env python3
"""Versioned API example. DEMONSTRATION BOXES ONLY; does not run inference or move."""
import argparse,json,os,time,urllib.request,urllib.error
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8872');p.add_argument('--token-file',type=Path,default=Path(os.environ.get('TURTBOT_MODEL_TOKEN_FILE',str(Path(__file__).resolve().parents[1]/'.robot/runtime/service.token'))));p.add_argument('--once',action='store_true');a=p.parse_args()
 token=a.token_file.read_text().strip();headers={'Authorization':'Bearer '+token}
 while True:
  try:
   with urllib.request.urlopen(urllib.request.Request(a.url+'/api/v1/perception/input',headers=headers),timeout=3) as r:sample=json.load(r)
   with urllib.request.urlopen(urllib.request.Request(a.url+sample['frame']['url'],headers=headers),timeout=3) as r:jpeg=r.read()
   # Replace only this block with your model. Coordinates normalized to this JPEG.
   results={'api_version':'1.0','model_id':'external-mock-example','mock':True,'frame_id':sample['frame']['id'],
            'timestamp':sample['frame']['timestamp'],'detections':[{'label':'EXTERNAL MOCK REGION','confidence':.91,'bbox':[.15,.2,.3,.4]}]}
   req=urllib.request.Request(a.url+'/api/v1/perception/results',json.dumps(results).encode(),headers={**headers,'Content-Type':'application/json'},method='POST')
   with urllib.request.urlopen(req,timeout=3) as r:print(json.loads(r.read()),'frame_bytes',len(jpeg),flush=True)
  except (OSError,urllib.error.HTTPError) as exc:
   print('Model input/result unavailable:',exc,flush=True)
   if a.once:raise SystemExit(1)
  if a.once:return
  time.sleep(.25)
if __name__=='__main__':main()
