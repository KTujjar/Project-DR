"""Bounded hardware-ISP+MJPEG benchmark; camera service must be stopped first."""
import argparse,json,subprocess,time,sys,statistics
from pathlib import Path
from io import BytesIO
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from camera.protocol import read_frame
from camera.benchmark import ROOT,SSH
p=argparse.ArgumentParser();p.add_argument('--width',type=int,default=640);p.add_argument('--height',type=int,default=480);p.add_argument('--frames',type=int,default=75);a=p.parse_args()
subprocess.run(SSH+[f'cd "$HOME/turtbot-dashboard" && python3 camera/configure.py --width {a.width} --height {a.height}'],check=True,stdout=subprocess.DEVNULL)
proc=subprocess.Popen(SSH+[f'"$HOME/turtbot-dashboard/camera/isp_worker" {a.frames}'],stdout=subprocess.PIPE,stderr=sys.stderr)
times=[];stamps=[];latencies=[];sizes=[];last=None
for i in range(a.frames):
 h,jpeg=read_frame(proc.stdout);times.append(time.monotonic());stamps.append(h['capture_unix']);sizes.append(len(jpeg));latencies.append((h['sent_unix']-h['capture_unix'])*1000);last=jpeg
 with Image.open(BytesIO(jpeg)) as im:im.load()
 if i==15:subprocess.run(SSH+[f'ps -p {h["pid"]} -o pid,pcpu,rss,args'],stdout=sys.stderr)
proc.wait(timeout=5)
report={'path':'Pi hardware ISP + MJPEG','native_mode':[a.width,a.height],'output':[h['width'],h['height']],'frames':a.frames,
 'delivered_fps':(a.frames-1)/(times[-1]-times[0]),'capture_fps':(a.frames-1)/(stamps[-1]-stamps[0]),
 'capture_to_encoded_ms_median':statistics.median(latencies),'capture_to_encoded_ms_p95':sorted(latencies)[int(len(latencies)*.95)],
 'jpeg_payload_megabit_s':sum(sizes[1:])*8/(times[-1]-times[0])/1e6,'source_dropped':h['source_dropped'],
 'not_measured':'Browser delivery and glass-to-glass latency; this is capture/encode/SSH receive only.'}
out=ROOT/'diagnostics/mission';(out/f'isp-{a.width}x{a.height}.json').write_text(json.dumps(report,indent=2));(out/f'isp-{a.width}x{a.height}.jpg').write_bytes(last);print(json.dumps(report,indent=2))
