"""Camera transport, mission records and versioned model API; no autonomous control."""
import asyncio,json,math,os,secrets,time,zipfile,hashlib
from collections import deque
from datetime import datetime,timezone
from io import BytesIO
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException,Request,WebSocket
from fastapi.responses import Response,StreamingResponse
from PIL import Image
from .mission import MissionLog,validate_detections


def register(app,store,control,directory,mode,same_origin):
    directory=Path(directory);mission=MissionLog(directory);recent=deque(maxlen=90);models={};acks=deque(maxlen=100)
    token_path=Path(os.environ.get('TURTBOT_TOKEN_FILE',str(directory.parent.parent/'.runtime/service.token')))
    token=token_path.read_text().strip() if token_path.exists() else None
    app.state.mission=mission;app.state.models=models;app.state.recent_frames=recent;app.state.browser_acks=acks
    app.state.mock_detector=False

    def authorize(request):
        value=request.headers.get('authorization','')
        if not token or not secrets.compare_digest(value,'Bearer '+token):raise HTTPException(401,'Service token required')

    async def body(request,limit):
        chunks=[];size=0
        async for chunk in request.stream():
            size+=len(chunk)
            if size>limit:raise HTTPException(413,'Payload too large')
            chunks.append(chunk)
        return b''.join(chunks)

    def context():
        m=store.message();return {'mode':mode,'pose':m['sensors']['odom'],'camera':m['sensors']['camera'],
            'scan_timestamp':m['sensors']['scan'].get('stamp'),'nearest_obstacle_m':min([x for x in (m['sensors']['scan'].get('data') or {}).get('ranges',[]) if x is not None and x>0],default=None)}

    def model_views():
        now=time.time();results=[]
        for m in list(models.values()):
            if now-m['received_unix']<1 and m.get('source_timestamp') and now-m['source_timestamp']<.75:results.append({**m,'result_age_ms':(now-m['source_timestamp'])*1000})
        if app.state.mock_detector:
            frame=store.describe('camera').get('data') or {}
            results.append({'api_version':'1.0','model_id':'mock-demonstrator','frame_id':frame.get('frame_id'),
                'mock':True,'received_unix':now,'detections':[{'label':'DEMO TARGET · MOCK','confidence':.92,'bbox':[.34,.24,.3,.42]}]})
        return results
    app.state.model_views=model_views

    @app.post('/api/internal/camera')
    async def ingest(request:Request):
        authorize(request)
        if mode!='hardware':raise HTTPException(409,'Hardware frames cannot enter mock mode')
        try:
            meta=json.loads(request.headers.get('x-frame-meta',''))
            frame_id=meta['frame_id'];captured=float(meta['capture_unix'])
            if not isinstance(frame_id,str) or len(frame_id)>100 or not math.isfinite(captured):raise ValueError('Invalid identity/timestamp')
        except (ValueError,KeyError,TypeError):raise HTTPException(422,'Invalid frame metadata')
        image=await body(request,2_000_000)
        digest=hashlib.sha256(image).hexdigest()
        if meta.get('jpeg_sha256') and meta['jpeg_sha256']!=digest:raise HTTPException(422,'JPEG integrity mismatch')
        try:
            with Image.open(BytesIO(image)) as decoded:
                width,height=decoded.size
                if decoded.format!='JPEG' or width*height>8_100_000:raise ValueError('Expected bounded JPEG')
                decoded.verify()
        except Exception:raise HTTPException(422,'JPEG failed validation')
        if width!=meta.get('width') or height!=meta.get('height'):raise HTTPException(422,'JPEG geometry mismatch')
        age=(time.time()-captured)*1000
        if not -200<=age<=5000:raise HTTPException(422,'Frame is stale or clock changed')
        data={**meta,'jpeg_sha256':digest,'width':width,'height':height,'verified':True,'format':'image/jpeg','source':'IMX219 / Pi ISP + hardware JPEG Q92' if meta.get('path')=='isp' else 'IMX219 / V4L2 → Mac processing',
              'pipeline_latency_ms':max(0,age),'clock_note':'Latency uses the Pi clock at capture and JPEG ingest; excludes browser display.'}
        store.update_camera(data,image,'image/jpeg',captured)
        recent.append({'id':frame_id,'timestamp':captured,'image':image,'data':data})
        with store.lock:
            store.metadata['camera_note']='Live IMX219; Pi ISP/JPEG Q92, unity digital gain, bounded auto exposure and gray-world WB; approximate reference color matrix' if meta.get('path')=='isp' else 'Live IMX219; Mac Bayer processing, gray-world WB, no viewing brightness boost; manual capture exposure'
            store.metadata['camera_pipeline']='V4L2 → Pi hardware ISP → Pi hardware JPEG Q92 → SSH relay → authenticated ingest' if meta.get('path')=='isp' else 'Native raw capture → SSH → Mac RGB/JPEG → authenticated Pi ingest'
        return {'accepted':frame_id,'pipeline_latency_ms':max(0,age)}

    @app.websocket('/ws/video')
    async def video(ws:WebSocket):
        if not same_origin(ws.headers.get('origin'),ws.headers.get('host')):
            await ws.close(code=1008);return
        await ws.accept();last=None;previous_ack=None
        try:
            while True:
                with store.lock:
                    camera=store.describe('camera');image=store.image;mime=store.image_mime
                data=camera.get('data') or {};identifier=data.get('frame_id') or str(camera.get('stamp'))
                if image is None or camera['status']!='live' or identifier==last:
                    try:
                        event=await asyncio.wait_for(ws.receive(),timeout=.02)
                        if event.get('type')=='websocket.disconnect':return
                    except asyncio.TimeoutError:pass
                    continue
                last=identifier
                await ws.send_json({'frame_id':identifier,'timestamp':camera.get('stamp'),'width':data.get('width'),
                    'height':data.get('height'),'mime':mime,'mode':mode,'jpeg_sha256':data.get('jpeg_sha256'),'models':model_views(),'previous_ack_latency_ms':previous_ack,'pipeline_latency_ms':data.get('pipeline_latency_ms'), 'server_send_unix':time.time()})
                await ws.send_bytes(image)
                ack=await asyncio.wait_for(ws.receive_json(),timeout=3)
                if ack.get('frame_id')!=identifier:raise ValueError('Video acknowledgement mismatch')
                if mode=='hardware' and camera.get('stamp'):
                    age=(time.time()-camera['stamp'])*1000
                    if 0<=age<10000:
                        previous_ack=age
                        if ack.get('client','browser')=='browser':
                            acks.append(age)
                            with store.lock:store.metadata['capture_to_browser_ack_ms']=age
        except Exception:
            try:await ws.close()
            except Exception:pass

    @app.get('/api/mission/events')
    async def events():return {'events':mission.list()}

    @app.post('/api/mission/events')
    async def add_event(request:Request):
        try:
            p=json.loads(await body(request,16384));note=p['note'].strip();kind=p.get('kind','annotation')
            if not 1<=len(note)<=1000 or kind not in ('annotation','poi'):raise ValueError()
        except (ValueError,KeyError,TypeError):raise HTTPException(422,'Provide a note (1–1000 characters), kind annotation or poi')
        return mission.add(kind,note,context())

    @app.get('/api/snapshots')
    async def history():
        captures=[]
        if directory.exists():
            for path in sorted(directory.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True):
                try:UUID(path.stem);captures.append(json.loads(path.read_text()))
                except (ValueError,OSError):continue
                if len(captures)==30:break
        return {'captures':captures}

    @app.get('/api/mission/export')
    async def export():
        output=BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('mission.json',json.dumps({'exported_utc':datetime.now(timezone.utc).isoformat(),'mode':mode,'events':mission.list(),'sensors':store.message()},indent=2))
            if directory.exists():
                for path in directory.iterdir():
                    if path.is_file() and path.suffix in ('.jpg','.png','.svg','.json','.jsonl'):archive.write(path,'captures/'+path.name)
        return Response(output.getvalue(),media_type='application/zip',headers={'Content-Disposition':'attachment; filename=turtle-mission.zip'})

    @app.post('/api/control/stop')
    async def stop(request:Request):
        authorize(request);control.disarm('Operator stop from launcher');return control.state()

    @app.get('/api/v1/perception/input')
    async def model_input(request:Request):
        authorize(request);m=store.message();c=m['sensors']['camera']
        if c['status']!='live' or not c['data']:raise HTTPException(503,'No fresh camera frame')
        frame=c['data'];identifier=frame.get('frame_id')
        if not identifier:raise HTTPException(503,'Camera has no frame identity')
        return {'api_version':'1.0','mode':mode,'frame':{'id':identifier,'timestamp':c['stamp'],
            'width':frame['width'],'height':frame['height'],'mime':store.image_mime,'url':'/api/v1/perception/frames/'+identifier,
            'sha256':frame.get('jpeg_sha256'),'calibration':frame.get('calibration',{'intrinsics':None})},'lidar':m['sensors']['scan'],'pose':m['sensors']['odom']}

    @app.get('/api/v1/perception/frames/{identifier}')
    async def model_frame(identifier:str,request:Request):
        authorize(request)
        for frame in reversed(recent):
            if frame['id']==identifier:return Response(frame['image'],media_type='image/jpeg')
        if mode=='mock':return Response(store.image,media_type=store.image_mime)
        raise HTTPException(410,'Frame expired; request a current input')

    @app.post('/api/v1/perception/results')
    async def model_results(request:Request):
        authorize(request)
        try:result=validate_detections(json.loads(await body(request,256_000)))
        except (ValueError,TypeError,AttributeError):raise HTTPException(422,'Invalid v1 detection payload')
        frame=next((f for f in reversed(recent) if f['id']==result['frame_id']),None)
        if frame is None and mode!='mock':raise HTTPException(410,'Unknown/expired frame identity')
        if frame and time.time()-frame['timestamp']>2:raise HTTPException(409,'Model result too old for live overlays')
        result['received_unix']=time.time();result['mock']=bool(result.get('mock',False));result['source_timestamp']=frame['timestamp'] if frame else None
        models[result['model_id']]=result
        if len(models)>12:models.pop(next(iter(models)))
        return {'accepted':True,'model_id':result['model_id'],'movement_generated':False}

    @app.post('/api/v1/perception/mock')
    async def toggle_mock():
        app.state.mock_detector=not app.state.mock_detector
        mission.add('model_status','Mock detector '+('enabled' if app.state.mock_detector else 'disabled'),{'mode':mode})
        if app.state.mock_detector:mission.add('mock_detection','Placeholder detection alert — demonstration only; no inference performed',{'mode':mode,'mock':True})
        return {'enabled':app.state.mock_detector,'mock':True,'movement_generated':False}

    @app.get('/api/map')
    async def map_state():
        with store.lock:
            grid=store.occupancy_map
            return {'available':grid is not None,'map':grid,'note':'No /map received. SLAM Toolbox is not installed on this Pi; raw scans stay live.' if grid is None else 'Existing ROS occupancy grid; no SLAM process launched by dashboard'}

    @app.get('/api/map/image.png')
    async def map_image():
        with store.lock:grid=store.occupancy_map
        if grid is None:raise HTTPException(503,'No occupancy map available')
        pixels=bytes(125 if p<0 else 255-round(min(100,p)*2.55) for p in grid['data'])
        image=Image.frombytes('L',(grid['width'],grid['height']),pixels).transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        output=BytesIO();image.save(output,format='PNG');return Response(output.getvalue(),media_type='image/png')
