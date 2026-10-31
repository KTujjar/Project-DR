"""Mac RAW10 processing worker. Latest-frame capture transport, HTTP JPEG ingest.
No ROS or motor commands. Reconnects with bounded backoff, no saved SSH password.
"""
import argparse,json,subprocess,time,sys,os,threading,http.client,hashlib
from urllib.parse import urlsplit
from pathlib import Path
from io import BytesIO
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from camera.protocol import read_frame
from camera.convert_raw10 import unpack_raw10,render,color_matrix
from scripts.missionctl import base as ssh_base


def run(target,control,url,token,stop=None,path='auto'):
    active_path='isp' if path=='auto' else path
    stop=stop or threading.Event();matrix=color_matrix('imx219',5000);restarts=0;failures=0
    while not stop.is_set():
        proc=None
        try:
            cmd=ssh_base({'target':target})
            cmd[cmd.index('-S')+1]=str(control)
            cmd+=['exec "$HOME/turtbot-dashboard/camera/'+('isp_worker' if active_path=='isp' else 'capture_worker')+'"']
            proc=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=sys.stderr,bufsize=0)
            latest={'header':None,'data':None,'error':None};condition=threading.Condition()
            def reader():
                try:
                    while not stop.is_set():
                        h,b=read_frame(proc.stdout)
                        with condition:latest.update(header=h,data=b);condition.notify()
                except (OSError,ValueError,EOFError) as exc:
                    with condition:latest['error']=exc;condition.notify()
            thread=threading.Thread(target=reader,daemon=True);thread.start()
            endpoint=urlsplit(url);connection=http.client.HTTPConnection(endpoint.hostname,endpoint.port or 80,timeout=2)
            last_sequence=None;skipped=0
            exposure=0.;count=0;session=f'{time.time_ns():x}';started=time.monotonic()
            while not stop.is_set():
                with condition:
                    condition.wait_for(lambda:latest['error'] or (latest['header'] and latest['header']['sequence']!=last_sequence) or stop.is_set(),timeout=4)
                    if stop.is_set():break
                    if latest['error']:raise latest['error']
                    header,data=latest['header'],latest['data']
                    if header is None or header['sequence']==last_sequence:raise EOFError('Camera stalled')
                if last_sequence is not None:skipped+=max(0,header['sequence']-last_sequence-1)
                last_sequence=header['sequence'];begin=time.monotonic()
                if header['format']=='JPEG':
                    jpeg=data;width=header['width'];height=header['height'];exposure=0.
                else:
                    raw=unpack_raw10(data,header['width'],header['height'],header['stride'])
                    # No hidden viewing stretch; WB estimates exclude clipped/dark cells.
                    rgb,stats=render(raw,ccm=matrix,exposure='0')
                    header['white_balance_gains_rgb']=stats['white_balance_gains_rgb']
                    im=Image.fromarray(rgb);im.thumbnail((1280,720),Image.Resampling.LANCZOS);out=BytesIO();im.save(out,format='JPEG',quality=92,subsampling=0)
                    jpeg=out.getvalue();width,height=im.size
                with Image.open(BytesIO(jpeg)) as checked:
                    checked.load()
                    if checked.format!='JPEG' or checked.size!=(width,height):raise ValueError('Encoded image failed full decode/geometry validation')
                    sample=np.asarray(checked.convert('RGB'))[::8,::8]
                    near_white=float(np.mean(np.all(sample>=250,axis=2)))
                    near_black=float(np.mean(np.all(sample<=5,axis=2)))
                count+=1
                if count>15:failures=0
                metadata={**header,'frame_id':f'{session}-{header["sequence"]}','width':width,'height':height,
                          'source_width':header.get('source_width',header['width']),'source_height':header.get('source_height',header['height']),'path':active_path,'processing_ms':(time.monotonic()-begin)*1000,
                          'relay_fps':count/max(.001,time.monotonic()-started),'restarts':restarts,'viewing_exposure_ev':exposure,
                          'calibration':{'intrinsics':None,'color':'Bounded gray-world WB; approximate IMX219 5000K reference CCM; not chart calibrated'},
                          'jpeg_sha256':hashlib.sha256(jpeg).hexdigest(),
                          'quality':{'near_white_fraction':near_white,'near_black_fraction':near_black,'extra_viewing_gain':1.,'jpeg_reencoded_on_mac':active_path!='isp','warning':'Most pixels are near white; check scene/lighting' if near_white>.3 else 'Most pixels are near black; check lighting/lens' if near_black>.5 else None},
                          'jpeg_bytes':len(jpeg),'decoded_on_mac':True,'jpeg_quality':92}
                metadata['relay_skipped']=skipped
                try:
                    connection.request('POST','/api/internal/camera',jpeg,headers={'Authorization':'Bearer '+token,'Content-Type':'image/jpeg','X-Frame-Meta':json.dumps(metadata,separators=(',',':'))})
                    response=connection.getresponse();message=response.read()
                    if response.status>=400 and count%15==1:print('Camera ingest rejected:',response.status,message[:150],file=sys.stderr,flush=True)
                except (OSError,http.client.HTTPException) as exc:
                    connection.close();connection=http.client.HTTPConnection(endpoint.hostname,endpoint.port or 80,timeout=2)
                    if count%15==1:print('Camera ingest unavailable:',exc,file=sys.stderr,flush=True)
                if count%150==0:print(json.dumps({'camera':'live','frames':count,'relay_fps':metadata['relay_fps'],'processing_ms':metadata['processing_ms'],'source_dropped':header['source_dropped']}),flush=True)
        except (OSError,ValueError,EOFError) as exc:
            print('Camera connection lost:',exc,file=sys.stderr,flush=True);restarts+=1;failures+=1
            if path=='auto' and failures>=3:active_path='raw'
        finally:
            if proc and proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=3)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
        stop.wait(min(5,1+restarts*.5))


def main():
    p=argparse.ArgumentParser();p.add_argument('--target',required=True);p.add_argument('--control',type=Path,required=True);p.add_argument('--url',default='http://127.0.0.1:8872');p.add_argument('--token-file',type=Path,required=True);p.add_argument('--path',choices=['auto','isp','raw'],default='auto');a=p.parse_args()
    stop=threading.Event()
    import signal
    for sig in (signal.SIGINT,signal.SIGTERM):signal.signal(sig,lambda *_:stop.set())
    run(a.target,a.control,a.url,a.token_file.read_text().strip(),stop,a.path)
if __name__=='__main__':main()
