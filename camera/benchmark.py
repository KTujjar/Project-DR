"""Approved runtime mode benchmark. Changes sensor mode/exposure/gain only."""
import argparse,json,subprocess,time,sys,threading,statistics
from pathlib import Path
from io import BytesIO
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from camera.protocol import read_frame
from camera.convert_raw10 import unpack_raw10,render,color_matrix
from PIL import Image
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
TARGET='turtle@fe80::ba27:ebff:fe79:d40f%en9'
SSH=['ssh','-S',str(ROOT/'.robot/control'),'-o','BatchMode=yes',TARGET]

def main():
 p=argparse.ArgumentParser();p.add_argument('--width',type=int,default=640);p.add_argument('--height',type=int,default=480);p.add_argument('--frames',type=int,default=90);a=p.parse_args()
 vb,exp=(6573,6500) if a.width==640 else (3527-a.height,3300)
 cmd=f'v4l2-ctl -d /dev/v4l-subdev0 --set-subdev-fmt pad=0,width={a.width},height={a.height},code=0x300f; v4l2-ctl -d /dev/video0 --set-fmt-video=width={a.width},height={a.height},pixelformat=pRAA; v4l2-ctl -d /dev/v4l-subdev0 --set-ctrl vertical_blanking={vb},exposure={exp},analogue_gain=192'
 subprocess.run(SSH+[cmd],check=True,stdout=subprocess.DEVNULL)
 proc=subprocess.Popen(SSH+[f'"$HOME/turtbot-dashboard/camera/capture_worker" /dev/video0 {a.frames}'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 times=[];source=[];cost=[];sizes=[];last=None;dropped=0;started=time.monotonic();matrix=color_matrix('imx219',5000)
 for i in range(a.frames):
  h,raw=read_frame(proc.stdout);t=time.monotonic();times.append(t);source.append(h['capture_unix']);dropped=h['source_dropped']
  begin=time.monotonic();m=unpack_raw10(raw,h['width'],h['height'],h['stride'])
  # Same pixel pipeline as the live relay, fixed WB/exposure avoids frame-to-frame flicker.
  rgb,stats=render(m,gains=[1.7,1,2.45],ccm=matrix,exposure='0');im=Image.fromarray(rgb);im.thumbnail((1280,720));out=BytesIO();im.save(out,format='JPEG',quality=80)
  cost.append((time.monotonic()-begin)*1000);sizes.append(len(raw));last=out.getvalue()
  if i==5:
   subprocess.run(SSH+[f'ps -p {h["pid"]} -o pid,pcpu,rss,args'],stdout=sys.stderr)
 proc.wait(timeout=5)
 duration=times[-1]-times[0]
 report={'mode':[a.width,a.height],'frames':len(times),'delivered_fps':(len(times)-1)/duration,'capture_timestamp_fps':(len(source)-1)/(source[-1]-source[0]),'raw_megabit_s':sum(sizes[1:])*8/duration/1e6,'processing_ms_mean':statistics.mean(cost),'processing_ms_p95':float(np.percentile(cost,95)),'source_dropped':dropped,'exposure_lines':exp,'analog_gain_register':192,'total_seconds':time.monotonic()-started,'jpeg_last_bytes':len(last),'not_measured':'Glass-to-glass latency; browser rendering is not part of this benchmark.'}
 dest=ROOT/'diagnostics/mission';dest.mkdir(exist_ok=True,parents=True);(dest/f'camera-{a.width}x{a.height}.json').write_text(json.dumps(report,indent=2));(dest/f'camera-{a.width}x{a.height}.jpg').write_bytes(last);print(json.dumps(report,indent=2))
if __name__=='__main__':main()
