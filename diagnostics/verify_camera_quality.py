"""Read-only camera delivery/quality audit; never arms or sends robot commands."""
import argparse,asyncio,hashlib,json,time,sys,urllib.request
from io import BytesIO
from pathlib import Path
import numpy as np
from PIL import Image
from websockets.asyncio.client import connect
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.missionctl import health
URL='http://127.0.0.1:8872'

def image_stats(jpeg):
    with Image.open(BytesIO(jpeg)) as im:
        im.load();a=np.asarray(im.convert('RGB'));q=im.quantization.get(0,[])
    luma=a@np.array([.2126,.7152,.0722])
    return {'width':a.shape[1],'height':a.shape[0],'jpeg_bytes':len(jpeg),'near_white_fraction':float(np.mean(np.all(a>=250,axis=2))),
            'near_black_fraction':float(np.mean(np.all(a<=5,axis=2))),'mean_rgb':a.mean((0,1)).tolist(),
            'luma_percentiles_1_10_50_90_99':np.percentile(luma,[1,10,50,90,99]).tolist(),'luma_quantization_table':q}

async def measure(seconds,output):
    output.mkdir(parents=True,exist_ok=True);frames=[];last=None;beg=time.monotonic()
    async with connect(URL.replace('http:','ws:')+'/ws/video',origin=URL,max_size=3_000_000) as ws:
        while time.monotonic()-beg<seconds:
            meta=json.loads(await asyncio.wait_for(ws.recv(),5));jpeg=await asyncio.wait_for(ws.recv(),5)
            digest=hashlib.sha256(jpeg).hexdigest();assert digest==meta['jpeg_sha256'],'JPEG changed after ingest'
            stats=image_stats(jpeg);frames.append({'received_mono':time.monotonic(),'frame_id':meta['frame_id'],'sha256':digest,
                'previous_ack_latency_ms':meta.get('previous_ack_latency_ms'),'pipeline_latency_ms':meta.get('pipeline_latency_ms'),**stats})
            await ws.send(json.dumps({'frame_id':meta['frame_id'],'client':'quality-audit'}));last=jpeg
    token=(ROOT/'.robot/runtime/service.token').read_text().strip()
    req=urllib.request.Request(URL+'/api/v1/perception/frames/'+frames[-1]['frame_id'],headers={'Authorization':'Bearer '+token})
    exact=urllib.request.urlopen(req,timeout=5).read();assert exact==last,'Exact-frame API bytes differ from video'
    (output/'after-live.jpg').write_bytes(last)
    h=health();(output/'after-health.json').write_text(json.dumps(h,indent=2))
    def summary(values):
        a=np.array([x for x in values if x is not None]);return {'median':float(np.median(a)),'p95':float(np.percentile(a,95))} if len(a) else None
    report={'frames':len(frames),'duration_s':frames[-1]['received_mono']-frames[0]['received_mono'],
        'delivered_fps':(len(frames)-1)/(frames[-1]['received_mono']-frames[0]['received_mono']),
        'capture_to_backend_ms':summary([f['pipeline_latency_ms'] for f in frames]),
        'capture_to_decode_ack_ms':summary([f['previous_ack_latency_ms'] for f in frames]),
        'latency_definition':'Pi end-of-frame to decode/ACK, includes audit processing; not optical latency',
        'all_video_hashes_match_relay_jpeg':True,'exact_frame_api_equals_video_bytes':True,
        'distinct_luma_quantization_tables':len({tuple(f['luma_quantization_table']) for f in frames}),
        'last_image':frames[-1],'camera':h['sensors']['camera']['data'],'motion_enabled':h['motion_enabled'],'armed':h['control']['armed'],
        'obstacle_override':h['control']['obstacle_guard'].get('bypassed'),'frames_data':frames}
    (output/'delivery-quality.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ['frames_data','camera','last_image']},indent=2))
    print(json.dumps({'last_image':{k:v for k,v in report['last_image'].items() if k!='luma_quantization_table'},'camera':{k:v for k,v in report['camera'].items() if k in ['width','height','isp_digital_gain','jpeg_quality','white_balance_gains_rgb','requested_exposure_ms','requested_analogue_gain','quality','raw_saturated_fraction']}},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--seconds',type=float,default=15);p.add_argument('--output',type=Path,default=ROOT/'diagnostics/camera-quality');a=p.parse_args();asyncio.run(measure(a.seconds,a.output))
