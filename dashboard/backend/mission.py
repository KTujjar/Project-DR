"""Mission records and versioned model contracts. No motion references."""
from datetime import datetime,timezone
import json,math,threading
from pathlib import Path
from uuid import uuid4


def utc():return datetime.now(timezone.utc).isoformat()


class MissionLog:
    def __init__(self,directory):
        self.directory=Path(directory);self.lock=threading.RLock();self.events=[]
        self.path=self.directory/'mission-events.jsonl'
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                try:self.events.append(json.loads(line))
                except ValueError:continue
        self.events=self.events[-500:]
    def add(self,kind,note,context=None,**extra):
        event={'id':str(uuid4()),'timestamp_utc':utc(),'kind':kind,'note':note,'context':context or {},**extra}
        with self.lock:
            self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
            with self.path.open('a') as f:f.write(json.dumps(event,allow_nan=False)+'\n')
            self.events.append(event);self.events=self.events[-500:]
        return event
    def list(self):
        with self.lock:return list(reversed(self.events))


def validate_detections(payload):
    json.dumps(payload,allow_nan=False)
    if not isinstance(payload.get('mock',False),bool):raise ValueError('mock must be boolean')
    if payload.get('api_version')!='1.0':raise ValueError('api_version must be 1.0')
    if not isinstance(payload.get('model_id'),str) or not 1<=len(payload['model_id'])<=80:raise ValueError('model_id required, at most 80 characters')
    if not isinstance(payload.get('frame_id'),str) or len(payload['frame_id'])>100:raise ValueError('frame_id required')
    results=payload.get('detections')
    if not isinstance(results,list) or len(results)>100:raise ValueError('detections must contain at most 100 items')
    clean=[]
    for d in results:
        if not isinstance(d,dict) or not isinstance(d.get('label'),str) or not 1<=len(d['label'])<=100:raise ValueError('label required')
        confidence=d.get('confidence')
        if isinstance(confidence,bool) or not isinstance(confidence,(int,float)) or not math.isfinite(confidence) or not 0<=confidence<=1:raise ValueError('confidence must be in [0,1]')
        box=d.get('bbox');mask=d.get('mask')
        if box is None and mask is None:raise ValueError('bbox or polygon mask required')
        if box is not None:
            if not isinstance(box,list) or len(box)!=4 or not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and 0<=x<=1 for x in box):raise ValueError('bbox must be normalized [x,y,width,height]')
            if box[2]<=0 or box[3]<=0 or box[0]+box[2]>1.00001 or box[1]+box[3]>1.00001:raise ValueError('bbox outside frame')
        if mask is not None:
            polys=mask.get('polygons') if isinstance(mask,dict) else None
            if not isinstance(polys,list) or not 1<=len(polys)<=16:raise ValueError('mask.polygons must contain 1–16 normalized polygons')
            for poly in polys:
                if not isinstance(poly,list) or not 3<=len(poly)<=512:raise ValueError('Polygon requires 3–512 vertices')
                for point in poly:
                    if not isinstance(point,list) or len(point)!=2 or not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and 0<=x<=1 for x in point):raise ValueError('Invalid normalized polygon coordinate')
        clean.append({'label':d['label'],'confidence':confidence,'bbox':box,'mask':mask,'metadata':d.get('metadata',{})})
    return {**payload,'detections':clean}
