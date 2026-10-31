"""Measure real video transport, decode/ACK latency and Pi resources; no motion."""
import argparse,asyncio,json,statistics,subprocess,time,sys
from pathlib import Path
from io import BytesIO
from PIL import Image
from websockets.asyncio.client import connect
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.missionctl import health,config,ssh,base
ROOT=Path(__file__).resolve().parents[1]
REMOTE='''import json,time,os
from pathlib import Path
state=json.loads(Path('.runtime/pi-processes.json').read_text());pids=[state['dashboard']['pid']]
for p in Path('/proc').glob('[0-9]*/cmdline'):
 try:
  if b'/camera/isp_worker' in p.read_bytes() or b'/camera/capture_worker' in p.read_bytes():pids.append(int(p.parent.name))
 except OSError:pass
result={'time':time.monotonic(),'cpu':list(map(int,Path('/proc/stat').read_text().splitlines()[0].split()[1:])),'net':{n:int(Path('/sys/class/net/eth0/statistics/'+n).read_text()) for n in ['rx_bytes','tx_bytes']},'processes':{}}
for pid in pids:
 try:
  s=Path(f'/proc/{pid}/stat').read_text().split();result['processes'][str(pid)]={'ticks':int(s[13])+int(s[14]),'rss_mb':int(s[23])*os.sysconf('SC_PAGE_SIZE')/1048576,'command':Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\\0',b' ').decode()}
 except OSError:pass
result['ticks_per_sec']=os.sysconf('SC_CLK_TCK');print(json.dumps(result))
'''
def snapshot():
 c=config();proc=subprocess.run(base(c)+['cd "$HOME/turtbot-dashboard" && python3 -'],input=REMOTE,capture_output=True,text=True,timeout=10)
 if proc.returncode:raise RuntimeError(proc.stderr)
 return json.loads(proc.stdout)
async def measure(seconds):
 before=snapshot();received=[];ack=[];pipeline=[];sizes=[];source=[];cpu=[];temp=[]
 async with connect('ws://127.0.0.1:8872/ws/video',origin='http://127.0.0.1:8872',max_size=3_000_000) as ws:
  start=time.monotonic();next_health=start
  while time.monotonic()-start<seconds:
   meta=json.loads(await asyncio.wait_for(ws.recv(),5));jpeg=await asyncio.wait_for(ws.recv(),5)
   with Image.open(BytesIO(jpeg)) as im:im.load()
   received.append(time.monotonic());sizes.append(len(jpeg));source.append(meta['frame_id'])
   if meta.get('previous_ack_latency_ms') is not None:ack.append(meta['previous_ack_latency_ms'])
   if meta.get('pipeline_latency_ms') is not None:pipeline.append(meta['pipeline_latency_ms'])
   await ws.send(json.dumps({'frame_id':meta['frame_id'],'client':'benchmark'}))
   if time.monotonic()>next_health:
    next_health=time.monotonic()+2;h=await asyncio.to_thread(health)
    if h:
     s=h.get('metadata',{}).get('system',{});cpu.append(s.get('cpu_percent'));temp.append(s.get('temperature_c'))
 after=snapshot();h=health();delta=after['time']-before['time'];duration=received[-1]-received[0]
 def stats(values):
  values=sorted(x for x in values if x is not None)
  return {'median':statistics.median(values),'p95':values[min(len(values)-1,int(.95*len(values)))],'min':values[0],'max':values[-1]} if values else None
 total=sum(after['cpu'])-sum(before['cpu']);idle=sum(after['cpu'][3:5])-sum(before['cpu'][3:5])
 resources={}
 for pid,p in after['processes'].items():
  if pid in before['processes']:resources[pid]={**p,'cpu_percent_one_core_100':(p['ticks']-before['processes'][pid]['ticks'])/after['ticks_per_sec']/delta*100}
 skipped=0
 for previous,current in zip(source,source[1:]):
  try:
   if previous.rsplit('-',1)[0]==current.rsplit('-',1)[0]:skipped+=max(0,int(current.rsplit('-',1)[1])-int(previous.rsplit('-',1)[1])-1)
  except ValueError:pass
 report={'sample_seconds':duration,'frames_fully_decoded_and_acknowledged':len(received),'delivered_fps':(len(received)-1)/duration,
   'jpeg_payload_mbit_s':sum(sizes[1:])*8/duration/1e6,'capture_to_backend_ms':stats(pipeline),'capture_to_client_decode_ack_ms':stats(ack),
   'latency_definition':'Pi end-of-frame timestamp through client JPEG decode and ACK receipt on Pi; not optical glass-to-glass latency. Browser is also open during this second-client test.',
   'eth0_mbit_s':{k:(after['net'][k]-before['net'][k])*8/delta/1e6 for k in before['net']},
   'system_cpu_percent':100*(1-idle/total),'sampled_cpu_percent':stats(cpu),'temperature_c':stats(temp),'processes':resources,
   'camera':h['sensors']['camera']['data'],'sensor_rates_hz':{k:v['hz'] for k,v in h['sensors'].items()},
   'intentional_or_source_sequence_skips_at_this_client':skipped,'motion_enabled':h['motion_enabled'],'control_armed':h['control']['armed']}
 destination=ROOT/'diagnostics/mission/performance.json';destination.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--seconds',type=int,default=30);a=p.parse_args();asyncio.run(measure(a.seconds))
